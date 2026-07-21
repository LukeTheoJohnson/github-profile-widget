#!/usr/bin/env python3
"""Build the feature-proposal review report.

Five ambitious enhancements to the *live* profile widget (assets/widget.svg in
the github-profile-widget repo) — each rendered as a real before/after SVG in
the widget's own Tokyo-Night design language, using the real GitHub snapshot so
we're comparing effects, not mock-ups.

Distinct from spikes/ (which are whole-card redesigns): these are incremental
features that could ship on top of the current linear-column layout.

Output: spikes/proposals/report.html  (self-contained, open in a browser)
"""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent / "report.html"

# ── palettes ─────────────────────────────────────────────────────────────────
# dark (live widget — Tokyo Night)
D = dict(
    BG="#1a1b27", PANEL="#24283b", PANEL2="#1f2335", FG="#c0caf5", MUTED="#565f89",
    BLUE="#70a5fd", PURPLE="#bb9af7", GREEN="#9ece6a", ORANGE="#e0af68", CYAN="#7dcfff",
    HEAT=["#2d3350", "#3b6e47", "#519a4e", "#73c05a", "#9ece6a"], STROKE="#565f89",
)
# light (proposed Tokyo-Day counterpart for the theming feature)
L = dict(
    BG="#e1e2e7", PANEL="#d0d1d8", PANEL2="#d5d6db", FG="#343b58", MUTED="#8990b3",
    BLUE="#2e7de9", PURPLE="#7847bd", GREEN="#587539", ORANGE="#8f5e15", CYAN="#007197",
    HEAT=["#dcdee3", "#9ec98a", "#6ea950", "#4c8a34", "#33691e"], STROKE="#a1a6c5",
)

FONT = "'Inter','Segoe UI',-apple-system,BlinkMacSystemFont,sans-serif"

# ── real snapshot (from the live widget.svg / spikes/data.json) ───────────────
UPSTREAM = [  # (name, stars_k, merged_prs)
    ("oh-my-claudecode", 37.8, 9),
    ("compound-engineering", 23.2, 5),
    ("statsmodels", 11.5, 3),
    ("cli-printing-press", 4.0, 2),
    ("printing-press-library", 1.8, 3),
]
REACH_K = 78.3  # combined upstream stars
PROJECTS = [  # (name, lang, desc, commits, heat[14])
    ("trove", "Python", "CLI that polls 70+ sources into SQLite", 41,
     [8, 0, 0, 7, 0, 0, 1, 9, 3, 7, 1, 3, 2, 5]),
    ("thing-explainer", "Python", "Explain things using only common words", 14,
     [0, 0, 0, 6, 0, 0, 0, 0, 0, 5, 0, 3, 0, 0]),
    ("dashboard-studio", "Python", "Dynamic dashboards across frontends", 9,
     [0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 1, 5, 0, 0]),
]
# language mix across public repos (illustrative, Python-dominant)
STACK = [("Python", 78, "#3572A5"), ("Shell", 11, "#89E051"),
         ("TypeScript", 7, "#3178C6"), ("Other", 4, "#565f89")]

LANG_DOT = {"Python": "#3572A5", "Shell": "#89E051", "TypeScript": "#3178C6"}


def esc(s) -> str:
    return escape(str(s))


def heat_color(pal, n: int) -> str:
    h = pal["HEAT"]
    if n <= 0:
        return h[0]
    if n <= 1:
        return h[1]
    if n <= 3:
        return h[2]
    if n <= 6:
        return h[3]
    return h[4]


