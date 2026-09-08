#!/usr/bin/env python3
"""Accepted Prism Orbit presentation; data is supplied by waveform.py.

Number and chart are independent render functions. All native motion and exact
font outlines are bundled; viewing and scheduled rendering need no font service.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime
from html import escape
from pathlib import Path

if __package__:
    from .prism import font
else:
    from prism import font

HERE = Path(__file__).resolve().parent / "prism"
BIO = json.loads((HERE / "bio.json").read_text())
LICENSE = (HERE / "GeistMono-OFL.txt").read_text()
AVATAR = "data:image/jpeg;base64," + base64.b64encode((HERE / "avatar.jpg").read_bytes()).decode()

# Astra-proven 62/38 sibling geometry, height 700 * 0.84 = 588.
H = 588
LW, RW = 533.2, 326.8
LP, RP = 522.536, 320.264
LG, RG = 10.664, 6.536  # transparent inner gutters; LG + RG = 17.2
assert abs((LP + LG) - LW) < 1e-6 and abs((RP + RG) - RW) < 1e-6
assert abs(LP / RP - 62 / 38) < 1e-9

WHITE, MUTED, HOT = "#f4fbff", "#d5dfef", "#ff2ec8"
HOT_LABEL = "#ffb5e6"
PRISM = ("#7ee8ff", "#c084ff", "#ff7ad9", "#d6ff8a")
RIBBON = "#ccff5e"
CANDIDATE = "prism-orbit"


def f(n: float) -> str:
    value = round(float(n), 3)
    if abs(value - int(value)) < 1e-9:
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".")


def txt(s, x, y, size=16, weight=420, color=WHITE, anchor="start", extra="", opacity=None):
    if opacity is None:
        opacity = 0.95 if size == 16 and weight == 420 else 1
    return font.text(str(s), x, y, size, weight, color, opacity, anchor=anchor, extra=extra)


def weekday(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%A')} {d.day} {d.strftime('%b')}"


def streak_shape(w: float) -> str:
    # Astra cutline: top-left + bottom-right opposing chamfers (named 02-cutline).
    return f"M18 .6H{f(w - .6)}V569.4L{f(w - 18.6)} 587.4H.6V18.6Z"


def bay_shape(w: float) -> str:
    # Orbit-bay ticket notches (named 01-orbit-bay) on a ribbon octagon.
    mid = 262
    return (
        f"M14 .6H{f(w - 14)}L{f(w - .6)} 14V{mid - 14}L{f(w - 16)} {mid}L{f(w - .6)} {mid + 14}"
        f"V574L{f(w - 14)} 587.4H14L.6 574V{mid + 14}L16 {mid}L.6 {mid - 14}V14Z"
    )


def motion_css() -> str:
    return '<style>' + (HERE / 'motion.css').read_text() + '</style>'


def streak_defs() -> str:
    a, b, c, dcol = PRISM
    return f"""<defs>
<path id="panel-shape" d="{streak_shape(LP)}"/>
<clipPath id="panel-clip"><use href="#panel-shape"/></clipPath>
<linearGradient id="surface" x2=".72" y2="1">
  <stop stop-color="#0b1020" stop-opacity=".88"/>
  <stop offset="1" stop-color="#16102a" stop-opacity=".92"/>
</linearGradient>
<radialGradient id="light-a" cx=".5" cy=".5" r=".5">
  <stop class="tint-a" stop-color="{a}" stop-opacity=".46"/>
  <stop offset=".5" stop-color="{b}" stop-opacity=".16"/>
  <stop offset="1" stop-color="{b}" stop-opacity="0"/>
</radialGradient>
<radialGradient id="light-b" cx=".5" cy=".5" r=".5">
  <stop class="tint-b" stop-color="{b}" stop-opacity=".34"/>
  <stop offset="1" stop-color="{c}" stop-opacity="0"/>
</radialGradient>
<radialGradient id="epicenter" cx=".5" cy=".5" r=".5" data-role="glow-epicenter">
  <stop class="tint-a" stop-color="{a}" stop-opacity=".50"/>
  <stop class="tint-b" offset=".45" stop-color="{b}" stop-opacity=".30"/>
  <stop offset="1" stop-color="{b}" stop-opacity="0"/>
