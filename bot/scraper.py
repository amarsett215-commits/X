"""
Tweet scraper — pulls viral tweets from niche accounts and keywords.

Strategy (in order of reliability):
1. Nitter instances (no login, no JS required)
2. DuckDuckGo search for X posts (fallback)
3. Manual seed list (always available)

Returns a list of Tweet dicts:
{
    "text": str,
    "author": str,
    "likes": int,
    "retweets": int,
    "url": str,
    "source": str,  # "nitter" | "search" | "seed"
}
"""

import time
import random
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

from config import (
    NITTER_INSTANCES,
    NICHE_ACCOUNTS,
    NICHE_KEYWORDS,
    MIN_LIKES,
    MIN_RETWEETS,
    TWEETS_TO_COLLECT,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class Tweet:
    text: str
    author: str
    likes: int = 0
    retweets: int = 0
    url: str = ""
    source: str = "unknown"

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "author": self.author,
            "likes": self.likes,
            "retweets": self.retweets,
            "url": self.url,
            "source": self.source,
        }

    @property
    def engagement_score(self) -> int:
        return self.likes + (self.retweets * 3)


def _parse_count(raw: str) -> int:
    """Parse '1.2K' or '45' into an integer."""
    raw = raw.strip().replace(",", "")
    if not raw:
        return 0
    try:
        if raw.endswith("K"):
            return int(float(raw[:-1]) * 1000)
        if raw.endswith("M"):
            return int(float(raw[:-1]) * 1_000_000)
        return int(raw)
    except ValueError:
        return 0


def _get_working_nitter() -> Optional[str]:
    """Return the first Nitter instance that responds."""
    for instance in NITTER_INSTANCES:
        try:
            r = requests.get(instance, headers=HEADERS, timeout=6)
            if r.status_code == 200:
                log.info(f"Using Nitter instance: {instance}")
                return instance
        except requests.RequestException:
            continue
    log.warning("No Nitter instance available.")
    return None


def _scrape_nitter_profile(base_url: str, username: str) -> list[Tweet]:
    """Scrape recent tweets from a single profile on Nitter."""
    tweets = []
    url = f"{base_url}/{username}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return tweets
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".timeline-item"):
            # Skip retweets and pinned tweets
            if item.select_one(".retweet-header") or item.select_one(".pinned"):
                continue
            content = item.select_one(".tweet-content")
            if not content:
                continue
            text = content.get_text(separator=" ").strip()
            # Engagement stats
            stats = item.select(".tweet-stat")
            likes = retweets = 0
            for stat in stats:
                icon = stat.select_one(".icon-heart, .icon-retweet")
                count_el = stat.select_one(".tweet-stat-count")
                if not icon or not count_el:
                    continue
                count = _parse_count(count_el.get_text())
                if "heart" in (icon.get("class") or []):
                    likes = count
                elif "retweet" in (icon.get("class") or []):
                    retweets = count
            # Tweet URL
            link = item.select_one(".tweet-link")
            tweet_url = f"https://x.com{link['href']}" if link else ""
            tweets.append(
                Tweet(
                    text=text,
                    author=username,
                    likes=likes,
                    retweets=retweets,
                    url=tweet_url,
                    source="nitter",
                )
            )
    except Exception as e:
        log.warning(f"Error scraping {username}: {e}")
    return tweets


