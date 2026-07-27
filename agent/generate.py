#!/usr/bin/env python3
"""Profile widget: what I've shipped, and what I've landed upstream.

Reads real data from the GitHub API and renders a clean data-viz card — no
agent theater, no synthetic loading traces. It leads with completed work:

  left   my own public projects — language, stars and a commit-activity heatmap
  right  merged pull requests grouped by the upstream project they landed in,
         plus a 12-month merged-PR cadence sparkline

The card ships two deliberately-designed palettes — Tokyo Night (dark) and a
Tokyo Day sibling (light) — and swaps between them with a
`@media (prefers-color-scheme)` block inside the SVG, so the same file blends
into either GitHub theme with no extra request.

Entrance motion is CSS inside the SVG (bars grow, heatmap cells sweep in, the
spark line draws once; today's active cell pulses) and is gated behind
prefers-reduced-motion, so reduced-motion viewers get the static final state.

Two timeframes are in play and both are labelled on the card: pull-request
totals cover the last year; the per-project commit heatmaps cover the last
14 days.

Identity is env-configurable but needs nothing set: WIDGET_USER defaults to the
repo owner when run in GitHub Actions, and the header name defaults to that
account's GitHub display name ("Luke Johnson", not the login) — WIDGET_NAME
overrides it. The top-right tagline auto-derives from the reviewed data (see derive_tagline):
a couple of uppercase domain keywords mined from the projects and upstream repos
on the card, so a fork gets a fitting strip with nothing to set. WIDGET_TAGLINE
overrides it with a literal string, or hides it when set to empty. Row counts
are configurable too: WIDGET_PROJECT_LIMIT and WIDGET_BAR_LIMIT cap the two
columns, and the card height stretches to fit whatever those allow.

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
# Unset → the account's GitHub display name (profile_name), e.g. "Luke Johnson",
# not the login; any value overrides it.
NAME_ENV = os.environ.get("WIDGET_NAME")
# Unset → auto-derived from the reviewed data (derive_tagline); an explicit
# empty string hides the strip; any other value is used verbatim.
TAGLINE_ENV = os.environ.get("WIDGET_TAGLINE")
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
TAGLINE_MAX = _env_int("WIDGET_TAGLINE_KEYWORDS", 3)  # keywords in the auto tagline

# ── theming ──────────────────────────────────────────────────────────────────
# Colours are applied through CSS custom properties + utility classes, never
# `var()` in a presentation attribute (Firefox/Safari ignore that). A single
# `@media (prefers-color-scheme: light)` block re-points the variables, so the
# same file follows the viewer's theme. Linguist language colours (LANG_COLOURS)
# and the logo marks stay fixed across themes, exactly as GitHub renders them.
DARK_VARS = {
    "bg0": "#1a1b27", "bg1": "#1f2335", "panel": "#24283b", "panel2": "#1f2335",
    "fg": "#c0caf5", "muted": "#565f89",
    "blue": "#70a5fd", "purple": "#bb9af7", "green": "#9ece6a",
    "orange": "#e0af68", "cyan": "#7dcfff",
    "bar0": "#519a4e", "bar1": "#9ece6a",
    "h0": "#2d3350", "h1": "#3b6e47", "h2": "#519a4e", "h3": "#73c05a", "h4": "#9ece6a",
}
# Tokyo Day — a deliberate light sibling in the same hue family: soft grey
# ground, ink-navy text, accents deepened for contrast on a light background.
LIGHT_VARS = {
    "bg0": "#e8e9ee", "bg1": "#dcdee6", "panel": "#d6d8e3", "panel2": "#ccd0de",
    "fg": "#2c3053", "muted": "#656c96",
    "blue": "#2e7de9", "purple": "#7847bd", "green": "#587539",
    "orange": "#8f5e15", "cyan": "#007197",
    "bar0": "#7faa5f", "bar1": "#587539",
    "h0": "#d2d4de", "h1": "#a6c68c", "h2": "#7faa5f", "h3": "#5c8a3c", "h4": "#3d6420",
}
# semantic class names — a fill unless prefixed s- (stroke). Defined once in the
# <style> block, so an element just carries the class and follows the theme.
C_FG, C_MUTED, C_CYAN = "t-fg", "t-mut", "t-cyan"
C_GREEN, C_BLUE, C_PURPLE, C_ORANGE = "t-green", "t-blue", "t-purple", "t-orange"
C_PANEL = "t-panel"
S_MUTED, S_GREEN = "s-mut", "s-green"

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

# Per-language <symbol> logo marks, drawn in place of the plain coloured dot for
# any language we have a mark for. Two are bespoke — the official multi-colour
# Python mark and a Shell terminal octicon — and the rest are monochrome brand
# glyphs (Simple Icons, CC0) tinted with the language's own linguist colour, so a
# mark reads exactly like the dot it replaces. Languages absent from LOGOS keep
# their dot; repos with no language get no mark. Add one by dropping a row in
# LOGO_MARKS (symbol id → (viewBox, inner markup)) and mapping the language to it
# in LOGOS. Only the marks a card actually draws are emitted (see logo_defs).
LOGO_MARKS = {
    # Official Python logo mark (two-snake, no text)
    "logo-python": ("0 0 256 255",
        '<path fill="#3776AB" d="M126.916.072c-64.832 0-60.784 28.115-60.784 28.115l.072 29.128h61.868v8.745H41.631S.145 61.355.145 126.77c0 65.417 36.21 63.097 36.21 63.097h21.61v-30.356s-1.165-36.21 35.632-36.21h61.362s34.475.557 34.475-33.319V33.97S194.67.072 126.916.072zM92.802 19.66a11.12 11.12 0 0 1 11.13 11.13 11.12 11.12 0 0 1-11.13 11.13 11.12 11.12 0 0 1-11.13-11.13 11.12 11.12 0 0 1 11.13-11.13z"/>'
        '<path fill="#FFD43B" d="M128.757 254.126c64.832 0 60.784-28.115 60.784-28.115l-.072-29.127H127.6v-8.745h86.542s41.486 4.705 41.486-60.712c0-65.416-36.21-63.096-36.21-63.096h-21.61v30.355s1.165 36.21-35.632 36.21h-61.362s-34.475-.557-34.475 33.32v56.013s-5.235 33.897 62.518 33.897zm34.114-19.586a11.12 11.12 0 0 1-11.13-11.13 11.12 11.12 0 0 1 11.13-11.131 11.12 11.12 0 0 1 11.13 11.13 11.12 11.12 0 0 1-11.13 11.13z"/>'),
    # Terminal glyph (GitHub octicon), tinted the Shell linguist green
    "logo-shell": ("0 0 16 16",
        '<path fill="#89E051" d="M0 2.75C0 1.784.784 1 1.75 1h12.5c.966 0 1.75.784 1.75 1.75v10.5A1.75 1.75 0 0 1 14.25 15H1.75A1.75 1.75 0 0 1 0 13.25Zm1.75-.25a.25.25 0 0 0-.25.25v10.5c0 .138.112.25.25.25h12.5a.25.25 0 0 0 .25-.25V2.75a.25.25 0 0 0-.25-.25ZM7.25 8a.749.749 0 0 1-.22.53l-2.25 2.25a.749.749 0 0 1-1.06 0 .749.749 0 0 1 0-1.06L5.44 8 3.72 6.28a.749.749 0 1 1 1.06-1.06l2.25 2.25c.141.14.22.331.22.53Zm1.5 1.5h3a.75.75 0 0 1 0 1.5h-3a.75.75 0 0 1 0-1.5Z"/>'),
    # Monochrome brand glyphs (Simple Icons, CC0), each tinted its linguist colour
    "logo-html": ("0 0 24 24",
        '<path fill="#e34c26" d="M1.5 0h21l-1.91 21.563L11.977 24l-8.564-2.438L1.5 0zm7.031 9.75l-.232-2.718 10.059.003.23-2.622L5.412 4.41l.698 8.01h9.126l-.326 3.426-2.91.804-2.955-.81-.188-2.11H6.248l.33 4.171L12 19.351l5.379-1.443.744-8.157H8.531z"/>'),
    "logo-css": ("0 0 24 24",
        '<path fill="#663399" d="M1.5 0h21l-1.91 21.563L11.977 24l-8.565-2.438L1.5 0zm17.09 4.413L5.41 4.41l.213 2.622 10.125.002-.255 2.716h-6.64l.24 2.573h6.182l-.366 3.523-2.91.804-2.956-.81-.188-2.11h-2.61l.29 3.855L12 19.288l5.373-1.53L18.59 4.414z"/>'),
    "logo-js": ("0 0 24 24",
        '<path fill="#f1e05a" d="M0 0h24v24H0V0zm22.034 18.276c-.175-1.095-.888-2.015-3.003-2.873-.736-.345-1.554-.585-1.797-1.14-.091-.33-.105-.51-.046-.705.15-.646.915-.84 1.515-.66.39.12.75.42.976.9 1.034-.676 1.034-.676 1.755-1.125-.27-.42-.404-.601-.586-.78-.63-.705-1.469-1.065-2.834-1.034l-.705.089c-.676.165-1.32.525-1.71 1.005-1.14 1.291-.811 3.541.569 4.471 1.365 1.02 3.361 1.244 3.616 2.205.24 1.17-.87 1.545-1.966 1.41-.811-.18-1.26-.586-1.755-1.336l-1.83 1.051c.21.48.45.689.81 1.109 1.74 1.756 6.09 1.666 6.871-1.004.029-.09.24-.705.074-1.65l.046.067zm-8.983-7.245h-2.248c0 1.938-.009 3.864-.009 5.805 0 1.232.063 2.363-.138 2.711-.33.689-1.18.601-1.566.48-.396-.196-.597-.466-.83-.855-.063-.105-.11-.196-.127-.196l-1.825 1.125c.305.63.75 1.172 1.324 1.517.855.51 2.004.675 3.207.405.783-.226 1.458-.691 1.811-1.411.51-.93.402-2.07.397-3.346.012-2.054 0-4.109 0-6.179l.004-.056z"/>'),
    "logo-ts": ("0 0 24 24",
        '<path fill="#3178c6" d="M1.125 0C.502 0 0 .502 0 1.125v21.75C0 23.498.502 24 1.125 24h21.75c.623 0 1.125-.502 1.125-1.125V1.125C24 .502 23.498 0 22.875 0zm17.363 9.75c.612 0 1.154.037 1.627.111a6.38 6.38 0 0 1 1.306.34v2.458a3.95 3.95 0 0 0-.643-.361 5.093 5.093 0 0 0-.717-.26 5.453 5.453 0 0 0-1.426-.2c-.3 0-.573.028-.819.086a2.1 2.1 0 0 0-.623.242c-.17.104-.3.229-.393.374a.888.888 0 0 0-.14.49c0 .196.053.373.156.529.104.156.252.304.443.444s.423.276.696.41c.273.135.582.274.926.416.47.197.892.407 1.266.628.374.222.695.473.963.753.268.279.472.598.614.957.142.359.214.776.214 1.253 0 .657-.125 1.21-.373 1.656a3.033 3.033 0 0 1-1.012 1.085 4.38 4.38 0 0 1-1.487.596c-.566.12-1.163.18-1.79.18a9.916 9.916 0 0 1-1.84-.164 5.544 5.544 0 0 1-1.512-.493v-2.63a5.033 5.033 0 0 0 3.237 1.2c.333 0 .624-.03.872-.09.249-.06.456-.144.623-.25.166-.108.29-.234.373-.38a1.023 1.023 0 0 0-.074-1.089 2.12 2.12 0 0 0-.537-.5 5.597 5.597 0 0 0-.807-.444 27.72 27.72 0 0 0-1.007-.436c-.918-.383-1.602-.852-2.053-1.405-.45-.553-.676-1.222-.676-2.005 0-.614.123-1.141.369-1.582.246-.441.58-.804 1.004-1.089a4.494 4.494 0 0 1 1.47-.629 7.536 7.536 0 0 1 1.77-.201zm-15.113.188h9.563v2.166H9.506v9.646H6.789v-9.646H3.375z"/>'),
    "logo-go": ("0 0 24 24",
        '<path fill="#00ADD8" d="M1.811 10.231c-.047 0-.058-.023-.035-.059l.246-.315c.023-.035.081-.058.128-.058h4.172c.046 0 .058.035.035.07l-.199.303c-.023.036-.082.07-.117.07zM.047 11.306c-.047 0-.059-.023-.035-.058l.245-.316c.023-.035.082-.058.129-.058h5.328c.047 0 .07.035.058.07l-.093.28c-.012.047-.058.07-.105.07zm2.828 1.075c-.047 0-.059-.035-.035-.07l.163-.292c.023-.035.07-.07.117-.07h2.337c.047 0 .07.035.07.082l-.023.28c0 .047-.047.082-.082.082zm12.129-2.36c-.736.187-1.239.327-1.963.514-.176.046-.187.058-.34-.117-.174-.199-.303-.327-.548-.444-.737-.362-1.45-.257-2.115.175-.795.514-1.204 1.274-1.192 2.22.011.935.654 1.706 1.577 1.835.795.105 1.46-.175 1.987-.77.105-.13.198-.27.315-.434H10.47c-.245 0-.304-.152-.222-.35.152-.362.432-.97.596-1.274a.315.315 0 01.292-.187h4.253c-.023.316-.023.631-.07.947a4.983 4.983 0 01-.958 2.29c-.841 1.11-1.94 1.8-3.33 1.986-1.145.152-2.209-.07-3.143-.77-.865-.655-1.356-1.52-1.484-2.595-.152-1.274.222-2.419.993-3.424.83-1.086 1.928-1.776 3.272-2.02 1.098-.2 2.15-.07 3.096.571.62.41 1.063.97 1.356 1.648.07.105.023.164-.117.2m3.868 6.461c-1.064-.024-2.034-.328-2.852-1.029a3.665 3.665 0 01-1.262-2.255c-.21-1.32.152-2.489.947-3.529.853-1.122 1.881-1.706 3.272-1.95 1.192-.21 2.314-.095 3.33.595.923.63 1.496 1.484 1.648 2.605.198 1.578-.257 2.863-1.344 3.962-.771.783-1.718 1.273-2.805 1.495-.315.06-.63.07-.934.106zm2.78-4.72c-.011-.153-.011-.27-.034-.387-.21-1.157-1.274-1.81-2.384-1.554-1.087.245-1.788.935-2.045 2.033-.21.912.234 1.835 1.075 2.21.643.28 1.285.244 1.905-.07.923-.48 1.425-1.228 1.484-2.233z"/>'),
    "logo-rust": ("0 0 24 24",
        '<path fill="#dea584" d="M23.8346 11.7033l-1.0073-.6236a13.7268 13.7268 0 00-.0283-.2936l.8656-.8069a.3483.3483 0 00-.1154-.578l-1.1066-.414a8.4958 8.4958 0 00-.087-.2856l.6904-.9587a.3462.3462 0 00-.2257-.5446l-1.1663-.1894a9.3574 9.3574 0 00-.1407-.2622l.49-1.0761a.3437.3437 0 00-.0274-.3361.3486.3486 0 00-.3006-.154l-1.1845.0416a6.7444 6.7444 0 00-.1873-.2268l.2723-1.153a.3472.3472 0 00-.417-.4172l-1.1532.2724a14.0183 14.0183 0 00-.2278-.1873l.0415-1.1845a.3442.3442 0 00-.49-.328l-1.076.491c-.0872-.0476-.1742-.0952-.2623-.1407l-.1903-1.1673A.3483.3483 0 0016.256.955l-.9597.6905a8.4867 8.4867 0 00-.2855-.086l-.414-1.1066a.3483.3483 0 00-.5781-.1154l-.8069.8666a9.2936 9.2936 0 00-.2936-.0284L12.2946.1683a.3462.3462 0 00-.5892 0l-.6236 1.0073a13.7383 13.7383 0 00-.2936.0284L9.9803.3374a.3462.3462 0 00-.578.1154l-.4141 1.1065c-.0962.0274-.1903.0567-.2855.086L7.744.955a.3483.3483 0 00-.5447.2258L7.009 2.348a9.3574 9.3574 0 00-.2622.1407l-1.0762-.491a.3462.3462 0 00-.49.328l.0416 1.1845a7.9826 7.9826 0 00-.2278.1873L3.8413 3.425a.3472.3472 0 00-.4171.4171l.2713 1.1531c-.0628.075-.1255.1509-.1863.2268l-1.1845-.0415a.3462.3462 0 00-.328.49l.491 1.0761a9.167 9.167 0 00-.1407.2622l-1.1662.1894a.3483.3483 0 00-.2258.5446l.6904.9587a13.303 13.303 0 00-.087.2855l-1.1065.414a.3483.3483 0 00-.1155.5781l.8656.807a9.2936 9.2936 0 00-.0283.2935l-1.0073.6236a.3442.3442 0 000 .5892l1.0073.6236c.008.0982.0182.1964.0283.2936l-.8656.8079a.3462.3462 0 00.1155.578l1.1065.4141c.0273.0962.0567.1914.087.2855l-.6904.9587a.3452.3452 0 00.2268.5447l1.1662.1893c.0456.088.0922.1751.1408.2622l-.491 1.0762a.3462.3462 0 00.328.49l1.1834-.0415c.0618.0769.1235.1528.1873.2277l-.2713 1.1541a.3462.3462 0 00.4171.4161l1.153-.2713c.075.0638.151.1255.2279.1863l-.0415 1.1845a.3442.3442 0 00.49.327l1.0761-.49c.087.0486.1741.0951.2622.1407l.1903 1.1662a.3483.3483 0 00.5447.2268l.9587-.6904a9.299 9.299 0 00.2855.087l.414 1.1066a.3452.3452 0 00.5781.1154l.8079-.8656c.0972.0111.1954.0203.2936.0294l.6236 1.0073a.3472.3472 0 00.5892 0l.6236-1.0073c.0982-.0091.1964-.0183.2936-.0294l.8069.8656a.3483.3483 0 00.578-.1154l.4141-1.1066a8.4626 8.4626 0 00.2855-.087l.9587.6904a.3452.3452 0 00.5447-.2268l.1903-1.1662c.088-.0456.1751-.0931.2622-.1407l1.0762.49a.3472.3472 0 00.49-.327l-.0415-1.1845a6.7267 6.7267 0 00.2267-.1863l1.1531.2713a.3472.3472 0 00.4171-.416l-.2713-1.1542c.0628-.0749.1255-.1508.1863-.2278l1.1845.0415a.3442.3442 0 00.328-.49l-.49-1.076c.0475-.0872.0951-.1742.1407-.2623l1.1662-.1893a.3483.3483 0 00.2258-.5447l-.6904-.9587.087-.2855 1.1066-.414a.3462.3462 0 00.1154-.5781l-.8656-.8079c.0101-.0972.0202-.1954.0283-.2936l1.0073-.6236a.3442.3442 0 000-.5892zm-6.7413 8.3551a.7138.7138 0 01.2986-1.396.714.714 0 11-.2997 1.396zm-.3422-2.3142a.649.649 0 00-.7715.5l-.3573 1.6685c-1.1035.501-2.3285.7795-3.6193.7795a8.7368 8.7368 0 01-3.6951-.814l-.3574-1.6684a.648.648 0 00-.7714-.499l-1.473.3158a8.7216 8.7216 0 01-.7613-.898h7.1676c.081 0 .1356-.0141.1356-.088v-2.536c0-.074-.0536-.0881-.1356-.0881h-2.0966v-1.6077h2.2677c.2065 0 1.1065.0587 1.394 1.2088.0901.3533.2875 1.5044.4232 1.8729.1346.413.6833 1.2381 1.2685 1.2381h3.5716a.7492.7492 0 00.1296-.0131 8.7874 8.7874 0 01-.8119.9526zM6.8369 20.024a.714.714 0 11-.2997-1.396.714.714 0 01.2997 1.396zM4.1177 8.9972a.7137.7137 0 11-1.304.5791.7137.7137 0 011.304-.579zm-.8352 1.9813l1.5347-.6824a.65.65 0 00.33-.8585l-.3158-.7147h1.2432v5.6025H3.5669a8.7753 8.7753 0 01-.2834-3.348zm6.7343-.5437V8.7836h2.9601c.153 0 1.0792.1772 1.0792.8697 0 .575-.7107.7815-1.2948.7815zm10.7574 1.4862c0 .2187-.008.4363-.0243.651h-.9c-.09 0-.1265.0586-.1265.1477v.413c0 .973-.5487 1.1846-1.0296 1.2382-.4576.0517-.9648-.1913-1.0275-.4717-.2704-1.5186-.7198-1.8436-1.4305-2.4034.8817-.5599 1.799-1.386 1.799-2.4915 0-1.1936-.819-1.9458-1.3769-2.3153-.7825-.5163-1.6491-.6195-1.883-.6195H5.4682a8.7651 8.7651 0 014.907-2.7699l1.0974 1.151a.648.648 0 00.9182.0213l1.227-1.1743a8.7753 8.7753 0 016.0044 4.2762l-.8403 1.8982a.652.652 0 00.33.8585l1.6178.7188c.0283.2875.0425.577.0425.8717zm-9.3006-9.5993a.7128.7128 0 11.984 1.0316.7137.7137 0 01-.984-1.0316zm8.3389 6.71a.7107.7107 0 01.9395-.3625.7137.7137 0 11-.9405.3635z"/>'),
    "logo-ruby": ("0 0 24 24",
        '<path fill="#701516" d="M20.156.083c3.033.525 3.893 2.598 3.829 4.77L24 4.822 22.635 22.71 4.89 23.926h.016C3.433 23.864.15 23.729 0 19.139l1.645-3 2.819 6.586.503 1.172 2.805-9.144-.03.007.016-.03 9.255 2.956-1.396-5.431-.99-3.9 8.82-.569-.615-.51L16.5 2.114 20.159.073l-.003.01zM0 19.089zM5.13 5.073c3.561-3.533 8.157-5.621 9.922-3.84 1.762 1.777-.105 6.105-3.673 9.636-3.563 3.532-8.103 5.734-9.864 3.957-1.766-1.777.045-6.217 3.612-9.75l.003-.003z"/>'),
    "logo-php": ("0 0 24 24",
        '<path fill="#4F5D95" d="M7.01 10.207h-.944l-.515 2.648h.838c.556 0 .97-.105 1.242-.314.272-.21.455-.559.55-1.049.092-.47.05-.802-.124-.995-.175-.193-.523-.29-1.047-.29zM12 5.688C5.373 5.688 0 8.514 0 12s5.373 6.313 12 6.313S24 15.486 24 12c0-3.486-5.373-6.312-12-6.312zm-3.26 7.451c-.261.25-.575.438-.917.551-.336.108-.765.164-1.285.164H5.357l-.327 1.681H3.652l1.23-6.326h2.65c.797 0 1.378.209 1.744.628.366.418.476 1.002.33 1.752a2.836 2.836 0 0 1-.305.847c-.143.255-.33.49-.561.703zm4.024.715l.543-2.799c.063-.318.039-.536-.068-.651-.107-.116-.336-.174-.687-.174H11.46l-.704 3.625H9.388l1.23-6.327h1.367l-.327 1.682h1.218c.767 0 1.295.134 1.586.401s.378.7.263 1.299l-.572 2.944h-1.389zm7.597-2.265a2.782 2.782 0 0 1-.305.847c-.143.255-.33.49-.561.703a2.44 2.44 0 0 1-.917.551c-.336.108-.765.164-1.286.164h-1.18l-.327 1.682h-1.378l1.23-6.326h2.649c.797 0 1.378.209 1.744.628.366.417.477 1.001.331 1.751zM17.766 10.207h-.943l-.516 2.648h.838c.557 0 .971-.105 1.242-.314.272-.21.455-.559.551-1.049.092-.47.049-.802-.125-.995s-.524-.29-1.047-.29z"/>'),
    "logo-cpp": ("0 0 24 24",
        '<path fill="#f34b7d" d="M22.394 6c-.167-.29-.398-.543-.652-.69L12.926.22c-.509-.294-1.34-.294-1.848 0L2.26 5.31c-.508.293-.923 1.013-.923 1.6v10.18c0 .294.104.62.271.91.167.29.398.543.652.69l8.816 5.09c.508.293 1.34.293 1.848 0l8.816-5.09c.254-.147.485-.4.652-.69.167-.29.27-.616.27-.91V6.91c.003-.294-.1-.62-.268-.91zM12 19.11c-3.92 0-7.109-3.19-7.109-7.11 0-3.92 3.19-7.11 7.11-7.11a7.133 7.133 0 016.156 3.553l-3.076 1.78a3.567 3.567 0 00-3.08-1.78A3.56 3.56 0 008.444 12 3.56 3.56 0 0012 15.555a3.57 3.57 0 003.08-1.778l3.078 1.78A7.135 7.135 0 0112 19.11zm7.11-6.715h-.79v.79h-.79v-.79h-.79v-.79h.79v-.79h.79v.79h.79zm2.962 0h-.79v.79h-.79v-.79h-.79v-.79h.79v-.79h.79v.79h.79z"/>'),
    "logo-c": ("0 0 24 24",
        '<path fill="#555555" d="M16.5921 9.1962s-.354-3.298-3.627-3.39c-3.2741-.09-4.9552 2.474-4.9552 6.14 0 3.6651 1.858 6.5972 5.0451 6.5972 3.184 0 3.5381-3.665 3.5381-3.665l6.1041.365s.36 3.31-2.196 5.836c-2.552 2.5241-5.6901 2.9371-7.8762 2.9201-2.19-.017-5.2261.034-8.1602-2.97-2.938-3.0101-3.436-5.9302-3.436-8.8002 0-2.8701.556-6.6702 4.047-9.5502C7.444.72 9.849 0 12.254 0c10.0422 0 10.7172 9.2602 10.7172 9.2602z"/>'),
    "logo-csharp": ("0 0 24 24",
        '<path fill="#7355dd" d="M1.194 7.543v8.913c0 1.103.588 2.122 1.544 2.674l7.718 4.456a3.086 3.086 0 0 0 3.088 0l7.718-4.456a3.087 3.087 0 0 0 1.544-2.674V7.543a3.084 3.084 0 0 0-1.544-2.673L13.544.414a3.086 3.086 0 0 0-3.088 0L2.738 4.87a3.085 3.085 0 0 0-1.544 2.673Zm5.403 2.914v3.087a.77.77 0 0 0 .772.772.773.773 0 0 0 .772-.772.773.773 0 0 1 1.317-.546.775.775 0 0 1 .226.546 2.314 2.314 0 1 1-4.631 0v-3.087c0-.615.244-1.203.679-1.637a2.312 2.312 0 0 1 3.274 0c.434.434.678 1.023.678 1.637a.769.769 0 0 1-.226.545.767.767 0 0 1-1.091 0 .77.77 0 0 1-.226-.545.77.77 0 0 0-.772-.772.771.771 0 0 0-.772.772Zm12.35 3.087a.77.77 0 0 1-.772.772h-.772v.772a.773.773 0 0 1-1.544 0v-.772h-1.544v.772a.773.773 0 0 1-1.317.546.775.775 0 0 1-.226-.546v-.772H12a.771.771 0 1 1 0-1.544h.772v-1.543H12a.77.77 0 1 1 0-1.544h.772v-.772a.773.773 0 0 1 1.317-.546.775.775 0 0 1 .226.546v.772h1.544v-.772a.773.773 0 0 1 1.544 0v.772h.772a.772.772 0 0 1 0 1.544h-.772v1.543h.772a.776.776 0 0 1 .772.772Zm-3.088-2.315h-1.544v1.543h1.544v-1.543Z"/>'),
    "logo-jupyter": ("0 0 24 24",
        '<path fill="#DA5B0B" d="M7.157 22.201A1.784 1.799 0 0 1 5.374 24a1.784 1.799 0 0 1-1.784-1.799 1.784 1.799 0 0 1 1.784-1.799 1.784 1.799 0 0 1 1.783 1.799zM20.582 1.427a1.415 1.427 0 0 1-1.415 1.428 1.415 1.427 0 0 1-1.416-1.428A1.415 1.427 0 0 1 19.167 0a1.415 1.427 0 0 1 1.415 1.427zM4.992 3.336A1.047 1.056 0 0 1 3.946 4.39a1.047 1.056 0 0 1-1.047-1.055A1.047 1.056 0 0 1 3.946 2.28a1.047 1.056 0 0 1 1.046 1.056zm7.336 1.517c3.769 0 7.06 1.38 8.768 3.424a9.363 9.363 0 0 0-3.393-4.547 9.238 9.238 0 0 0-5.377-1.728A9.238 9.238 0 0 0 6.95 3.73a9.363 9.363 0 0 0-3.394 4.547c1.713-2.04 5.004-3.424 8.772-3.424zm.001 13.295c-3.768 0-7.06-1.381-8.768-3.425a9.363 9.363 0 0 0 3.394 4.547A9.238 9.238 0 0 0 12.33 21a9.238 9.238 0 0 0 5.377-1.729 9.363 9.363 0 0 0 3.393-4.547c-1.712 2.044-5.003 3.425-8.772 3.425Z"/>'),
    "logo-kotlin": ("0 0 24 24",
        '<path fill="#A97BFF" d="M24 24H0V0h24L12 12Z"/>'),
    "logo-swift": ("0 0 24 24",
        '<path fill="#F05138" d="M7.508 0c-.287 0-.573 0-.86.002-.241.002-.483.003-.724.01-.132.003-.263.009-.395.015A9.154 9.154 0 0 0 4.348.15 5.492 5.492 0 0 0 2.85.645 5.04 5.04 0 0 0 .645 2.848c-.245.48-.4.972-.495 1.5-.093.52-.122 1.05-.136 1.576a35.2 35.2 0 0 0-.012.724C0 6.935 0 7.221 0 7.508v8.984c0 .287 0 .575.002.862.002.24.005.481.012.722.014.526.043 1.057.136 1.576.095.528.25 1.02.495 1.5a5.03 5.03 0 0 0 2.205 2.203c.48.244.97.4 1.498.495.52.093 1.05.124 1.576.138.241.007.483.009.724.01.287.002.573.002.86.002h8.984c.287 0 .573 0 .86-.002.241-.001.483-.003.724-.01a10.523 10.523 0 0 0 1.578-.138 5.322 5.322 0 0 0 1.498-.495 5.035 5.035 0 0 0 2.203-2.203c.245-.48.4-.972.495-1.5.093-.52.124-1.05.138-1.576.007-.241.009-.481.01-.722.002-.287.002-.575.002-.862V7.508c0-.287 0-.573-.002-.86a33.662 33.662 0 0 0-.01-.724 10.5 10.5 0 0 0-.138-1.576 5.328 5.328 0 0 0-.495-1.5A5.039 5.039 0 0 0 21.152.645 5.32 5.32 0 0 0 19.654.15a10.493 10.493 0 0 0-1.578-.138 34.98 34.98 0 0 0-.722-.01C17.067 0 16.779 0 16.492 0H7.508zm6.035 3.41c4.114 2.47 6.545 7.162 5.549 11.131-.024.093-.05.181-.076.272l.002.001c2.062 2.538 1.5 5.258 1.236 4.745-1.072-2.086-3.066-1.568-4.088-1.043a6.803 6.803 0 0 1-.281.158l-.02.012-.002.002c-2.115 1.123-4.957 1.205-7.812-.022a12.568 12.568 0 0 1-5.64-4.838c.649.48 1.35.902 2.097 1.252 3.019 1.414 6.051 1.311 8.197-.002C9.651 12.73 7.101 9.67 5.146 7.191a10.628 10.628 0 0 1-1.005-1.384c2.34 2.142 6.038 4.83 7.365 5.576C8.69 8.408 6.208 4.743 6.324 4.86c4.436 4.47 8.528 6.996 8.528 6.996.154.085.27.154.36.213.085-.215.16-.437.224-.668.708-2.588-.09-5.548-1.893-7.992z"/>'),
    "logo-dart": ("0 0 24 24",
        '<path fill="#00B4AB" d="M4.105 4.105S9.158 1.58 11.684.316a3.079 3.079 0 0 1 1.481-.315c.766.047 1.677.788 1.677.788L24 9.948v9.789h-4.263V24H9.789l-9-9C.303 14.5 0 13.795 0 13.105c0-.319.18-.818.316-1.105l3.789-7.895zm.679.679v11.787c.002.543.021 1.024.498 1.508L10.204 23h8.533v-4.263L4.784 4.784zm12.055-.678c-.899-.896-1.809-1.78-2.74-2.643-.302-.267-.567-.468-1.07-.462-.37.014-.87.195-.87.195L6.341 4.105l10.498.001z"/>'),
    "logo-vue": ("0 0 24 24",
        '<path fill="#41b883" d="M24,1.61H14.06L12,5.16,9.94,1.61H0L12,22.39ZM12,14.08,5.16,2.23H9.59L12,6.41l2.41-4.18h4.43Z"/>'),
    "logo-svelte": ("0 0 24 24",
        '<path fill="#ff3e00" d="M10.354 21.125a4.44 4.44 0 0 1-4.765-1.767 4.109 4.109 0 0 1-.703-3.107 3.898 3.898 0 0 1 .134-.522l.105-.321.287.21a7.21 7.21 0 0 0 2.186 1.092l.208.063-.02.208a1.253 1.253 0 0 0 .226.83 1.337 1.337 0 0 0 1.435.533 1.231 1.231 0 0 0 .343-.15l5.59-3.562a1.164 1.164 0 0 0 .524-.778 1.242 1.242 0 0 0-.211-.937 1.338 1.338 0 0 0-1.435-.533 1.23 1.23 0 0 0-.343.15l-2.133 1.36a4.078 4.078 0 0 1-1.135.499 4.44 4.44 0 0 1-4.765-1.766 4.108 4.108 0 0 1-.702-3.108 3.855 3.855 0 0 1 1.742-2.582l5.589-3.563a4.072 4.072 0 0 1 1.135-.499 4.44 4.44 0 0 1 4.765 1.767 4.109 4.109 0 0 1 .703 3.107 3.943 3.943 0 0 1-.134.522l-.105.321-.286-.21a7.204 7.204 0 0 0-2.187-1.093l-.208-.063.02-.207a1.255 1.255 0 0 0-.226-.831 1.337 1.337 0 0 0-1.435-.532 1.231 1.231 0 0 0-.343.15L8.62 9.368a1.162 1.162 0 0 0-.524.778 1.24 1.24 0 0 0 .211.937 1.338 1.338 0 0 0 1.435.533 1.235 1.235 0 0 0 .344-.151l2.132-1.36a4.067 4.067 0 0 1 1.135-.498 4.44 4.44 0 0 1 4.765 1.766 4.108 4.108 0 0 1 .702 3.108 3.857 3.857 0 0 1-1.742 2.583l-5.589 3.562a4.072 4.072 0 0 1-1.135.499m10.358-17.95C18.484-.015 14.082-.96 10.9 1.068L5.31 4.63a6.412 6.412 0 0 0-2.896 4.295 6.753 6.753 0 0 0 .666 4.336 6.43 6.43 0 0 0-.96 2.396 6.833 6.833 0 0 0 1.168 5.167c2.229 3.19 6.63 4.135 9.812 2.108l5.59-3.562a6.41 6.41 0 0 0 2.896-4.295 6.756 6.756 0 0 0-.665-4.336 6.429 6.429 0 0 0 .958-2.396 6.831 6.831 0 0 0-1.167-5.168Z"/>'),
}

# GitHub language → symbol id in LOGO_MARKS
LOGOS = {
    "Python": "logo-python", "Shell": "logo-shell", "HTML": "logo-html",
    "CSS": "logo-css", "JavaScript": "logo-js", "TypeScript": "logo-ts",
    "Go": "logo-go", "Rust": "logo-rust", "Ruby": "logo-ruby", "PHP": "logo-php",
    "C++": "logo-cpp", "C": "logo-c", "C#": "logo-csharp",
    "Jupyter Notebook": "logo-jupyter", "Kotlin": "logo-kotlin",
    "Swift": "logo-swift", "Dart": "logo-dart", "Vue": "logo-vue",
    "Svelte": "logo-svelte",
}


def logo_defs(langs) -> str:
    """<symbol> defs for just the languages present on the card, keyed once each.
    Some brand paths run to a few KB, so emitting only the marks actually drawn
    keeps every widget.svg lean rather than carrying the whole registry."""
    ids: list[str] = []
    for lang in langs:
        sid = LOGOS.get(lang)
        if sid and sid not in ids:
            ids.append(sid)
    return "".join(
        f'<symbol id="{sid}" viewBox="{LOGO_MARKS[sid][0]}">{LOGO_MARKS[sid][1]}'
        f'</symbol>'
        for sid in ids
    )

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


def profile_name() -> str:
    """The account's GitHub display name (the profile 'name' field), e.g.
    'Luke Johnson', falling back to the login when it's unset. Keeps a fork's
    header a real name with nothing to configure; WIDGET_NAME still overrides."""
    try:
        return (gh(f"/users/{USER}").get("name") or "").strip() or USER
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"warn: profile name fetch failed ({e})", file=sys.stderr)
        return USER


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


def days_since(iso: str) -> int | None:
    """Whole days between an ISO timestamp and now, or None if unparseable."""
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return (datetime.now(timezone.utc) - d).days


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
    # A project only earns a card if it saw real activity inside the heatmap
    # window. pushed_at older than HEAT_DAYS can't hold a commit in that window,
    # so it's a cheap pre-filter (no API call); the heat sum then confirms actual
    # default-branch commits — a push to a side branch bumps pushed_at but leaves
    # the heatmap empty, and we don't want those hollow cards.
    active = []
    for pr in out:
        ago = days_since(pr["pushed_at"])
        if ago is None or ago >= HEAT_DAYS:
            continue
        pr["heat"] = commit_days(pr["name"])
        pr["commits"] = sum(pr["heat"])
        if pr["commits"] > 0:
            active.append(pr)
        if len(active) >= limit:
            break
    return active


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


# ── auto-derived tagline ─────────────────────────────────────────────────────
# The header's top-right strip (the old "data science · agentic engineering"
# tagline) is regenerated from the data the card already reviewed rather than
# hand-set: the names, descriptions and languages of my own projects plus the
# upstream repos I landed PRs in, scored against a small curated lexicon of
# domain labels. Deterministic and offline like the rest of the card — the same
# repos always yield the same keywords. Short, ambiguous triggers are space-
# padded (" ml ", " api ") so they only match on word boundaries, not inside
# unrelated words. WIDGET_TAGLINE overrides it; an empty WIDGET_TAGLINE hides it.
TAGLINE_LEXICON = [
    ("AGENTIC ENGINEERING",
     (" agent", "agentic", " mcp", "autonomous", "orchestrat", " swarm")),
    ("LLM SYSTEMS",
     (" llm", "claude", " gpt", "openai", "anthropic", "prompt", " rag",
      "gemma", "ollama", " ai ")),
    ("DATA SCIENCE",
     (" data", "pandas", "numpy", "dataframe", "analytic", "analysis",
      "dataset", "jupyter", "notebook", "plotly")),
    ("MACHINE LEARNING",
     ("machine learning", "pytorch", "tensorflow", "sklearn", "scikit",
      "neural", "embedding", " ml ")),
    ("AUTOMATION",
     ("automat", "pipeline", " workflow", " bot ", " cron", "scheduler",
      " etl", "scrap")),
    ("DEV TOOLING",
     (" cli", " sdk", "devtool", "tooling", "framework", "compiler", "linter")),
    ("WEB & APIs",
     (" api ", "fastapi", "flask", "django", "backend", " server", " http",
      " rest")),
]


def derive_tagline(projects: list[dict], c: dict, limit: int = TAGLINE_MAX) -> str:
    """A short, uppercase keyword strip mined from the reviewed data.

    Scores the curated lexicon against the text the card already collected —
    own-project names/descriptions/languages and the upstream repos PRs landed
    in — and returns the top `limit` labels joined with ` · `. On a tie the
    lexicon's own order wins (stable sort), so stronger signals lead. Falls back
    to the most common project language when nothing scores, so a fresh fork
    still gets a sensible strip. Deterministic: same repos → same keywords.
    """
    parts: list[str] = []
    langs: list[str] = []
    for p in projects:
        parts += [p.get("name", ""), p.get("description", ""), p.get("language", "")]
        if p.get("language"):
            langs.append(p["language"])
    for b in c.get("bars", []):
        parts += [b.get("name", ""), b.get("full", "")]

    raw = " ".join(parts).lower()
    for ch in "_-/.,:()[]":
        raw = raw.replace(ch, " ")
    corpus = " " + " ".join(raw.split()) + " "  # padded so boundary triggers match

    scored = [
        (sum(corpus.count(tk) for tk in triggers), label)
        for label, triggers in TAGLINE_LEXICON
    ]
    scored = [pair for pair in scored if pair[0]]
    scored.sort(key=lambda pair: pair[0], reverse=True)  # stable → ties keep order
    keywords = [label for _, label in scored[:limit]]

    if len(keywords) < limit and langs:
        top_lang = max(sorted(set(langs)), key=langs.count).upper()
        if top_lang not in keywords:
            keywords.append(top_lang)

    return " · ".join(keywords[:limit])


# ── render ───────────────────────────────────────────────────────────────────
def t(s: str, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def heat_color(n: int) -> str:
    """Map a daily commit count to a ramp class — fixed thresholds so even a
    single commit reads as clearly green (GitHub-style), not relative-faint."""
    if n <= 0:
        return "h0"
    if n <= 1:
        return "h1"
    if n <= 3:
        return "h2"
    if n <= 6:
        return "h3"
    return "h4"


def octicon(name: str, x, y, cls: str, size: int = 16) -> str:
    """A themed 16px GitHub octicon as a positioned nested <svg>."""
    return (
        f'<svg x="{x}" y="{y}" width="{size}" height="{size}" viewBox="0 0 16 16">'
        f'<path class="{cls}" d="{STAT_ICONS[name]}"/></svg>'
    )


def kfmt(n: int) -> str:
    """Compact star count: 1234 -> '1.2k', 950 -> '950'."""
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def nice_ticks(peak: int) -> tuple[int, list[int]]:
    """A rounded axis ceiling >= peak plus evenly-spaced integer ticks up to it,
    so the sparkline's y-axis reads in clean round numbers (0, 5, 10, 15, 20)
    rather than a bare 0-and-peak pair. Aims for at most four intervals."""
    if peak <= 0:
        return 1, [0, 1]
    step = 1
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if peak / step <= 4:
            break
    top = -(-peak // step) * step  # ceil(peak / step) * step
    return top, list(range(0, top + 1, step))


def _style_block() -> str:
    """The <style>: theme variables + the light override + utility classes,
    then the one-shot entrance motion (gated behind prefers-reduced-motion)."""
    dark = "".join(f"--{k}:{v};" for k, v in DARK_VARS.items())
    light = "".join(f"--{k}:{v};" for k, v in LIGHT_VARS.items())
    return (
        "<style>"
        f":root{{{dark}}}"
        f"@media (prefers-color-scheme:light){{:root{{{light}}}}}"
        ".t-fg{fill:var(--fg)}.t-mut{fill:var(--muted)}.t-cyan{fill:var(--cyan)}"
        ".t-green{fill:var(--green)}.t-blue{fill:var(--blue)}"
        ".t-purple{fill:var(--purple)}.t-orange{fill:var(--orange)}"
        ".t-panel{fill:var(--panel)}.t-panel2{fill:var(--panel2)}"
        ".s-mut{stroke:var(--muted)}.s-green{stroke:var(--green)}"
        ".h0{fill:var(--h0)}.h1{fill:var(--h1)}.h2{fill:var(--h2)}"
        ".h3{fill:var(--h3)}.h4{fill:var(--h4)}"
        "@media (prefers-reduced-motion: no-preference){"
        ".bar{transform-box:fill-box;transform-origin:left;"
        "animation:grow .55s cubic-bezier(.2,.7,.3,1) backwards}"
        ".cell{animation:fade .45s ease-out backwards}"
        ".pulse{animation:pulse 3s ease-in-out infinite}"
        ".line{stroke-dasharray:620;stroke-dashoffset:620;"
        "animation:draw 1s ease-out .25s forwards}"
        ".fill,.dot{animation:fade .7s ease-out .7s backwards}"
        "}"
        "@keyframes grow{from{transform:scaleX(0)}}"
        "@keyframes fade{from{opacity:0}}"
        "@keyframes draw{to{stroke-dashoffset:0}}"
        "@keyframes pulse{50%{opacity:.4}}"
        "</style>"
    )


def _lang_mark(lang: str, x: int, y: int, size: int = 14):
    """(markup, name_x) for a language mark: a logo <use> if we have one, else a
    coloured dot (linguist colour, fixed across themes), else nothing."""
    sym = LOGOS.get(lang)
    if sym:
        return (f'<use href="#{sym}" x="{x}" y="{y}" width="{size}" '
                f'height="{size}"/>', x + size + 6)
    if lang:
        cx, cy, r = x + size / 2, y + size / 2, size * 0.29
        dot = LANG_COLOURS.get(lang)
        fill = f'fill="{dot}"' if dot else f'class="{C_MUTED}"'
        return (f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" {fill}/>',
                x + size + 2)
    return ("", x)


def render_svg(projects: list[dict], c: dict, name: str = "", tagline: str = "") -> str:
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
    spark_h = 48
    # sparkline height includes room for the x-axis month labels
    right_bottom = (spark_top + spark_h + 18) if has_spark else bars_end
    H = max(left_bottom, right_bottom) + 30

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logo_syms = logo_defs(pr.get("language", "") for pr in projects)
    p: list[str] = []

    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" '
        f'font-family="\'Inter\',\'Segoe UI\',-apple-system,sans-serif">'
    )
    p.append(
        '<defs>'
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" style="stop-color:var(--bg0)"/>'
        '<stop offset="1" style="stop-color:var(--bg1)"/>'
        '</linearGradient>'
        '<linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" style="stop-color:var(--bar0)"/>'
        '<stop offset="1" style="stop-color:var(--bar1)"/>'
        '</linearGradient>'
        '<linearGradient id="spark" x1="0" y1="0" x2="0" y2="1">'
        '<stop offset="0" style="stop-color:var(--green)" stop-opacity="0.35"/>'
        '<stop offset="1" style="stop-color:var(--green)" stop-opacity="0.02"/>'
        f'</linearGradient>{logo_syms}</defs>'
    )
    p.append(_style_block())
    p.append(f'<rect width="{W}" height="{H}" rx="16" fill="url(#bg)"/>')
    p.append(
        f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="15" fill="none" '
        f'class="{S_MUTED}" stroke-opacity="0.30"/>'
    )

    # header
    p.append(
        f'<text x="32" y="50" class="{C_FG}" font-size="27" font-weight="700">'
        f'{escape(name)}</text>'
    )
    if tagline:
        p.append(
            f'<text x="{W-32}" y="44" class="{C_CYAN}" font-size="13" '
            f'text-anchor="end" letter-spacing="2">{escape(t(tagline, 46))}</text>'
        )
    p.append(
        f'<text x="{W-32}" y="76" class="{C_MUTED}" font-size="19" '
        f'text-anchor="end">{today}</text>'
    )

    # key-insight caption — a generated finding, not a totals summary. The
    # eyebrow + coloured numerals read as one curated statement about the core
    # (high-star) open-source work; the long tail is left to the merged-PR bars.
    p.append(
        f'<text x="32" y="97" class="{C_CYAN}" font-size="11.5" '
        f'letter-spacing="1.5">✦ KEY INSIGHT</text>'
    )
    # insight laid out as positioned runs so the merge/repo icons sit inline,
    # just left of their coloured numbers; textLength pins each text run's
    # advance so the icons stay aligned regardless of the renderer's metrics.
    isz, ix, iy = 21, 32, 129
    thr = f'★ {kfmt(CORE_STARS)}+'
    if c["core_projects"]:
        runs = [
            ("i", "merge", C_PURPLE), ("n", str(c["core_contributions"]), C_PURPLE),
            ("t", " merged PRs across ", C_FG),
            ("i", "repo", C_BLUE), ("n", str(c["core_projects"]), C_BLUE),
            ("t", " open-source projects, each with ", C_FG),
            ("n", thr, C_ORANGE), ("t", " stars.", C_FG),
        ]
    elif c["merged_upstream"]:
        runs = [
            ("i", "merge", C_PURPLE), ("n", str(c["merged_upstream"]), C_PURPLE),
            ("t", " merged PRs across ", C_FG),
            ("i", "repo", C_BLUE), ("n", str(c["merged_projects"]), C_BLUE),
            ("t", " open-source projects.", C_FG),
        ]
    else:
        runs = [("t", "Building in the open — first contributions landing soon.", C_FG)]

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
            f'<text x="{ix:.0f}" y="{iy}" class="{col}" font-size="{isz}"{bold} '
            f'textLength="{w:.0f}" lengthAdjust="spacingAndGlyphs" '
            f'xml:space="preserve">{escape(val)}</text>'
        )
        ix += w

    p.append(
        f'<line x1="32" y1="146" x2="{W-32}" y2="146" '
        f'class="{S_MUTED}" stroke-opacity="0.25"/>'
    )

    # ── left: my own projects (cards with commit heatmap) ────────────────────
    p.append(
        f'<text x="32" y="174" class="{C_CYAN}" font-size="11.5" '
        f'letter-spacing="1.5">PROJECTS I&apos;M WORKING ON</text>'
    )
    p.append(
        f'<text x="442" y="174" class="{C_MUTED}" font-size="10" '
        f'text-anchor="end" letter-spacing="0.5">commits / {HEAT_DAYS}d</text>'
    )
    cy = 188
    if projects:
        for pr in projects:
            p.append(
                f'<rect x="{cx}" y="{cy}" width="{cw}" height="{card_h}" rx="10" '
                f'class="{C_PANEL}"/>'
            )
            mark, name_x = _lang_mark(pr["language"], cx + 16, cy + 9, 14)
            if not pr["language"]:
                name_x = cx + 16
            p.append(mark)
            p.append(
                f'<text x="{name_x}" y="{cy+21}" class="{C_FG}" font-size="15" '
                f'font-weight="600">{escape(t(pr["name"], 20))}</text>'
            )
            p.append(
                f'<text x="{cx+cw-16}" y="{cy+38}" class="{C_MUTED}" '
                f'font-size="10.5" text-anchor="end">'
                f'{pr.get("commits", 0)} commits</text>'
            )
            p.append(
                f'<text x="{cx+16}" y="{cy+38}" class="{C_MUTED}" '
                f'font-size="12">{escape(pr["desc_line"])}</text>'
            )
            heat = pr.get("heat") or [0] * HEAT_DAYS
            x0 = cx + cw - 16 - strip_w
            for i, n in enumerate(heat):
                if i == HEAT_DAYS - 1 and n > 0:
                    cls, style = f'{heat_color(n)} pulse', ""
                else:
                    cls = f'{heat_color(n)} cell'
                    style = f' style="animation-delay:{0.1 + i * 0.03:.2f}s"'
                p.append(
                    f'<rect x="{x0 + i*(sq+gap)}" y="{cy+11}" width="{sq}" '
                    f'height="{sq}" rx="2" class="{cls}"{style}/>'
                )
            cy += pitch
    else:
        p.append(
            f'<text x="{cx+4}" y="{cy+18}" class="{C_MUTED}" font-size="13">'
            f'building it</text>'
        )

    # ── right: merged PRs by upstream project (bars) ─────────────────────────
    bx = 470
    p.append(
        f'<text x="{bx}" y="174" class="{C_GREEN}" font-size="11.5" '
        f'letter-spacing="1.5">MERGED PRs</text>'
    )
    bars = c["bars"]
    maxv = max((b["value"] for b in bars), default=1) or 1
    name_x = bx + 52  # left gutter reserved for the star column
    longest = max((len(t(b["name"], 28)) for b in bars), default=0)
    track_x = name_x + min(int(longest * 6.7) + 14, 210)
    track_w = max(W - 32 - 34 - track_x, 60)
    by = 198
    if not bars:
        p.append(
            f'<text x="{bx+4}" y="{by+18}" class="{C_MUTED}" font-size="13">'
            f'none merged upstream yet</text>'
        )
    for i, b in enumerate(bars):
        bw = max(int((b["value"] / maxv) * track_w), 9)
        if b.get("stars"):
            p.append(
                f'<text x="{bx}" y="{by+11}" class="{C_ORANGE}" '
                f'font-size="10.5">★</text>'
            )
            p.append(
                f'<text x="{bx+44}" y="{by+11}" class="{C_MUTED}" '
                f'font-size="10.5" text-anchor="end">{kfmt(b["stars"])}</text>'
            )
        p.append(
            f'<text x="{name_x}" y="{by+11}" class="{C_FG}" font-size="13">'
            f'{escape(t(b["name"], 28))}</text>'
        )
        p.append(
            f'<rect x="{track_x}" y="{by}" width="{bw}" height="14" rx="4" '
            f'fill="url(#bar)" class="bar" '
            f'style="animation-delay:{0.1 + i * 0.08:.2f}s"/>'
        )
        p.append(
            f'<text x="{track_x+track_w+10}" y="{by+11}" class="{C_GREEN}" '
            f'font-size="12.5" font-weight="600">{b["value"]}</text>'
        )
        by += 30

    # ── merged-PR cadence, last 12 months (area sparkline with light axes);
    # skipped entirely when the year is all zeros — no flatline chart ────────
    monthly = c["monthly"]
    if has_spark:
        p.append(
            f'<text x="{bx}" y="{spark_label_y}" class="{C_MUTED}" font-size="10" '
            f'letter-spacing="1">MERGED PRs / MONTH</text>'
        )
        sw = W - 32 - bx
        speak = max(monthly)
        # a rounded axis ceiling so the y-axis carries several round ticks
        # (0, 5, 10, 15, 20) rather than a bare 0-and-peak pair
        axis_top, ticks = nice_ticks(speak)
        xstep = sw / (len(monthly) - 1)
        base = spark_top + spark_h
        pts = [
            (bx + i * xstep, base - (v / axis_top) * spark_h)
            for i, v in enumerate(monthly)
        ]
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)

        # y-gridlines behind the area: a solid zero baseline plus dashed ticks
        # up to the ceiling, each labelled in the gutter just left of the plot
        for tv in ticks:
            gy = base - (tv / axis_top) * spark_h
            dash = "" if tv == 0 else ' stroke-dasharray="3 3"'
            op = "0.25" if tv == 0 else "0.15"
            p.append(
                f'<line x1="{bx}" y1="{gy:.1f}" x2="{W-32}" y2="{gy:.1f}" '
                f'class="{S_MUTED}" stroke-opacity="{op}"{dash}/>'
            )
            p.append(
                f'<text x="{bx-6}" y="{gy+3:.1f}" class="{C_MUTED}" font-size="9" '
                f'text-anchor="end">{tv}</text>'
            )

        p.append(
            f'<polygon points="{pts[0][0]:.1f},{base} {line} '
            f'{pts[-1][0]:.1f},{base}" fill="url(#spark)" class="fill"/>'
        )
        p.append(
            f'<polyline points="{line}" fill="none" class="line {S_GREEN}" '
            f'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>'
        )
        p.append(
            f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3" '
            f'class="{C_GREEN} dot"/>'
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
                f'<text x="{pts[idx][0]:.1f}" y="{axis_y}" class="{C_MUTED}" '
                f'font-size="9" text-anchor="{anchor}">{_mlabel(idx, yr)}</text>'
            )

    p.append("</svg>")
    return "".join(p)


def main():
    projects = collect_projects()
    contrib = collect_contributions()
    name = NAME_ENV or profile_name()  # display name, not the login, unless set
    # unset → derive from the data; explicit value (incl. "") wins verbatim
    tagline = derive_tagline(projects, contrib) if TAGLINE_ENV is None else TAGLINE_ENV
    svg = render_svg(projects, contrib, name, tagline)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg, encoding="utf-8")
    print(
        f"wrote {OUT} ({len(svg)} bytes) · "
        f"{len(projects)} projects / {contrib['merged']} merged / "
        f"{len(contrib['bars'])} bars · tagline: {tagline or '(none)'}"
    )


if __name__ == "__main__":
    main()
