"""
X Account Bot — main entry point.

BASIC USAGE:
    python main.py                        # Full run: scrape → analyze → SOP
    python main.py --week 3               # Force week number

SKIP FLAGS:
    python main.py --analyze-only         # Skip scraping, reuse saved tweets
    python main.py --sop-only             # Skip scrape + analyze, regenerate SOP

MEMORY COMMANDS (run after posting your tweets):
    python main.py --memory               # Print full memory report
    python main.py --log-growth 142       # Log your current follower count
    python main.py --log-tweet            # Interactive: log a tweet's performance

SETUP:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=your_key_here
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from glob import glob

from scraper import collect_tweets
from analyzer import analyze_tweets
from sop_generator import generate_weekly_sop
from memory import log_account_growth, log_your_tweet, print_memory_report
from config import OUTPUT_DIR

os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(OUTPUT_DIR, "bot.log")),
    ],
)
log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def detect_week_number() -> int:
    existing = glob(os.path.join(OUTPUT_DIR, "week_*_sop_*.md"))
    if not existing:
        return 1
    weeks = []
    for f in existing:
        try:
            week = int(os.path.basename(f).split("_")[1])
            weeks.append(week)
        except (IndexError, ValueError):
            continue
    return (max(weeks) + 1) if weeks else 1


def load_last_tweets() -> list[dict]:
    files = sorted(glob(os.path.join(OUTPUT_DIR, "week_*_tweets_raw_*.json")))
    if not files:
        return []
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


def load_last_analysis() -> dict:
    files = sorted(glob(os.path.join(OUTPUT_DIR, "week_*_analysis_*.json")))
    if not files:
        log.error("No saved analysis files found. Run the full pipeline first.")
        sys.exit(1)
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


def save_raw_tweets(tweets: list[dict], week: int) -> str:
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(OUTPUT_DIR, f"week_{week:02d}_tweets_raw_{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tweets, f, indent=2, ensure_ascii=False)
    return path


def check_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\n  ERROR: ANTHROPIC_API_KEY not set.")
        print("  Run: export ANTHROPIC_API_KEY=your_key_here\n")
        sys.exit(1)


def print_banner(week: int) -> None:
    print("\n" + "═" * 60)
    print("  X ACCOUNT BOT  ·  Claude AI + Digital Products Niche")
    print(f"  Week {week}  ·  {datetime.now().strftime('%B %d, %Y')}")
    print("═" * 60 + "\n")


def print_step(n: int, total: int, label: str) -> None:
    print(f"  [{n}/{total}] {label}...")


def print_done(week: int, sop_path: str, batch_path: str) -> None:
    print("\n" + "═" * 60)
    print(f"  ✓  Week {week} content ready")
    print("═" * 60)
    print(f"  SOP file:    {sop_path}")
    print(f"  Tweet batch: {batch_path}")
    print(f"  Memory:      {os.path.join(OUTPUT_DIR, 'memory.json')}")
    print()
    print("  NEXT STEPS:")
    print("  1. Open the tweet batch file")
    print("  2. Load into Buffer / Hypefury")
    print("  3. Schedule Mon–Fri at 8–10 AM your timezone")
    print("  4. 15 min/day: reply to niche posts BEFORE yours go live")
    print()
    print("  AFTER YOUR TWEETS ARE POSTED (24-48h later):")
    print("  python main.py --log-tweet     ← record impressions + likes")
    print("  python main.py --log-growth N  ← record follower count")
    print("═" * 60 + "\n")


# ── Memory commands ───────────────────────────────────────────────────────────

def cmd_log_tweet(week: int) -> None:
    """Interactive prompt to log a posted tweet's performance."""
    print("\n  LOG TWEET PERFORMANCE")
    print("  (Enter data from X Analytics, 24-48h after posting)\n")
    text = input("  Tweet text (first 100 chars): ").strip()
    fmt = input("  Format used (e.g. build-in-public, numbered list, contrarian): ").strip()
    try:
        impressions = int(input("  Impressions: ").strip() or "0")
        likes = int(input("  Likes: ").strip() or "0")
        retweets = int(input("  Retweets: ").strip() or "0")
        clicks = int(input("  Link clicks: ").strip() or "0")
    except ValueError:
        print("  Invalid number — logging with 0s.")
        impressions = likes = retweets = clicks = 0

    log_your_tweet(
        text=text,
        format_used=fmt,
        week=week,
        impressions=impressions,
        likes=likes,
        retweets=retweets,
        clicks=clicks,
    )
    er = round((likes + retweets) / impressions * 100, 2) if impressions else 0
    print(f"\n  ✓ Logged — {impressions:,} impressions | {er}% engagement rate\n")


# ── Main pipeline ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="X Account Content Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--week", type=int, default=None)
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--sop-only", action="store_true")
    parser.add_argument("--memory", action="store_true", help="Print memory report and exit")
    parser.add_argument("--log-growth", type=int, metavar="FOLLOWERS",
                        help="Log current follower count (e.g. --log-growth 250)")
    parser.add_argument("--log-tweet", action="store_true",
                        help="Interactively log a posted tweet's performance")
    args = parser.parse_args()

    week = args.week or detect_week_number()

    # ── Memory-only commands (no API key needed) ──
    if args.memory:
        print_memory_report()
        return

    if args.log_growth is not None:
        log_account_growth(week=week, followers=args.log_growth)
        print(f"\n  ✓ Logged {args.log_growth:,} followers for Week {week}\n")
        return

    if args.log_tweet:
        cmd_log_tweet(week)
        return

    # ── Pipeline ──────────────────────────────────
    check_api_key()
    print_banner(week)

    total_steps = 3

    # Step 1 — Collect
    if args.sop_only:
        analysis = load_last_analysis()
    else:
        if args.analyze_only:
            print_step(1, total_steps, "Loading saved tweets (--analyze-only)")
            tweets = load_last_tweets()
            if not tweets:
                print("  No saved tweets found — running fresh scrape instead.")
                tweets = collect_tweets()
        else:
            print_step(1, total_steps, "Collecting tweets from X niche")
            tweets = collect_tweets()
            if not tweets:
                log.error("No tweets collected. Check network / Nitter availability.")
                sys.exit(1)
            path = save_raw_tweets(tweets, week)
            print(f"      ✓ {len(tweets)} tweets collected → {path}\n")

    # Step 2 — Analyze
    if not args.sop_only:
        print_step(2, total_steps, "Analyzing patterns with Claude (streaming)\n")
        analysis = analyze_tweets(tweets, week=week)
        print(f"\n      ✓ {len(analysis.get('top_tweets', []))} tweets analyzed\n")

    # Step 3 — Generate SOP
    print_step(3, total_steps, "Generating SOP + tweet batch (streaming)\n")
    sop_path, batch_path = generate_weekly_sop(analysis, week)

    print_done(week, sop_path, batch_path)


if __name__ == "__main__":
    main()
