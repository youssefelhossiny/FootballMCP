"""
Team News Scraper
Fetches fast, free third-party injury/lineup news — faster than FPL's own
bootstrap-static `news`/`status` fields, which lag behind real announcements
(FPL's editorial team updates them manually, sometimes a day+ behind).

Two sources, both plain server-rendered HTML (no Cloudflare/JS-challenge,
no Selenium needed — same aiohttp+BeautifulSoup pattern as
bot_decision_maker.fetch_livefpl_predictions):

- Knocks and Bans (knocksandbans.com): per-player injury/suspension status,
  type, expected return date, with a per-entry last-updated timestamp.
- Fantasy Football Scout team news (fantasyfootballscout.co.uk/team-news):
  per-team predicted starting XI + Out/Doubts/Banned lists, with a
  per-team last-updated timestamp. This is DIFFERENT data than injury
  status — it's "who's actually expected to start," including rotation
  risk for players who are fully fit but might be benched.
"""

import re
from typing import Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup

KNOCKS_AND_BANS_URL = "https://www.knocksandbans.com/"
FFSCOUT_TEAM_NEWS_URL = "https://www.fantasyfootballscout.co.uk/team-news/"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

def _normalize_status(status_text: str) -> str:
    """
    Knocks and Bans renders status as either a word ('OUT', 'SUSPENDED') or
    a bare percentage ('75%') with color conveying doubt vs. definite-out —
    but the text itself is unambiguous, so just normalize on that.
    """
    text = status_text.strip().lower()
    if not text:
        return "unknown"
    if text.endswith("%"):
        return f"doubtful ({text} chance)"
    return text


async def fetch_knocks_and_bans(session: aiohttp.ClientSession) -> List[Dict]:
    """
    Fetch per-player injury/suspension status from Knocks and Bans.

    Returns a list of dicts: {name, injury_type, status, expected_return,
    last_updated}. `status` is 'out'/'doubtful'/'unknown' based on the
    status text color (red=out, orange=doubtful per the site's own styling).
    """
    async with session.get(KNOCKS_AND_BANS_URL, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        if resp.status != 200:
            return []
        html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for row in soup.find_all("a", href=re.compile(r"-injuries-suspensions-\d+$")):
        name_tag = row.find("strong")
        if not name_tag:
            continue
        name = name_tag.get_text(strip=True)

        injury_type_tag = row.find("span", class_=None)
        # injury type is the free-text span right after the name/status icon
        spans = row.find_all("span")
        injury_type = ""
        for s in spans:
            text = s.get_text(strip=True)
            if text and text not in ("-",) and "font-semibold" not in (s.get("class") or []):
                if s.get("class") == ["text-sm"]:
                    injury_type = text
                    break

        status_span = row.find("span", class_="font-semibold")
        status_text = status_span.get_text(strip=True) if status_span else ""
        status = _normalize_status(status_text)

        return_span = row.find("img", alt="Expected return")
        expected_return = None
        if return_span:
            container = return_span.find_parent("div")
            spans_in_container = container.find_all("span") if container else []
            if spans_in_container:
                expected_return = spans_in_container[-1].get_text(strip=True)

        last_updated_tag = row.find(attrs={"x-data": re.compile(r"relativeTime")})
        last_updated = None
        if last_updated_tag and last_updated_tag.get("x-data"):
            m = re.search(r"timestamp:\s*'([^']+)'", last_updated_tag["x-data"])
            if m:
                last_updated = m.group(1)

        entries.append({
            "name": name,
            "injury_type": injury_type,
            "status": status,
            "expected_return": expected_return,
            "last_updated": last_updated,
        })

    return entries


async def fetch_ffscout_team_news(session: aiohttp.ClientSession) -> List[Dict]:
    """
    Fetch per-team predicted starting XI + Out/Doubts/Banned lists from
    Fantasy Football Scout's team news page.

    Returns a list of dicts, one per PL team: {team, predicted_lineup,
    out, doubts, banned, last_updated}. `predicted_lineup` is a flat list
    of player names in goalkeeper-to-forward row order (formation rows,
    not itself the full squad).
    """
    async with session.get(FFSCOUT_TEAM_NEWS_URL, headers=_HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
        if resp.status != 200:
            return []
        html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")
    teams = []
    for item in soup.find_all("li", class_="team-news-item"):
        h2 = item.find("h2")
        team_name = h2.get_text(strip=True) if h2 else None
        if not team_name:
            continue

        predicted_lineup = []
        for row in item.find_all("ul", class_=lambda c: c and c.startswith("row-")):
            for li in row.find_all("li"):
                name = li.get("title") or li.get_text(strip=True)
                if name:
                    predicted_lineup.append(name)

        out, doubts, banned = [], [], []
        last_updated = None
        story_parts = item.find("ul", class_="story-parts")
        if story_parts:
            for li in story_parts.find_all("li"):
                strong = li.find("strong")
                if strong:
                    label = strong.get_text(strip=True).rstrip(":").lower()
                    players_ul = li.find("ul", class_="players")
                    names = []
                    if players_ul:
                        for p in players_ul.find_all("li"):
                            percent_tag = p.find("span", class_="doubt-percent")
                            percent = percent_tag.get_text(strip=True) if percent_tag else None
                            if percent_tag:
                                percent_tag.extract()
                            player_name = p.get_text(strip=True)
                            names.append(f"{player_name} ({percent})" if percent else player_name)
                    if label == "out":
                        out = names
                    elif label == "doubts":
                        doubts = names
                    elif label == "banned":
                        banned = names
                else:
                    em = li.find("em")
                    if em and "Last Updated" in em.get_text():
                        last_updated = em.get_text(strip=True).replace("Last Updated", "").strip()

        teams.append({
            "team": team_name,
            "predicted_lineup": predicted_lineup,
            "out": out,
            "doubts": doubts,
            "banned": banned,
            "last_updated": last_updated,
        })

    return teams
