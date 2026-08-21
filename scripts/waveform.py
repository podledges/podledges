#!/usr/bin/env python3
"""Generate the profile's PodleStreak and commit waveform SVGs.

The streak follows GitHub's GraphQL contribution calendar. The waveform follows
complete authored commits on each owned repository's default and gh-pages
branches. A profile-owner token with private repository access is required.

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
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

USER = os.environ.get("GH_USER", "podledges")
PROFILE_UTC_OFFSET_HOURS = int(os.environ.get("PROFILE_UTC_OFFSET_HOURS", "8"))
PROFILE_TIMEZONE = timezone(timedelta(hours=PROFILE_UTC_OFFSET_HOURS))
API = "https://api.github.com"
WAVEFORM_DAYS = 56
HISTORY_DAYS = 365
CHANNELS = 5

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
                "with a token owned by the profile user."
            )
        self.token = token
        self.user = user

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            API + "/graphql",
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers=self.headers({"Content-Type": "application/json"}),
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            raise RuntimeError(f"GitHub GraphQL API {error.code}: {detail}") from error
        if payload.get("errors"):
            raise RuntimeError(f"GitHub GraphQL API errors: {payload['errors']}")
        return payload["data"]

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"{self.user}-profile-generator",
        }
        headers.update(extra or {})
        return headers

    def get(self, path: str, *, missing_ok: bool = False) -> Any:
        request = urllib.request.Request(API + path, headers=self.headers())
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if missing_ok and error.code in (404, 409):
                return None
            detail = error.read().decode("utf-8", "replace")
            raise RuntimeError(f"GitHub REST API {error.code}: {detail}") from error

    def paginated(self, path: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        separator = "&" if "?" in path else "?"
        while True:
            batch = self.get(f"{path}{separator}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise RuntimeError("GitHub REST pagination returned a non-list response")
            records.extend(batch)
            if len(batch) < 100:
                return records
            page += 1

    def owned_repositories(self) -> list[dict[str, Any]]:
        repositories = self.paginated("/user/repos?affiliation=owner&sort=updated")
        return [repository for repository in repositories if not repository.get("fork")]

    def has_branch(self, full_name: str, branch: str) -> bool:
        repository = "/".join(urllib.parse.quote(part) for part in full_name.split("/"))
        encoded_branch = urllib.parse.quote(branch, safe="")
        return self.get(
            f"/repos/{repository}/branches/{encoded_branch}", missing_ok=True
        ) is not None

    def commits(self, full_name: str, branches: list[str], since: datetime) -> list[dict[str, str]]:
        repository = "/".join(urllib.parse.quote(part) for part in full_name.split("/"))
        author = urllib.parse.quote(self.user)
        since_value = urllib.parse.quote(since.isoformat().replace("+00:00", "Z"))
        commits_by_sha: dict[str, dict[str, str]] = {}
        for branch in branches:
            encoded_branch = urllib.parse.quote(branch, safe="")
            path = (
                f"/repos/{repository}/commits?author={author}&sha={encoded_branch}"
                f"&since={since_value}"
            )
            for commit in self.paginated(path):
                authored_at = (commit.get("commit", {}).get("author") or {}).get("date")
                if authored_at:
                    commits_by_sha[commit["sha"]] = {
                        "sha": commit["sha"],
                        "date": authored_at,
                    }
        return list(commits_by_sha.values())


CONTRIBUTIONS_QUERY = """
query ProfileContributions(
  $login: String!
  $historyFrom: DateTime!
  $windowFrom: DateTime!
  $to: DateTime!
) {
  viewer { login }
  user(login: $login) {
    history: contributionsCollection(from: $historyFrom, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
    window: contributionsCollection(from: $windowFrom, to: $to) {
      totalCommitContributions
    }
  }
}
"""


def calendar_days(collection: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"date": day["date"], "count": day["contributionCount"]}
        for week in collection["contributionCalendar"]["weeks"]
        for day in week["contributionDays"]
    ]


def contribution_source(data: dict[str, Any], user: str = USER) -> tuple[list[dict[str, Any]], int]:
    viewer = data.get("viewer") or {}
    if viewer.get("login", "").lower() != user.lower():
        raise RuntimeError(
            "WAVEFORM_TOKEN must belong to the profile user so private-inclusive "
            "statistics cannot silently degrade to public-only data."
        )
    profile = data.get("user")
    if not profile:
        raise RuntimeError(f"GitHub user {user!r} was not found")
    return calendar_days(profile["history"]), int(profile["window"]["totalCommitContributions"])


def local_day_start_utc(day: date) -> datetime:
    return datetime.combine(day, time.min, PROFILE_TIMEZONE).astimezone(timezone.utc)


def fetch_activity(token: str, today: date) -> dict[str, Any]:
    api = GitHubApi(token)
    history_start = today - timedelta(days=HISTORY_DAYS - 1)
    window_start = today - timedelta(days=WAVEFORM_DAYS - 1)
    to = datetime.combine(today + timedelta(days=1), time.min, PROFILE_TIMEZONE)
    data = api.graphql(
        CONTRIBUTIONS_QUERY,
        {
            "login": api.user,
            "historyFrom": datetime.combine(history_start, time.min, PROFILE_TIMEZONE).isoformat(),
            "windowFrom": datetime.combine(window_start, time.min, PROFILE_TIMEZONE).isoformat(),
            "to": to.isoformat(),
        },
    )
    contribution_days, visible_commit_total = contribution_source(data, api.user)

    repositories = []
    public_commit_total = 0
    since = local_day_start_utc(window_start)
    for repository in api.owned_repositories():
        branches = [repository["default_branch"]]
        if repository["default_branch"] != "gh-pages" and api.has_branch(
            repository["full_name"], "gh-pages"
        ):
            branches.append("gh-pages")
        try:
            commits = api.commits(repository["full_name"], branches, since)
        except RuntimeError as error:
            label = "<PRIVATE🔒>" if repository["private"] else repository["name"]
            raise RuntimeError(f"Unable to list complete commits for {label}: {error}") from error
        if not commits:
            continue
        repositories.append(
            {
                "name": repository["name"],
                "private": bool(repository["private"]),
                "commits": commits,
            }
        )
        count = len(commits)
        label = "<PRIVATE🔒>" if repository["private"] else repository["name"]
        print(f"  {label}: {count} commits", file=os.sys.stderr)
        if not repository["private"]:
            public_commit_total += count

    if public_commit_total != visible_commit_total:
        raise RuntimeError(
            "Public REST commit total does not match GitHub GraphQL's visible commit total: "
            f"{public_commit_total} != {visible_commit_total}. Refusing to publish inconsistent data."
        )

    return {
        "user": api.user,
        "today": today.isoformat(),
        "streak_source": "GitHub GraphQL contribution calendar",
        "waveform_source": "complete GitHub REST default and gh-pages branch commits",
        "contribution_days": contribution_days,
        "repositories": repositories,
    }


def commit_day(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(PROFILE_TIMEZONE).date()


def daily_counts(activity: dict[str, Any], start: date, days: int) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for repository in activity["repositories"]:
        counts = [0] * days
        for commit in repository["commits"]:
            day = commit_day(commit["date"])
            index = (day - start).days
            if 0 <= index < days:
                counts[index] += 1
        result[repository["name"]] = counts
    return result


def contribution_streak(activity: dict[str, Any], today: date) -> int:
    counts = {
        date.fromisoformat(day["date"]): int(day["count"])
        for day in activity["contribution_days"]
    }
    cursor = today
    # Do not erase an established streak before the current day has activity.
    if counts.get(cursor, 0) == 0:
        cursor -= timedelta(days=1)
    streak = 0
    while counts.get(cursor, 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)
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
        f"Animated neon timing diagram of {total} authored commits from {len(ranked)} recent "
        f"repository channels over eight weeks, including masked private repositories. The busiest "
        f"seven-day period, {highlight_date:%b %d} to {highlight_last_date:%b %d}, contains "
        f"{highlight_count} commits."
    )
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="wave-title wave-desc" font-family="{MONO}" data-generated-date="{today.isoformat()}">',
        '  <title id="wave-title">Commit waveform</title>',
        f'  <desc id="wave-desc">{svg_escape(desc)}</desc>',
        '  <defs>',
        '    <linearGradient id="wave-bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#05060a"><animate attributeName="stop-color" values="#05060a;#071421;#05060a" dur="7s" repeatCount="indefinite"/></stop><stop offset=".58" stop-color="#09111b"/><stop offset="1" stop-color="#15091d"><animate attributeName="stop-color" values="#15091d;#210b2b;#15091d" dur="7s" repeatCount="indefinite"/></stop></linearGradient>',
        '    <linearGradient id="wave-cursor-burst" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#2ee9ff" stop-opacity="0"/><stop offset=".5" stop-color="#ff2ec8" stop-opacity=".28"/><stop offset="1" stop-color="#ccff5e" stop-opacity="0"/></linearGradient>',
        '    <linearGradient id="wave-highlight" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#2ee9ff"/><stop offset=".25" stop-color="#ccff5e"/><stop offset=".5" stop-color="#fff4d8"/><stop offset=".75" stop-color="#ff2ec8"/><stop offset="1" stop-color="#2ee9ff"><animate attributeName="stop-color" values="#2ee9ff;#ff2ec8;#2ee9ff" dur="1.6s" repeatCount="indefinite"/></stop></linearGradient>',
        '    <radialGradient id="wave-dot" cx="30%" cy="30%"><stop stop-color="#fff"/><stop offset=".28" stop-color="#ccff5e"/><stop offset=".7" stop-color="#2ee9ff"/><stop offset="1" stop-color="#2effbf"/></radialGradient>',
        '    <pattern id="wave-grid" width="83.5" height="59" patternUnits="userSpaceOnUse"><path d="M83.5 0H0V59" fill="none" stroke="#2ee9ff" stroke-opacity=".1" stroke-width="1"/></pattern>',
        '    <clipPath id="wave-cursor-window"><rect x="158" y="70" width="24" height="315"><animate attributeName="x" values="158;826" dur="2.8s" repeatCount="indefinite"/></rect></clipPath>',
        '    <filter id="wave-glow" filterUnits="userSpaceOnUse" x="-12" y="50" width="24" height="360"><feGaussianBlur stdDeviation="4" result="blur"><animate attributeName="stdDeviation" values="3;6;3" dur="1.9s" repeatCount="indefinite"/></feGaussianBlur><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '    <filter id="wave-dot-glow" filterUnits="userSpaceOnUse" x="8" y="8" width="38" height="38"><feGaussianBlur stdDeviation="6" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '    <filter id="wave-signal-glow" filterUnits="userSpaceOnUse" x="150" y="70" width="708" height="315"><feGaussianBlur stdDeviation="5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '    <style>@keyframes wave-atmosphere{0%,100%{opacity:.55}50%{opacity:1}}.wave-channel{animation:wave-atmosphere 3.2s ease-in-out infinite}.wave-channel title{pointer-events:none}</style>',
        '  </defs>',
        f'  <rect class="wave-surface" data-role="outer-frame" x="1" y="1" width="858" height="444" rx="15" fill="url(#wave-bg)" stroke="{GREEN}" stroke-opacity=".28"><animate attributeName="stroke-opacity" values=".22;.5;.22" dur="4.6s" repeatCount="indefinite"/></rect>',
        '  <circle cx="27" cy="27" r="5" fill="url(#wave-dot)" filter="url(#wave-dot-glow)"><animate attributeName="r" values="4;6.5;4" dur="2s" repeatCount="indefinite"/></circle>',
        f'  <text x="43" y="31" font-size="12" font-weight="800" letter-spacing="3"><tspan fill="{BRIGHT}">PODLEHUB</tspan><tspan fill="{GREEN}">  /  COMMIT WAVEFORM</tspan></text>',
        f'  <text x="838" y="31" text-anchor="end" fill="{TEXT}" font-size="10" letter-spacing="1">{total} COMMITS · {sum(1 for counts in counts_by_repo.values() if sum(counts))} ACTIVE REPOS · {private_count} PRIVATE · 8-WEEK WINDOW</text>',
        '  <line x1="22" y1="48" x2="838" y2="48" stroke="#88d6ff" stroke-opacity=".18"/>',
        f'  <rect data-role="highlight-window" x="{fmt(highlight_start)}" y="68" width="{fmt(highlight_end - highlight_start)}" height="{fmt(chart_bottom - 60)}" fill="url(#wave-highlight)" fill-opacity=".12" stroke="url(#wave-highlight)" stroke-opacity=".55" stroke-dasharray="4 7"><animate attributeName="fill-opacity" values=".08;.24;.08" dur="1.6s" repeatCount="indefinite"/><animate attributeName="stroke-dashoffset" values="0;-22" dur="1.6s" repeatCount="indefinite"/></rect>',
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
        f'  <rect x="{fmt(chart_start)}" y="78" width="{fmt(chart_width)}" height="{fmt(chart_bottom - 70)}" fill="url(#wave-grid)" opacity=".7"/>',
        f'  <rect data-role="cursor-burst" x="{fmt(chart_start - 34)}" y="72" width="68" height="{fmt(chart_bottom - 64)}" fill="url(#wave-cursor-burst)"><animate attributeName="x" values="{fmt(chart_start - 34)};{fmt(chart_end - 34)}" dur="2.8s" repeatCount="indefinite"/></rect>',
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
        tooltip_label = "Private repository" if name and metadata[name]["private"] else (name or f"Channel {index} idle")
        lines.extend(
            [
                f'  <g class="wave-channel" data-role="channel"><title>{svg_escape(tooltip_label)}: {sum(counts)} commits</title>',
                f'    <path d="{path}" fill="none" stroke="{color}" stroke-opacity=".16" stroke-width="6" stroke-linejoin="round"/>',
                f'    <path class="signal-main" data-role="signal" data-chart-start="{fmt(chart_start)}" data-chart-end="{fmt(chart_end)}" d="{path}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round"><animate attributeName="stroke-opacity" values=".68;1;.68" dur="3.2s" begin="{index * 0.18:.2f}s" repeatCount="indefinite"/><animate attributeName="stroke-dashoffset" values="0;-18" dur="1.4s" repeatCount="indefinite"/></path>',
                f'    <path class="signal-hot" data-role="hotseg" d="{path}" fill="none" stroke="{GREEN if index % 2 else BRIGHT}" stroke-width="6" stroke-linejoin="round" clip-path="url(#wave-cursor-window)" filter="url(#wave-signal-glow)"/>',
                '  </g>',
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
            f'  <g data-role="cursor" aria-hidden="true"><line x1="0" y1="72" x2="0" y2="{axis_y}" stroke="{BRIGHT}" stroke-opacity=".8" stroke-width="1.5" stroke-dasharray="4 5" filter="url(#wave-glow)"/><circle cx="0" cy="72" r="3" fill="{BRIGHT}"/><circle cx="0" cy="{axis_y}" r="3" fill="{BRIGHT}"/><animateTransform attributeName="transform" type="translate" from="{fmt(chart_start)} 0" to="{fmt(chart_end)} 0" dur="2.8s" repeatCount="indefinite"/></g>',
            '</svg>',
        ]
    )
    return "\n".join(lines) + "\n"


def render_reactor(activity: dict[str, Any], today: date) -> str:
    streak = contribution_streak(activity, today)
    week_start = today - timedelta(days=6)
    counts_by_repo = daily_counts(activity, week_start, 7)
    week_counts = [sum(values[index] for values in counts_by_repo.values()) for index in range(7)]
    max_count = max(week_counts, default=1) or 1
    total_week = sum(week_counts)
    desc = (
        f"PodleStreak shows the current streak of {streak} consecutive GitHub contribution days, "
        f"calculated on {today:%B %d, %Y}. PodleWeek bars show {total_week} authored commits over the "
        "latest seven days. Private repository activity is included while names remain hidden."
    )
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="860" height="442" viewBox="0 0 860 442" role="img" aria-labelledby="reactor-title reactor-desc" data-generated-date="{today.isoformat()}">',
        '  <title id="reactor-title">PodleHub PodleStreak and Podle Bay</title>',
        f'  <desc id="reactor-desc">{svg_escape(desc)}</desc>',
        '  <defs>',
        '    <linearGradient id="reactor-bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#05070c"><animate attributeName="stop-color" values="#05070c;#071624;#05070c" dur="7s" repeatCount="indefinite"/></stop><stop offset=".55" stop-color="#0b121c"/><stop offset="1" stop-color="#16091b"><animate attributeName="stop-color" values="#16091b;#240b2d;#16091b" dur="7s" repeatCount="indefinite"/></stop></linearGradient>',
        '    <linearGradient id="reactor-number" x1="0%" y1="0" x2="100%" y2="0"><stop stop-color="#fff"/><stop offset=".3" stop-color="#2ee9ff"/><stop offset=".58" stop-color="#ff2ec8"/><stop offset=".78" stop-color="#fff4d8"/><stop offset="1" stop-color="#ccff5e"/><animate attributeName="x1" values="-100%;100%;-100%" dur="3.6s" repeatCount="indefinite"/><animate attributeName="x2" values="0%;200%;0%" dur="3.6s" repeatCount="indefinite"/></linearGradient>',
        '    <linearGradient id="reactor-rail" x1="0%" y1="0" x2="100%" y2="0"><stop stop-color="#2ee9ff"/><stop offset=".38" stop-color="#ff2ec8"/><stop offset=".7" stop-color="#fff4d8"/><stop offset="1" stop-color="#2ee9ff"/><animate attributeName="x1" values="-100%;100%;-100%" dur="4.8s" repeatCount="indefinite"/><animate attributeName="x2" values="0%;200%;0%" dur="4.8s" repeatCount="indefinite"/></linearGradient>',
        '    <pattern id="reactor-hatch" width="16" height="16" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><rect width="16" height="16" fill="#171018"/><rect width="8" height="16" fill="#2c1d12" fill-opacity=".65"/></pattern>',
        '    <filter id="reactor-cyan" filterUnits="userSpaceOnUse" x="14" y="60" width="522" height="366"><feGaussianBlur stdDeviation="4" result="blur"><animate attributeName="stdDeviation" values="3;7;3" dur="2.6s" repeatCount="indefinite"/></feGaussianBlur><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '    <filter id="reactor-number-glow" filterUnits="userSpaceOnUse" x="25" y="105" width="500" height="112"><feGaussianBlur stdDeviation="5" result="blur"><animate attributeName="stdDeviation" values="4;10;4" dur="2.4s" repeatCount="indefinite"/></feGaussianBlur><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '    <filter id="reactor-pink" filterUnits="userSpaceOnUse" x="10" y="10" width="34" height="34"><feGaussianBlur stdDeviation="6" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '    <style>@keyframes panel-breathe{0%,100%{opacity:.76}50%{opacity:1}}.reactor-panel{animation:panel-breathe 3.2s ease-in-out infinite}.reactor-day title{pointer-events:none}</style>',
        '  </defs>',
        '  <rect data-role="outer-frame" x="1" y="1" width="858" height="440" rx="15" fill="url(#reactor-bg)" stroke="#263746"/>',
        '  <rect x="2" y="2" width="856" height="438" rx="14" fill="none" stroke="#ff2ec8" stroke-opacity=".2"><animate attributeName="stroke-opacity" values=".14;.42;.14" dur="4.2s" repeatCount="indefinite"/></rect>',
        f'  <g font-family="{MONO}">',
        '    <circle cx="25" cy="27" r="5" fill="#ff2ec8" filter="url(#reactor-pink)"><animate attributeName="r" values="4;6;4" dur="2.4s" repeatCount="indefinite"/></circle>',
        f'    <text x="41" y="31" fill="{BRIGHT}" font-size="12" font-weight="800" letter-spacing="3">PODLEHUB</text>',
        f'    <text x="838" y="31" fill="{CYAN}" font-size="11" font-weight="700" text-anchor="end" letter-spacing="2">PODLE REACTOR · {today:%Y-%m-%d} · GITHUB CALENDAR</text>',
        '    <line x1="22" y1="50" x2="838" y2="50" stroke="#88d6ff" stroke-opacity=".18"/>',
        f'    <rect class="reactor-panel" data-role="streak-panel" x="22" y="68" width="500" height="350" rx="14" fill="{PANEL}" stroke="{CYAN}" stroke-opacity=".3"><title>PodleStreak panel - hover for a brighter neon edge</title><animate attributeName="stroke-opacity" values=".24;.52;.24" dur="3.4s" repeatCount="indefinite"/></rect>',
        '    <rect class="reactor-panel reactor-bay" data-role="bay-panel" x="548" y="68" width="290" height="350" rx="14" fill="url(#reactor-hatch)" stroke="#ffb347" stroke-opacity=".72" stroke-dasharray="6 5"><title>Podle Bay reserved module panel</title><animate attributeName="stroke-dashoffset" values="0;-22" dur="3s" repeatCount="indefinite"/><animate attributeName="stroke-opacity" values=".52;.92;.52" dur="3.2s" repeatCount="indefinite"/></rect>',
        f'    <text x="42" y="98" fill="{CYAN}" font-size="11" font-weight="800" letter-spacing="3">PODLESTREAK</text>',
        '    <rect x="170" y="90" width="290" height="9" rx="4" fill="url(#reactor-rail)" filter="url(#reactor-cyan)"/>',
        '    <rect x="170" y="90" width="42" height="9" rx="4" fill="#ffffff" fill-opacity=".62"><animate attributeName="x" values="170;418;170" dur="3.6s" repeatCount="indefinite"/><animate attributeName="fill-opacity" values=".38;.9;.38" dur="1.8s" repeatCount="indefinite"/></rect>',
        f'    <text x="42" y="198" fill="url(#reactor-number)" filter="url(#reactor-number-glow)" font-family="Segoe UI, Helvetica Neue, sans-serif" font-size="94" font-weight="850" letter-spacing="-7">{streak} DAYS<animate attributeName="opacity" values=".84;1;.84" dur="2.4s" repeatCount="indefinite"/></text>',
        '    <rect x="112" y="218" width="320" height="8" rx="4" fill="url(#reactor-rail)" filter="url(#reactor-cyan)"/>',
        '    <rect x="112" y="218" width="46" height="8" rx="4" fill="#fff" fill-opacity=".5"><animate attributeName="x" values="112;386;112" dur="4.1s" repeatCount="indefinite"/></rect>',
        f'    <text x="42" y="255" fill="{BRIGHT}" font-family="Segoe UI, Helvetica Neue, sans-serif" font-size="18" font-weight="800">consecutive daily contribution streak</text>',
        f'    <text x="42" y="277" fill="#9bb0c6" font-size="11" letter-spacing="1">GitHub calendar · calculated {today:%Y-%m-%d} · private activity included</text>',
        '    <line x1="42" y1="296" x2="502" y2="296" stroke="#88d6ff" stroke-opacity=".16"/>',
        f'    <text x="42" y="320" fill="#9fb3ca" font-size="11" font-weight="800" letter-spacing="3">PODLEWEEK · {total_week} COMMITS</text>',
    ]

    for index, count in enumerate(week_counts):
        x = 42 + index * 65
        bar_height = 10 + (count / max_count) * 50 if count else 8
        day = week_start + timedelta(days=index)
        opacity = "1" if count else ".22"
        popup_width = 84
        lines.extend(
            [
                f'    <g class="reactor-day" data-role="week-day" data-index="{index}" transform="translate({x + 23} 382)"><title>{day:%A, %B %d}: {count} commits</title>',
                f'      <rect data-role="day-bar" x="-23" y="-{fmt(bar_height)}" width="46" height="{fmt(bar_height)}" rx="3" fill="{CYAN}" fill-opacity="{opacity}"><animate attributeName="fill" values="{CYAN};{PINK};{PINK};{CYAN};{CYAN}" keyTimes="0;.02;.14;.16;1" dur="7s" begin="{index}s" repeatCount="indefinite"/><animate attributeName="fill-opacity" values="{opacity};1;1;{opacity};{opacity}" keyTimes="0;.02;.14;.16;1" dur="7s" begin="{index}s" repeatCount="indefinite"/><animateTransform attributeName="transform" type="scale" values="1 1;1 1.14;1 1.14;1 1;1 1" keyTimes="0;.02;.14;.16;1" dur="7s" begin="{index}s" repeatCount="indefinite" additive="sum"/></rect>',
                f'      <g data-role="week-popup" opacity="0"><animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;.02;.14;.16;1" dur="7s" begin="{index}s" repeatCount="indefinite"/><rect x="-{popup_width / 2:.0f}" y="-{fmt(bar_height + 27)}" width="{popup_width}" height="20" rx="10" fill="url(#reactor-rail)"/><text x="0" y="-{fmt(bar_height + 13)}" text-anchor="middle" fill="#fff" font-size="9" font-weight="800">{count} commits</text></g>',
                '    </g>',
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


def render_pages(activity: dict[str, Any], today: date) -> str:
    """Render the honest pointer-interactive counterpart to the README images."""
    streak = contribution_streak(activity, today)
    week_start = today - timedelta(days=6)
    counts_by_repo = daily_counts(activity, week_start, 7)
    week_counts = [sum(values[index] for values in counts_by_repo.values()) for index in range(7)]
    max_count = max(week_counts, default=1) or 1
    days = []
    for index, count in enumerate(week_counts):
        day = week_start + timedelta(days=index)
        height = 12 + (count / max_count) * 58 if count else 8
        days.append(
            f'<div class="day" data-commits="{count}"><span style="height:{fmt(height)}px"></span><b>{day:%a}</b></div>'
        )
    waveform_svg = render_waveform(activity, today)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Interactive Podle Reactor</title>
  <style>
    :root{{--cyan:#2ee9ff;--pink:#ff2ec8;--lime:#ccff5e;--amber:#ffb347;--text:#e8f4ff;--muted:#9bb0c6}}
    *{{box-sizing:border-box}} body{{margin:0;background:radial-gradient(circle at 18% 8%,#2ee9ff33,transparent 28rem),radial-gradient(circle at 82% 4%,#ff2ec833,transparent 25rem),linear-gradient(135deg,#04050a,#07111b 48%,#17091e);color:var(--text);font-family:Inter,system-ui,sans-serif}}
    main{{width:min(920px,calc(100vw - 24px));margin:auto;padding:24px 0 48px}} .kicker{{color:var(--cyan);font:800 11px ui-monospace,monospace;letter-spacing:2.8px}} h1{{margin:8px 0 20px;font-size:clamp(28px,5vw,50px)}}
    .reactor,.wave-card{{border-radius:16px;background:linear-gradient(135deg,#07080d,#0a111a 54%,#14091a);border:1px solid #2ee9ff2e;box-shadow:0 18px 40px #0008;padding:18px;transition:transform .18s,box-shadow .18s}} .wave-card{{margin-top:16px;border-color:#ccff5e38;padding:0;overflow:hidden}} .wave-card:hover{{transform:translateY(-2px);box-shadow:0 0 42px #ccff5e2e,0 18px 40px #0008}}
    .top{{height:34px;border-bottom:1px solid #88d6ff29;font:800 11px ui-monospace,monospace;letter-spacing:2.8px;display:flex;align-items:center;gap:14px}} .dot{{width:10px;height:10px;border-radius:50%;background:var(--pink);box-shadow:0 0 18px var(--pink)}}
    .grid{{display:grid;grid-template-columns:minmax(0,1fr) 232px;gap:24px;padding-top:20px}} .panel{{min-height:360px;border-radius:14px;transition:transform .18s,box-shadow .18s}} .streak{{padding:18px 20px;background:#080c13;border:1px solid #2ee9ff3d}} .streak:hover{{transform:translateY(-2px);box-shadow:0 0 36px #2ee9ff38}} .bay{{padding:18px;background:repeating-linear-gradient(135deg,#171018 0 11px,#2c1d12 11px 22px);border:1px dashed #ffb347a6;color:#ffd6a0}} .bay:hover{{transform:translateY(-2px);box-shadow:0 0 36px #ff2ec838}}
    .rail{{display:inline-block;width:min(300px,58%);height:9px;margin-left:20px;border-radius:99px;background:linear-gradient(90deg,var(--cyan),var(--pink),#fff4d8,var(--cyan));background-size:260% 100%;box-shadow:0 0 18px var(--cyan);animation:rail 4.8s ease-in-out infinite alternate}} @keyframes rail{{to{{background-position:100%}}}} .num{{margin:38px 0 0;font-size:88px;font-weight:850;letter-spacing:-8px;background:linear-gradient(90deg,#fff,var(--cyan),var(--pink),#fff,var(--lime));background-size:220%;-webkit-background-clip:text;color:transparent;animation:num 2.4s ease-in-out infinite}} @keyframes num{{50%{{background-position:100%;filter:drop-shadow(0 0 24px #ff2ec8)}}}}
    .week{{margin-top:28px;padding-top:12px;border-top:1px solid #88d6ff24}} .bars{{height:88px;display:grid;grid-template-columns:repeat(7,1fr);gap:14px;align-items:end}} .day{{position:relative;display:flex;flex-direction:column;align-items:center;gap:7px;font:800 11px ui-monospace,monospace}} .day span{{width:100%;max-width:48px;border-radius:4px;background:var(--cyan);box-shadow:0 0 18px #2ee9ffcc;transform-origin:bottom;transition:.16s}} .day:before{{content:attr(data-commits) ' commits';position:absolute;bottom:100%;opacity:0;transform:translateY(6px);padding:5px 8px;border-radius:999px;background:linear-gradient(90deg,var(--cyan),var(--pink));white-space:nowrap;transition:.16s;z-index:2}} .day:hover:before{{opacity:1;transform:none}} .day:hover span{{transform:scaleY(1.14);background:var(--pink);box-shadow:0 0 24px #ff2ec8e6}}
    .bay h2{{margin:42px 0 20px;font:800 24px ui-monospace,monospace;letter-spacing:3px;color:var(--amber)}} .source{{color:var(--muted);font:12px ui-monospace,monospace;margin:14px 2px}} .wave-card svg{{display:block;width:100%;height:auto}}
    @media(max-width:700px){{.grid{{grid-template-columns:1fr}}.rail{{display:block;margin:14px 0;width:80%}}.num{{font-size:68px}}}}
  </style>
</head>
<body><main data-generated-date="{today.isoformat()}">
  <div class="kicker">INTERACTIVE PROFILE LAB</div><h1>Podle Reactor</h1>
  <section class="reactor" aria-label="Interactive PodleStreak and Podle Bay">
    <div class="top"><span class="dot"></span>PODLEHUB</div>
    <div class="grid">
      <section class="panel streak"><div class="kicker">PODLESTREAK <span class="rail"></span></div><div class="num">{streak} DAYS</div><h2>consecutive daily contribution streak</h2><div class="source">GitHub contribution calendar</div><div class="week"><div class="kicker">PODLEWEEK · {sum(week_counts)} COMMITS</div><div class="bars">{''.join(days)}</div></div></section>
      <aside class="panel bay"><div class="kicker">PODLE BAY</div><h2>HELD OPEN</h2><div>Separate selectable panel.</div><div class="source">Future module docks here.</div></aside>
    </div>
  </section>
  <section id="waveform" class="wave-card" aria-label="Interactive commit waveform">{waveform_svg}</section>
  <p class="source">Generated {today.isoformat()} from GitHub contribution-calendar streak data and complete private-inclusive default/gh-pages branch commit data.</p>
</main></body></html>
'''


def load_activity(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_assets(
    activity: dict[str, Any], output_dir: Path, pages_output: Path | None = None
) -> None:
    today = date.fromisoformat(activity["today"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "podle-reactor.svg").write_text(render_reactor(activity, today), encoding="utf-8")
    (output_dir / "waveform.svg").write_text(render_waveform(activity, today), encoding="utf-8")
    if pages_output is not None:
        pages_output.parent.mkdir(parents=True, exist_ok=True)
        pages_output.write_text(render_pages(activity, today), encoding="utf-8")
    print(f"wrote {output_dir / 'podle-reactor.svg'}", file=os.sys.stderr)
    print(f"wrote {output_dir / 'waveform.svg'}", file=os.sys.stderr)
    if pages_output is not None:
        print(f"wrote {pages_output}", file=os.sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="render from captured activity JSON")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "assets",
    )
    parser.add_argument("--today", type=date.fromisoformat, help="profile-local date for a live fetch")
    parser.add_argument(
        "--pages-output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "docs" / "reactor.html",
    )
    args = parser.parse_args()

    if args.fixture:
        activity = load_activity(args.fixture)
    else:
        today = args.today or datetime.now(PROFILE_TIMEZONE).date()
        activity = fetch_activity(os.environ.get("GH_TOKEN", ""), today)
    write_assets(activity, args.output_dir, args.pages_output)


if __name__ == "__main__":
    main()