</radialGradient>
<linearGradient id="digit-ink" x1="0" y1="0" x2=".8" y2="1">
  <stop class="digit-tint-a" stop-color="#e6fbff"/>
  <stop class="digit-tint-b" offset="1" stop-color="#c7b9ff"/>
</linearGradient>
<linearGradient id="hot-ink" x1="0" y1="1" x2="0" y2="0" data-role="hot-gradient">
  <stop offset="0" stop-color="#7a0038"/>
  <stop offset=".45" stop-color="{HOT}"/>
  <stop offset="1" stop-color="#ffd4f0"/>
</linearGradient>
<linearGradient id="hot-light" x1="0" y1="1" x2="0" y2="0">
  <stop stop-color="#ffd7ed" stop-opacity="0"/>
  <stop offset=".5" stop-color="#ffe6f3" stop-opacity=".72"/>
  <stop offset="1" stop-color="#ffd7ed" stop-opacity="0"/>
</linearGradient>
<linearGradient id="p-rail" x1="0" y1="0" x2="0" y2="1">
  <stop stop-color="{dcol}" stop-opacity="0"/>
  <stop offset=".5" stop-color="{a}" stop-opacity=".95"/>
  <stop offset="1" stop-color="{b}" stop-opacity="0"/>
</linearGradient>
<filter id="digit-blur" filterUnits="userSpaceOnUse" x="20" y="0" width="480" height="340">
  <feGaussianBlur stdDeviation="14"/>
</filter>
<filter id="shard-glow" filterUnits="userSpaceOnUse" x="-40" y="-40" width="80" height="80">
  <feGaussianBlur stdDeviation="2.2"/>
</filter>
<g id="prism-shard">
  <circle r="8" fill="#7ee8ff" fill-opacity=".3" filter="url(#shard-glow)"/>
  <polygon points="0,-6 4.8,0 0,6 -4.8,0" fill="#f7fbff" stroke="#d6ff8a" stroke-width=".7"/>
  <polygon points="0,-6 4.8,0 0,0" fill="#c084ff"/>
  <polygon points="0,0 0,6 -4.8,0" fill="#7ee8ff"/>
</g>
{motion_css()}
</defs>"""


def bay_defs() -> str:
    return f"""<defs>
<path id="panel-shape" d="{bay_shape(RP)}"/>
<clipPath id="panel-clip"><use href="#panel-shape"/></clipPath>
<linearGradient id="surface" x2=".7" y2="1">
  <stop stop-color="#07140f" stop-opacity=".92"/>
  <stop offset="1" stop-color="#161b0f" stop-opacity=".94"/>
</linearGradient>
<radialGradient id="bay-aura" cx=".5" cy=".5" r=".5">
  <stop class="bay-tint" stop-color="#ccff5e" stop-opacity=".17"/>
  <stop offset="1" stop-color="#ffd089" stop-opacity="0"/>
</radialGradient>
<linearGradient id="bay-trail"><stop stop-color="#ccff5e" stop-opacity="0"/><stop offset="1" stop-color="#ffd089"/></linearGradient>
<clipPath id="portrait"><circle cx="{f(RP / 2)}" cy="236" r="92"/></clipPath>
{motion_css()}
</defs>"""


def stars() -> str:
    # Space interest: a few clipped pinpoints, not a starfield wallpaper.
    pts = [
        (48, 86, 1.1), (92, 54, 0.8), (410, 72, 1.0), (468, 118, 0.7),
        (38, 210, 0.7), (490, 188, 0.9), (72, 268, 0.6), (452, 250, 0.8),
    ]
    bits = ['<g data-role="space-pinpoints" aria-hidden="true">']
    for x, y, r in pts:
        bits.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#e8f0ff" fill-opacity=".22"/>')
    bits.append("</g>")
    return "".join(bits)


def orbit(cx: float, cy: float) -> str:
    rx, ry = 168, 89
    path = f"M {f(cx - rx)} {f(cy)} A {rx} {ry} 0 1 1 {f(cx + rx)} {f(cy)} A {rx} {ry} 0 1 1 {f(cx - rx)} {f(cy)}"
    return f"""<g data-role="orbit" class="orbit">
  <ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{rx}" ry="{ry}" fill="none" stroke="#7ee8ff" stroke-opacity=".34" stroke-width="1.15"/>
  <ellipse cx="{f(cx)}" cy="{f(cy)}" rx="{rx}" ry="{ry}" fill="none" stroke="#c084ff" stroke-opacity=".22" stroke-width=".7" stroke-dasharray="2 9"/>
  <g data-role="orbit-object"><use href="#prism-shard"/>
    <animateMotion dur="10.5s" rotate="auto" repeatCount="indefinite" path="{path}"/>
  </g>
  <g class="orbit-rest" data-role="orbit-rest" transform="translate({f(cx + 145.492)} {f(cy - 44.5)}) rotate(41)"><use href="#prism-shard"/></g>
