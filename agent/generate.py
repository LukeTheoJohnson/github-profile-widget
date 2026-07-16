#!/usr/bin/env python3
"""Profile widget: what I've shipped, and what I've landed upstream.

Reads real data from the GitHub API and renders a clean data-viz card — no
agent theater, no synthetic loading traces. It leads with completed work:

  left   my own public projects — language, stars and a commit-activity heatmap
  right  merged pull requests grouped by the upstream project they landed in,
         plus a 12-month merged-PR cadence sparkline

Entrance motion is CSS inside the SVG (bars grow, heatmap cells sweep in, the
spark line draws once; today's active cell pulses) and is gated behind
prefers-reduced-motion, so reduced-motion viewers get the static final state.

Two timeframes are in play and both are labelled on the card: pull-request
totals cover the last year; the per-project commit heatmaps cover the last
14 days.

Identity is env-configurable — WIDGET_USER (defaults to the repo owner when
run in GitHub Actions), WIDGET_NAME and WIDGET_TAGLINE — so a fork works
without code edits. Row counts are too: WIDGET_PROJECT_LIMIT and
WIDGET_BAR_LIMIT cap the two columns, and the card height stretches to fit
whatever those allow.

Deterministic, so it runs without any API key and its output is reproducible.
Merged-PR data is scoped to public repos explicitly (is:public) and paginated,
so private work never leaks regardless of which token runs it — a local PAT
and the GitHub Actions token produce the same card; private commit volume
already surfaces via the stats card.

Output: assets/widget.svg
"""

from __future__ import annotations

import calendar
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

USER = (
    os.environ.get("WIDGET_USER")
    or os.environ.get("GITHUB_REPOSITORY_OWNER")  # set by GitHub Actions
    or "LukeTheoJohnson"
)
NAME = os.environ.get("WIDGET_NAME") or USER
TAGLINE = os.environ.get("WIDGET_TAGLINE", "")
GH_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
OUT = Path(__file__).resolve().parent.parent / "assets" / "widget.svg"

HEAT_DAYS = 14  # how many days of commit history each project heatmap shows
WINDOW_DAYS = 365  # contribution stats (PRs, reviews) cover the last year


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        print(f"warn: {name} is not an integer, using {default}", file=sys.stderr)
        return default


PROJECT_LIMIT = _env_int("WIDGET_PROJECT_LIMIT", 6)  # own-project cards drawn
BAR_LIMIT = _env_int("WIDGET_BAR_LIMIT", 6)  # merged-PR repo bars drawn
CORE_STARS = _env_int("WIDGET_CORE_STARS", 10_000)  # star floor for a "core" project

# ── tokyo-night palette (matches the rest of the profile README) ─────────────
BG = "#1a1b27"
PANEL = "#24283b"
PANEL2 = "#1f2335"
FG = "#c0caf5"
MUTED = "#565f89"
BLUE = "#70a5fd"
PURPLE = "#bb9af7"
GREEN = "#9ece6a"
ORANGE = "#e0af68"
CYAN = "#7dcfff"
# green ramp for the commit heatmap (empty → busiest), GitHub-style
HEAT = ["#2d3350", "#3b6e47", "#519a4e", "#73c05a", "#9ece6a"]
# GitHub linguist colours for the per-project language dot. The full map is
# vendored in lang_colours.json (~675 languages); this inline dozen is only
# the fallback if that file goes missing.
LANG_COLOURS = {
    "Python": "#3572A5", "Go": "#00ADD8", "TypeScript": "#3178C6",
    "JavaScript": "#F1E05A", "Rust": "#DEA584", "HTML": "#E34C26",
    "CSS": "#663399", "Shell": "#89E051", "Jupyter Notebook": "#DA5B0B",
    "C": "#555555", "C++": "#F34B7D", "Ruby": "#701516",
}
try:
    LANG_COLOURS.update(
        json.loads(
            Path(__file__).with_name("lang_colours.json").read_text(encoding="utf-8")
        )
    )
