#!/usr/bin/env python3
"""Generate the profile's PodleStreak and commit waveform SVGs.

The generator uses commits from every owned, non-fork repository. A classic or
fine-grained personal access token that can read those repositories is required
so private commit activity can be counted without exposing repository names.

Run against GitHub:
    GH_TOKEN=... python3 scripts/waveform.py

Run deterministically from a captured fixture:
    python3 scripts/waveform.py --fixture activity.json --output-dir assets
"""

from __future__ import annotations

import argparse
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

USER = os.environ.get("GH_USER", "podledges")
PROFILE_UTC_OFFSET_HOURS = int(os.environ.get("PROFILE_UTC_OFFSET_HOURS", "8"))
PROFILE_TIMEZONE = timezone(timedelta(hours=PROFILE_UTC_OFFSET_HOURS))
PROFILE_TIMEZONE_LABEL = f"UTC{PROFILE_UTC_OFFSET_HOURS:+03d}:00"
API = "https://api.github.com"
WAVEFORM_DAYS = 56
HISTORY_DAYS = 370
CHANNELS = 5

BG = "#05060a"
PANEL = "#080d14"
DIM = "#46586a"
TEXT = "#a9bfd0"
BRIGHT = "#e8f4ff"
BLUE = "#7fd0f5"
CYAN = "#2ee9ff"
PINK = "#ff54a8"
AMBER = "#ffb347"
GREEN = "#ccff5e"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def svg_escape(value: str) -> str:
    return html.escape(value, quote=True)


def fmt(value: float) -> str:
    rounded = round(value, 2)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.2f}".rstrip("0").rstrip(".")


class GitHubApi:
    def __init__(self, token: str, user: str = USER) -> None:
        if not token:
            raise ValueError(
                "GH_TOKEN is required. Configure the WAVEFORM_TOKEN repository secret "
                "with read access to all owned repositories."
            )
        self.token = token
        self.user = user

    def get(self, path: str) -> Any:
        request = urllib.request.Request(
            API + path,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"{self.user}-profile-generator",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise RuntimeError(f"GitHub API {error.code} for {path}: {detail}") from error

    def owned_repositories(self) -> list[dict[str, Any]]:
        repositories: list[dict[str, Any]] = []
        for page in range(1, 11):
            batch = self.get(
                f"/user/repos?per_page=100&affiliation=owner&sort=updated&page={page}"
            )
            repositories.extend(batch)
            if len(batch) < 100:
                break
        return [repository for repository in repositories if not repository.get("fork")]

    def commits(self, full_name: str, since: date) -> list[dict[str, str]]:
        commits: list[dict[str, str]] = []
        encoded_author = urllib.parse.quote(self.user)
        encoded_since = urllib.parse.quote(f"{since.isoformat()}T00:00:00Z")
        encoded_repo = "/".join(urllib.parse.quote(part) for part in full_name.split("/"))
        for page in range(1, 11):
            path = (
                f"/repos/{encoded_repo}/commits?author={encoded_author}&since={encoded_since}"
                f"&per_page=100&page={page}"
            )
            try:
                batch = self.get(path)
            except RuntimeError as error:
                if "GitHub API 409" in str(error):
                    return commits
                raise
            for commit in batch:
                author = commit.get("commit", {}).get("author") or {}
                timestamp = author.get("date")
                if timestamp:
                    commits.append({"sha": commit["sha"], "date": timestamp})
            if len(batch) < 100:
                break
        return commits


def fetch_activity(token: str, today: date) -> dict[str, Any]:
    api = GitHubApi(token)
    since = today - timedelta(days=HISTORY_DAYS - 1)
    repositories = []
    for repository in api.owned_repositories():
        commits = api.commits(repository["full_name"], since)
        if not commits:
            continue
        repositories.append(
            {
                "name": repository["name"],
                "private": bool(repository["private"]),
                "commits": commits,
            }
        )
        if repository["private"]:
            print(f"  <PRIVATE🔒>: {len(commits)} commits", file=os.sys.stderr)
        else:
            print(f"  {repository['name']}: {len(commits)} commits (public)", file=os.sys.stderr)
    return {"user": api.user, "today": today.isoformat(), "repositories": repositories}


def parse_commit_date(value: str) -> date:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(PROFILE_TIMEZONE)
        .date()
    )


