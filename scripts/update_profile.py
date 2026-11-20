"""Generate profile SVGs from GitHub GraphQL using only Python's standard library.

No personal token is required in Actions. Failed fetches leave existing SVGs intact.
Use --placeholders only for the initial, unpublished upload package.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
from html import escape
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BLUE, TEAL, PURPLE, MUTED = '#70a5fd', '#23c8b5', '#bf91f3', '#9aa8bf'
QUERY = '''query($login:String!, $cursor:String) {
  user(login:$login) {
    login
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalRepositoriesWithContributedCommits
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
    repositories(first:50, after:$cursor, ownerAffiliations:[OWNER],
                 isFork:false, privacy:PUBLIC) {
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        languages(first:100, orderBy:{field:SIZE, direction:DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}'''


def fetch_data(login, token):
    """Paginate owned public repositories; never log tokens or raw responses."""
    cursor, user, repositories = None, None, []
    while True:
        request = urllib.request.Request(
            'https://api.github.com/graphql',
            data=json.dumps({'query': QUERY, 'variables': {
                'login': login, 'cursor': cursor}}).encode(),
            headers={'Authorization': f'Bearer {token}',
                     'User-Agent': 'Bbuddhika-profile-cards',
                     'Content-Type': 'application/json'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    payload = json.load(response)
                break
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError(f'GitHub request failed (HTTP {error.code}).') from None
                time.sleep(2 ** attempt)
            except urllib.error.URLError:
                if attempt == 2:
                    raise RuntimeError('Cannot connect to GitHub; previous cards preserved.') from None
                time.sleep(2 ** attempt)
        if payload.get('errors'):
            raise RuntimeError('GitHub GraphQL returned errors; previous cards preserved.')
        current = payload.get('data', {}).get('user')
        if not current:
            raise RuntimeError('GitHub user not found; previous cards preserved.')
        if user is None:
            user = current
        connection = current['repositories']
        repositories.extend(connection['nodes'])
        if not connection['pageInfo']['hasNextPage']:
            break
        next_cursor = connection['pageInfo']['endCursor']
        if not next_cursor or next_cursor == cursor:
            raise RuntimeError('Invalid repository pagination cursor.')
        cursor = next_cursor
    user['repositories'] = repositories
    return user


def streak_lengths(days):
    """Current streak allows today to be incomplete; longest uses this calendar only."""
    longest = run = 0
    for day in days:
        run = run + 1 if day['contributionCount'] > 0 else 0
        longest = max(longest, run)
    counts = [day['contributionCount'] for day in days]
    if counts and counts[-1] == 0:
        counts.pop()
    current = 0
    for count in reversed(counts):
        if count == 0:
            break
        current += 1
    return current, longest


def text(x, y, content, color=MUTED, size=14, anchor='start', weight='400'):
    return (f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{escape(str(content))}</text>')


def card(width, height, title, body, updated):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title">'
            f'<title id="title">{escape(title)}</title>'
            f'<rect width="{width}" height="{height}" rx="7" fill="#1a1b27"/>'
            '<g font-family="Segoe UI,Arial,sans-serif">'
            + text(24, 36, title, BLUE, 19, weight='600') + body
            + text(24, height - 15, updated, MUTED, 10) + '</g></svg>')


def render(user, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = 'Updated ' + now.strftime('%Y-%m-%d %H:%M UTC')
    contributions = user['contributionsCollection']
    calendar = contributions['contributionCalendar']
    days = sorted((day for week in calendar['weeks'] for day in week['contributionDays']
                   if date.fromisoformat(day['date']) <= now.date()), key=lambda d: d['date'])
    if not days:
        raise ValueError('Contribution calendar is empty; previous cards preserved.')
    period = f"{days[0]['date']} to {days[-1]['date']}"
    repositories = user['repositories']
    stats = [
        ('Stars (owned public repos)', sum(repo['stargazerCount'] for repo in repositories)),
        ('Commits (past year)', contributions['totalCommitContributions']),
        ('Pull requests (past year)', contributions['totalPullRequestContributions']),
        ('Issues (past year)', contributions['totalIssueContributions']),
        ('Repos with commits (past year)', contributions['totalRepositoriesWithContributedCommits']),
    ]
    body = ''.join(text(25, 75+i*30, label, TEAL, 13) +
                   text(450, 75+i*30, f'{value:,}', TEAL, 15, 'end', '600')
                   for i, (label, value) in enumerate(stats))
    cards = {'stats': card(490, 255, "BUDDHIKA CHATHURA's GitHub Stats", body, stamp)}

    language_bytes, colors = Counter(), {}
    for repo in repositories:
        for edge in repo['languages']['edges']:
            language = edge['node']
            language_bytes[language['name']] += edge['size']
            colors[language['name']] = language['color'] or BLUE
    ranked = language_bytes.most_common()
    shown = ranked[:5]
    if len(ranked) > 5:
        shown.append(('Other', sum(size for _, size in ranked[5:])))
        colors['Other'] = MUTED
    total, x = sum(language_bytes.values()), 25.0
    body = text(25, 60, 'Owned public repositories · share of code bytes', MUTED, 12)
    if total:
        for index, (name, size) in enumerate(shown):
            width = 440 * size / total
            color = escape(colors[name], quote=True)
            body += f'<rect x="{x:.2f}" y="80" width="{width:.2f}" height="10" fill="{color}"/>'
            x += width
            column, row = index % 2, index // 2
            label_x, label_y = 25 + column*230, 125 + row*32
            body += f'<circle cx="{label_x+4}" cy="{label_y-5}" r="5" fill="{color}"/>'
            body += text(label_x+16, label_y, f'{name} {size / total:.1%}', TEAL, 12)
    else:
        body += text(25, 110, 'No language data in owned public repositories.', TEAL, 13)
    cards['languages'] = card(490, 255, 'Most Used Languages', body, stamp)

    current, longest = streak_lengths(days)
    body = ''
    for x_pos in (230, 470):
        body += f'<path d="M{x_pos} 60V193" stroke="#45475a"/>'
    body += '<circle cx="350" cy="103" r="43" fill="none" stroke="#70a5fd" stroke-width="5"/>'
    body += text(115, 115, f"{calendar['totalContributions']:,}", BLUE, 30, 'middle', '700')
    body += text(350, 115, current, PURPLE, 30, 'middle', '700')
    body += text(585, 115, longest, BLUE, 30, 'middle', '700')
    for x_pos, label in ((115, 'Contributions (past year)'), (350, 'Current streak'), (585, 'Longest (past year)')):
        body += text(x_pos, 171, label, PURPLE if x_pos == 350 else BLUE, 14, 'middle')
    body += text(350, 207, period + ' · Streaks measured in days', TEAL, 11, 'middle')
    cards['streak'] = card(700, 250, 'Contribution Streak', body, stamp)

    recent = days[-31:]
    maximum = max(4, max(day['contributionCount'] for day in recent))
    step = max(1, math.ceil(maximum / 4))
    maximum = step * 4
    left, top, chart_width, chart_height = 65, 80, 860, 210
    body = ''
    for tick in range(5):
        y = top + chart_height - tick * chart_height / 4
        body += f'<path d="M{left} {y}h{chart_width}" stroke="#35405c" stroke-dasharray="2 3"/>'
        body += text(left - 12, y+4, tick*step, BLUE, 11, 'end')
    points = []
    for index, day in enumerate(recent):
        x_pos = left + index * chart_width / max(1, len(recent)-1)
        y = top + chart_height - day['contributionCount'] / maximum * chart_height
        points.append(f'{x_pos:.2f},{y:.2f}')
        if index % 3 == 0 or index == len(recent)-1:
            body += text(x_pos, 313, day['date'][5:], BLUE, 10, 'middle')
        body += (f'<circle cx="{x_pos:.2f}" cy="{y:.2f}" r="3" fill="#a9b1d6">'
                 f'<title>{day["date"]}: {day["contributionCount"]} contributions</title></circle>')
    body += f'<polyline points="{" ".join(points)}" fill="none" stroke="{BLUE}" stroke-width="2.5"/>'
    body += text(65, 60, 'Daily contributions · last 31 calendar days', MUTED, 12)
    cards['activity'] = card(960, 355, "BUDDHIKA CHATHURA's Contribution Graph", body, stamp)
    return cards


def save_cards(cards):
    # Build every card before changing files. Replace each file atomically.
    import xml.etree.ElementTree as ET
    for value in cards.values():
        ET.fromstring(value)
    target = ROOT / 'assets'
    target.mkdir(exist_ok=True)
    for name, svg in cards.items():
        temporary = target / (name + '.svg.tmp')
        temporary.write_text(svg, encoding='utf-8')
        temporary.replace(target / (name + '.svg'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--placeholders', action='store_true')
    args = parser.parse_args()
    if args.placeholders:
        dimensions = {'stats': (490, 255), 'languages': (490, 255),
                      'streak': (700, 250), 'activity': (960, 355)}
        titles = {'stats': "BUDDHIKA CHATHURA's GitHub Stats", 'languages': 'Most Used Languages',
                  'streak': 'Contribution Streak', 'activity': "BUDDHIKA CHATHURA's Contribution Graph"}
        cards = {name: card(width, height, titles[name],
                            text(24, 100, 'Waiting for the first GitHub Actions run.', TEAL, 14) +
                            text(24, 130, 'Upload the workflow, then select Run workflow.', MUTED, 12),
                            'No activity data has been fetched yet.')
                 for name, (width, height) in dimensions.items()}
    else:
        token = os.environ.get('GH_TOKEN')
        if not token:
            raise SystemExit('GH_TOKEN is required. In Actions, use the automatic github.token.')
        cards = render(fetch_data(os.environ.get('PROFILE_USER', 'Bbuddhika'), token))
    save_cards(cards)
    print('Generated four profile cards.')


if __name__ == '__main__':
    main()