except (OSError, ValueError) as e:
    print(f"warn: lang_colours.json not loaded ({e})", file=sys.stderr)

# Reusable <symbol> logo marks for project cards, drawn in place of the plain
# language dot for any language we have a mark for. Languages absent from LOGOS
# keep their coloured dot; repos with no language get no mark. Add a language by
# dropping a <symbol> in LOGO_DEFS and a row in LOGOS.
LOGO_DEFS = (
    # Official Python logo mark (two-snake, no text)
    '<symbol id="logo-python" viewBox="0 0 256 255">'
    '<path fill="#3776AB" d="M126.916.072c-64.832 0-60.784 28.115-60.784 28.115l.072 29.128h61.868v8.745H41.631S.145 61.355.145 126.77c0 65.417 36.21 63.097 36.21 63.097h21.61v-30.356s-1.165-36.21 35.632-36.21h61.362s34.475.557 34.475-33.319V33.97S194.67.072 126.916.072zM92.802 19.66a11.12 11.12 0 0 1 11.13 11.13 11.12 11.12 0 0 1-11.13 11.13 11.12 11.12 0 0 1-11.13-11.13 11.12 11.12 0 0 1 11.13-11.13z"/>'
    '<path fill="#FFD43B" d="M128.757 254.126c64.832 0 60.784-28.115 60.784-28.115l-.072-29.127H127.6v-8.745h86.542s41.486 4.705 41.486-60.712c0-65.416-36.21-63.096-36.21-63.096h-21.61v30.355s1.165 36.21-35.632 36.21h-61.362s-34.475-.557-34.475 33.32v56.013s-5.235 33.897 62.518 33.897zm34.114-19.586a11.12 11.12 0 0 1-11.13-11.13 11.12 11.12 0 0 1 11.13-11.131 11.12 11.12 0 0 1 11.13 11.13 11.12 11.12 0 0 1-11.13 11.13z"/>'
    '</symbol>'
    # Terminal glyph (GitHub octicon), tinted the Shell linguist green
    '<symbol id="logo-shell" viewBox="0 0 16 16">'
    '<path fill="#89E051" d="M0 2.75C0 1.784.784 1 1.75 1h12.5c.966 0 1.75.784 1.75 1.75v10.5A1.75 1.75 0 0 1 14.25 15H1.75A1.75 1.75 0 0 1 0 13.25Zm1.75-.25a.25.25 0 0 0-.25.25v10.5c0 .138.112.25.25.25h12.5a.25.25 0 0 0 .25-.25V2.75a.25.25 0 0 0-.25-.25ZM7.25 8a.749.749 0 0 1-.22.53l-2.25 2.25a.749.749 0 0 1-1.06 0 .749.749 0 0 1 0-1.06L5.44 8 3.72 6.28a.749.749 0 1 1 1.06-1.06l2.25 2.25c.141.14.22.331.22.53Zm1.5 1.5h3a.75.75 0 0 1 0 1.5h-3a.75.75 0 0 1 0-1.5Z"/>'
    '</symbol>'
)
# GitHub language → symbol id in LOGO_DEFS
LOGOS = {"Python": "logo-python", "Shell": "logo-shell"}

