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

if __package__:
    from . import prism_orbit
else:
    import prism_orbit

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

    def get(self, path: str, *, missing_ok: bool = False, empty_ok: bool = False) -> Any:
        request = urllib.request.Request(API + path, headers=self.headers())
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if missing_ok and error.code in (404, 409):
                return None
            detail = error.read().decode("utf-8", "replace")
            if empty_ok and error.code == 409:
                try:
                    if json.loads(detail).get("message") == "Git Repository is empty.":
                        return []
                except (ValueError, AttributeError):
                    pass
            raise RuntimeError(f"GitHub REST API {error.code}: {detail}") from error

    def paginated(self, path: str, *, empty_ok: bool = False) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page = 1
        separator = "&" if "?" in path else "?"
        while True:
            batch = self.get(f"{path}{separator}per_page=100&page={page}", empty_ok=empty_ok)
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
            for commit in self.paginated(path, empty_ok=True):
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


def fetch_contributions(token: str, now: datetime | None = None) -> dict[str, Any]:
    """Fetch the calendar independently of the unrelated REST commit waveform."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    today = now.date()
    api = GitHubApi(token)
    data = api.graphql(CONTRIBUTIONS_QUERY, {
        "login": api.user,
        "historyFrom": datetime.combine(today - timedelta(days=HISTORY_DAYS - 1), time.min, timezone.utc).isoformat(),
        "windowFrom": datetime.combine(today - timedelta(days=WAVEFORM_DAYS - 1), time.min, timezone.utc).isoformat(),
        "to": now.isoformat(),
    })
    days, _ = contribution_source(data, api.user)
    return {"user": api.user, "today": today.isoformat(),
            "retrieved_at": now.isoformat().replace("+00:00", "Z"), "contribution_days": days}


def fetch_activity(token: str, today: date) -> dict[str, Any]:
    api = GitHubApi(token)
    history_start = today - timedelta(days=HISTORY_DAYS - 1)
    window_start = today - timedelta(days=WAVEFORM_DAYS - 1)
    to = datetime.combine(today + timedelta(days=1), time.min, PROFILE_TIMEZONE)
    retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
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
        "retrieved_at": retrieved_at,
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


def profile_data(activity: dict[str, Any]) -> dict[str, Any]:
    """Normalize an owner-authenticated calendar; never invent missing dates."""
    retrieved_at = activity.get("retrieved_at", activity["today"] + "T00:00:00Z")
    retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    if retrieved.tzinfo is None:
        raise ValueError("retrieved_at must include its UTC offset")
    # Contribution dates belong to GitHub's calendar, not the waveform's SG days.
    today = min(date.fromisoformat(activity["today"]), retrieved.astimezone(timezone.utc).date())
    counts = {}
    for day in activity["contribution_days"]:
        stamp = date.fromisoformat(day["date"])
        count = day["count"]
        if stamp in counts or type(count) is not int or count < 0:
            raise ValueError("Calendar dates must be unique with nonnegative integer counts")
        counts[stamp] = count
    dates = [today - timedelta(days=13 - i) for i in range(14)]
    if any(day not in counts for day in dates):
        raise ValueError("A complete fourteen-date contribution calendar is required")
    streak_days = contribution_streak(activity, today)
    end = today if counts[today] else today - timedelta(days=1)
    start = end - timedelta(days=streak_days - 1) if streak_days else None
    if start and start - timedelta(days=1) not in counts:
        raise ValueError("Current streak reaches the capture boundary; fetch more history before claiming an exact length")
    daily = [{"date": day.isoformat(), "count": counts[day]} for day in dates]
    return {
        "today": today.isoformat(),
        "retrieved_at": retrieved.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "GitHub GraphQL contribution calendar; owner-authenticated, private-inclusive",
        "current_streak": {"days": streak_days, "start": start.isoformat() if start else None,
                           "end": end.isoformat() if streak_days else None},
        "longest_ever": None,
        "chart": {"daily": daily, "total": sum(day["count"] for day in daily)},
    }


def render_reactor(activity: dict[str, Any], today: date) -> str:
    """Compatibility entry point now renders the accepted independent streak."""
    return prism_orbit.streak_svg(profile_data({**activity, "today": today.isoformat()}))


def render_pages(activity: dict[str, Any], today: date) -> str:
    data = profile_data({**activity, "today": today.isoformat()})
    hub = (Path(__file__).resolve().parent.parent / "assets" / "codex-hardline-podlehub.svg").read_text()
    return prism_orbit.render_pages(data, render_waveform(activity, today), hub)


def load_activity(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def write_assets(
    activity: dict[str, Any], output_dir: Path, pages_output: Path | None = None,
    *, contributions_only: bool = False,
) -> None:
    today = date.fromisoformat(activity["today"])
    data = profile_data(activity)
    # Render everything before touching outputs: invalid input must leave the
    # previous complete capture intact. The old reactor path is a compatibility alias.
    streak = prism_orbit.streak_svg(data)
    waveform_svg = ((output_dir / "waveform.svg").read_text() if contributions_only
                    else render_waveform(activity, today))
    outputs = {
        output_dir / "prism-orbit-streak.svg": streak,
        output_dir / "podle-reactor.svg": streak,
        output_dir / "prism-orbit-bay.svg": prism_orbit.bay_svg(data),
        output_dir / "profile-contributions.json": json.dumps(data, indent=2) + "\n",
    }
    if not contributions_only:
        outputs[output_dir / "waveform.svg"] = waveform_svg
    if pages_output is not None:
        hub = (Path(__file__).resolve().parent.parent / "assets" / "codex-hardline-podlehub.svg").read_text()
        outputs[pages_output] = prism_orbit.render_pages(data, waveform_svg, hub)
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path}", file=os.sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, help="render from captured activity JSON")
    parser.add_argument("--contributions-only", action="store_true",
                        help="refresh the calendar pair and page; preserve the existing waveform capture")
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
    elif args.contributions_only:
        if args.today:
            parser.error("--today is only supported for full REST captures; calendar-only uses the actual UTC retrieval date")
        activity = fetch_contributions(os.environ.get("GH_TOKEN", ""))
    else:
        today = args.today or datetime.now(PROFILE_TIMEZONE).date()
        activity = fetch_activity(os.environ.get("GH_TOKEN", ""), today)
    write_assets(activity, args.output_dir, args.pages_output, contributions_only=args.contributions_only)


if __name__ == "__main__":
    main()
