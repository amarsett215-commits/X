"""
X Account Bot — main entry point.

Usage:
    python main.py                   # Run full pipeline (scrape → analyze → generate SOP)
    python main.py --week 3          # Specify week number manually
    python main.py --analyze-only    # Skip scraping, use last saved tweets
    python main.py --sop-only        # Skip scrape + analyze, regenerate SOP from last analysis

Requirements:
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
from config import OUTPUT_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(OUTPUT_DIR, "bot.log") if os.path.exists(OUTPUT_DIR) else "bot.log"),
    ],
)
log = logging.getLogger(__name__)


def detect_week_number() -> int:
    """Auto-detect week number from existing output files."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    existing = glob(os.path.join(OUTPUT_DIR, "week_*_sop_*.md"))
    if not existing:
        return 1
    # Extract week numbers and return next
    weeks = []
    for f in existing:
        try:
            name = os.path.basename(f)
            week = int(name.split("_")[1])
            weeks.append(week)
        except (IndexError, ValueError):
            continue
    return (max(weeks) + 1) if weeks else 1


def load_last_tweets() -> list[dict]:
    """Load the most recently saved tweet collection."""
    files = sorted(glob(os.path.join(OUTPUT_DIR, "week_*_tweets_raw_*.json")))
    if not files:
        log.warning("No saved tweet files found — running full scrape.")
        return []
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


def load_last_analysis() -> dict:
    """Load the most recently saved analysis."""
    files = sorted(glob(os.path.join(OUTPUT_DIR, "week_*_analysis_*.json")))
    if not files:
        log.error("No saved analysis files found. Run full pipeline first.")
        sys.exit(1)
    with open(files[-1], encoding="utf-8") as f:
        return json.load(f)


def save_raw_tweets(tweets: list[dict], week: int) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(OUTPUT_DIR, f"week_{week:02d}_tweets_raw_{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tweets, f, indent=2, ensure_ascii=False)
    log.info(f"Raw tweets saved: {path}")
    return path


def print_banner():
    print("\n" + "=" * 60)
    print("  X ACCOUNT BOT — Claude AI + Digital Products Niche")
    print("  Scrape → Analyze → Generate SOP + Tweet Batch")
    print("=" * 60 + "\n")


def main():
    print_banner()

    parser = argparse.ArgumentParser(description="X Account Content Bot")
    parser.add_argument("--week", type=int, default=None, help="Week number (auto-detected if omitted)")
    parser.add_argument("--analyze-only", action="store_true", help="Skip scraping, use saved tweets")
    parser.add_argument("--sop-only", action="store_true", help="Skip scraping + analysis, regenerate SOP")
    args = parser.parse_args()

    week = args.week or detect_week_number()
    log.info(f"Running Week {week} pipeline")

    # ── Step 1: Collect tweets ──────────────────────────────────────
    if args.sop_only:
        log.info("SOP-only mode — loading last analysis")
        analysis = load_last_analysis()
    elif args.analyze_only:
        log.info("Analyze-only mode — loading saved tweets")
        tweets = load_last_tweets() or collect_tweets()
    else:
        print("\n[1/3] Collecting tweets from X niche...")
        tweets = collect_tweets()
        if not tweets:
            log.error("No tweets collected. Check network or Nitter availability.")
            sys.exit(1)
        save_raw_tweets(tweets, week)
        print(f"      ✓ Collected {len(tweets)} tweets\n")

    # ── Step 2: Analyze ─────────────────────────────────────────────
    if not args.sop_only:
        print("[2/3] Analyzing tweet patterns with Claude...\n")
        analysis = analyze_tweets(tweets)
        print(f"\n      ✓ Analysis complete — {len(analysis.get('top_tweets', []))} tweets studied\n")

    # ── Step 3: Generate SOP + Tweet Batch ─────────────────────────
    print("[3/3] Generating weekly SOP and tweet batch...\n")
    sop_path, batch_path = generate_weekly_sop(analysis, week)

    # ── Summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  DONE — Week", week, "content ready")
    print("=" * 60)
    print(f"  SOP:         {sop_path}")
    print(f"  Tweet batch: {batch_path}")
    print(f"  Log:         {os.path.join(OUTPUT_DIR, 'bot.log')}")
    print()
    print("  NEXT STEPS:")
    print("  1. Open the tweet batch file")
    print("  2. Load into Buffer / Hypefury")
    print("  3. Schedule Mon-Fri at 8-10 AM")
    print("  4. Spend 15 min/day replying to niche posts")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
