# github-profile-widget


<a href="https://github.com/LukeTheoJohnson?tab=repositories">
<img src="assets/widget.svg" alt="Profile widget demo" width="100%"/>
</a>

This creates a dynamic profile widget using real contribution data from the user. It gets refreshed daily by GitHub Actions.

Private repos are not included. merged PR data is explicitly scoped to public repositories (`is:public`).

The left column is "what I'm working on" over the last 14 days: your own repos with recent commits, interleaved with upstream repos where one of your PRs saw activity. Upstream cards swap the language mark for a git-merge (landed) or git-pull-request (still open) glyph and show the repo as `owner/name`, so a contribution to someone else's project never reads as one of yours.

---

## Setup

**1. Fork this repo.**

Your GitHub username is detected automatically from the Actions environment with no code edits needed. Enable Actions on the fork if prompted (Settings → Actions → Allow all actions).

**2. Set your display name and tagline** under Settings → Secrets and variables → Actions → **Variables** (not Secrets):

| Variable | Default | Description |
|---|---|---|
| `WIDGET_NAME` | your GitHub display name | Header name. Defaults to the `name` on your GitHub profile (e.g. `Luke Johnson`), falling back to your username |
| `WIDGET_TAGLINE` | *auto-derived* | Identified-stack strip beside the KEY INSIGHT eyebrow. Left unset, it's generated from your data (see below). Set a literal string to override, e.g. `OPEN SOURCE · PYTHON · ML`, or an empty value to hide it |
| `WIDGET_TAGLINE_KEYWORDS` | `3` | How many keywords the auto tagline shows |
| `WIDGET_PROJECT_LIMIT` | `6` | Max cards on the left (own projects plus upstream PR cards) |
| `WIDGET_BAR_LIMIT` | `10` | Max merged-PR repo bars on the right |
| `WIDGET_CORE_STARS` | `10000` | Star threshold for the key-insight caption to call a project "core" |

The identified-stack strip beside the KEY INSIGHT eyebrow (e.g. `DATA SCIENCE · AGENTIC ENGINEERING`) is generated from data the card already reviews: names, descriptions and languages of projects plus the upstream PRs. That info in matched against a lexicon of domain labels. It's deterministic and needs no API key, so the same repos always yield the same keywords, and a fresh fork gets a relevant headline.

**3. Trigger the first run** manually: Actions → profile-widget → Run workflow. The widget generates immediately and commits `assets/widget.svg`. After that it refreshes daily at 06:17 UTC.

**4. Embed it** in your profile README (`YOUR_USERNAME/YOUR_USERNAME`):

```markdown
<a href="https://github.com/YOUR_USERNAME?tab=repositories">
<img src="https://raw.githubusercontent.com/YOUR_USERNAME/github-profile-widget/HEAD/assets/widget.svg" width="100%"/>
</a>
```

---

## How it works

- Python standard library (`urllib`, `json`, `pathlib`) with no external dependencies
- Uses the built-in `GITHUB_TOKEN` provided by Actions.
- Generates a single SVG with CSS entrance
- The workflow handles push races with a fetch-reset-retry loop
