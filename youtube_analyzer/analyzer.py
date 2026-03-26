"""Core analysis engine - processes video data into structured insights."""

import re
from collections import Counter
from datetime import datetime


def analyze_channel(channel_info: dict, videos: list[dict]) -> dict:
    """Run full analysis on a channel's video catalog."""
    if not videos:
        return {"error": "No videos found for this channel."}

    sorted_by_views = sorted(videos, key=lambda v: v["view_count"], reverse=True)
    avg_views = sum(v["view_count"] for v in videos) / len(videos)

    return {
        "channel": channel_info,
        "total_videos_analyzed": len(videos),
        "avg_views": int(avg_views),
        "median_views": _median([v["view_count"] for v in videos]),
        "top_videos": _analyze_top_videos(sorted_by_views[:20], avg_views),
        "bottom_videos": _analyze_bottom_videos(sorted_by_views[-20:], avg_views),
        "script_formats": _analyze_script_formats(videos),
        "thumbnail_patterns": _analyze_thumbnail_patterns(sorted_by_views),
        "title_patterns": _analyze_title_patterns(sorted_by_views),
        "posting_patterns": _analyze_posting_patterns(videos),
        "tag_analysis": _analyze_tags(videos),
        "duration_analysis": _analyze_durations(videos, avg_views),
        "engagement_ratios": _analyze_engagement(videos),
        "growth_trajectory": _analyze_growth(videos),
    }