</g>"""


def flame(cx: float, cy: float) -> str:
    return (
        f'<path data-role="hotzone-flame" d="M{f(cx)} {f(cy + 6)}C{f(cx - 8)} {f(cy + 3)} {f(cx - 5)} {f(cy - 3)} {f(cx - 1)} {f(cy - 6)}'
        f'C{f(cx - 2)} {f(cy - 1)} {f(cx + 3)} {f(cy - 4)} {f(cx + 3)} {f(cy - 7)}'
        f'C{f(cx + 11)} {f(cy + 1)} {f(cx + 6)} {f(cy + 6)} {f(cx)} {f(cy + 6)}Z" fill="{HOT}"/>'
    )


def bar_group(i: int, day: dict, x: float, y: float, w: float, h: float) -> str:
    hot = day["count"] >= 50
    palette = [PRISM[0], "#5ec8ff", PRISM[3], PRISM[1], "#7dffc8", "#b07cff", "#e4dcff"]
    fill = "url(#hot-ink)" if hot else palette[i % 7]
    nxt = palette[(i + 3) % 7]
    title = f"{weekday(day['date'])}: {day['count']} contributions"
    ink = (
        ""
        if hot
        else (
            f' class="bar-ink" style="--a:{fill};--b:{nxt};animation-delay:-{i * 0.8:.1f}s"'
        )
    )
    body = [
        f'<g class="bar-enter" style="animation-delay:{i * 0.035:.3f}s" data-role="contribution-bar" '
        f'data-date="{day["date"]}" data-count="{day["count"]}" data-hotzone="{str(hot).lower()}">',
        f"<title>{escape(title)}</title>",
        f'<rect data-role="bar-measure" x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="2.2" fill="{fill}"{ink}/>',
    ]
    if hot:
        body.append(
            f'<clipPath id="hot-{i}"><rect x="{f(x)}" y="{f(y)}" width="{f(w)}" height="{f(h)}" rx="2.2"/></clipPath>'
            f'<g clip-path="url(#hot-{i})">'
            f'<rect class="hot-sheen" data-role="hot-sheen" x="{f(x - 1)}" y="{f(y - 36)}" width="{f(w + 2)}" height="72" fill="url(#hot-light)"/>'
            f"</g>"
        )
    body.append("</g>")
    return "".join(body)


def number_body(current_streak: dict, retrieved_at: str) -> str:
    """Numeral ownership: no chart input or presentation settings."""
    streak_days = current_streak["days"]
    updated = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    cx = LP / 2
    cy = 145
    pieces = [stars()]
    pieces.append(
        f'<g id="number-atmosphere" aria-hidden="true">'
        f'<g class="drift-a"><ellipse cx="{f(cx)}" cy="{f(cy)}" rx="236" ry="168" fill="url(#light-a)"/></g>'
        f'<g class="drift-b"><ellipse cx="{f(cx + 10)}" cy="{f(cy + 18)}" rx="176" ry="118" fill="url(#light-b)"/></g>'
        f'<g class="drift-a" data-role="epicenter-drift">'
        f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="188" ry="122" fill="url(#epicenter)" opacity=".9"/>'
        f"</g>"
        f'<g class="drift-b" opacity=".5">'
        f'<ellipse cx="{f(cx)}" cy="{f(cy)}" rx="86" ry="68" fill="#c084ff" fill-opacity=".22" filter="url(#digit-blur)"/>'
        f"</g></g>"
    )
    pieces.append(orbit(cx, cy))
    # Restored visible PodleStreak title (captain finale supersedes six-drafts hide-title).
    pieces.append(txt("PodleStreak", cx, 42, 36, 676, WHITE, "middle"))
    # Fit longer streaks without moving the independently owned orbit/chart.
    digit_size = min(176, 440 / max(1, len(str(streak_days))) / .6)
    glow_digit = txt(streak_days, cx, 186, digit_size, 676, "#8bf5e8", "middle", extra='class="digit-glow"')
    pieces.append(f'<g opacity=".22" filter="url(#digit-blur)">{glow_digit}</g>')
    pieces.append(
        f'<g id="streak-number" data-source="current_streak.days" data-value="{streak_days}" '
        f'data-start="{current_streak["start"] or ""}" data-end="{current_streak["end"] or ""}">'
        f'<g class="digit-float">{txt(streak_days, cx, 186, digit_size, 676, "url(#digit-ink)", "middle")}</g>'
        f'{txt("DAYS", cx, 222, 32, 555, "#ecffc0", "middle")}'
        f"</g>"
    )
    pieces.append(txt("Current contribution streak", cx, 260, 21, 500, WHITE, "middle"))
    pieces.append(txt(f"Last update / {updated:%d %b %H:%M}Z", cx, 284, 16, 420, MUTED, "middle"))
    pieces.append(f'<path d="M32 302H{f(LP - 32)}" stroke="#8194b5" stroke-opacity=".23"/>')

    return "".join(pieces)


def fortnite_chart(chart: dict) -> str:
    """Independent chart: linear from zero; fit future peaks without clipping."""
    daily = chart["daily"]
    pieces = []
    # Piano interest as five quiet staff hairlines under the chart — not literal keys.
    base = 548
    scale = 150 / max(75, max(day["count"] for day in daily))
    lo, hi, bw = 48, LP - 48, 14
    step = (hi - lo - bw) / 13
    pieces.append('<g data-role="staff-guides" aria-hidden="true">')
    for k in range(5):
        y = 398 + k * 30
        pieces.append(f'<path d="M{f(lo)} {y}H{f(hi)}" stroke="#9eb6ff" stroke-opacity=".10"/>')
    pieces.append("</g>")
    pieces.append(
        f'<g id="fortnite-chart" data-source="chart.daily" data-metric="GitHub contributions" data-days="14" data-units-per-contribution="{scale}">'
        f'{txt("PodleFortnite", 32, 332, 21, 500)}'
        f'{txt(str(chart["total"]) + " contributions", LP - 32, 332, 16, 420, MUTED, "end")}'
        f'<path d="M{f(lo)} {base + .5}H{f(hi)}" stroke="#8c9ab5" stroke-opacity=".20"/>'
        f'<clipPath id="p-railclip"><rect x="{f(lo - 18)}" y="360" width="12" height="190"/></clipPath>'
        f'<g clip-path="url(#p-railclip)"><rect class="rail-scan" data-role="prism-rail" x="{f(lo - 18)}" y="360" width="12" height="56" fill="url(#p-rail)"/></g>'
    )
    for i, day in enumerate(daily):
        h = day["count"] * scale
        x = lo + i * step
        y = base - h
        bcx = x + bw / 2
        pieces.append(bar_group(i, day, x, y, bw, h))
        color = HOT_LABEL if day["count"] >= 50 else MUTED
        pieces.append(f'<g data-role="count-label" data-date="{day["date"]}">' + txt(day["count"], bcx, y - 10, 16, 420, color, "middle", opacity=1) + '</g>')
        if day["count"] >= 50:
            pieces.append(flame(bcx, y - 40))
        pieces.append(txt(day["date"][-2:], bcx, 568, 16, 420, MUTED, "middle"))
    pieces.append("</g>")
    return "".join(pieces)


def social(x: float, y: float, name: str) -> str:
    color = RIBBON if name == "Spotify" else "#a8cbf4"
    s = (
        f'<g role="img" aria-label="{name}, non-clickable placeholder; URL pending">'
        f"<title>{name}: URL pending, not a link</title>"
        f'<circle cx="{f(x)}" cy="{f(y)}" r="15" fill="none" stroke="{color}" stroke-opacity=".7"/>'
    )
    if name == "Spotify":
        s += (
            f'<path d="M{f(x - 8)} {f(y - 4)}Q{f(x)} {f(y - 8)} {f(x + 8)} {f(y - 3)}'
            f'M{f(x - 7)} {f(y + 1)}Q{f(x)} {f(y - 2)} {f(x + 7)} {f(y + 2)}'
            f'M{f(x - 6)} {f(y + 6)}Q{f(x)} {f(y + 3)} {f(x + 5)} {f(y + 7)}" '
            f'stroke="{color}" stroke-width="1.5" fill="none" stroke-linecap="round"/>'
        )
    else:
        s += (
            f'<path d="M{f(x - 9)} {f(y - 2)}L{f(x + 10)} {f(y - 9)}L{f(x + 6)} {f(y + 10)}'
            f'L{f(x - 1)} {f(y + 4)}L{f(x - 5)} {f(y + 7)}L{f(x - 4)} {f(y + 1)}'
            f'L{f(x + 5)} {f(y - 5)}L{f(x - 6)} {f(y)}" fill="{color}"/>'
        )
    return s + "</g>"


def bay_body() -> str:
    c = RP / 2
    s = [
        f'<g class="bay-aura" aria-hidden="true"><ellipse cx="{f(c)}" cy="266" rx="152" ry="160" fill="url(#bay-aura)"/></g>',
        txt("Podledges", 22, 42, 36, 676, "#f4fbff"),
        txt("Ayden/Podles Profile", 22, 68, 16, 420, MUTED),
        f'<path d="M22 82H{f(RP - 22)}" stroke="{RIBBON}" stroke-opacity=".35"/>',
        f'<circle cx="{f(c)}" cy="236" r="100" fill="none" stroke="{RIBBON}" stroke-opacity=".28" stroke-width="1.2"/>',
        f'<circle cx="{f(c)}" cy="236" r="108" fill="none" stroke="#e4cf8b" stroke-opacity=".24" stroke-dasharray="2 8"/>',
        f'<g transform="translate({f(c)} 236)" aria-hidden="true"><g class="portrait-satellite" data-role="portrait-satellite">'
        f'<circle r="100" fill="none" stroke="#ccff5e" stroke-width="2" stroke-linecap="round" stroke-dasharray="34 594.319"/>'
        f'<circle cx="100" r="3" fill="#ffd089"/></g></g>',
        f'<image x="{f(c - 92)}" y="144" width="184" height="184" href="{AVATAR}" '
        f'preserveAspectRatio="xMidYMid slice" clip-path="url(#portrait)"/>',
        txt("@podledges", c, 360, 26, 555, "#e2edff", "middle"),
        txt(BIO["line1"], c, 390, 16, 420, MUTED, "middle"),
        txt(BIO["line2"], c, 412, 16, 420, MUTED, "middle"),
        f'<path d="M22 436H{f(RP - 22)}" stroke="#a4b0bd" stroke-opacity=".18"/>',
        social(46, 470, "Spotify") + txt("Spotify", 70, 475, 16, 420),
        social(178, 470, "Telegram") + txt("Telegram", 202, 475, 16, 420),
        txt("URLs pending", c, 510, 16, 420, MUTED, "middle"),
        f'<g aria-hidden="true" data-role="ribbon-coda"><path d="M62 548H{f(RP - 62)}M80 554H{f(RP - 80)}" stroke="#ccff5e" stroke-opacity=".17"/>'
        f'<g transform="translate({f(c)} 548)"><g class="ribbon-shuttle" data-role="ribbon-shuttle">'
        f'<path d="M-28 0H0" stroke="url(#bay-trail)" stroke-width="1.6"/>'
        f'<path d="M0 -3L5 0 0 3-5 0Z" fill="#ffd089"/></g></g></g>',
    ]
    return "".join(s)


def root(width: float, title: str, desc: str, defs: str, body: str, data: dict, profile: bool = False) -> str:
    shift = f'transform="translate({f(RG)} 0)"' if profile else ""
    border = "#ccff5e" if profile else "#8a6ad4"
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    meta = (
        f"Prism Orbit. GitHub contribution calendar retrieved {data['retrieved_at']}; "
        f"sha256={digest}. Original Geist Mono outlines. {escape(LICENSE)}"
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{H}" viewBox="0 0 {width} {H}" role="img" aria-labelledby="title desc" data-candidate="{CANDIDATE}" data-generated-date="{data['today']}" data-retrieved-at="{data['retrieved_at']}" data-statistics-sha256="{digest}">
<title id="title">{escape(title)}</title>
<desc id="desc">{escape(desc)}</desc>
<metadata>{meta}</metadata>
{defs}
<g {shift}><use class="surface-paint" href="#panel-shape" fill="url(#surface)" stroke="{border}" stroke-opacity=".65" stroke-width="1.2"/>
<g clip-path="url(#panel-clip)">{body}</g></g>
</svg>
"""


