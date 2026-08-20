from __future__ import annotations

import importlib.util
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
    public_commits = []
    private_commits = []
    # Today is deliberately empty. The current incomplete day must not make the
    # displayed streak briefly drop to zero.
    for offset in range(1, 5):
        day = today - timedelta(days=offset)
        public_commits.append(commit(day, offset))
    # Make the latest complete seven-day period the deterministic busiest span.
    for offset in range(1, 8):
        day = today - timedelta(days=offset)
        private_commits.extend(commit(day, 100 + offset * 10 + index) for index in range(offset))
    return {
        "user": "podledges",
        "today": today.isoformat(),
        "repositories": [
            {"name": "podledges", "private": False, "commits": public_commits},
            {"name": "secret-project", "private": True, "commits": private_commits},
        ],
    }


class ProfileGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.today = date(2026, 8, 21)
        self.activity = fixture(self.today)

    def test_commit_streak_uses_latest_complete_day(self) -> None:
        self.assertEqual(waveform.commit_streak(self.activity, self.today), 7)

    def test_commit_days_follow_the_profile_time_zone(self) -> None:
        self.assertEqual(
            waveform.parse_commit_date("2026-08-20T23:30:00Z"),
            date(2026, 8, 21),
        )

    def test_signals_share_exact_chart_bounds(self) -> None:
        root = ET.fromstring(waveform.render_waveform(self.activity, self.today))
        signals = root.findall(".//svg:path[@data-role='signal']", SVG)
        self.assertEqual(len(signals), waveform.CHANNELS)
        self.assertEqual({signal.attrib["data-chart-start"] for signal in signals}, {"170"})
        self.assertEqual({signal.attrib["data-chart-end"] for signal in signals}, {"838"})
        self.assertTrue(all(signal.attrib["d"].startswith("M170 ") for signal in signals))
        self.assertTrue(all("L838 " in signal.attrib["d"] for signal in signals))

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
        for renderer in (waveform.render_reactor, waveform.render_waveform):
            root = ET.fromstring(renderer(self.activity, self.today))
            self.assertIsNotNone(root.find("svg:title", SVG))
            self.assertIsNotNone(root.find("svg:desc", SVG))
            animations = root.findall(".//svg:animate", SVG) + root.findall(
                ".//svg:animateTransform", SVG
            )
            self.assertTrue(animations)
            self.assertFalse(root.findall(".//svg:script", SVG))

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
        _, expected = waveform.busiest_window(aggregate)
        self.assertIn(f"🔥🔥{expected} commits 🥵🥵", rendered)

    def test_written_assets_are_valid_svg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            waveform.write_assets(self.activity, output)
            ET.parse(output / "podle-reactor.svg")
            ET.parse(output / "waveform.svg")


if __name__ == "__main__":
    unittest.main()