# GitHub octicons (16px viewBox) tagging each banner stat, tinted to the stat's
# colour: git-merge, git-pull-request, repo, code-review.
STAT_ICONS = {
    "merge": "M5.45 5.154A4.25 4.25 0 0 0 9.25 7.5h1.378a2.251 2.251 0 1 1 0 1.5H9.25A5.734 5.734 0 0 1 5 7.123v3.505a2.25 2.25 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.95-.218ZM4.25 13.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm8.5-4.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5ZM5 3.25a.75.75 0 1 0 0 .005V3.25Z",
    "pr": "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z",
    "repo": "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z",
    "review": "M1.75 1h12.5c.966 0 1.75.784 1.75 1.75v8.5A1.75 1.75 0 0 1 14.25 13H8.061l-2.574 2.573A1.458 1.458 0 0 1 3 14.543V13H1.75A1.75 1.75 0 0 1 0 11.25v-8.5C0 1.784.784 1 1.75 1ZM1.5 2.75v8.5c0 .138.112.25.25.25h2a.75.75 0 0 1 .75.75v2.19l2.72-2.72a.749.749 0 0 1 .53-.22h6.5a.25.25 0 0 0 .25-.25v-8.5a.25.25 0 0 0-.25-.25H1.75a.25.25 0 0 0-.25.25Zm5.28 1.72a.75.75 0 0 1 0 1.06L5.31 7l1.47 1.47a.751.751 0 0 1-.018 1.042.751.751 0 0 1-1.042.018l-2-2a.75.75 0 0 1 0-1.06l2-2a.75.75 0 0 1 1.06 0Zm2.44 0a.75.75 0 0 1 1.06 0l2 2a.75.75 0 0 1 0 1.06l-2 2a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L10.69 7 9.22 5.53a.75.75 0 0 1 0-1.06Z",
}