def _median(values: list[int]) -> int:
    s = sorted(values)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) // 2
    return s[n // 2]


def _analyze_top_videos(top_videos: list[dict], avg_views: float) -> list[dict]:
    results = []
    for v in top_videos:
        multiplier = v["view_count"] / avg_views if avg_views > 0 else 0
        results.append({
            "title": v["title"],
            "views": v["view_count"],
            "likes": v["like_count"],
            "comments": v["comment_count"],
            "multiplier_vs_avg": round(multiplier, 1),
            "duration": v["duration"],
            "published": v["published_at"],
            "thumbnail_url": v["thumbnail_url"],
            "tags": v["tags"][:10],
            "url": f"https://youtube.com/watch?v={v['id']}",
        })
    return results


def _analyze_bottom_videos(bottom_videos: list[dict], avg_views: float) -> list[dict]:
    results = []
    for v in bottom_videos:
        ratio = v["view_count"] / avg_views if avg_views > 0 else 0
        issues = _diagnose_underperformance(v, avg_views)
        results.append({
            "title": v["title"],
            "views": v["view_count"],
            "ratio_vs_avg": round(ratio, 2),
            "duration": v["duration"],
            "published": v["published_at"],
            "diagnosed_issues": issues,
            "url": f"https://youtube.com/watch?v={v['id']}",
        })
    return results


def _diagnose_underperformance(video: dict, avg_views: float) -> list[str]:
    """Identify likely reasons a video underperformed."""
    issues = []
    duration_mins = _parse_duration_minutes(video["duration"])

    if duration_mins and duration_mins < 3:
        issues.append("Too short (<3 min) - may not get recommended")
    if duration_mins and duration_mins > 30:
        issues.append("Very long (>30 min) - may lose casual viewers")

    title = video["title"]
    if len(title) > 70:
        issues.append("Title too long - gets truncated in search results")
    if len(title) < 20:
        issues.append("Title too short - may lack searchable keywords")
    if title.isupper():
        issues.append("ALL CAPS title - can appear spammy")
    if not any(c.isdigit() for c in title) and not any(w in title.lower() for w in ["how", "why", "what", "best", "top", "vs"]):
        issues.append("Title lacks power words or numbers")

    if not video["tags"]:
        issues.append("No tags set - missed SEO opportunity")
    elif len(video["tags"]) < 5:
        issues.append("Very few tags - weak discoverability")

    like_ratio = video["like_count"] / video["view_count"] if video["view_count"] > 0 else 0
    if like_ratio < 0.02:
        issues.append("Low like-to-view ratio (<2%) - content may not resonate")

    comment_ratio = video["comment_count"] / video["view_count"] if video["view_count"] > 0 else 0
    if comment_ratio < 0.001:
        issues.append("Very low comment engagement - no call to action or discussion trigger")

    if not issues:
        issues.append("No obvious structural issues - may be niche topic or algorithm timing")

    return issues


def _analyze_script_formats(videos: list[dict]) -> dict:
    """Detect common script/content formats from titles and descriptions."""
    format_patterns = {
        "listicle": r"\b\d+\s+(things|ways|tips|reasons|facts|mistakes|secrets|signs|steps|ideas|hacks)\b",
        "how_to": r"\bhow\s+to\b",
        "tutorial": r"\btutorial\b",
        "review": r"\breview\b",
        "comparison": r"\bvs\.?\b|\bversus\b|\bcompared\b",
        "story_time": r"\bstory\s*time\b|\bwhat\s+happened\b|\bI\s+(tried|did|went|bought|tested)\b",
        "reaction": r"\breact(ing|ion)?\b|\bresponding\b",
        "challenge": r"\bchallenge\b",
        "tier_list": r"\btier\s+list\b|\branking\b",
        "explained": r"\bexplain(ed|ing)?\b|\bbreakdown\b",
        "vlog": r"\bvlog\b|\bday\s+in\s+(my|the)\s+life\b",
        "q_and_a": r"\bq\s*(&|and)\s*a\b|\bask\s+me\b",
        "documentary": r"\bdocumentary\b|\bthe\s+(rise|fall|story|truth|history)\s+of\b",
        "top_list": r"\btop\s+\d+\b|\bbest\s+\d+\b|\bworst\s+\d+\b",
    }

    format_counts = Counter()
    format_examples = {}
    format_avg_views = {}

    for v in videos:
        text = f"{v['title']} {v['description'][:200]}".lower()
        for fmt, pattern in format_patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                format_counts[fmt] += 1
                format_examples.setdefault(fmt, [])
                if len(format_examples[fmt]) < 3:
                    format_examples[fmt].append(v["title"])
                format_avg_views.setdefault(fmt, []).append(v["view_count"])

    results = {}
    for fmt, count in format_counts.most_common():
        views = format_avg_views[fmt]
        results[fmt] = {
            "count": count,
            "percentage": round(count / len(videos) * 100, 1),
            "avg_views": int(sum(views) / len(views)),
            "examples": format_examples[fmt],
        }

    return results


def _analyze_thumbnail_patterns(sorted_videos: list[dict]) -> dict:
    """Analyze thumbnail patterns from top vs bottom performers."""
    top_20 = sorted_videos[:20]
    bottom_20 = sorted_videos[-20:] if len(sorted_videos) >= 40 else sorted_videos[len(sorted_videos) // 2:]

    return {
        "top_performer_thumbnails": [
            {"title": v["title"], "url": v["thumbnail_url"], "views": v["view_count"]}
            for v in top_20
        ],
        "bottom_performer_thumbnails": [
            {"title": v["title"], "url": v["thumbnail_url"], "views": v["view_count"]}
            for v in bottom_20
        ],
        "analysis_notes": [
            "Compare face expressions, text overlay, colors, and composition between top and bottom",
            "Top thumbnails often share: bright colors, clear faces with emotion, minimal text (3-5 words max)",
            "Bottom thumbnails often have: cluttered designs, small text, no human element, dark/muted colors",
        ],
    }


def _analyze_title_patterns(sorted_videos: list[dict]) -> dict:
    """Extract title formula patterns from high-performing videos."""
    top = sorted_videos[:20]
    bottom = sorted_videos[-20:] if len(sorted_videos) >= 40 else sorted_videos[len(sorted_videos) // 2:]

    def title_features(vids):
        lengths = [len(v["title"]) for v in vids]
        has_numbers = sum(1 for v in vids if any(c.isdigit() for c in v["title"]))
        has_question = sum(1 for v in vids if "?" in v["title"])
        has_brackets = sum(1 for v in vids if any(b in v["title"] for b in "[]()"))
        has_caps_word = sum(1 for v in vids if any(w.isupper() and len(w) > 1 for w in v["title"].split()))
        has_emoji = sum(1 for v in vids if any(ord(c) > 0x1F600 for c in v["title"]))
        power_words = ["secret", "insane", "shocking", "ultimate", "never", "always", "worst", "best", "crazy", "impossible", "finally", "actually"]
        has_power = sum(1 for v in vids if any(pw in v["title"].lower() for pw in power_words))

        return {
            "avg_length": round(sum(lengths) / len(lengths), 1) if lengths else 0,
            "has_numbers_pct": round(has_numbers / len(vids) * 100) if vids else 0,
            "has_question_pct": round(has_question / len(vids) * 100) if vids else 0,
            "has_brackets_pct": round(has_brackets / len(vids) * 100) if vids else 0,
            "has_caps_emphasis_pct": round(has_caps_word / len(vids) * 100) if vids else 0,
            "has_power_words_pct": round(has_power / len(vids) * 100) if vids else 0,
        }

    return {
        "top_performer_patterns": title_features(top),
        "bottom_performer_patterns": title_features(bottom),
        "top_titles": [v["title"] for v in top[:10]],
    }


def _analyze_posting_patterns(videos: list[dict]) -> dict:
    """Analyze upload frequency and best posting days."""
    day_counts = Counter()
    hour_counts = Counter()
    day_views = {}

    for v in videos:
        try:
            dt = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
            day_name = dt.strftime("%A")
            day_counts[day_name] += 1
            hour_counts[dt.hour] += 1
            day_views.setdefault(day_name, []).append(v["view_count"])
        except (ValueError, KeyError):
            continue

    best_days = {}
    for day, views in day_views.items():
        best_days[day] = {
            "uploads": day_counts[day],
            "avg_views": int(sum(views) / len(views)),
        }

    # Calculate upload frequency
    dates = []
    for v in videos:
        try:
            dates.append(datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")))
        except (ValueError, KeyError):
            continue

    avg_days_between = 0
    if len(dates) >= 2:
        dates.sort(reverse=True)
        gaps = [(dates[i] - dates[i + 1]).days for i in range(len(dates) - 1)]
        avg_days_between = round(sum(gaps) / len(gaps), 1)

    return {
        "avg_days_between_uploads": avg_days_between,
        "uploads_per_week": round(7 / avg_days_between, 1) if avg_days_between > 0 else 0,
        "day_performance": dict(sorted(best_days.items(), key=lambda x: x[1]["avg_views"], reverse=True)),
        "peak_hours_utc": [h for h, _ in hour_counts.most_common(3)],
    }


def _analyze_tags(videos: list[dict]) -> dict:
    """Find most effective tags across top performers."""
    all_tags = Counter()
    top_tags = Counter()

    sorted_vids = sorted(videos, key=lambda v: v["view_count"], reverse=True)
    top_20_pct = sorted_vids[: max(1, len(sorted_vids) // 5)]

    for v in videos:
        for tag in v["tags"]:
            all_tags[tag.lower()] += 1

    for v in top_20_pct:
        for tag in v["tags"]:
            top_tags[tag.lower()] += 1

    return {
        "most_used_tags": all_tags.most_common(20),
        "top_performer_tags": top_tags.most_common(20),
    }


def _analyze_durations(videos: list[dict], avg_views: float) -> dict:
    """Find the sweet spot for video length."""
    buckets = {
        "shorts_0-1min": {"range": (0, 1), "videos": [], "views": []},
        "short_1-5min": {"range": (1, 5), "videos": [], "views": []},
        "medium_5-10min": {"range": (5, 10), "videos": [], "views": []},
        "standard_10-20min": {"range": (10, 20), "videos": [], "views": []},
        "long_20-40min": {"range": (20, 40), "videos": [], "views": []},
        "very_long_40plus": {"range": (40, 9999), "videos": [], "views": []},
    }

    for v in videos:
        mins = _parse_duration_minutes(v["duration"])
        if mins is None:
            continue
        for bucket_name, bucket in buckets.items():
            low, high = bucket["range"]
            if low <= mins < high:
                bucket["videos"].append(v["title"])
                bucket["views"].append(v["view_count"])
                break

    results = {}
    best_bucket = None
    best_avg = 0
    for name, bucket in buckets.items():
        if bucket["views"]:
            avg = int(sum(bucket["views"]) / len(bucket["views"]))
            results[name] = {
                "count": len(bucket["views"]),
                "avg_views": avg,
            }
            if avg > best_avg:
                best_avg = avg
                best_bucket = name

    results["sweet_spot"] = best_bucket
    return results


def _analyze_engagement(videos: list[dict]) -> dict:
    """Calculate engagement metrics."""
    like_ratios = []
    comment_ratios = []

    for v in videos:
        if v["view_count"] > 0:
            like_ratios.append(v["like_count"] / v["view_count"])
            comment_ratios.append(v["comment_count"] / v["view_count"])

    return {
        "avg_like_ratio": round(sum(like_ratios) / len(like_ratios) * 100, 2) if like_ratios else 0,
        "avg_comment_ratio": round(sum(comment_ratios) / len(comment_ratios) * 100, 3) if comment_ratios else 0,
    }


def _analyze_growth(videos: list[dict]) -> dict:
    """Track performance trend over time."""
    sorted_by_date = sorted(videos, key=lambda v: v["published_at"])
    if len(sorted_by_date) < 10:
        return {"note": "Not enough videos for growth analysis"}

    chunk_size = len(sorted_by_date) // 4
    quarters = [sorted_by_date[i * chunk_size:(i + 1) * chunk_size] for i in range(4)]

    results = []
    for i, q in enumerate(quarters):
        if q:
            avg_v = int(sum(v["view_count"] for v in q) / len(q))
            results.append({
                "period": f"Q{i+1} (oldest)" if i == 0 else f"Q{i+1} (newest)" if i == 3 else f"Q{i+1}",
                "videos": len(q),
                "avg_views": avg_v,
                "date_range": f"{q[0]['published_at'][:10]} to {q[-1]['published_at'][:10]}",
            })

    return {"quarters": results}


def _parse_duration_minutes(duration: str) -> float | None:
    """Parse ISO 8601 duration to minutes."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 60 + minutes + seconds / 60