def _scrape_nitter_search(base_url: str, query: str) -> list[Tweet]:
    """Search Nitter for a keyword and return matching tweets."""
    tweets = []
    encoded = requests.utils.quote(query)
    url = f"{base_url}/search?q={encoded}&f=tweets"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return tweets
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".timeline-item"):
            if item.select_one(".retweet-header"):
                continue
            content = item.select_one(".tweet-content")
            if not content:
                continue
            text = content.get_text(separator=" ").strip()
            author_el = item.select_one(".username")
            author = author_el.get_text().strip().lstrip("@") if author_el else "unknown"
            stats = item.select(".tweet-stat")
            likes = retweets = 0
            for stat in stats:
                icon = stat.select_one(".icon-heart, .icon-retweet")
                count_el = stat.select_one(".tweet-stat-count")
                if not icon or not count_el:
                    continue
                count = _parse_count(count_el.get_text())
                if "heart" in (icon.get("class") or []):
                    likes = count
                elif "retweet" in (icon.get("class") or []):
                    retweets = count
            link = item.select_one(".tweet-link")
            tweet_url = f"https://x.com{link['href']}" if link else ""
            tweets.append(
                Tweet(
                    text=text,
                    author=author,
                    likes=likes,
                    retweets=retweets,
                    url=tweet_url,
                    source="nitter_search",
                )
            )
    except Exception as e:
        log.warning(f"Search error for '{query}': {e}")
    return tweets


