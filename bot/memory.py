"""
Bot memory — persistent intelligence layer.

Tracks everything across weeks so Claude gets smarter over time:
- Which formats/hooks/emotions performed best historically
- Week-over-week trend shifts (rising vs fading angles)
- Your own tweet performance (manually logged)
- Account growth tracking
- Evergreen frameworks that keep working

All stored in output/memory.json — a single growing file.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any

from config import OUTPUT_DIR

log = logging.getLogger(__name__)
MEMORY_FILE = os.path.join(OUTPUT_DIR, "memory.json")

EMPTY_MEMORY = {
    "meta": {
        "created": "",
        "last_updated": "",
        "total_weeks_run": 0,
        "niche": "Claude AI + digital products + make money online",
    },
    "account_growth": [],          # [{week, date, followers, following}]
    "weekly_snapshots": [],        # Summary of each week's analysis
    "format_leaderboard": {},      # format_name → {appearances, total_engagement, avg_engagement}
    "hook_leaderboard": {},        # hook_type → {appearances, avg_engagement}
    "emotion_leaderboard": {},     # emotion → {appearances}
    "evergreen_frameworks": [],    # Formats that appeared 3+ weeks in a row
    "fading_formats": [],          # Formats that dropped off
    "your_tweet_log": [],          # Your own posted tweets + performance
    "best_tweets_all_time": [],    # Top 10 tweets seen across all weeks
    "running_opportunities": [],   # Opportunity angles identified each week
}


def _load() -> dict:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(MEMORY_FILE):
        mem = dict(EMPTY_MEMORY)
        mem["meta"]["created"] = datetime.now().isoformat()
        _save(mem)
        return mem
    with open(MEMORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(memory: dict) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    memory["meta"]["last_updated"] = datetime.now().isoformat()
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)


# ── Public API ────────────────────────────────────────────────────────────────

def get_memory_context(week: int) -> str:
    """
    Returns a formatted memory block to inject into Claude prompts.
    Gives Claude historical context so analysis improves each week.
    """
    mem = _load()
    if not mem["weekly_snapshots"]:
        return "This is Week 1 — no historical data yet. Establish baselines."

    lines = [f"HISTORICAL INTELLIGENCE (Weeks 1–{week - 1}):\n"]

    # Format leaderboard
    if mem["format_leaderboard"]:
        sorted_formats = sorted(
            mem["format_leaderboard"].items(),
            key=lambda x: x[1].get("avg_engagement", 0),
            reverse=True,
        )[:5]
        lines.append("Top performing formats historically:")
        for fmt, data in sorted_formats:
            lines.append(
                f"  • {fmt}: appeared {data['appearances']}x, "
                f"avg engagement {data.get('avg_engagement', 0):,}"
            )

    # Evergreen frameworks
    if mem["evergreen_frameworks"]:
        lines.append(f"\nEvergreen (3+ consecutive weeks): {', '.join(mem['evergreen_frameworks'])}")

    # Fading formats
    if mem["fading_formats"]:
        lines.append(f"Fading (avoid over-using): {', '.join(mem['fading_formats'])}")

    # Last week's opportunity vs this week
    if mem["running_opportunities"]:
        last = mem["running_opportunities"][-1]
        lines.append(f"\nLast week's opportunity angle: {last.get('opportunity', 'n/a')}")

    # Account growth
    if mem["account_growth"]:
        latest = mem["account_growth"][-1]
        lines.append(f"\nAccount: {latest.get('followers', 0)} followers as of Week {latest.get('week', '?')}")

    # Your best performing tweet
    if mem["your_tweet_log"]:
        best = max(mem["your_tweet_log"], key=lambda t: t.get("impressions", 0))
        if best.get("impressions", 0) > 0:
            lines.append(
                f"\nYour best tweet so far: {best['impressions']:,} impressions\n"
                f"  Format: {best.get('format', 'unknown')}\n"
                f"  Text: {best['text'][:100]}..."
            )

    lines.append(
        "\nUse this history to: avoid repeating oversaturated angles, "
        "double down on what's working, and identify new gaps."
    )
    return "\n".join(lines)


def save_week_snapshot(week: int, analysis: dict) -> None:
    """Save this week's analysis results to memory after a run."""
    mem = _load()
    patterns = analysis.get("patterns", {})
    top_tweets = analysis.get("top_tweets", [])

    # Weekly snapshot
    snapshot = {
        "week": week,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "dominant_formats": patterns.get("dominant_formats", []),
        "dominant_emotions": patterns.get("dominant_emotions", []),
        "dominant_hooks": patterns.get("dominant_hooks", []),
        "opportunity": analysis.get("this_week_opportunity", ""),
        "tweet_count_analyzed": len(top_tweets),
    }
    # Remove duplicate weeks
    mem["weekly_snapshots"] = [s for s in mem["weekly_snapshots"] if s["week"] != week]
    mem["weekly_snapshots"].append(snapshot)

    # Update format leaderboard
    for fmt in patterns.get("dominant_formats", []):
        if fmt not in mem["format_leaderboard"]:
            mem["format_leaderboard"][fmt] = {"appearances": 0, "total_engagement": 0, "avg_engagement": 0}
        mem["format_leaderboard"][fmt]["appearances"] += 1

    # Update hook leaderboard
    for hook in patterns.get("dominant_hooks", []):
        if hook not in mem["hook_leaderboard"]:
            mem["hook_leaderboard"][hook] = {"appearances": 0}
        mem["hook_leaderboard"][hook]["appearances"] += 1

    # Update emotion leaderboard
    for emotion in patterns.get("dominant_emotions", []):
        if emotion not in mem["emotion_leaderboard"]:
            mem["emotion_leaderboard"][emotion] = {"appearances": 0}
        mem["emotion_leaderboard"][emotion]["appearances"] += 1

    # Track opportunity angles
    if analysis.get("this_week_opportunity"):
        mem["running_opportunities"].append({
            "week": week,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "opportunity": analysis["this_week_opportunity"],
        })

    # Best tweets all-time (keep top 10 by engagement)
    for t in top_tweets[:3]:
        engagement = t.get("engagement", {})
        score = engagement.get("likes", 0) + engagement.get("retweets", 0) * 3
        mem["best_tweets_all_time"].append({
            "week": week,
            "author": t.get("author", ""),
            "text": t.get("text_excerpt", ""),
            "url": t.get("url", ""),
            "engagement_score": score,
            "format": t.get("format", ""),
            "emotion": t.get("emotion_triggered", ""),
        })
    mem["best_tweets_all_time"].sort(key=lambda x: x["engagement_score"], reverse=True)
    mem["best_tweets_all_time"] = mem["best_tweets_all_time"][:10]

    # Detect evergreen formats (appeared in last 3+ snapshots)
    if len(mem["weekly_snapshots"]) >= 3:
        recent_formats = [
            set(s.get("dominant_formats", []))
            for s in mem["weekly_snapshots"][-3:]
        ]
        evergreen = set.intersection(*recent_formats) if recent_formats else set()
        mem["evergreen_frameworks"] = list(evergreen)

    # Detect fading formats (appeared 3+ weeks ago, not in last 2)
    if len(mem["weekly_snapshots"]) >= 4:
        old_formats = set()
        for s in mem["weekly_snapshots"][:-2]:
            old_formats.update(s.get("dominant_formats", []))
        recent_formats_flat = set()
        for s in mem["weekly_snapshots"][-2:]:
            recent_formats_flat.update(s.get("dominant_formats", []))
        mem["fading_formats"] = list(old_formats - recent_formats_flat)

    mem["meta"]["total_weeks_run"] = len(mem["weekly_snapshots"])
    _save(mem)
    log.info(f"Memory updated — Week {week} snapshot saved.")