def frame(pal, w, h, inner="", rx=14) -> str:
    """A widget-style rounded card of the given palette wrapping `inner`."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="{FONT}">'
        f'<rect width="{w}" height="{h}" rx="{rx}" fill="{pal["BG"]}"/>'
        f'<rect x="1" y="1" width="{w-2}" height="{h-2}" rx="{rx-1}" fill="none" '
        f'stroke="{pal["STROKE"]}" stroke-opacity="0.30"/>{inner}</svg>'
    )


# ── a compact but faithful mini-render of the whole live card ─────────────────
def mini_widget(pal) -> str:
    """Small silhouette of the current widget: header, insight, project cards,
    upstream bars, footer — enough to read the layout and the palette."""
    p = [f'<text x="20" y="30" fill="{pal["FG"]}" font-size="17" '
         f'font-weight="700">LukeTheoJohnson</text>',
         f'<text x="410" y="27" fill="{pal["CYAN"]}" font-size="8" '
         f'text-anchor="end" letter-spacing="1.5">ML · DATA SCIENCE</text>',
         f'<text x="20" y="54" fill="{pal["PURPLE"]}" font-size="10" '
         f'font-weight="700">17<tspan fill="{pal["FG"]}" font-weight="400"> merged PRs · '
         f'</tspan><tspan fill="{pal["BLUE"]}" font-weight="700">3</tspan>'
         f'<tspan fill="{pal["FG"]}" font-weight="400"> projects · </tspan>'
         f'<tspan fill="{pal["ORANGE"]}" font-weight="700">★ 10k+</tspan></text>',
         f'<line x1="20" y1="66" x2="410" y2="66" stroke="{pal["STROKE"]}" '
         f'stroke-opacity="0.3"/>']
    # left project cards
    for i, (name, lang, _desc, _c, heat) in enumerate(PROJECTS):
        cy = 80 + i * 34
        p.append(f'<rect x="20" y="{cy}" width="200" height="28" rx="6" '
                 f'fill="{pal["PANEL"]}"/>')
        p.append(f'<circle cx="32" cy="{cy+14}" r="3.5" '
                 f'fill="{LANG_DOT.get(lang, pal["MUTED"])}"/>')
        p.append(f'<text x="42" y="{cy+13}" fill="{pal["FG"]}" font-size="10" '
                 f'font-weight="600">{esc(name)}</text>')
        for j, n in enumerate(heat[6:]):  # last 8 days to fit
            p.append(f'<rect x="{132+j*10}" y="{cy+9}" width="7" height="7" rx="1.5" '
                     f'fill="{heat_color(pal, n)}"/>')
    # right upstream bars
    p.append(f'<text x="240" y="88" fill="{pal["GREEN"]}" font-size="9" '
             f'letter-spacing="1.5">MERGED PRs</text>')
    maxv = max(v for _, _, v in UPSTREAM)
    for i, (name, _s, v) in enumerate(UPSTREAM[:4]):
        by = 98 + i * 20
        p.append(f'<text x="240" y="{by+9}" fill="{pal["FG"]}" '
                 f'font-size="9">{esc(name[:16])}</text>')
        bw = int(v / maxv * 70)
        p.append(f'<rect x="330" y="{by}" width="{bw}" height="11" rx="3" '
                 f'fill="{pal["GREEN"]}"/>')
        p.append(f'<text x="{330+bw+6}" y="{by+9}" fill="{pal["GREEN"]}" '
                 f'font-size="9" font-weight="700">{v}</text>')
    p.append(f'<line x1="20" y1="196" x2="410" y2="196" stroke="{pal["STROKE"]}" '
             f'stroke-opacity="0.3"/>')
    p.append(f'<text x="20" y="212" fill="{pal["MUTED"]}" font-size="8">'
             f'GitHub API · refreshed daily</text>')
    return frame(pal, 430, 228, "".join(p))


# ═══════════════════════════════════════════════════════════════════════════
# F1 — adaptive light/dark theming
# ═══════════════════════════════════════════════════════════════════════════
def f1_before() -> str:
    # dark card marooned on a light README page
    inner = (f'<rect width="470" height="268" fill="#ffffff"/>'
             f'<text x="20" y="24" fill="#57606a" font-size="12" '
             f'font-family="{FONT}">github.com/LukeTheoJohnson · light theme</text>'
             f'<g transform="translate(20,36)">{mini_widget(D)}</g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="470" height="288" '
            f'viewBox="0 0 470 288">{inner}</svg>')


def f1_after() -> str:
    inner = (f'<rect width="470" height="268" fill="#ffffff"/>'
             f'<text x="20" y="24" fill="#57606a" font-size="12" '
             f'font-family="{FONT}">github.com/LukeTheoJohnson · light theme</text>'
             f'<g transform="translate(20,36)">{mini_widget(L)}</g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="470" height="288" '
            f'viewBox="0 0 470 288">{inner}</svg>')


# ═══════════════════════════════════════════════════════════════════════════
# F2 — open-source reach hero band
# ═══════════════════════════════════════════════════════════════════════════
def f2_before() -> str:
    pal = D
    p = [f'<text x="24" y="34" fill="{pal["CYAN"]}" font-size="11" '
         f'letter-spacing="1.5">✦ KEY INSIGHT</text>',
         f'<text x="24" y="66" font-size="19"><tspan fill="{pal["PURPLE"]}" '
         f'font-weight="700">17</tspan><tspan fill="{pal["FG"]}"> merged PRs across </tspan>'
         f'<tspan fill="{pal["BLUE"]}" font-weight="700">3</tspan>'
         f'<tspan fill="{pal["FG"]}"> projects, each </tspan>'
         f'<tspan fill="{pal["ORANGE"]}" font-weight="700">★ 10k+</tspan>'
         f'<tspan fill="{pal["FG"]}">.</tspan></text>',
         f'<text x="24" y="120" fill="{pal["MUTED"]}" font-size="12" '
         f'font-style="italic">(no aggregate impact figure today)</text>']
    return frame(pal, 470, 150, "".join(p))


def f2_after() -> str:
    pal = D
    p = [f'<text x="24" y="30" fill="{pal["CYAN"]}" font-size="11" '
         f'letter-spacing="1.5">✦ OPEN-SOURCE REACH</text>']
    # giant reach numeral
    p.append(f'<text x="24" y="86" fill="{pal["ORANGE"]}" font-size="52" '
             f'font-weight="800">78k</text>')
    p.append(f'<text x="150" y="66" fill="{pal["FG"]}" font-size="15">'
             f'combined ★ across the</text>')
    p.append(f'<text x="150" y="88" fill="{pal["FG"]}" font-size="15">'
             f'<tspan fill="{pal["PURPLE"]}" font-weight="700">5</tspan> upstream projects '
             f'your code ships in</text>')
    # stacked reach bar segmented by repo
    seg_x = 24
    total = sum(s for _, s, _ in UPSTREAM)
    barw = 422
    cols = [pal["ORANGE"], pal["PURPLE"], pal["CYAN"], pal["BLUE"], pal["GREEN"]]
    for i, (name, s, _v) in enumerate(UPSTREAM):
        w = s / total * barw
        p.append(f'<rect x="{seg_x:.1f}" y="106" width="{max(w-2,2):.1f}" height="16" '
                 f'rx="3" fill="{cols[i]}" opacity="0.85"/>')
        seg_x += w
    p.append(f'<text x="24" y="140" fill="{pal["MUTED"]}" font-size="10.5">'
             f'oh-my-claudecode 37.8k · compound-eng 23.2k · statsmodels 11.5k · +2</text>')
    return frame(pal, 470, 156, "".join(p))


# ═══════════════════════════════════════════════════════════════════════════
# F3 — tech-stack identity ring
# ═══════════════════════════════════════════════════════════════════════════
def f3_before() -> str:
    pal = D
    p = [f'<text x="24" y="42" fill="{pal["FG"]}" font-size="24" '
         f'font-weight="700">LukeTheoJohnson</text>',
         f'<text x="446" y="38" fill="{pal["CYAN"]}" font-size="12" '
         f'text-anchor="end" letter-spacing="2">ML · DATA SCIENCE</text>',
         f'<text x="446" y="60" fill="{pal["MUTED"]}" font-size="12" '
         f'text-anchor="end">2026-07-21</text>',
         f'<line x1="24" y1="80" x2="446" y2="80" stroke="{pal["STROKE"]}" '
         f'stroke-opacity="0.25"/>',
         f'<text x="24" y="112" fill="{pal["MUTED"]}" font-size="12" '
         f'font-style="italic">header right is mostly empty space today</text>']
    return frame(pal, 470, 140, "".join(p))


def _donut(pal, cx, cy, r, thick) -> str:
    import math
    segs = []
    start = -90.0
    total = sum(w for _, w, _ in STACK)
    for name, w, col in STACK:
        frac = w / total
        end = start + frac * 360
        a0, a1 = math.radians(start), math.radians(end)
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        large = 1 if (end - start) > 180 else 0
        segs.append(
            f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 {large} 1 {x1:.1f},{y1:.1f}" '
            f'fill="none" stroke="{col}" stroke-width="{thick}"/>')
        start = end
    segs.append(f'<text x="{cx}" y="{cy-2}" fill="{pal["FG"]}" font-size="14" '
                f'font-weight="700" text-anchor="middle">Py</text>')
    segs.append(f'<text x="{cx}" y="{cy+13}" fill="{pal["MUTED"]}" font-size="9" '
                f'text-anchor="middle">78%</text>')
    return "".join(segs)


def f3_after() -> str:
    pal = D
    p = [f'<text x="24" y="42" fill="{pal["FG"]}" font-size="24" '
         f'font-weight="700">LukeTheoJohnson</text>',
         f'<text x="24" y="64" fill="{pal["CYAN"]}" font-size="12" '
         f'letter-spacing="2">ML · DATA SCIENCE</text>']
    # donut top-right
    p.append(_donut(pal, 400, 62, 30, 9))
    # legend
    ly = 40
    for name, w, col in STACK:
        p.append(f'<rect x="150" y="{ly-9}" width="9" height="9" rx="2" fill="{col}"/>')
        p.append(f'<text x="164" y="{ly}" fill="{pal["FG"]}" font-size="11">'
                 f'{esc(name)} <tspan fill="{pal["MUTED"]}">{w}%</tspan></text>')
        ly += 18
    p.append(f'<line x1="24" y1="112" x2="446" y2="112" stroke="{pal["STROKE"]}" '
             f'stroke-opacity="0.25"/>')
    return frame(pal, 470, 140, "".join(p))


# ═══════════════════════════════════════════════════════════════════════════
# F4 — 52-week contribution wall
# ═══════════════════════════════════════════════════════════════════════════
def _wall(pal, x0, y0) -> str:
    # deterministic believable pattern: busier recent weeks, lighter weekends
    cells = []
    for wk in range(52):
        for d in range(7):
            recency = wk / 51.0
            weekend = 0.45 if d in (0, 6) else 1.0
            seed = (wk * 7 + d * 13) % 17
            base = (seed / 17.0) * recency * weekend
            n = 0 if base < 0.22 else 1 if base < 0.4 else 2 if base < 0.6 else 4 if base < 0.8 else 8
            cells.append(f'<rect x="{x0+wk*7:.0f}" y="{y0+d*7:.0f}" width="5.6" '
                         f'height="5.6" rx="1.3" fill="{heat_color(pal, n)}"/>')
    return "".join(cells)


def f4_before() -> str:
    pal = D
    p = [f'<text x="24" y="30" fill="{pal["MUTED"]}" font-size="12" '
         f'font-style="italic">…lots of quiet space above the footer today…</text>',
         f'<line x1="24" y1="96" x2="446" y2="96" stroke="{pal["STROKE"]}" '
         f'stroke-opacity="0.25"/>',
         f'<text x="24" y="116" fill="{pal["MUTED"]}" font-size="11">'
         f'pull requests: last year (44 analysed) · GitHub API · refreshed daily</text>']
    return frame(pal, 470, 140, "".join(p))


def f4_after() -> str:
    pal = D
    p = [f'<text x="24" y="28" fill="{pal["GREEN"]}" font-size="11" '
         f'letter-spacing="1.5">A YEAR OF SHIPPING</text>',
         f'<text x="446" y="28" fill="{pal["MUTED"]}" font-size="9" '
         f'text-anchor="end">1,240 commits</text>']
    p.append(_wall(pal, 24, 40))
    p.append(f'<line x1="24" y1="96" x2="446" y2="96" stroke="{pal["STROKE"]}" '
             f'stroke-opacity="0.25"/>')
    p.append(f'<text x="24" y="116" fill="{pal["MUTED"]}" font-size="11">'
             f'pull requests: last year (44 analysed) · GitHub API · refreshed daily</text>')
    return frame(pal, 470, 140, "".join(p))


# ═══════════════════════════════════════════════════════════════════════════
# F5 — "currently shipping" spotlight
# ═══════════════════════════════════════════════════════════════════════════
def f5_before() -> str:
    pal = D
    name, lang, desc, commits, heat = PROJECTS[0]
    p = [f'<text x="24" y="30" fill="{pal["CYAN"]}" font-size="11" '
         f'letter-spacing="1.5">PROJECTS I&apos;M WORKING ON</text>']
    cy = 44
    p.append(f'<rect x="24" y="{cy}" width="422" height="46" rx="10" fill="{pal["PANEL"]}"/>')
    p.append(f'<circle cx="42" cy="{cy+16}" r="4" fill="{LANG_DOT[lang]}"/>')
    p.append(f'<text x="54" y="{cy+21}" fill="{pal["FG"]}" font-size="15" '
             f'font-weight="600">{esc(name)}</text>')
    p.append(f'<text x="54" y="{cy+38}" fill="{pal["MUTED"]}" font-size="12">{esc(desc)}</text>')
    p.append(f'<text x="422" y="{cy+38}" fill="{pal["MUTED"]}" font-size="10.5" '
             f'text-anchor="end">{commits} commits</text>')
    for j, n in enumerate(heat):
        p.append(f'<rect x="{250+j*11}" y="{cy+11}" width="9" height="9" rx="2" '
                 f'fill="{heat_color(pal, n)}"/>')
    return frame(pal, 470, 116, "".join(p))


def f5_after() -> str:
    pal = D
    name, lang, desc, commits, heat = PROJECTS[0]
    p = [f'<text x="24" y="30" fill="{pal["CYAN"]}" font-size="11" '
         f'letter-spacing="1.5">CURRENTLY SHIPPING</text>']
    cy = 42
    # elevated hero card with accent border + glow
    p.append(f'<rect x="24" y="{cy}" width="422" height="64" rx="12" fill="{pal["PANEL2"]}" '
             f'stroke="{pal["GREEN"]}" stroke-opacity="0.55"/>')
    p.append(f'<circle cx="45" cy="{cy+20}" r="5" fill="{LANG_DOT[lang]}"/>')
    p.append(f'<text x="58" y="{cy+25}" fill="{pal["FG"]}" font-size="17" '
             f'font-weight="700">{esc(name)}</text>')
    # live pulse dot + label
    p.append(f'<circle cx="{24+422-90}" cy="{cy+18}" r="4" fill="{pal["GREEN"]}">'
             f'<animate attributeName="opacity" values="1;0.3;1" dur="2s" '
             f'repeatCount="indefinite"/></circle>')
    p.append(f'<text x="{24+422-80}" y="{cy+22}" fill="{pal["GREEN"]}" font-size="11" '
             f'font-weight="600">shipping now</text>')
    # latest commit message
    p.append(f'<text x="58" y="{cy+45}" fill="{pal["MUTED"]}" font-size="12.5">'
             f'↳ latest: "poll 3 new sources, dedupe by URL hash" · 2h ago</text>')
    # bigger heatmap along the bottom
    for j, n in enumerate(heat):
        p.append(f'<rect x="{250+j*13}" y="{cy+52}" width="10" height="7" rx="1.5" '
                 f'fill="{heat_color(pal, n)}"/>')
    return frame(pal, 470, 122, "".join(p))


# ── report assembly ──────────────────────────────────────────────────────────
FEATURES = [
    dict(
        n=1, title="Adaptive light / dark theming",
        pitch="The card reads the viewer's GitHub theme and repaints itself — no more dark slab on a light profile.",
        why=("GitHub renders READMEs in both light and dark mode, but the widget is "
             "hard-locked to Tokyo-Night dark. Roughly half of visitors see a heavy "
             "dark rectangle floating on a white page — the one element that doesn't "
             "belong. A <code>@media (prefers-color-scheme)</code> block inside the SVG "
             "swaps a palette of CSS custom properties, so the same file blends into "
             "either theme with zero extra requests."),
        needs="No new data. Refactor the ~12 hard-coded hex values into CSS variables + one light override block. ~1 evening.",
        effort="Low", risk="Low", data="None (pure render)",
        before=f1_before(), after=f1_after(),
        blabel="Today — dark card on a light profile", alabel="Proposed — repaints to match the viewer",
    ),
    dict(
        n=2, title="Open-source “reach” hero band",
        pitch="Lead with the number that actually lands: the combined star-weight of every project your code ships inside.",
        why=("The current insight line counts <em>your</em> PRs. It undersells the story. "
             "The stronger, rarer flex is <strong>reach</strong>: your merged code now runs "
             "inside projects with ~78k combined stars. Reframing from effort (17 PRs) to "
             "impact (78k reach) is the single highest-leverage narrative change — it's the "
             "line a recruiter or collaborator screenshots. A segmented bar shows which "
             "upstreams contribute the weight."),
        needs="Already fetched — the bars carry per-repo star counts. Just sum them and add one hero row + stacked bar. ~half a day.",
        effort="Low", risk="Low", data="Reuses existing star lookups",
        before=f2_before(), after=f2_after(),
        blabel="Today — effort framing (PR count)", alabel="Proposed — impact framing (reach)",
    ),
    dict(
        n=3, title="Tech-stack identity ring",
        pitch="A small language donut in the dead space top-right — an instant read on what you build with.",
        why=("The header's right side is near-empty. A compact donut of language share "
             "across your public repos (Python 78% · Shell · TS · …) gives a one-glance "
             "signature that no amount of prose does. It fills negative space with signal, "
             "and doubles as a colour anchor tying the card to the GitHub linguist palette "
             "already used for the project dots."),
        needs="One extra API pass over repo languages (or reuse repo.language already fetched). Add donut geometry + legend. ~1 day.",
        effort="Medium", risk="Low", data="repo languages (partly already fetched)",
        before=f3_before(), after=f3_after(),
        blabel="Today — empty header right", alabel="Proposed — language donut + legend",
    ),
    dict(
        n=4, title="52-week contribution wall",
        pitch="The iconic GitHub year-grid as a full-width band — proof of consistent shipping, not a single snapshot.",
        why=("The per-project 14-day strips show <em>recent</em> bursts but not the "
             "<em>habit</em>. A 52×7 contribution wall (the universally-recognised GitHub "
             "grid) says “this person ships every week” faster than any stat. It slots into "
             "the quiet band above the footer, turning dead space into the card's strongest "
             "at-a-glance credibility signal."),
        needs="Aggregate daily commit counts across repos for 365 days (GraphQL contributions API is one call). Render 364 cells. ~1–2 days.",
        effort="Medium", risk="Medium (needs auth'd GraphQL for private+public totals)", data="contributions calendar (GraphQL)",
        before=f4_before(), after=f4_after(),
        blabel="Today — quiet space above footer", alabel="Proposed — a year of shipping",
    ),
    dict(
        n=5, title="“Currently shipping” spotlight",
        pitch="Promote the single hottest repo this week into a live hero card — latest commit message and a pulsing “shipping now”.",
        why=("The widget is refreshed daily but feels static. Elevating the most-active "
             "repo into a distinct hero row — accent border, its latest commit message, a "
             "pulsing live dot — makes the card feel <em>alive</em>: “here's what I'm building "
             "right now.” It rewards return visitors with something that visibly moves and "
             "answers the first question anyone asks a builder: what are you working on today?"),
        needs="One extra call for the top repo's latest commit message. Pick max-heat project, render the hero variant. ~1 day.",
        effort="Medium", risk="Low", data="latest commit of hottest repo",
        before=f5_before(), after=f5_after(),
        blabel="Today — top project is just another row", alabel="Proposed — live hero spotlight",
    ),
]


def badge(label, value, kind):
    return (f'<span class="badge {kind}"><span class="bk">{label}</span>'
            f'<span class="bv">{esc(value)}</span></span>')


def main():
    rows = []
    for f in FEATURES:
        rows.append(f"""
    <section class="card" id="f{f['n']}">
      <div class="head">
        <div class="num">{f['n']}</div>
        <div>
          <h2>{esc(f['title'])}</h2>
          <p class="pitch">{f['pitch']}</p>
        </div>
      </div>
      <div class="badges">
        {badge('EFFORT', f['effort'], 'e-' + f['effort'].lower())}
        {badge('RISK', f['risk'].split(' ')[0], 'r-' + f['risk'].split(' ')[0].lower())}
        {badge('DATA', f['data'], 'neutral')}
      </div>
      <div class="compare">
        <figure><figcaption><span class="tag before">BEFORE</span> {esc(f['blabel'])}</figcaption>{f['before']}</figure>
        <figure><figcaption><span class="tag after">AFTER</span> {esc(f['alabel'])}</figcaption>{f['after']}</figure>
      </div>
      <p class="why">{f['why']}</p>
      <p class="needs"><strong>What it needs:</strong> {esc(f['needs'])}</p>
      <div class="verdict">
        <span class="v-approve">☐ Approve</span>
        <span class="v-reject">☐ Reject</span>
        <span class="v-note">notes: _______________________________</span>
      </div>
    </section>""")

    # summary table
    trows = "".join(
        f"<tr><td class='c'>{f['n']}</td><td>{esc(f['title'])}</td>"
        f"<td>{f['effort']}</td><td>{esc(f['risk'])}</td>"
        f"<td class='dim'>{esc(f['pitch'])}</td></tr>"
        for f in FEATURES)

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Profile Widget — Feature Proposals</title>
<style>
  :root {{
    --bg:#16161e; --panel:#1a1b27; --panel2:#24283b; --fg:#c0caf5; --muted:#565f89;
    --blue:#70a5fd; --purple:#bb9af7; --green:#9ece6a; --orange:#e0af68; --cyan:#7dcfff;
    --line:#2b3050;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font-family:{FONT}; line-height:1.5; padding:48px 24px 96px; }}
  .wrap {{ max-width:1040px; margin:0 auto; }}
  header.top {{ border-bottom:1px solid var(--line); padding-bottom:24px; margin-bottom:8px; }}
  h1 {{ font-size:30px; margin:0 0 6px; letter-spacing:-.02em; }}
  .sub {{ color:var(--muted); font-size:15px; margin:0; }}
  .sub b {{ color:var(--cyan); font-weight:600; }}
  table.summary {{ width:100%; border-collapse:collapse; margin:28px 0 8px; font-size:14px; }}
  table.summary th {{ text-align:left; color:var(--cyan); font-size:11px; letter-spacing:1.5px;
    font-weight:600; padding:8px 12px; border-bottom:1px solid var(--line); }}
  table.summary td {{ padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
  table.summary td.c {{ color:var(--purple); font-weight:700; text-align:center; width:32px; }}
  table.summary td.dim {{ color:var(--muted); }}
  .card {{ background:linear-gradient(160deg,var(--panel),#15161f);
    border:1px solid var(--line); border-radius:16px; padding:26px 28px;
    margin:26px 0; box-shadow:0 8px 30px rgba(0,0,0,.35); }}
  .head {{ display:flex; gap:16px; align-items:flex-start; }}
  .num {{ flex:none; width:40px; height:40px; border-radius:11px;
    background:var(--panel2); color:var(--green); font-weight:800; font-size:20px;
    display:flex; align-items:center; justify-content:center; }}
  h2 {{ font-size:21px; margin:2px 0 6px; }}
  .pitch {{ margin:0; color:var(--fg); font-size:15px; opacity:.92; }}
  .badges {{ display:flex; gap:10px; margin:16px 0 4px; flex-wrap:wrap; }}
  .badge {{ display:inline-flex; align-items:center; gap:8px; font-size:11.5px;
    padding:5px 11px; border-radius:999px; background:var(--panel2); }}
  .badge .bk {{ color:var(--muted); letter-spacing:1px; }}
  .badge .bv {{ font-weight:700; }}
  .e-low .bv, .r-low .bv {{ color:var(--green); }}
  .e-medium .bv {{ color:var(--orange); }}
  .r-medium .bv {{ color:var(--orange); }}
  .neutral .bv {{ color:var(--blue); }}
  .compare {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; margin:20px 0 8px; }}
  figure {{ margin:0; background:var(--bg); border:1px solid var(--line);
    border-radius:12px; padding:12px; }}
  figure svg {{ width:100%; height:auto; display:block; border-radius:6px; }}
  figcaption {{ font-size:12px; color:var(--muted); margin-bottom:10px; display:flex;
    align-items:center; gap:8px; }}
  .tag {{ font-size:10px; font-weight:700; letter-spacing:1px; padding:2px 7px;
    border-radius:5px; }}
  .tag.before {{ background:#33253a; color:#f7768e; }}
  .tag.after {{ background:#1f3326; color:var(--green); }}
  .why {{ font-size:14.5px; color:#a9b3e0; margin:14px 0 6px; }}
  .why code {{ background:var(--panel2); padding:1px 6px; border-radius:5px; font-size:13px; }}
  .needs {{ font-size:13.5px; color:var(--muted); margin:6px 0 0; }}
  .needs strong {{ color:var(--cyan); font-weight:600; }}
  .verdict {{ display:flex; gap:22px; align-items:center; margin-top:18px;
    padding-top:16px; border-top:1px dashed var(--line); font-size:14px; }}
  .v-approve {{ color:var(--green); font-weight:600; }}
  .v-reject {{ color:#f7768e; font-weight:600; }}
  .v-note {{ color:var(--muted); font-size:13px; }}
  footer {{ color:var(--muted); font-size:13px; margin-top:40px; text-align:center; }}
  @media (max-width:720px) {{ .compare {{ grid-template-columns:1fr; }} }}
</style></head>
<body><div class="wrap">
  <header class="top">
    <h1>Profile Widget — 5 Feature Proposals</h1>
    <p class="sub">Ambitious enhancements to the live widget, each shown as a real
      before/after in its own Tokyo-Night style. Rendered from the real snapshot —
      <b>17 merged PRs · ~78k combined upstream ★</b>. Distinct from the <code
      style="color:var(--purple)">spikes/</code> full redesigns; these layer onto the
      current layout. Approve / reject each below.</p>
    <table class="summary">
      <thead><tr><th>#</th><th>Feature</th><th>Effort</th><th>Risk</th><th>One-liner</th></tr></thead>
      <tbody>{trows}</tbody>
    </table>
  </header>
  {''.join(rows)}
  <footer>Review artifact · generated by spikes/proposals/build_report.py · not shipped to the live widget</footer>
</div></body></html>"""

    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
