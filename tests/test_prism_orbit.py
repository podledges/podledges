from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import waveform, prism_orbit
from test_profile_assets import fixture, SVG


class PrismOrbitTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 8)
        self.activity = fixture(self.today)
        self.activity['retrieved_at'] = '2026-09-08T20:15:00Z'
        series = [32, 17, 5, 10, 6, 28, 6, 50, 17, 30, 11, 50, 13, 75]
        for row, count in zip(self.activity['contribution_days'][-14:], series):
            row['count'] = count

    def test_real_thresholds_and_linear_scale_preserve_selected_geometry(self):
        data = waveform.profile_data(self.activity)
        self.assertEqual(data['current_streak']['days'], 52)
        self.assertEqual(data['chart']['total'], 350)
        root = ET.fromstring(prism_orbit.streak_svg(data))
        self.assertEqual(root.attrib['viewBox'], '0 0 533.2 588')
        bars = root.findall('.//svg:g[@data-role="contribution-bar"]', SVG)
        self.assertEqual(len(bars), 14)
        self.assertEqual([int(b.attrib['data-count']) for b in bars if b.attrib['data-hotzone'] == 'true'], [50, 50, 75])
        for bar, day in zip(bars, data['chart']['daily']):
            rect = bar.find('svg:rect', SVG)
            self.assertEqual(float(rect.attrib['height']), day['count'] * 2)
            self.assertEqual(float(rect.attrib['y']) + float(rect.attrib['height']), 548)
        self.assertEqual(ET.fromstring(prism_orbit.bay_svg(data)).attrib['viewBox'], '0 0 326.8 588')

    def test_future_peaks_remain_linear_without_changing_number(self):
        data = waveform.profile_data(self.activity)
        before = ET.fromstring(prism_orbit.streak_svg(data))
        changed = copy.deepcopy(data)
        changed['chart']['daily'][-1]['count'] = 300
        changed['chart']['total'] += 225
        after = ET.fromstring(prism_orbit.streak_svg(changed))
        for selector in ('streak-number', 'number-atmosphere'):
            self.assertEqual(ET.tostring(before.find(f'.//svg:g[@id="{selector}"]', SVG)),
                             ET.tostring(after.find(f'.//svg:g[@id="{selector}"]', SVG)))
        for rect, day in zip(after.findall('.//svg:rect[@data-role="bar-measure"]', SVG), changed['chart']['daily']):
            self.assertEqual(float(rect.attrib['height']), day['count'] * .5)
            self.assertGreaterEqual(float(rect.attrib['y']), 398)
        self.assertEqual(prism_orbit.number_body(data['current_streak'], data['retrieved_at']),
                         prism_orbit.number_body(changed['current_streak'], changed['retrieved_at']))

    def test_zero_days_and_inclusive_fifty_hotzone(self):
        rows = self.activity['contribution_days'][-14:]
        for row, count in zip(rows, [0, 49, 50, 51] + [1] * 10):
            row['count'] = count
        root = ET.fromstring(prism_orbit.streak_svg(waveform.profile_data(self.activity)))
        bars = root.findall('.//svg:g[@data-role="contribution-bar"]', SVG)
        self.assertEqual([b.attrib['data-hotzone'] for b in bars[:4]], ['false', 'false', 'true', 'true'])
        self.assertEqual(bars[0].find('svg:rect', SVG).attrib['height'], '0')

    def test_refresh_updates_all_primary_outputs_and_page_atomically_on_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            waveform.write_assets(self.activity, out / 'assets', out / 'reactor.html')
            first = (out / 'assets/prism-orbit-streak.svg').read_bytes()
            self.activity['contribution_days'][-1]['count'] += 1
            waveform.write_assets(self.activity, out / 'assets', out / 'reactor.html')
            self.assertNotEqual(first, (out / 'assets/prism-orbit-streak.svg').read_bytes())
            self.assertEqual((out / 'assets/podle-reactor.svg').read_bytes(), (out / 'assets/prism-orbit-streak.svg').read_bytes())
            self.assertEqual(json.loads((out / 'assets/profile-contributions.json').read_text())['chart']['total'], 351)
            saved = {p: p.read_bytes() for p in out.rglob('*') if p.is_file()}
            self.activity['contribution_days'].pop()
            with self.assertRaisesRegex(ValueError, 'fourteen-date'):
                waveform.write_assets(self.activity, out / 'assets', out / 'reactor.html')
            self.assertEqual(saved, {p: p.read_bytes() for p in out.rglob('*') if p.is_file()})

    def test_committed_primary_outputs_reproduce_from_their_public_snapshot(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / 'assets/profile-contributions.json').read_text())
        expected = prism_orbit.streak_svg(data)
        for name in ('prism-orbit-streak.svg', 'podle-reactor.svg'):
            self.assertEqual((root / 'assets' / name).read_text(), expected)
        self.assertEqual((root / 'assets/prism-orbit-bay.svg').read_text(), prism_orbit.bay_svg(data))
        self.assertEqual((root / 'docs/reactor.html').read_text(), prism_orbit.render_pages(
            data, (root / 'assets/waveform.svg').read_text(), (root / 'assets/codex-hardline-podlehub.svg').read_text()))

    def test_calendar_fetch_requires_owner_and_never_requests_rest_commits(self):
        def response(login):
            return {'viewer': {'login': login}, 'user': {
                'history': {'contributionCalendar': {'weeks': [{'contributionDays': [
                    {'date': day['date'], 'contributionCount': day['count']} for day in self.activity['contribution_days']
                ]}]}}, 'window': {'totalCommitContributions': 0}}}
        now = datetime(2026, 9, 8, 20, 15, tzinfo=timezone.utc)
        with patch.object(waveform.GitHubApi, 'graphql', return_value=response('podledges')) as graphql, patch.object(waveform.GitHubApi, 'get') as rest:
            captured = waveform.fetch_contributions('not-a-real-token', now)
            self.assertEqual(waveform.profile_data(captured)['chart']['total'], 350)
            self.assertEqual(graphql.call_args.args[1]['to'], now.isoformat())
            rest.assert_not_called()
        with patch.object(waveform.GitHubApi, 'graphql', return_value=response('github-actions[bot]')), self.assertRaisesRegex(RuntimeError, 'must belong'):
            waveform.fetch_contributions('not-a-real-token', now)

    def test_calendar_only_refresh_preserves_waveform_and_requires_no_commit_feed(self):
        activity = {k: v for k, v in self.activity.items() if k != 'repositories'}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            original = (Path(__file__).resolve().parents[1] / 'assets/waveform.svg').read_bytes()
            (out / 'waveform.svg').write_bytes(original)
            waveform.write_assets(activity, out, out / 'reactor.html', contributions_only=True)
            self.assertEqual((out / 'waveform.svg').read_bytes(), original)
            self.assertEqual(json.loads((out / 'profile-contributions.json').read_text())['chart']['total'], 350)

    def test_incomplete_invalid_or_history_bounded_data_is_rejected(self):
        for mutation in ('missing', 'negative', 'duplicate', 'boundary'):
            activity = copy.deepcopy(self.activity)
            if mutation == 'missing': activity['contribution_days'].pop(-2)
            elif mutation == 'negative': activity['contribution_days'][-1]['count'] = -1
            elif mutation == 'duplicate': activity['contribution_days'].append(activity['contribution_days'][-1])
            else: activity['contribution_days'].pop(0)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                waveform.profile_data(activity)

    def test_calendar_date_does_not_advance_at_singapore_midnight(self):
        self.activity['today'] = '2026-09-09'
        data = waveform.profile_data(self.activity)
        self.assertEqual(data['today'], '2026-09-08')
        self.assertEqual(data['current_streak']['days'], 52)
        self.assertEqual(data['chart']['daily'][-1]['date'], '2026-09-08')

    def test_native_output_is_self_contained_with_preserved_rest_objects(self):
        data = waveform.profile_data(self.activity)
        for value in (prism_orbit.streak_svg(data), prism_orbit.bay_svg(data)):
            root = ET.fromstring(value)
            self.assertIsNotNone(root.find('svg:title', SVG))
            self.assertIsNotNone(root.find('svg:desc', SVG))
            for node in root.iter():
                self.assertNotIn(node.tag.split('}')[-1], ('text', 'script', 'foreignObject', 'a'))
                for key, val in node.attrib.items():
                    self.assertFalse(key.startswith('on'))
                    if key.split('}')[-1] == 'href': self.assertTrue(val.startswith(('#', 'data:')))
        root = ET.fromstring(prism_orbit.streak_svg(data))
        moving = root.find('.//svg:g[@data-role="orbit-object"]/svg:use', SVG)
        resting = root.find('.//svg:g[@data-role="orbit-rest"]/svg:use', SVG)
        self.assertEqual(moving.attrib['href'], resting.attrib['href'])
        self.assertIsNone(data['longest_ever'])

    def test_exact_font_outlines_and_explicit_unsupported_character(self):
        from scripts.prism import font
        self.assertEqual(font.atlas()['font_sha256'], 'd00e590b8eb3a59acc329b2d044fd143ae935090b7da33199ebee27cc7de8196')
        for weight in (420, 500, 555, 676):
            root = ET.fromstring(font.text('PodleStreak 52', 0, 0, 36, weight))
            self.assertEqual(root.attrib['data-weight'], str(weight))
            self.assertTrue(root.findall('path'))
        with self.assertRaisesRegex(ValueError, 'Unsupported profile character'):
            font.text('\U0001f9ff', 0, 0, 16)