def log_your_tweet(
    text: str,
    format_used: str,
    week: int,
    impressions: int = 0,
    likes: int = 0,
    retweets: int = 0,
    clicks: int = 0,
    posted_date: str = "",
) -> None:
    """
    Log one of YOUR posted tweets and its performance.
    Run this manually after you have engagement data (24-48h post).

    Example:
        python -c "from memory import log_your_tweet; log_your_tweet(
            text='Day 1. I have $0 in digital product sales...',
            format_used='build-in-public',
            week=1, impressions=4200, likes=87, retweets=23
        )"
    """
    mem = _load()
    entry = {
        "week": week,
        "posted_date": posted_date or datetime.now().strftime("%Y-%m-%d"),
        "text": text[:200],
        "format": format_used,
        "impressions": impressions,
        "likes": likes,
        "retweets": retweets,
        "clicks": clicks,
        "engagement_rate": round((likes + retweets) / impressions * 100, 2) if impressions else 0,
    }
    mem["your_tweet_log"].append(entry)

    # Update format leaderboard with your real engagement data
    if format_used in mem["format_leaderboard"] and impressions > 0:
        fl = mem["format_leaderboard"][format_used]
        fl["total_engagement"] = fl.get("total_engagement", 0) + impressions
        fl["avg_engagement"] = fl["total_engagement"] // fl["appearances"]

    _save(mem)
    log.info(f"Tweet logged — {impressions:,} impressions, {likes} likes.")