def gh(path: str):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "oss-profile-widget",
            **({"Authorization": f"Bearer {GH_TOKEN}"} if GH_TOKEN else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def search_count(q: str) -> int:
    try:
        return int(gh(f"/search/issues?q={q}&per_page=1").get("total_count", 0))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        print(f"warn: count failed for {q!r} ({e})", file=sys.stderr)
        return 0


def search_issues_all(q: str, cap_pages: int = 10) -> list[dict]:
    """Every issue/PR search hit for query q, following pagination.

    The GitHub search API returns at most 100 hits per page and 1000 total
    (10 pages), so we walk pages until one comes back short. Fetching all
    pages — rather than a single sorted page — is what keeps the merged-PR
    counts honest once the year holds more than 100 PRs.
    """
    items: list[dict] = []
    for page in range(1, cap_pages + 1):
        try:
            res = gh(f"/search/issues?q={q}&per_page=100&page={page}")
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            print(f"warn: PR search failed (page {page}: {e})", file=sys.stderr)
            break
        batch = res.get("items", [])
        items.extend(batch)
        if len(batch) < 100:
            break
    return items


def repo_stars(full: str) -> int:
    """Stargazer count for an owner/name repo (0 on any failure)."""
    try:
        return int(gh(f"/repos/{full}").get("stargazers_count", 0))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        print(f"warn: stars fetch failed for {full} ({e})", file=sys.stderr)
        return 0


def rel_age(iso: str) -> str:
    """Human 'updated 2d ago' from an ISO timestamp."""
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return "active"
    days = (datetime.now(timezone.utc) - d).days
    if days <= 0:
        return "updated today"
    if days == 1:
        return "updated yesterday"
    if days < 30:
        return f"updated {days}d ago"
    return f"updated {days // 30}mo ago"


def commit_days(repo: str, days: int = HEAT_DAYS) -> list[int]:
    """Commits per day on the default branch, oldest→newest, last `days`."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        commits = gh(f"/repos/{USER}/{repo}/commits?since={since}&per_page=100")
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"warn: commits fetch failed for {repo} ({e})", file=sys.stderr)
        return [0] * days
    counts = [0] * days
    for cm in commits:
        info = cm.get("commit", {})
        ds = (info.get("author") or {}).get("date") or (
            info.get("committer") or {}
        ).get("date")
        try:
            d = datetime.fromisoformat((ds or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        day = (now - d).days
        if 0 <= day < days:
            counts[days - 1 - day] += 1  # newest on the right
    return counts


# ── my own public projects (non-fork repos I push to) ────────────────────────
def collect_projects(limit: int = PROJECT_LIMIT) -> list[dict]:
    try:
        repos = gh(f"/users/{USER}/repos?sort=pushed&per_page=100")
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"warn: repos fetch failed ({e})", file=sys.stderr)
        return []
    out = []
    for r in repos:
        if r.get("fork") or r.get("archived"):
            continue
        if r.get("name", "").lower() == USER.lower():
            continue  # the profile repo itself is not a project
        out.append(
            {
                "name": r["name"],
                "language": r.get("language") or "",
                "stars": r.get("stargazers_count", 0),
                "description": (r.get("description") or "").strip(),
                "pushed_at": r.get("pushed_at", ""),
            }
        )
    out.sort(key=lambda d: d["pushed_at"], reverse=True)
    out = out[:limit]
    for pr in out:  # only fetch commit history for the few we'll actually draw
        pr["heat"] = commit_days(pr["name"])
        pr["commits"] = sum(pr["heat"])
    return out


# ── my merged contributions (PRs that actually landed, grouped by repo) ───────
def collect_contributions() -> dict:
    since = (
        datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    ).strftime("%Y-%m-%d")
    # is:public keeps private repos out no matter which token runs this, so a
    # local PAT and the CI token render the same card; pagination lifts the old
    # 100-PR single-page cap that silently dropped the least-recent months.
    items = search_issues_all(
        f"type:pr+author:{USER}+is:public+created:>={since}"
    )

    by_repo: dict[str, dict] = defaultdict(
        lambda: {"merged": 0, "open": 0, "owner": ""}
    )
    merged = 0
    for it in items:
        full = it.get("repository_url", "").split("/repos/", 1)[-1]
        if not full or "/" not in full:
            continue
        by_repo[full]["owner"] = full.split("/", 1)[0]
        if it.get("pull_request", {}).get("merged_at"):
            by_repo[full]["merged"] += 1
            merged += 1
        elif it.get("state") == "open":
            by_repo[full]["open"] += 1

    def is_external(repo: str) -> bool:
        return by_repo[repo]["owner"].lower() != USER.lower()

    # merged PRs per external repo, with one star lookup each so we can split
    # "core" (high-star) projects from the long tail
    external = {
        r: s["merged"] for r, s in by_repo.items() if is_external(r) and s["merged"]
    }
    stars = {r: repo_stars(r) for r in external}

    merged_upstream = sum(external.values())
    merged_projects = len(external)

    core = {r: n for r, n in external.items() if stars[r] >= CORE_STARS}
    core_contributions = sum(core.values())
    core_projects = len(core)

    bars = sorted(
        (
            {"full": r, "name": r.split("/", 1)[1], "value": n, "stars": stars[r]}
            for r, n in external.items()
        ),
        key=lambda d: d["value"],
        reverse=True,
    )[:BAR_LIMIT]

    # merged PRs bucketed by merge month, oldest → newest, for the sparkline
    monthly = [0] * 12
    now = datetime.now(timezone.utc)
    for it in items:
        merged_at = it.get("pull_request", {}).get("merged_at")
        if not merged_at:
            continue
        try:
            d = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        mb = (now.year - d.year) * 12 + (now.month - d.month)
        if 0 <= mb < 12:
            monthly[11 - mb] += 1

    return {
        "monthly": monthly,
        "merged": merged,
        "merged_upstream": merged_upstream,
        "merged_projects": merged_projects,
        "core_contributions": core_contributions,
        "core_projects": core_projects,
        "bars": bars,
        "total_prs": len(items),
    }


# ── render ───────────────────────────────────────────────────────────────────
def t(s: str, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def heat_color(n: int) -> str:
    """Map a daily commit count to a ramp colour — fixed thresholds so even a
    single commit reads as clearly green (GitHub-style), not relative-faint."""
    if n <= 0:
        return HEAT[0]
    if n <= 1:
        return HEAT[1]
    if n <= 3:
        return HEAT[2]
    if n <= 6:
        return HEAT[3]
    return HEAT[4]


def octicon(name: str, x, y, col: str, size: int = 16) -> str:
    """A tinted 16px GitHub octicon as a positioned nested <svg>."""
    return (
        f'<svg x="{x}" y="{y}" width="{size}" height="{size}" viewBox="0 0 16 16">'
        f'<path fill="{col}" d="{STAT_ICONS[name]}"/></svg>'
    )


def kfmt(n: int) -> str:
    """Compact star count: 1234 -> '1.2k', 950 -> '950'."""
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def render_svg(projects: list[dict], c: dict) -> str:
    W = 900
    cx, cw = 32, 410
    sq, gap = 9, 2
    strip_w = HEAT_DAYS * (sq + gap) - gap
    card_h, pitch = 46, 54  # each project card, and the row-to-row pitch

    # pre-measure so the total height hugs the content. Each card is two rows:
    # the language mark + name (with the heatmap opposite), then a description
    # line with the commit count opposite it.
    for pr in projects:
        pr["desc_line"] = t(pr["description"] or rel_age(pr["pushed_at"]), 44)

    left_bottom = 188 + (len(projects) * pitch - 8 if projects else 22)
    bars_end = 198 + (len(c["bars"]) * 30 if c["bars"] else 22)
    has_spark = max(c["monthly"]) > 0  # all-zero months: skip the flatline chart
    spark_label_y = bars_end + 10
    spark_top = spark_label_y + 10
    spark_h = 36
    # sparkline height includes room for the x-axis month labels
    right_bottom = (spark_top + spark_h + 18) if has_spark else bars_end
    H = max(left_bottom, right_bottom) + 58

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p: list[str] = []

    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" '
        f'font-family="\'Inter\',\'Segoe UI\',-apple-system,sans-serif">'
    )
    p.append(
        '<defs>'
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{BG}"/><stop offset="1" stop-color="{PANEL2}"/>'
        '</linearGradient>'
        f'<linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="#519a4e"/><stop offset="1" stop-color="{GREEN}"/>'
        '</linearGradient>'
        f'<linearGradient id="spark" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{GREEN}" stop-opacity="0.35"/>'
        f'<stop offset="1" stop-color="{GREEN}" stop-opacity="0.02"/>'
        f'</linearGradient>{LOGO_DEFS}</defs>'
    )
    # one-shot entrance motion only (bars grow, cells sweep in, spark line
    # draws); the sole loop is a slow pulse on today's active heatmap cell.
    p.append(
        '<style>'
        '@media (prefers-reduced-motion: no-preference){'
        '.bar{transform-box:fill-box;transform-origin:left;'
        'animation:grow .55s cubic-bezier(.2,.7,.3,1) backwards}'
        '.cell{animation:fade .45s ease-out backwards}'
        '.pulse{animation:pulse 3s ease-in-out infinite}'
        '.line{stroke-dasharray:620;stroke-dashoffset:620;'
        'animation:draw 1s ease-out .25s forwards}'
        '.fill,.dot{animation:fade .7s ease-out .7s backwards}'
        '}'
        '@keyframes grow{from{transform:scaleX(0)}}'
        '@keyframes fade{from{opacity:0}}'
        '@keyframes draw{to{stroke-dashoffset:0}}'
        '@keyframes pulse{50%{opacity:.4}}'
        '</style>'
    )
    p.append(f'<rect width="{W}" height="{H}" rx="16" fill="url(#bg)"/>')
    p.append(
        f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="15" fill="none" '
        f'stroke="{MUTED}" stroke-opacity="0.30"/>'
    )

    # header
    p.append(
        f'<text x="32" y="50" fill="{FG}" font-size="27" font-weight="700">'
        f'{escape(NAME)}</text>'
    )
    if TAGLINE:
        p.append(
            f'<text x="{W-32}" y="44" fill="{CYAN}" font-size="13" text-anchor="end" '
            f'letter-spacing="2">{escape(TAGLINE)}</text>'
        )
    p.append(
        f'<text x="{W-32}" y="76" fill="{MUTED}" font-size="15" text-anchor="end">'
        f'{today}</text>'
    )

    # key-insight caption — a generated finding, not a totals summary. The
    # eyebrow + coloured numerals read as one curated statement about the core
    # (high-star) open-source work; the long tail is left to the merged-PR bars.
    p.append(
        f'<text x="32" y="97" fill="{CYAN}" font-size="11.5" '
        f'letter-spacing="1.5">✦ KEY INSIGHT</text>'
    )
    p.append(
        f'<text x="{W-32}" y="97" fill="{MUTED}" font-size="10.5" '
        f'text-anchor="end" letter-spacing="1">LAST YEAR</text>'
    )
    # insight laid out as positioned runs so the merge/repo icons sit inline,
    # just left of their coloured numbers; textLength pins each text run's
    # advance so the icons stay aligned regardless of the renderer's metrics.
    # stars reuse the same ★ glyph as the bars, inline in the gold number run.
    isz, ix, iy = 19, 32, 128
    thr = f'★ {kfmt(CORE_STARS)}+'
    if c["core_projects"]:
        runs = [
            ("i", "merge", PURPLE), ("n", str(c["core_contributions"]), PURPLE),
            ("t", " merged PRs across ", FG),
            ("i", "repo", BLUE), ("n", str(c["core_projects"]), BLUE),
            ("t", " open-source projects, each with ", FG),
            ("n", thr, ORANGE), ("t", " stars.", FG),
        ]
    elif c["merged_upstream"]:
        runs = [
            ("i", "merge", PURPLE), ("n", str(c["merged_upstream"]), PURPLE),
            ("t", " merged PRs across ", FG),
            ("i", "repo", BLUE), ("n", str(c["merged_projects"]), BLUE),
            ("t", " open-source projects.", FG),
        ]
    else:
        runs = [("t", "Building in the open — first contributions landing soon.", FG)]

    for kind, val, col in runs:
        if kind == "i":
            p.append(octicon(val, ix, iy - isz + 4, col, isz - 4))
            ix += isz - 2
            continue
        w = sum(
            (0.28 if ch in " .,;:'!iljtfrI" else 0.86 if ch in "mwMW" else 0.54) * isz
            for ch in val
        )
        bold = ' font-weight="700"' if kind == "n" else ""
        p.append(
            f'<text x="{ix:.0f}" y="{iy}" fill="{col}" font-size="{isz}"{bold} '
            f'textLength="{w:.0f}" lengthAdjust="spacingAndGlyphs" '
            f'xml:space="preserve">{escape(val)}</text>'
        )
        ix += w

    p.append(
        f'<line x1="32" y1="146" x2="{W-32}" y2="146" '
        f'stroke="{MUTED}" stroke-opacity="0.25"/>'
    )

    # ── left: my own projects (cards with commit heatmap) ────────────────────
    p.append(
        f'<text x="32" y="174" fill="{CYAN}" font-size="11.5" letter-spacing="1.5">'
        f'PROJECTS I&apos;M WORKING ON</text>'
    )
    p.append(
        f'<text x="442" y="174" fill="{MUTED}" font-size="10" text-anchor="end" '
        f'letter-spacing="0.5">commits / {HEAT_DAYS}d</text>'
    )
    cy = 188
    if projects:
        for pr in projects:
            p.append(
                f'<rect x="{cx}" y="{cy}" width="{cw}" height="{card_h}" rx="10" '
                f'fill="{PANEL}"/>'
            )
            # name row: language mark (a logo if we have one for the language,
            # else a coloured dot) sits immediately left of the name; the
            # heatmap sits opposite
            lang = pr["language"]
            sym = LOGOS.get(lang)
            if sym:
                p.append(
                    f'<use href="#{sym}" x="{cx+16}" y="{cy+9}" '
                    f'width="14" height="14"/>'
                )
                name_x = cx + 36
            elif lang:
                p.append(
                    f'<circle cx="{cx+20}" cy="{cy+16}" r="4" '
                    f'fill="{LANG_COLOURS.get(lang, MUTED)}"/>'
                )
                name_x = cx + 30
            else:
                name_x = cx + 16
            p.append(
                f'<text x="{name_x}" y="{cy+21}" fill="{FG}" font-size="15" '
                f'font-weight="600">{escape(t(pr["name"], 20))}</text>'
            )
            # commit count, right-anchored under the heatmap
            p.append(
                f'<text x="{cx+cw-16}" y="{cy+38}" fill="{MUTED}" font-size="10.5" '
                f'text-anchor="end">{pr.get("commits", 0)} commits</text>'
            )
            # description (second row, left)
            p.append(
                f'<text x="{cx+16}" y="{cy+38}" fill="{MUTED}" '
                f'font-size="12">{escape(pr["desc_line"])}</text>'
            )
            # daily commit heatmap, top-right; today's active cell pulses
            heat = pr.get("heat") or [0] * HEAT_DAYS
            x0 = cx + cw - 16 - strip_w
            for i, n in enumerate(heat):
                if i == HEAT_DAYS - 1 and n > 0:
                    anim = ' class="pulse"'
                else:
                    anim = (
                        f' class="cell" '
                        f'style="animation-delay:{0.1 + i * 0.03:.2f}s"'
                    )
                p.append(
                    f'<rect x="{x0 + i*(sq+gap)}" y="{cy+11}" width="{sq}" '
                    f'height="{sq}" rx="2" fill="{heat_color(n)}"{anim}/>'
                )
            cy += pitch
    else:
        p.append(
            f'<text x="{cx+4}" y="{cy+18}" fill="{MUTED}" font-size="13">'
            f'building it</text>'
        )

    # ── right: merged PRs by upstream project (bars) ─────────────────────────
    bx = 470
    p.append(
        f'<text x="{bx}" y="174" fill="{GREEN}" font-size="11.5" letter-spacing="1.5">'
        f'MERGED PRs</text>'
    )
    bars = c["bars"]
    maxv = max((b["value"] for b in bars), default=1) or 1
    name_x = bx + 52  # left gutter reserved for the star column
    # name column sized to the longest repo name (~6.7px/char at 13px), so
    # long names get room and the bar track absorbs whatever is left over
    longest = max((len(t(b["name"], 28)) for b in bars), default=0)
    track_x = name_x + min(int(longest * 6.7) + 14, 210)
    track_w = max(W - 32 - 34 - track_x, 60)
    by = 198
    if not bars:
        p.append(
            f'<text x="{bx+4}" y="{by+18}" fill="{MUTED}" font-size="13">'
            f'none merged upstream yet</text>'
        )
    for i, b in enumerate(bars):
        bw = max(int((b["value"] / maxv) * track_w), 9)
        # star gutter: ★ glyphs in a fixed left column, counts right-aligned
        # against the name column, so neither wanders with count length
        if b.get("stars"):
            p.append(
                f'<text x="{bx}" y="{by+11}" fill="{ORANGE}" '
                f'font-size="10.5">★</text>'
            )
            p.append(
                f'<text x="{bx+44}" y="{by+11}" fill="{MUTED}" '
                f'font-size="10.5" text-anchor="end">{kfmt(b["stars"])}</text>'
            )
        p.append(
            f'<text x="{name_x}" y="{by+11}" fill="{FG}" font-size="13">'
            f'{escape(t(b["name"], 28))}</text>'
        )
        p.append(
            f'<rect x="{track_x}" y="{by}" width="{bw}" height="14" rx="4" '
            f'fill="url(#bar)" class="bar" '
            f'style="animation-delay:{0.1 + i * 0.08:.2f}s"/>'
        )
        p.append(
            f'<text x="{track_x+track_w+10}" y="{by+11}" fill="{GREEN}" '
            f'font-size="12.5" font-weight="600">{b["value"]}</text>'
        )
        by += 30

    # ── merged-PR cadence, last 12 months (area sparkline with light axes);
    # skipped entirely when the year is all zeros — no flatline chart ────────
    monthly = c["monthly"]
    if has_spark:
        p.append(
            f'<text x="{bx}" y="{spark_label_y}" fill="{MUTED}" font-size="10" '
            f'letter-spacing="1">MERGED PRs / MONTH</text>'
        )
        sw = W - 32 - bx
        speak = max(monthly)
        step = sw / (len(monthly) - 1)
        base = spark_top + spark_h
        pts = [
            (bx + i * step, base - (v / speak) * spark_h)
            for i, v in enumerate(monthly)
        ]
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)

        # y-gridlines behind the area: a zero baseline, and a dashed peak
        # line — each labelled in the gutter just left of the plot
        grid = [
            (base, "0", ""),
            (spark_top, str(speak), ' stroke-dasharray="3 3"'),
        ]
        for gy, glabel, dash in grid:
            p.append(
                f'<line x1="{bx}" y1="{gy:.1f}" x2="{W-32}" y2="{gy:.1f}" '
                f'stroke="{MUTED}" stroke-opacity="0.25"{dash}/>'
            )
            p.append(
                f'<text x="{bx-6}" y="{gy+3:.1f}" fill="{MUTED}" font-size="9" '
                f'text-anchor="end">{glabel}</text>'
            )

        p.append(
            f'<polygon points="{pts[0][0]:.1f},{base} {line} '
            f'{pts[-1][0]:.1f},{base}" fill="url(#spark)" class="fill"/>'
        )
        p.append(
            f'<polyline points="{line}" fill="none" stroke="{GREEN}" '
            f'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round" '
            f'class="line"/>'
        )
        p.append(
            f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3" '
            f'fill="{GREEN}" class="dot"/>'
        )

        # x-axis: month labels at the start, middle and end of the window
        now_m = datetime.now(timezone.utc)

        def _mlabel(idx: int, with_year: bool = False) -> str:
            m, y = now_m.month - (len(monthly) - 1 - idx), now_m.year
            while m <= 0:
                m, y = m + 12, y - 1
            lab = calendar.month_abbr[m]
            return f"{lab} ’{y % 100:02d}" if with_year else lab

        # only the two ends carry a 2-digit year, so the span's year boundary is
        # legible without cluttering the axis; the midpoint stays a bare month
        axis_y = base + 13
        for idx, anchor, yr in ((0, "start", True),
                                (len(monthly) // 2, "middle", False),
                                (len(monthly) - 1, "end", True)):
            p.append(
                f'<text x="{pts[idx][0]:.1f}" y="{axis_y}" fill="{MUTED}" '
                f'font-size="9" text-anchor="{anchor}">{_mlabel(idx, yr)}</text>'
            )

    # ── provenance, with both timeframes spelled out ─────────────────────────
    p.append(
        f'<line x1="32" y1="{H-32}" x2="{W-32}" y2="{H-32}" '
        f'stroke="{MUTED}" stroke-opacity="0.25"/>'
    )
    p.append(
        f'<text x="32" y="{H-14}" fill="{MUTED}" font-size="11">'
        f'pull requests: last year ({c["total_prs"]} analysed) · '
        f'commit heatmaps: last {HEAT_DAYS} days · GitHub API · refreshed daily'
        f'</text>'
    )

    p.append("</svg>")
    return "".join(p)


def main():
    projects = collect_projects()
    contrib = collect_contributions()
    svg = render_svg(projects, contrib)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg, encoding="utf-8")
    print(
        f"wrote {OUT} ({len(svg)} bytes) · "
        f"{len(projects)} projects / {contrib['merged']} merged / "
        f"{len(contrib['bars'])} bars"
    )


if __name__ == "__main__":
    main()