def daily_counts(activity: dict[str, Any], start: date, days: int) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for repository in activity["repositories"]:
        counts = [0] * days
        for commit in repository["commits"]:
            commit_day = parse_commit_date(commit["date"])
            index = (commit_day - start).days
            if 0 <= index < days:
                counts[index] += 1
        result[repository["name"]] = counts
    return result


def commit_streak(activity: dict[str, Any], today: date) -> int:
    start = today - timedelta(days=HISTORY_DAYS - 1)
    counts_by_repo = daily_counts(activity, start, HISTORY_DAYS)
    aggregate = [sum(values[index] for values in counts_by_repo.values()) for index in range(HISTORY_DAYS)]
    index = HISTORY_DAYS - 1
    # Do not erase an established streak before the current UTC day has had a commit.
    if aggregate[index] == 0:
        index -= 1
    streak = 0
    while index >= 0 and aggregate[index] > 0:
        streak += 1
        index -= 1
    return streak


def repository_metadata(activity: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        repository["name"]: {"private": bool(repository["private"])}
        for repository in activity["repositories"]
    }


def signal_path(counts: list[int], x_start: float, x_end: float, center_y: float) -> str:
    step = (x_end - x_start) / len(counts)
    amplitude = 11
    slope = min(3.2, step * 0.35)
    level = center_y - amplitude if counts[0] else center_y + amplitude
    commands = [f"M{fmt(x_start)} {fmt(level)}"]
    for index, count in enumerate(counts[1:], start=1):
        new_level = center_y - amplitude if count else center_y + amplitude
        if new_level != level:
            x = x_start + index * step
            commands.append(
                f"L{fmt(x - slope)} {fmt(level)} L{fmt(x + slope)} {fmt(new_level)}"
            )
            level = new_level
    commands.append(f"L{fmt(x_end)} {fmt(level)}")
    return " ".join(commands)


def busiest_window(aggregate: list[int], width: int = 7) -> tuple[int, int]:
    candidates = ((sum(aggregate[index : index + width]), index) for index in range(len(aggregate) - width + 1))
    count, index = max(candidates, default=(0, 0))
    return index, count