class EmptyRepositoryTests(unittest.TestCase):
    def test_only_confirmed_empty_commit_repository_is_zero_not_a_fetch_failure(self):
        api = waveform.GitHubApi('not-a-real-token')
        body = json.dumps({'message': 'Git Repository is empty.'}).encode()
        def fail(*args, **kwargs):
            raise urllib.error.HTTPError('https://api.github.com/test', 409, 'Conflict', {}, io.BytesIO(body))
        with patch('urllib.request.urlopen', side_effect=fail):
            self.assertEqual(api.commits('owner/empty', ['main'], waveform.local_day_start_utc(date(2026, 9, 8))), [])
            with self.assertRaises(RuntimeError): api.get('/unrelated')

    def test_other_conflicts_auth_errors_and_missing_repos_still_fail_closed(self):
        api = waveform.GitHubApi('not-a-real-token')
        for status, message in ((409, 'Another conflict'), (403, 'Forbidden'), (404, 'Not found')):
            def fail(*args, **kwargs):
                raise urllib.error.HTTPError('https://api.github.com/test', status, message, {}, io.BytesIO(json.dumps({'message': message}).encode()))
            with self.subTest(status=status), patch('urllib.request.urlopen', side_effect=fail), self.assertRaises(RuntimeError):
                api.commits('owner/repo', ['main'], waveform.local_day_start_utc(date(2026, 9, 8)))


if __name__ == '__main__':
    unittest.main()
