from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("waveform", ROOT / "scripts" / "waveform.py")
assert SPEC and SPEC.loader
waveform = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = waveform
SPEC.loader.exec_module(waveform)

SVG = {"svg": "http://www.w3.org/2000/svg"}


def commit(day: date, index: int) -> dict[str, str]:
    return {"sha": f"sha-{day}-{index}", "date": f"{day.isoformat()}T12:00:00Z"}


def fixture(today: date) -> dict:
    public_contributions = []
    private_contributions = []
    for offset in range(1, 5):
        day = today - timedelta(days=offset)
        public_contributions.append(commit(day, offset))
    streak_start = date(2026, 7, 19)
    # Make the latest complete seven-day period the deterministic busiest
    # commit span. Aug 9 deliberately has no commit even though GitHub counts a
    # contribution on that day.
    for offset in range(1, 8):
        day = today - timedelta(days=offset)
        private_contributions.extend(
            commit(day, 100 + offset * 10 + index) for index in range(offset)
        )

    contribution_days = [
        {
            "date": (streak_start + timedelta(days=offset)).isoformat(),
            "count": 1,
        }
        for offset in range((today - streak_start).days + 1)
    ]
    return {
        "user": "podledges",
        "today": today.isoformat(),
        "contribution_days": contribution_days,
        "repositories": [
            {"name": "podledges", "private": False, "commits": public_contributions},
            {"name": "secret-project", "private": True, "commits": private_contributions},
        ],
    }


class ProfileGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.today = date(2026, 8, 21)
        self.activity = fixture(self.today)

    def test_streak_uses_github_contribution_days_not_repository_commits(self) -> None:
        # Aug 9 has a GitHub contribution but no commit in this fixture. A
        # repository-commit streak would incorrectly stop there at 11 days.
        august_ninth = next(
            day for day in self.activity["contribution_days"] if day["date"] == "2026-08-09"
        )
        self.assertEqual(august_ninth["count"], 1)
        window_start = self.today - timedelta(days=waveform.WAVEFORM_DAYS - 1)
        commit_counts = waveform.daily_counts(
            self.activity, window_start, waveform.WAVEFORM_DAYS
        )
        august_ninth_index = (date(2026, 8, 9) - window_start).days
        self.assertEqual(
            sum(repository[august_ninth_index] for repository in commit_counts.values()),
            0,
        )
        self.assertEqual(waveform.contribution_streak(self.activity, self.today), 34)
        self.assertIn("34 DAYS", waveform.render_reactor(self.activity, self.today))

    def test_contribution_streak_uses_latest_complete_day(self) -> None:
        activity = fixture(self.today)
        activity["contribution_days"] = [
            day for day in activity["contribution_days"] if day["date"] != self.today.isoformat()
        ]
        self.assertEqual(waveform.contribution_streak(activity, self.today), 33)

    def test_signals_share_exact_chart_bounds(self) -> None:
        root = ET.fromstring(waveform.render_waveform(self.activity, self.today))
        signals = root.findall(".//svg:path[@data-role='signal']", SVG)
        self.assertEqual(len(signals), waveform.CHANNELS)
        self.assertEqual({signal.attrib["data-chart-start"] for signal in signals}, {"170"})
        self.assertEqual({signal.attrib["data-chart-end"] for signal in signals}, {"838"})
        self.assertTrue(all(signal.attrib["d"].startswith("M170 ") for signal in signals))
        self.assertTrue(all("L838 " in signal.attrib["d"] for signal in signals))
        hot_segments = root.findall(".//svg:path[@data-role='hotseg']", SVG)
        self.assertEqual(len(hot_segments), waveform.CHANNELS)
        self.assertTrue(all(segment.attrib["d"].startswith("M170 ") for segment in hot_segments))
        self.assertTrue(all("L838 " in segment.attrib["d"] for segment in hot_segments))

    def test_weekly_axis_and_guides_match_signal_bounds(self) -> None:
        root = ET.fromstring(waveform.render_waveform(self.activity, self.today))
        axis = root.find(".//svg:line[@data-role='week-axis']", SVG)
        guides = root.findall(".//svg:line[@data-role='week-guide']", SVG)
        self.assertIsNotNone(axis)
        self.assertEqual((axis.attrib["x1"], axis.attrib["x2"]), ("170", "838"))
        self.assertEqual((guides[0].attrib["x1"], guides[-1].attrib["x1"]), ("170", "838"))

    def test_animated_cursor_is_inside_its_filter_region(self) -> None:
        root = ET.fromstring(waveform.render_waveform(self.activity, self.today))
        glow = root.find(".//svg:filter[@id='wave-glow']", SVG)
        self.assertIsNotNone(glow)
        left = float(glow.attrib["x"])
        right = left + float(glow.attrib["width"])
        self.assertLessEqual(left, 0)
        self.assertGreaterEqual(right, 0)

    def test_svg_native_animation_and_accessibility_are_present(self) -> None:
        reactor = ET.fromstring(waveform.render_reactor(self.activity, self.today))
        rendered_waveform = ET.fromstring(waveform.render_waveform(self.activity, self.today))
        for root in (reactor, rendered_waveform):
            self.assertIsNotNone(root.find("svg:title", SVG))
            self.assertIsNotNone(root.find("svg:desc", SVG))
            self.assertFalse(root.findall(".//svg:script", SVG))
            self.assertFalse(root.findall(".//svg:foreignObject", SVG))
            self.assertFalse(
                any(
                    attribute.lower().startswith("on")
                    for element in root.iter()
                    for attribute in element.attrib
                )
            )

        reactor_animations = reactor.findall(".//svg:animate", SVG)
        waveform_animations = rendered_waveform.findall(".//svg:animate", SVG)
        self.assertGreaterEqual(len(reactor_animations), 20)
        self.assertGreaterEqual(len(waveform_animations), 18)
        self.assertEqual(
            len(rendered_waveform.findall(".//svg:path[@data-role='hotseg']", SVG)),
            waveform.CHANNELS,
        )
        self.assertIsNotNone(
            rendered_waveform.find(".//svg:rect[@data-role='cursor-burst']", SVG)
        )
        self.assertEqual(
            len(reactor.findall(".//svg:rect[@data-role='day-bar']", SVG)),
            7,
        )
        self.assertEqual(
            len(reactor.findall(".//svg:g[@data-role='week-popup']", SVG)),
            7,
        )
        cursor = rendered_waveform.find(".//svg:g[@data-role='cursor']/svg:animateTransform", SVG)
        self.assertIsNotNone(cursor)
        self.assertEqual(cursor.attrib["dur"], "2.8s")
        self.assertEqual((cursor.attrib["from"], cursor.attrib["to"]), ("170 0", "838 0"))

    def test_reactor_frame_and_glows_have_clipping_room(self) -> None:
        root = ET.fromstring(waveform.render_reactor(self.activity, self.today))
        frame = root.find("svg:rect[@data-role='outer-frame']", SVG)
        self.assertIsNotNone(frame)
        self.assertEqual((frame.attrib["x"], frame.attrib["y"]), ("1", "1"))
        for filter_element in root.findall(".//svg:filter", SVG):
            self.assertEqual(filter_element.attrib["filterUnits"], "userSpaceOnUse")
            self.assertTrue({"x", "y", "width", "height"}.issubset(filter_element.attrib))

    def test_private_names_are_masked_and_highlight_count_is_computed(self) -> None:
        rendered = waveform.render_waveform(self.activity, self.today)
        self.assertIn("&lt;PRIVATE🔒&gt;", rendered)
        self.assertNotIn("SECRET-PROJECT", rendered)
        aggregate_start = self.today - timedelta(days=waveform.WAVEFORM_DAYS - 1)
        counts = waveform.daily_counts(
            self.activity, aggregate_start, waveform.WAVEFORM_DAYS
        )
        aggregate = [sum(repo[index] for repo in counts.values()) for index in range(waveform.WAVEFORM_DAYS)]
        highlight_index, expected = waveform.busiest_window(aggregate)
        self.assertIn(f"🔥🔥{expected} commits 🥵🥵", rendered)
        self.assertIn(f">{sum(aggregate)} COMMITS ·", rendered)
        root = ET.fromstring(rendered)
        highlight = root.find(".//svg:rect[@data-role='highlight-window']", SVG)
        self.assertIsNotNone(highlight)
        expected_x = 170 + highlight_index * ((838 - 170) / waveform.WAVEFORM_DAYS)
        self.assertAlmostEqual(float(highlight.attrib["x"]), expected_x, places=2)

    def test_pages_clone_preserves_real_hover_interactions(self) -> None:
        rendered = waveform.render_pages(self.activity, self.today)
        self.assertIn(".streak:hover", rendered)
        self.assertIn(".bay:hover", rendered)
        self.assertIn(".day:hover:before", rendered)
        self.assertIn(".day:hover span", rendered)
        self.assertIn('id="waveform"', rendered)
        self.assertIn("34 DAYS", rendered)
        self.assertNotIn("SECRET-PROJECT", rendered)

    def test_readme_links_images_to_interactive_pages_clone(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://podledges.github.io/podledges/reactor.html", readme)
        self.assertIn("https://podledges.github.io/podledges/reactor.html#waveform", readme)

    def test_profile_has_one_live_streak_and_one_live_commit_panel(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        sources = re.findall(r'<img src="([^"]+\.svg)"', readme)
        self.assertEqual(
            sources,
            [
                "assets/podle-reactor.svg",
                "assets/codex-hardline-podlehub.svg",
                "assets/waveform.svg",
            ],
        )
        panels = {
            source: (ROOT / source).read_text(encoding="utf-8") for source in sources
        }
        streak_panels = [source for source, panel in panels.items() if "PODLESTREAK" in panel]
        commit_panels = [
            source
            for source, panel in panels.items()
            if "COMMIT ANALYZER" in panel or "COMMIT WAVEFORM" in panel
        ]
        self.assertEqual(streak_panels, ["assets/podle-reactor.svg"])
        self.assertEqual(commit_panels, ["assets/waveform.svg"])
        for source in streak_panels + commit_panels:
            self.assertIn("data-generated-date=", panels[source])

        workflow = (ROOT / ".github" / "workflows" / "waveform.yml").read_text(
            encoding="utf-8"
        )
        for source in streak_panels + commit_panels:
            self.assertIn(source, workflow)

    def test_committed_generated_files_are_valid_and_accessible(self) -> None:
        reactor = ET.parse(ROOT / "assets" / "podle-reactor.svg").getroot()
        rendered_waveform = ET.parse(ROOT / "assets" / "waveform.svg").getroot()
        for root in (reactor, rendered_waveform):
            self.assertIsNotNone(root.find("svg:title", SVG))
            self.assertIsNotNone(root.find("svg:desc", SVG))
            self.assertIn("data-generated-date", root.attrib)
        pages = (ROOT / "docs" / "reactor.html").read_text(encoding="utf-8")
        self.assertIn("data-generated-date=\"", pages)

    def test_graphql_calendar_counts_august_ninth_for_streak(self) -> None:
        contribution_days = self.activity["contribution_days"]
        data = {
            "viewer": {"login": "podledges"},
            "user": {
                "history": {
                    "contributionCalendar": {
                        "weeks": [{"contributionDays": [
                            {"date": day["date"], "contributionCount": day["count"]}
                            for day in contribution_days
                        ]}]
                    }
                },
                "window": {"totalCommitContributions": 92},
            },
        }
        days, public_commit_total = waveform.contribution_source(data)
        self.assertIn({"date": "2026-08-09", "count": 1}, days)
        self.assertEqual(public_commit_total, 92)
        activity = {**self.activity, "contribution_days": days}
        self.assertEqual(waveform.contribution_streak(activity, self.today), 34)

    def test_graphql_token_must_belong_to_profile_owner(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must belong to the profile user"):
            waveform.contribution_source(
                {"viewer": {"login": "github-actions[bot]"}, "user": {}},
            )

    def test_rest_pagination_has_no_ten_page_cap(self) -> None:
        api = waveform.GitHubApi("token")
        calls = []

        def fake_get(path: str, **_kwargs):
            page = int(path.rsplit("page=", 1)[1])
            calls.append(page)
            if page <= 10:
                return [{"id": f"{page}-{index}"} for index in range(100)]
            return [{"id": "last"}]

        api.get = fake_get
        records = api.paginated("/example")
        self.assertEqual(len(records), 1001)
        self.assertEqual(calls, list(range(1, 12)))

    def test_commit_window_starts_at_singapore_midnight(self) -> None:
        self.assertEqual(
            waveform.local_day_start_utc(date(2026, 6, 27)).isoformat(),
            "2026-06-26T16:00:00+00:00",
        )

    def test_written_assets_are_valid_svg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            waveform.write_assets(self.activity, output)
            ET.parse(output / "podle-reactor.svg")
            ET.parse(output / "waveform.svg")


if __name__ == "__main__":
    unittest.main()