def _duckduckgo_x_search(query: str) -> list[Tweet]:
    """
    Fallback: use DuckDuckGo to find X posts for a keyword.
    Parses search snippets as approximate tweet content.
    """
    tweets = []
    search_url = "https://html.duckduckgo.com/html/"
    params = {"q": f"site:x.com {query}", "kl": "us-en"}
    try:
        r = requests.post(search_url, data=params, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        for result in soup.select(".result"):
            title_el = result.select_one(".result__title a")
            snippet_el = result.select_one(".result__snippet")
            if not title_el or not snippet_el:
                continue
            href = title_el.get("href", "")
            if "x.com" not in href and "twitter.com" not in href:
                continue
            # Extract username from URL
            parts = href.replace("https://x.com/", "").replace("https://twitter.com/", "").split("/")
            author = parts[0] if parts else "unknown"
            text = snippet_el.get_text().strip()
            if len(text) < 30:
                continue
            tweets.append(
                Tweet(
                    text=text,
                    author=author,
                    likes=0,  # Can't get engagement from search snippets
                    retweets=0,
                    url=href,
                    source="duckduckgo",
                )
            )
            if len(tweets) >= 5:
                break
    except Exception as e:
        log.warning(f"DuckDuckGo search failed: {e}")
    return tweets


def _seed_tweets() -> list[Tweet]:
    """
    Hardcoded high-quality seed tweets from the research phase.
    Always available as a baseline — ensures the bot produces output
    even when all scraping methods fail.
    """
    seeds = [
        Tweet(
            text=(
                "I used Claude Code to build my client's entire product from scratch. "
                "727 commits across 36 active days. Claude Code handled 95% of the coding autonomously. "
                "The $50K agency quote you got in 2024 is not the number for 2026. "
                "That gap is your window."
            ),
            author="sukh_saroy",
            likes=1200,
            retweets=340,
            url="https://x.com/sukh_saroy/status/2036501664765714825",
            source="seed",
        ),
        Tweet(
            text=(
                "How to make $1M in 2026 using Claude Memory (step by step business plan): "
                "Claude launched memory imports — you can migrate anyone from ChatGPT to Claude in 60 seconds. "
                "The business: Claude Migration as a Service. "
                "$2,500–$10,000 per workshop. $5,000/month documentation retainer."
            ),
            author="ideabrowser",
            likes=980,
            retweets=290,
            url="https://x.com/ideabrowser/status/2028111088449896826",
            source="seed",
        ),
        Tweet(
            text=(
                "I was using Claude to help me set up some formulas for an Excel sheet. "
                "Claude suggested we build a web app instead. "
                "I then spent 3 hours standing up a full web app — Slack alerts, QuickBooks integration, email automation. "
                "I am not technical. It walked me through setting up a db."
            ),
            author="theisaacmed",
            likes=2100,
            retweets=510,
            url="https://x.com/theisaacmed/status/2022067410518573519",
            source="seed",
        ),
        Tweet(
            text=(
                "using claude you can become money printing machine. "
                "get claude subscription → go on maps, linkedin, google business "
                "→ search logistics, e-commerce, ed-tech companies "
                "→ tell them you can do better and faster "
                "→ automate their minor tasks"
            ),
            author="kmeanskaran",
            likes=870,
            retweets=220,
            url="https://x.com/kmeanskaran/status/2036297493986811946",
            source="seed",
        ),
        Tweet(
            text=(
                "ok some context - i'm non technical, absolutely hate coding, "
                "and am playing around with Claude. "
                "i can say that this is the fucking future. shit is absolutely crazy. "
                "it's true when they say the only limit is your imagination. "
                "this erased 60-80% of my work."
            ),
            author="0xkyle__",
            likes=3400,
            retweets=890,
            url="https://x.com/0xkyle__/status/2011251695993700482",
            source="seed",
        ),
        Tweet(
            text=(
                "Twitter is the only business where the lazy win. "
                "I see people writing posts inconsistently and get 100K+ views per post (when they feel like it) "
                "And make $50K+ per month selling digital products off of those posts. "
                "While those who try hard and make 20+ posts per day barely get traction."
            ),
            author="X_FINALBOSS",
            likes=1500,
            retweets=400,
            url="https://x.com/X_FINALBOSS/status/1994682829716812228",
            source="seed",
        ),
        Tweet(
            text=(
                "I did $114K in ONE day selling digital products with AI. "
                "Here's exactly how in 10 steps: "
                "1. AI generated 17M+ views on X in 30 days "
                "2. Gave free ebooks to warm up 2K+ leads "
                "3. Ran VSL + 5 day message sequence leading up to launch"
            ),
            author="X_FINALBOSS",
            likes=2200,
            retweets=600,
            url="https://x.com/X_FINALBOSS/status/2027612638914441331",
            source="seed",
        ),
    ]
    return seeds


def collect_tweets() -> list[dict]:
    """
    Main collection function. Tries Nitter → DuckDuckGo → seed data.
    Returns a deduplicated, engagement-sorted list of tweet dicts.
    """
    all_tweets: list[Tweet] = []

    # --- Method 1: Nitter ---
    nitter_base = _get_working_nitter()
    if nitter_base:
        # Profile scraping
        for account in NICHE_ACCOUNTS[:5]:  # Cap at 5 to stay polite
            log.info(f"Scraping profile: @{account}")
            profile_tweets = _scrape_nitter_profile(nitter_base, account)
            all_tweets.extend(profile_tweets)
            time.sleep(random.uniform(1.5, 3.0))  # polite delay

        # Keyword search
        for keyword in NICHE_KEYWORDS[:3]:
            log.info(f"Searching: '{keyword}'")
            search_tweets = _scrape_nitter_search(nitter_base, keyword)
            all_tweets.extend(search_tweets)
            time.sleep(random.uniform(1.5, 3.0))
    else:
        log.info("Nitter unavailable — falling back to DuckDuckGo search")
        for keyword in NICHE_KEYWORDS[:4]:
            log.info(f"DuckDuckGo search: '{keyword}'")
            ddg_tweets = _duckduckgo_x_search(keyword)
            all_tweets.extend(ddg_tweets)
            time.sleep(random.uniform(2.0, 4.0))

    # --- Method 2: Always include seed data ---
    log.info("Adding seed tweets as baseline")
    all_tweets.extend(_seed_tweets())

    # --- Deduplicate by text similarity (simple prefix match) ---
    seen: set[str] = set()
    unique: list[Tweet] = []
    for t in all_tweets:
        key = t.text[:80].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(t)

    # --- Filter + sort by engagement ---
    qualified = [
        t for t in unique
        if t.likes >= MIN_LIKES or t.retweets >= MIN_RETWEETS or t.source == "seed"
    ]
    qualified.sort(key=lambda t: t.engagement_score, reverse=True)

    top = qualified[:TWEETS_TO_COLLECT]
    log.info(f"Collected {len(top)} tweets for analysis")
    return [t.to_dict() for t in top]
