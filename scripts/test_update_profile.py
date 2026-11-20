"""Offline checks for calculations, pagination, rendering, and failure behavior."""
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import update_profile as profile


def days(counts):
    return [{'date': f'2026-11-{index+1:02}', 'contributionCount': count}
            for index, count in enumerate(counts)]


def sample_user(counts=(1, 0, 2, 3, 0)):
    return {'contributionsCollection': {
        'totalCommitContributions': 4,
        'totalPullRequestContributions': 1,
        'totalIssueContributions': 1,
        'totalRepositoriesWithContributedCommits': 2,
        'contributionCalendar': {'totalContributions': sum(counts),
                                 'weeks': [{'contributionDays': days(counts)}]}},
        'repositories': [{'stargazerCount': 7, 'languages': {'edges': [
            {'size': 300, 'node': {'name': 'TypeScript', 'color': '#3178c6'}},
            {'size': 100, 'node': {'name': 'Java', 'color': '#b07219'}}]}}]}


class ProfileTests(unittest.TestCase):
    def test_streak_allows_unfinished_today(self):
        self.assertEqual(profile.streak_lengths(days([1, 0, 2, 3, 0])), (2, 2))
        self.assertEqual(profile.streak_lengths(days([1, 1, 0, 0])), (0, 2))
        self.assertEqual(profile.streak_lengths(days([0, 2, 1])), (2, 2))
        self.assertEqual(profile.streak_lengths(days([])), (0, 0))

    def test_renders_real_values_and_valid_svg(self):
        cards = profile.render(sample_user(), datetime(2026, 11, 5, tzinfo=timezone.utc))
        for svg in cards.values():
            ET.fromstring(svg)
        self.assertIn('TypeScript 75.0%', cards['languages'])
        self.assertIn('Java 25.0%', cards['languages'])
        self.assertIn('2026-11-05 00:00 UTC', cards['stats'])
        self.assertIn('2026-11-03: 2 contributions', cards['activity'])

    def test_zero_activity_and_no_languages(self):
        user = sample_user((0, 0))
        user['repositories'] = []
        cards = profile.render(user, datetime(2026, 11, 2, tzinfo=timezone.utc))
        self.assertIn('No language data', cards['languages'])
        for svg in cards.values():
            self.assertNotIn('nan', svg.lower())
            ET.fromstring(svg)

    def test_graphql_pages_and_errors(self):
        class Response:
            def __init__(self, payload): self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps(self.payload).encode()

        def page(stars, more, cursor):
            return {'data': {'user': {'login': 'Bbuddhika', 'repositories': {
                'nodes': [{'stargazerCount': stars}],
                'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}}}}

        with patch.object(profile.urllib.request, 'urlopen', side_effect=[
            Response(page(2, True, 'page2')), Response(page(3, False, None))]) as call:
            user = profile.fetch_data('Bbuddhika', 'test-token')
            self.assertEqual(sum(r['stargazerCount'] for r in user['repositories']), 5)
            self.assertEqual(json.loads(call.call_args.args[0].data)['variables']['cursor'], 'page2')

        with patch.object(profile.urllib.request, 'urlopen', return_value=Response({'errors': [{}]})):
            with self.assertRaises(RuntimeError):
                profile.fetch_data('Bbuddhika', 'test-token')


if __name__ == '__main__':
    unittest.main()