def render_waveform(activity: dict[str, Any], today: date) -> str:
    start = today - timedelta(days=WAVEFORM_DAYS - 1)
    counts_by_repo = daily_counts(activity, start, WAVEFORM_DAYS)
    metadata = repository_metadata(activity)
    ranked = sorted(
        (name for name, counts in counts_by_repo.items() if sum(counts)),
        key=lambda name: (-sum(counts_by_repo[name]), name.lower()),
    )[:CHANNELS]
    aggregate = [sum(values[index] for values in counts_by_repo.values()) for index in range(WAVEFORM_DAYS)]
    total = sum(aggregate)
    private_count = sum(1 for name in counts_by_repo if sum(counts_by_repo[name]) and metadata[name]["private"])

    width, height = 860, 446
    chart_start, chart_end = 170.0, 838.0
    chart_width = chart_end - chart_start
    week_width = chart_width / 8
    channel_top, channel_pitch = 82, 59
    chart_bottom = channel_top + CHANNELS * channel_pitch
    highlight_index, highlight_count = busiest_window(aggregate)
    day_width = chart_width / WAVEFORM_DAYS
    highlight_start = chart_start + highlight_index * day_width
    highlight_end = highlight_start + 7 * day_width
    highlight_date = start + timedelta(days=highlight_index)
    highlight_last_date = highlight_date + timedelta(days=6)
    highlight_label_x = min(
        max((highlight_start + highlight_end) / 2, chart_start + 95), chart_end - 95
    )

    desc = (
        f"Animated neon timing diagram of {total} commits from {len(ranked)} recent repository "
        f"channels over eight weeks, including masked private repositories. The busiest seven-day "
        f"period, {highlight_date:%b %d} to {highlight_last_date:%b %d}, contains {highlight_count} commits."
    )
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="wave-title wave-desc" font-family="{MONO}" data-generated-date="{today.isoformat()}">',
        '  <title id="wave-title">Commit waveform</title>',
        f'  <desc id="wave-desc">{svg_escape(desc)}</desc>',
        '  <defs>',
        '    <linearGradient id="wave-bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#05060a"/><stop offset=".58" stop-color="#09111b"/><stop offset="1" stop-color="#15091d"/></linearGradient>',
        '    <filter id="wave-glow" filterUnits="userSpaceOnUse" x="-10" y="50" width="20" height="360"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '  </defs>',
        f'  <rect data-role="outer-frame" x="1" y="1" width="858" height="444" rx="15" fill="url(#wave-bg)" stroke="{GREEN}" stroke-opacity=".28"/>',
        f'  <text x="22" y="31" font-size="12" font-weight="800" letter-spacing="3"><tspan fill="{BRIGHT}">PODLEHUB</tspan><tspan fill="{GREEN}">  /  COMMIT WAVEFORM</tspan></text>',
        f'  <text x="838" y="31" text-anchor="end" fill="{TEXT}" font-size="10" letter-spacing="1">{total} COMMITS · {sum(1 for counts in counts_by_repo.values() if sum(counts))} ACTIVE REPOS · {private_count} PRIVATE · 8-WEEK WINDOW</text>',
        '  <line x1="22" y1="48" x2="838" y2="48" stroke="#88d6ff" stroke-opacity=".18"/>',
        f'  <rect x="{fmt(highlight_start)}" y="68" width="{fmt(highlight_end - highlight_start)}" height="{fmt(chart_bottom - 60)}" fill="{AMBER}" fill-opacity=".08"/>',
        f'  <line x1="{fmt(highlight_start)}" y1="68" x2="{fmt(highlight_start)}" y2="{chart_bottom + 8}" stroke="{AMBER}" stroke-opacity=".55" stroke-dasharray="3 4"/>',
        f'  <line x1="{fmt(highlight_end)}" y1="68" x2="{fmt(highlight_end)}" y2="{chart_bottom + 8}" stroke="{AMBER}" stroke-opacity=".55" stroke-dasharray="3 4"/>',
        f'  <g data-role="highlight-label" role="img" aria-label="🔥🔥{highlight_count} commits 🥵🥵">',
        f'    <path d="M{fmt(highlight_label_x - 68)} 63c-5-7 2-11 1-18 8 5 10 12 6 18zM{fmt(highlight_label_x - 57)} 63c-5-7 2-11 1-18 8 5 10 12 6 18z" fill="#ff7b39"/>',
        f'    <path d="M{fmt(highlight_label_x - 66)} 62c-2-4 2-6 2-10 4 3 5 7 3 10zM{fmt(highlight_label_x - 55)} 62c-2-4 2-6 2-10 4 3 5 7 3 10z" fill="#ffd35a"/>',
        f'    <text x="{fmt(highlight_label_x)}" y="61" text-anchor="middle" fill="#fff4d8" font-size="10" font-weight="800">{highlight_count} commits</text>',
        f'    <g fill="#ffb347" stroke="#fff4d8" stroke-width=".7"><circle cx="{fmt(highlight_label_x + 56)}" cy="55" r="7"/><circle cx="{fmt(highlight_label_x + 72)}" cy="55" r="7"/></g>',
        f'    <g stroke="#6d321d" stroke-width="1" fill="none"><path d="M{fmt(highlight_label_x + 52)} 53l3-2M{fmt(highlight_label_x + 60)} 51l3 2M{fmt(highlight_label_x + 52)} 58h8M{fmt(highlight_label_x + 68)} 53l3-2M{fmt(highlight_label_x + 76)} 51l3 2M{fmt(highlight_label_x + 68)} 58h8"/></g>',
        f'    <path d="M{fmt(highlight_label_x + 64)} 58c3 3 3 6 0 7-3-1-3-4 0-7zM{fmt(highlight_label_x + 80)} 58c3 3 3 6 0 7-3-1-3-4 0-7z" fill="#2ee9ff"/>',
        '  </g>',
        f'  <text x="{fmt(highlight_label_x)}" y="74" text-anchor="middle" fill="{AMBER}" font-size="8">{highlight_date:%b %d} - {highlight_last_date:%b %d}</text>',
    ]

    for index in range(9):
        x = chart_start + index * week_width
        lines.append(
            f'  <line data-role="week-guide" data-index="{index}" x1="{fmt(x)}" y1="78" x2="{fmt(x)}" y2="{chart_bottom + 8}" stroke="#2e5165" stroke-opacity=".5" stroke-dasharray="2 5"/>'
        )

    for index in range(CHANNELS):
        name = ranked[index] if index < len(ranked) else None
        label_y = channel_top + index * channel_pitch + 14
        center_y = channel_top + index * channel_pitch + 40
        if name is None:
            lines.append(f'  <text x="22" y="{label_y}" fill="{DIM}" font-size="11">CH{index} IDLE</text>')
            counts = [0] * WAVEFORM_DAYS
            color = DIM
        else:
            is_private = metadata[name]["private"]
            label = "&lt;PRIVATE🔒&gt;" if is_private else svg_escape(name.upper())
            color = PINK if is_private else (GREEN if name.lower() == "podledges" else BLUE)
            lines.append(
                f'  <text x="22" y="{label_y}" font-size="11" font-weight="800" letter-spacing="1"><tspan fill="#7b93a8">CH{index}</tspan><tspan dx="8" fill="{AMBER if is_private else color}">{label}</tspan><tspan dx="8" fill="{GREEN}">+{sum(counts_by_repo[name])}</tspan></text>'
            )
            counts = counts_by_repo[name]
        path = signal_path(counts, chart_start, chart_end, center_y)
        lines.extend(
            [
                f'  <path d="{path}" fill="none" stroke="{color}" stroke-opacity=".16" stroke-width="5" stroke-linejoin="round"/>',
                f'  <path data-role="signal" data-chart-start="{fmt(chart_start)}" data-chart-end="{fmt(chart_end)}" d="{path}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linejoin="round"><animate attributeName="stroke-opacity" values=".72;1;.72" dur="3.2s" begin="{index * 0.18:.2f}s" repeatCount="indefinite"/></path>',
            ]
        )

    axis_y = chart_bottom + 20
    lines.append(f'  <line data-role="week-axis" x1="{fmt(chart_start)}" y1="{axis_y}" x2="{fmt(chart_end)}" y2="{axis_y}" stroke="{DIM}" stroke-opacity=".8"/>')
    for index in range(9):
        x = chart_start + index * week_width
        boundary_date = start + timedelta(days=min(index * 7, WAVEFORM_DAYS - 1))
        week_label = "NOW" if index == 8 else f"W-{8 - index}"
        lines.extend(
            [
                f'  <line data-role="week-tick" x1="{fmt(x)}" y1="{axis_y - 4}" x2="{fmt(x)}" y2="{axis_y + 4}" stroke="{DIM}"/>',
                f'  <text x="{fmt(x)}" y="{axis_y + 17}" text-anchor="middle" fill="#b3c8d8" font-size="9">{week_label}</text>',
                f'  <text x="{fmt(x)}" y="{axis_y + 29}" text-anchor="middle" fill="#7890a4" font-size="8">{boundary_date:%m/%d}</text>',
            ]
        )

    lines.extend(
        [
            f'  <g aria-hidden="true"><line x1="0" y1="72" x2="0" y2="{axis_y}" stroke="{BRIGHT}" stroke-opacity=".7" stroke-width="1" filter="url(#wave-glow)"/><animateTransform attributeName="transform" type="translate" from="{fmt(chart_start)} 0" to="{fmt(chart_end)} 0" dur="3.8s" repeatCount="indefinite"/></g>',
            '</svg>',
        ]
    )
    return "\n".join(lines) + "\n"


