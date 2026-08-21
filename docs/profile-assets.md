# Profile asset generation

`README.md` embeds generated `assets/podle-reactor.svg` and `assets/waveform.svg` files and links them to generated `docs/reactor.html`. Do not hand-edit these three files. Regenerate them with `scripts/waveform.py`.

## Two statistics with two GitHub definitions

The cards intentionally use different, clearly labeled GitHub data:

- **PodleStreak** uses GraphQL `contributionsCollection.contributionCalendar`. It follows the green-square profile semantics, including commits, issues, pull requests, reviews, and restricted private activity that GitHub counts.
- **Commit waveform and PodleWeek** use authored commits from complete REST listings of each owned, non-fork repository's default branch plus `gh-pages` when it exists. Timestamps are bucketed into Singapore days, UTC+08:00.

The waveform header, repository `+N` values, signal paths, hottest seven-day count, and highlighted dates all come from the same 56-day REST commit capture. Public repository names may be shown. Every private name is rendered and logged only as `<PRIVATE🔒>`.

The REST fetch follows every page without a fixed page cap and deduplicates commits that appear on both eligible branches. The generator cross-checks the public REST total against GraphQL `totalCommitContributions` and refuses to publish inconsistent data.

## Token and freshness

The `profile-assets` workflow runs every eight hours and updates both SVGs and the Pages clone together. It requires a repository secret named `WAVEFORM_TOKEN`. The normal Actions token cannot read the owner's other private repositories and is never used as a fallback.

`WAVEFORM_TOKEN` must:

- be owned by `podledges`, verified through GraphQL `viewer.login`
- be a classic PAT with `repo`, or a fine-grained PAT with resource owner `podledges`, all owned repositories selected, and Metadata: Read plus Contents: Read
- be expanded when a new private repository is added and rotated before expiry

The workflow fails explicitly when the secret is absent or inadequate. As of the regression investigation on 2026-08-21, the repository had no `WAVEFORM_TOKEN`, so scheduled refreshes could not replace the committed snapshot. Install the secret before expecting future automatic refreshes.

Run a live refresh locally with an equivalent token:

```sh
GH_TOKEN=... python3 scripts/waveform.py
```

## Why PR #7 displayed 11 days

PR #7 used REST `GET /repos/{owner}/{repo}/commits?author=podledges` without a `sha` for the streak. GitHub searches the default branch when `sha` is omitted. The code therefore measured authored default-branch commit days, not GitHub contribution days.

GitHub GraphQL and the public profile graph both record one restricted private contribution on 2026-08-09. The REST commit capture records zero commits that day. The old loop skipped an empty in-progress current day, counted August 10 through August 20, then stopped at August 9. That initiating default-branch data-source mismatch, masked by a label claiming private activity was included, produced the visible `11 DAYS` symptom.

The fixed streak uses only contribution-calendar dates and counts August 9. The commit waveform correctly leaves August 9 idle because it is explicitly a commit card.

## Lavish motion and interaction mapping

The Lavish HTML review artifact is the visual and interaction source of truth. README images cannot receive pointer events inside their SVG document, so the implementation provides both parts instead of silently dropping behavior:

- **GitHub README:** self-contained SVG autoplay uses SMIL and inline CSS keyframes, following the same mechanism as GitSkins. Rails crawl, the streak number blooms, panels breathe, PodleWeek bars and popups scan in sequence, the waveform dot glows, the rainbow highlight pulses, and the cursor plus neon hot segment sweep together.
- **GitHub Pages:** `docs/reactor.html` preserves real panel lift, colored hover glows, day-bar growth, and commit-count hover popups. README images link directly to this generated interactive clone.

The SVGs use no scripts, event-handler attributes, `foreignObject`, or README-level JavaScript/CSS. Their `<title>`, `<desc>`, README alt text, and Pages labels remain accessibility-friendly.

Glow filters have explicit user-space regions. Waveform signals, hot segments, guides, ticks, cursor, highlight, and axis preserve the common chart bounds `x=170..838`. Every signal path starts at 170 and ends at 838.

## Validation

```sh
python3 -m unittest discover -s tests -v
```

The suite verifies contribution-style streak semantics and August 9, complete REST pagination, UTC+08:00 window boundaries, private masking, computed totals/highlights, SVG-native autoplay, Pages interaction hooks, accessibility metadata, filter clipping room, and exact chart alignment.