def log_account_growth(week: int, followers: int, following: int = 0) -> None:
    """
    Log your current follower count.

    Example:
        python -c "from memory import log_account_growth; log_account_growth(week=1, followers=142)"
    """
    mem = _load()
    # Remove duplicate week entries
    mem["account_growth"] = [g for g in mem["account_growth"] if g["week"] != week]
    mem["account_growth"].append({
        "week": week,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "followers": followers,
        "following": following,
    })
    _save(mem)
    log.info(f"Growth logged — Week {week}: {followers} followers.")


def print_memory_report() -> None:
    """Print a human-readable summary of everything the bot has learned."""
    mem = _load()
    print("\n" + "=" * 60)
    print("  BOT MEMORY REPORT")
    print(f"  Weeks run: {mem['meta']['total_weeks_run']}")
    print(f"  Last updated: {mem['meta'].get('last_updated', 'never')[:10]}")
    print("=" * 60)

    if mem["account_growth"]:
        growth = mem["account_growth"]
        print(f"\n  ACCOUNT GROWTH")
        for g in growth:
            print(f"    Week {g['week']}: {g['followers']:,} followers")
        if len(growth) >= 2:
            delta = growth[-1]["followers"] - growth[0]["followers"]
            print(f"    Total gain: +{delta} followers")

    if mem["format_leaderboard"]:
        print(f"\n  TOP FORMATS (by appearances)")
        sorted_f = sorted(mem["format_leaderboard"].items(), key=lambda x: x[1]["appearances"], reverse=True)
        for fmt, data in sorted_f[:5]:
            print(f"    {fmt}: {data['appearances']}x | avg engagement: {data.get('avg_engagement', 0):,}")

    if mem["evergreen_frameworks"]:
        print(f"\n  EVERGREEN (use every week): {', '.join(mem['evergreen_frameworks'])}")

    if mem["fading_formats"]:
        print(f"  FADING (reduce usage): {', '.join(mem['fading_formats'])}")

    if mem["your_tweet_log"]:
        best = max(mem["your_tweet_log"], key=lambda t: t.get("impressions", 0))
        print(f"\n  YOUR BEST TWEET")
        print(f"    {best['impressions']:,} impressions | {best['likes']} likes | {best['retweets']} RTs")
        print(f"    Format: {best.get('format', '?')}")
        print(f"    \"{best['text'][:80]}...\"")

    if mem["running_opportunities"]:
        print(f"\n  OPPORTUNITY ANGLES BY WEEK")
        for opp in mem["running_opportunities"][-4:]:
            print(f"    Week {opp['week']}: {opp['opportunity'][:80]}...")

    print("\n" + "=" * 60 + "\n")