def render_reactor(activity: dict[str, Any], today: date) -> str:
    streak = commit_streak(activity, today)
    week_start = today - timedelta(days=6)
    counts_by_repo = daily_counts(activity, week_start, 7)
    week_counts = [sum(values[index] for values in counts_by_repo.values()) for index in range(7)]
    max_count = max(week_counts, default=1) or 1
    total_week = sum(week_counts)
    desc = (
        f"PodleStreak shows the current streak of {streak} consecutive {PROFILE_TIMEZONE_LABEL} "
        f"days with commits, calculated on {today:%B %d, %Y}. PodleWeek bars show {total_week} commits over the "
        "latest seven days. Private repository activity is included while names remain hidden."
    )
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="860" height="442" viewBox="0 0 860 442" role="img" aria-labelledby="reactor-title reactor-desc" data-generated-date="{today.isoformat()}">',
        '  <title id="reactor-title">PodleHub PodleStreak and Podle Bay</title>',
        f'  <desc id="reactor-desc">{svg_escape(desc)}</desc>',
        '  <defs>',
        '    <linearGradient id="reactor-bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#05070c"/><stop offset=".55" stop-color="#0b121c"/><stop offset="1" stop-color="#16091b"/></linearGradient>',
        '    <linearGradient id="reactor-number" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#fff"/><stop offset=".38" stop-color="#2ee9ff"/><stop offset=".68" stop-color="#ff2ec8"/><stop offset="1" stop-color="#ccff5e"/></linearGradient>',
        '    <linearGradient id="reactor-rail" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#2ee9ff"/><stop offset=".55" stop-color="#ff2ec8"/><stop offset="1" stop-color="#ccff5e"/></linearGradient>',
        '    <pattern id="reactor-hatch" width="16" height="16" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><rect width="16" height="16" fill="#171018"/><rect width="8" height="16" fill="#2c1d12" fill-opacity=".65"/></pattern>',
        '    <filter id="reactor-cyan" filterUnits="userSpaceOnUse" x="20" y="70" width="510" height="340"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '    <filter id="reactor-pink" filterUnits="userSpaceOnUse" x="10" y="10" width="34" height="34"><feGaussianBlur stdDeviation="6" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '  </defs>',
        '  <rect data-role="outer-frame" x="1" y="1" width="858" height="440" rx="15" fill="url(#reactor-bg)" stroke="#263746"/>',
        '  <rect x="2" y="2" width="856" height="438" rx="14" fill="none" stroke="#ff2ec8" stroke-opacity=".2"/>',
        f'  <g font-family="{MONO}">',
        '    <circle cx="25" cy="27" r="5" fill="#ff2ec8" filter="url(#reactor-pink)"><animate attributeName="r" values="4;6;4" dur="2.4s" repeatCount="indefinite"/></circle>',
        f'    <text x="41" y="31" fill="{BRIGHT}" font-size="12" font-weight="800" letter-spacing="3">PODLEHUB</text>',
        f'    <text x="838" y="31" fill="{CYAN}" font-size="11" font-weight="700" text-anchor="end" letter-spacing="2">PODLE REACTOR · {today:%Y-%m-%d} {PROFILE_TIMEZONE_LABEL}</text>',
        '    <line x1="22" y1="50" x2="838" y2="50" stroke="#88d6ff" stroke-opacity=".18"/>',
        f'    <rect x="22" y="68" width="500" height="350" rx="14" fill="{PANEL}" stroke="{CYAN}" stroke-opacity=".3"/>',
        '    <rect x="548" y="68" width="290" height="350" rx="14" fill="url(#reactor-hatch)" stroke="#ffb347" stroke-opacity=".72" stroke-dasharray="6 5"/>',
        f'    <text x="42" y="98" fill="{CYAN}" font-size="11" font-weight="800" letter-spacing="3">PODLESTREAK</text>',
        '    <rect x="170" y="90" width="290" height="9" rx="4" fill="url(#reactor-rail)" filter="url(#reactor-cyan)"/>',
        '    <rect x="170" y="90" width="42" height="9" rx="4" fill="#ffffff" fill-opacity=".55"><animate attributeName="x" values="170;418;170" dur="3.6s" repeatCount="indefinite"/></rect>',
        f'    <text x="42" y="198" fill="url(#reactor-number)" font-family="Segoe UI, Helvetica Neue, sans-serif" font-size="94" font-weight="850" letter-spacing="-7">{streak} DAYS</text>',
        '    <rect x="112" y="218" width="320" height="8" rx="4" fill="url(#reactor-rail)" filter="url(#reactor-cyan)"/>',
        f'    <text x="42" y="255" fill="{BRIGHT}" font-family="Segoe UI, Helvetica Neue, sans-serif" font-size="18" font-weight="800">consecutive daily commit streak</text>',
        f'    <text x="42" y="277" fill="#9bb0c6" font-size="11" letter-spacing="1">calculated {today:%Y-%m-%d} {PROFILE_TIMEZONE_LABEL} · private activity included</text>',
        '    <line x1="42" y1="296" x2="502" y2="296" stroke="#88d6ff" stroke-opacity=".16"/>',
        f'    <text x="42" y="320" fill="#9fb3ca" font-size="11" font-weight="800" letter-spacing="3">PODLEWEEK · {total_week} COMMITS</text>',
    ]

    for index, count in enumerate(week_counts):
        x = 42 + index * 65
        bar_height = 10 + (count / max_count) * 50 if count else 8
        y = 382 - bar_height
        day = week_start + timedelta(days=index)
        opacity = "1" if count else ".22"
        lines.extend(
            [
                f'    <rect x="{x}" y="{fmt(y)}" width="46" height="{fmt(bar_height)}" rx="3" fill="{CYAN}" fill-opacity="{opacity}" filter="url(#reactor-cyan)"><animate attributeName="fill-opacity" values="{opacity};.72;{opacity}" dur="3s" begin="{index * 0.16:.2f}s" repeatCount="indefinite"/></rect>',
                f'    <text x="{x + 23}" y="405" text-anchor="middle" fill="{BRIGHT}" font-size="10" font-weight="800">{day:%a}</text>',
                f'    <text x="{x + 23}" y="336" text-anchor="middle" fill="#9fb3ca" font-size="8">{count}</text>',
            ]
        )

    lines.extend(
        [
            '    <path d="M548 82h14M548 82v14M824 82h14M838 82v14M548 404h14M548 418v-14M824 418h14M838 418v-14" fill="none" stroke="#ffb347" stroke-width="2"/>',
            '    <text x="570" y="102" fill="#ffd6a0" font-size="11" font-weight="800" letter-spacing="3">PODLE BAY</text>',
            '    <text x="570" y="175" fill="#ffb347" font-size="25" font-weight="800" letter-spacing="3">HELD OPEN</text>',
            '    <text x="570" y="213" fill="#ffd6a0" font-family="Segoe UI, Helvetica Neue, sans-serif" font-size="15">Separate panel.</text>',
            '    <text x="570" y="238" fill="#ffd6a0" fill-opacity=".72" font-family="Segoe UI, Helvetica Neue, sans-serif" font-size="14">Future module docks here.</text>',
            '    <text x="570" y="383" fill="#ffd6a0" fill-opacity=".58" font-size="10" letter-spacing="2">STATUS / RESERVED</text>',
            '  </g>',
            '</svg>',
        ]
    )
    return "\n".join(lines) + "\n"


def load_activity(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_assets(activity: dict[str, Any], output_dir: Path) -> None:
    today = date.fromisoformat(activity["today"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "podle-reactor.svg").write_text(render_reactor(activity, today), encoding="utf-8")
    (output_dir / "waveform.svg").write_text(render_waveform(activity, today), encoding="utf-8")
    print(f"wrote {output_dir / 'podle-reactor.svg'}", file=os.sys.stderr)
    print(f"wrote {output_dir / 'waveform.svg'}", file=os.sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="render from captured activity JSON")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "assets",
    )
    parser.add_argument("--today", type=date.fromisoformat, help="UTC date for a live fetch")
    args = parser.parse_args()

    if args.fixture:
        activity = load_activity(args.fixture)
    else:
        today = args.today or datetime.now(PROFILE_TIMEZONE).date()
        activity = fetch_activity(os.environ.get("GH_TOKEN", ""), today)
    write_assets(activity, args.output_dir)


if __name__ == "__main__":
    main()
