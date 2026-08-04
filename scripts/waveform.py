#!/usr/bin/env python3
"""Render assets/waveform.svg — commit activity as a timing-analysis capture.

One channel per recent repo (signal high = commits that day) with slewed,
non-instantaneous transitions, a background data bus of commits/week in
hex, an animated time cursor sweeping the capture, and an auto-decoded
burst annotation. Private repos are captured too, with names masked.

Requires: GH_TOKEN env var (repo scope for private repos). Stdlib only.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

USER = os.environ.get("GH_USER", "podledges")
TOKEN = os.environ["GH_TOKEN"]
DAYS = 91  # 13 weeks
CHANNELS = 5

API = "https://api.github.com"


def gh(path):
    req = urllib.request.Request(
        API + path,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": USER,
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (404, 409):  # missing or empty repo
            return []
        raise


def fetch_repos():
    repos, page = [], 1
    while True:
        batch = gh(f"/user/repos?per_page=100&affiliation=owner&page={page}")
        if not batch:
            return repos
        repos += batch
        page += 1


def fetch_commit_days(repo, since):
    days, page = [], 1
    while page <= 5:
        batch = gh(
            f"/repos/{repo['full_name']}/commits"
            f"?author={USER}&since={since}&per_page=100&page={page}"
        )
        if not batch:
            break
        for c in batch:
            ts = c["commit"]["author"]["date"]
            days.append(datetime.fromisoformat(ts.replace("Z", "+00:00")).date())
        if len(batch) < 100:
            break
        page += 1
    return days


# ── palette ──────────────────────────────────────────────────────────────
BG = "#0a0e14"
PANEL = "#0e141c"
BORDER = "#1c2733"
DIM = "#46586a"
TEXT = "#93a7b8"
BRIGHT = "#e8f1f8"
BLUE = "#7fd0f5"      # public channels
PINK = "#ff54a8"      # private channels + accents (neon revolution)
AMBER = "#f5b043"     # <PRIVATE> labels + decode
CH_LABEL = "#7b93a8"  # CH0/CH1/… prefixes
MONO = "ui-monospace,'JetBrains Mono','Cascadia Code',Consolas,monospace"

# neon-green scale for commit counts — brightness tracks magnitude
GREEN_SCALE = [
    (10, "#3f6626"),    # < 10: very dark green
    (50, "#5e9433"),    # 10–50: dark green
    (150, "#86cc3f"),
    (300, "#aef04f"),
]
GREEN_MAX = "#ccff5e"   # 300+: full neon


def count_color(n):
    for limit, color in GREEN_SCALE:
        if n < limit:
            return color
    return GREEN_MAX


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def trace_path(counts, x0, step, cy, amp, slope):
    """Slewed digital trace: high when commits > 0, diagonal transitions."""
    lvl = cy - amp if counts[0] > 0 else cy + amp
    d = [f"M{x0:.1f},{lvl:.1f}"]
    for i in range(1, len(counts)):
        new = cy - amp if counts[i] > 0 else cy + amp
        if new != lvl:
            x = x0 + i * step
            d.append(f"L{x - slope:.1f},{lvl:.1f}L{x + slope:.1f},{new:.1f}")
            lvl = new
    d.append(f"L{x0 + len(counts) * step:.1f},{lvl:.1f}")
    return "".join(d)


def render(per_repo, repo_meta, today):
    agg = [sum(per_repo[r][i] for r in per_repo) for i in range(DAYS)]
    total = sum(agg)
    active = [r for r in per_repo if sum(per_repo[r]) > 0]
    ranked = sorted(active, key=lambda r: -sum(per_repo[r]))[:CHANNELS]
    n_priv = sum(1 for r in active if repo_meta[r]["private"])

    W, pad = 860, 22
    plot_w = W - 2 * pad
    step = plot_w / DAYS
    slope = min(3.5, step * 0.38)
    ch_h = 62
    ch_top = 78
    bus_top = ch_top + len(ranked) * ch_h + 14
    H = bus_top + 20 + 22

    s = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{MONO}">',
        f'<rect width="{W}" height="{H}" rx="10" fill="{BG}" stroke="{BORDER}"/>',
        # header
        f'<text x="{pad}" y="30" font-size="12" letter-spacing="3" font-weight="bold">'
        f'<tspan fill="{PINK}">COMMIT</tspan>'
        f'<tspan fill="{GREEN_MAX}"> ANALYZER</tspan>'
        f'<tspan fill="{BRIGHT}"> — </tspan>'
        f'<tspan fill="{PINK}">RECENT REPOSITORIES</tspan></text>',
        f'<text x="{W - pad}" y="30" font-size="10" text-anchor="end" fill="{BRIGHT}" '
        f'letter-spacing="1">{total} COMMITS · {len(active)} REPOS · {n_priv} PRIVATE · 13-WEEK WINDOW</text>',
        f'<line x1="{pad}" y1="44" x2="{W - pad}" y2="44" stroke="{BORDER}"/>',
    ]

    # background data bus: commits/week in hex, timing-diagram style
    weeks = [sum(agg[i * 7:(i + 1) * 7]) for i in range(13)]
    seg_w = plot_w / 13
    top, bot = bus_top, bus_top + 18
    mid = bus_top + 9
    x_end = W - pad
    bus = [
        f'<path d="M{pad},{mid}L{pad + 5},{top}" />',
        f'<path d="M{pad},{mid}L{pad + 5},{bot}" />',
        f'<path d="M{x_end - 5},{top}L{x_end},{mid}" />',
        f'<path d="M{x_end - 5},{bot}L{x_end},{mid}" />',
    ]
    for i in range(13):
        xl = pad + i * seg_w + 5
        xr = pad + (i + 1) * seg_w - 5
        bus.append(f'<path d="M{xl:.1f},{top}H{xr:.1f}"/>')
        bus.append(f'<path d="M{xl:.1f},{bot}H{xr:.1f}"/>')
        if i < 12:
            xb = pad + (i + 1) * seg_w
            bus.append(f'<path d="M{xb - 5:.1f},{top}L{xb + 5:.1f},{bot}"/>')
            bus.append(f'<path d="M{xb - 5:.1f},{bot}L{xb + 5:.1f},{top}"/>')
    s.append(
        f'<g stroke="{DIM}" stroke-opacity="0.45" fill="none" stroke-width="1">{"".join(bus)}</g>'
    )
    for i, wv in enumerate(weeks):
        s.append(
            f'<text x="{pad + (i + 0.5) * seg_w:.1f}" y="{mid + 3.5}" font-size="9" '
            f'text-anchor="middle" fill="{DIM}" fill-opacity="0.85">0x{wv:02X}</text>'
        )

    # busiest 7-day window → decode bracket over CH0
    best_a, best_n = 0, -1
    for a in range(DAYS - 6):
        w = sum(agg[a:a + 7])
        if w > best_n:
            best_a, best_n = a, w
    xa, xb = pad + best_a * step, pad + (best_a + 7) * step
    label_x = min(max((xa + xb) / 2, 170), W - 170)
    # soft highlight band over the decoded window, spanning all channels
    s.append(
        f'<rect x="{xa:.1f}" y="{ch_top - 4}" width="{xb - xa:.1f}" '
        f'height="{bus_top - ch_top - 4}" fill="{AMBER}" fill-opacity="0.05"/>'
    )
    for xe in (xa, xb):
        s.append(
            f'<line x1="{xe:.1f}" y1="{ch_top - 4}" x2="{xe:.1f}" y2="{bus_top - 8}" '
            f'stroke="{AMBER}" stroke-opacity="0.3" stroke-dasharray="2,4"/>'
        )
    s.append(
        f'<text x="{label_x:.1f}" y="{ch_top - 12}" font-size="10" text-anchor="middle" '
        f'fill="{AMBER}" letter-spacing="1">PODLES: UNLEASHED · {best_n} COMMITS / WEEK</text>'
    )

    # channels
    for idx, r in enumerate(ranked):
        meta = repo_meta[r]
        counts = per_repo[r]
        top_y = ch_top + idx * ch_h
        cy = top_y + 40
        color = PINK if meta["private"] else BLUE
        if meta["private"]:
            name_tspan = f'<tspan dx="7" fill="{AMBER}">&lt;PRIVATE&gt;</tspan><tspan dx="6" font-size="10">🔒</tspan>'
        else:
            nm = r.upper()
            nm = esc(nm if len(nm) <= 28 else nm[:27] + "…")
            name_tspan = f'<tspan dx="7" fill="{color}">{nm}</tspan>'
        s.append(
            f'<text x="{pad}" y="{top_y + 14}" font-size="11" letter-spacing="1">'
            f'<tspan fill="{CH_LABEL}">CH{idx}</tspan>{name_tspan}'
            f'<tspan dx="7" fill="{count_color(sum(counts))}" font-weight="bold">+{sum(counts)}</tspan></text>'
        )
        path = trace_path(counts, pad, step, cy, 12, slope)
        s.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-opacity="0.16" '
            f'stroke-width="4.5" stroke-linejoin="round"/>'
        )
        s.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.5" '
            f'stroke-linejoin="round"/>'
        )

    # animated time cursor sweeping the capture
    s.append(
        f'<g><line x1="0" y1="{ch_top - 4}" x2="0" y2="{bot}" stroke="{BRIGHT}" '
        f'stroke-opacity="0.55" stroke-width="1" stroke-dasharray="3,4"/>'
        f'<animateTransform attributeName="transform" type="translate" '
        f'from="{pad} 0" to="{W - pad} 0" dur="2.6s" repeatCount="indefinite"/></g>'
    )

    s.append("</svg>")
    return "".join(s)


def main():
    today = datetime.now(timezone.utc).date()
    since = (today - timedelta(days=DAYS - 1)).isoformat() + "T00:00:00Z"
    start = today - timedelta(days=DAYS - 1)

    per_repo, repo_meta = {}, {}
    for repo in fetch_repos():
        if repo.get("fork"):
            continue
        counts = [0] * DAYS
        for d in fetch_commit_days(repo, since):
            i = (d - start).days
            if 0 <= i < DAYS:
                counts[i] += 1
        if sum(counts) == 0:
            continue
        per_repo[repo["name"]] = counts
        repo_meta[repo["name"]] = {"private": repo["private"]}
        print(f"  {repo['name']}: {sum(counts)} commits", file=sys.stderr)

    svg = render(per_repo, repo_meta, today)
    out = os.path.join(os.path.dirname(__file__), "..", "assets", "waveform.svg")
    with open(out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {os.path.normpath(out)}", file=sys.stderr)


if __name__ == "__main__":
    main()