def streak_svg(data: dict) -> str:
    streak = data["current_streak"]
    desc = (
        f"PodleStreak shows {streak['days']} consecutive GitHub contribution calendar days "
        f"({streak['start']} to {streak['end']}). "
        f"PodleFortnite: 14 days, {data['chart']['total']} contributions, not authored commits. "
        f"Latest retrieval {data['retrieved_at']}; the latest day is partial. "
        f"Hot-pink flames mark days of at least 50 contributions. Longest-ever unavailable and omitted. "
        f"A prism shard orbits the numeral on an ellipse."
    )
    return root(LW, f"PodleStreak — {streak['days']} contribution days", desc, streak_defs(),
                number_body(streak, data["retrieved_at"]) + fortnite_chart(data["chart"]), data)


def bay_svg(data: dict) -> str:
    desc = (
        "Podledges / Ayden/Podles Profile. Existing GitHub avatar. @podledges. "
        "Custom title and short bio are clearly marked placeholders. "
        "Spotify and Telegram icons are inert; URLs pending. No invented biography or social links."
    )
    return root(RW, "Podledges — Ayden/Podles Profile", desc, bay_defs(), bay_body(), data, profile=True)


def render_pages(data: dict, waveform_svg: str, hub_svg: str) -> str:
    """Portable webpage using the exact native README images, plus readable data."""
    def image(svg: str, alt: str, width: str) -> str:
        uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
        return f'<img src="{uri}" alt="{escape(alt)}" width="{width}">'

    rows = "".join(f'<tr><th scope="row">{day["date"]}</th><td>{day["count"]}</td></tr>'
                   for day in data["chart"]["daily"])
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Podledges — Prism Orbit</title><style>
:root{{color-scheme:dark light}}*{{box-sizing:border-box}}body{{margin:0;background:#0d1117;color:#e6edf3;font:16px system-ui,sans-serif}}main{{max-width:884px;padding:24px 12px;margin:auto}}h1{{font-size:22px}}a{{color:#8bc9ff}}#candidate{{font-size:0}}img{{height:auto;max-width:100%;vertical-align:bottom}}.hub{{display:block;margin:16px 0}}.wave-card svg{{width:100%;height:auto;display:block}}.wave-card{{transition:filter .2s}}.wave-card:hover{{filter:drop-shadow(0 0 12px #ccff5e33)}}p{{font-size:14px;line-height:1.6}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}th,td{{text-align:left;padding:6px;border-bottom:1px solid #68758355}}
@media(prefers-color-scheme:light){{body{{background:#fff;color:#24292f}}a{{color:#0969da}}}}
@media(prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style></head><body><main data-generated-date="{data['today']}">
<h1>Podledges</h1><div id="candidate">{image(streak_svg(data), 'PodleStreak and fourteen-day contribution chart; values below.', '62%')}{image(bay_svg(data), 'Podledges profile. Title and bio placeholders; social URLs pending.', '38%')}</div>
<a class="hub" href="https://github.com/podledges/PodleHub">{image(hub_svg, 'Open PodleHub', '100%')}</a>
<section id="waveform" class="wave-card" aria-label="Interactive commit waveform">{waveform_svg}</section>
<p>Contribution calendar retrieved {escape(data['retrieved_at'])}. Current streak: {data['current_streak']['days']} days. Latest day partial; longest-ever unavailable. The fourteen-day chart counts contributions, not authored commits. All bars share a linear zero baseline; flames mean at least 50 contributions.</p>
<details><summary>Fourteen-day contributions: {data['chart']['total']}</summary><table><thead><tr><th>Date</th><th>Contributions</th></tr></thead><tbody>{rows}</tbody></table></details>
<p>The new pair respects reduced motion with a stationary prism and parked accents. The retained Hub and commit waveform keep their original animation. <a href="https://github.com/podledges/podledges">GitHub profile source</a>.</p>
</main></body></html>
'''
