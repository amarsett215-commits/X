"""Report generation - formats analysis into readable output."""

import json
import os
from datetime import datetime


def generate_full_report(analysis: dict, sop_text: str, subniche_text: str, output_dir: str = "reports") -> str:
    """Generate a full markdown report and save to file."""
    os.makedirs(output_dir, exist_ok=True)

    channel = analysis["channel"]
    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in channel["title"]).strip().replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{output_dir}/{safe_name}_analysis_{timestamp}.md"

    report = _build_report(analysis, sop_text, subniche_text)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(report)

    # Also save raw data as JSON
    json_filename = f"{output_dir}/{safe_name}_data_{timestamp}.json"
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, default=str)

    return filename


def _build_report(analysis: dict, sop_text: str, subniche_text: str) -> str:
    ch = analysis["channel"]
    lines = []

    lines.append(f"# YouTube Channel Analysis: {ch['title']}")
    lines.append(f"*Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}*\n")
    lines.append("---\n")

    # Channel overview
    lines.append("## Channel Overview\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Channel | [{ch['title']}](https://youtube.com/channel/{ch['id']}) |")
    lines.append(f"| Subscribers | {ch['subscriber_count']:,} |")
    lines.append(f"| Total Views | {ch['view_count']:,} |")
    lines.append(f"| Videos Analyzed | {analysis['total_videos_analyzed']} |")
    lines.append(f"| Avg Views/Video | {analysis['avg_views']:,} |")
    lines.append(f"| Median Views | {analysis['median_views']:,} |")
    lines.append(f"| Avg Like Ratio | {analysis['engagement_ratios']['avg_like_ratio']}% |")
    lines.append(f"| Avg Comment Ratio | {analysis['engagement_ratios']['avg_comment_ratio']}% |")
    lines.append("")

    # Top videos
    lines.append("## Top 20 Videos\n")
    lines.append("| # | Title | Views | Likes | vs Avg |")
    lines.append("|---|-------|-------|-------|--------|")
    for i, v in enumerate(analysis["top_videos"][:20], 1):
        title = v["title"][:60] + ("..." if len(v["title"]) > 60 else "")
        lines.append(f"| {i} | [{title}]({v['url']}) | {v['views']:,} | {v['likes']:,} | {v['multiplier_vs_avg']}x |")
    lines.append("")

    # Bottom videos with diagnostics
    lines.append("## Bottom 20 Videos (with Diagnosis)\n")
    for i, v in enumerate(analysis["bottom_videos"][:20], 1):
        lines.append(f"### {i}. [{v['title']}]({v['url']})")
        lines.append(f"- **Views:** {v['views']:,} ({v['ratio_vs_avg']}x of average)")
        lines.append(f"- **Issues identified:**")
        for issue in v["diagnosed_issues"]:
            lines.append(f"  - {issue}")
        lines.append("")

    # Script formats
    lines.append("## Script Format Analysis\n")
    if analysis["script_formats"]:
        lines.append("| Format | Count | % of Videos | Avg Views |")
        lines.append("|--------|-------|-------------|-----------|")
        for fmt, data in analysis["script_formats"].items():
            lines.append(f"| {fmt} | {data['count']} | {data['percentage']}% | {data['avg_views']:,} |")
        lines.append("")
    else:
        lines.append("No clear format patterns detected.\n")

    # Title patterns
    lines.append("## Title Pattern Analysis\n")
    tp = analysis["title_patterns"]
    lines.append("### Top Performers vs Bottom Performers\n")
    lines.append("| Pattern | Top Videos | Bottom Videos |")
    lines.append("|---------|-----------|---------------|")
    for key in tp["top_performer_patterns"]:
        top_val = tp["top_performer_patterns"][key]
        bot_val = tp["bottom_performer_patterns"].get(key, "N/A")
        lines.append(f"| {key} | {top_val} | {bot_val} |")
    lines.append("")

    # Duration analysis
    lines.append("## Video Duration Analysis\n")
    da = analysis["duration_analysis"]
    sweet = da.get("sweet_spot", "N/A")
    lines.append(f"**Sweet spot:** {sweet}\n")
    lines.append("| Duration Bucket | Count | Avg Views |")
    lines.append("|-----------------|-------|-----------|")
    for bucket, data in da.items():
        if bucket != "sweet_spot" and isinstance(data, dict):
            lines.append(f"| {bucket} | {data['count']} | {data['avg_views']:,} |")
    lines.append("")

    # Posting patterns
    lines.append("## Posting Schedule\n")
    pp = analysis["posting_patterns"]
    lines.append(f"- **Upload frequency:** Every {pp['avg_days_between_uploads']} days ({pp['uploads_per_week']} per week)")
    lines.append(f"- **Best posting hours (UTC):** {pp['peak_hours_utc']}\n")
    lines.append("### Performance by Day\n")
    lines.append("| Day | Uploads | Avg Views |")
    lines.append("|-----|---------|-----------|")
    for day, data in pp["day_performance"].items():
        lines.append(f"| {day} | {data['uploads']} | {data['avg_views']:,} |")
    lines.append("")

    # Growth trajectory
    lines.append("## Growth Trajectory\n")
    gt = analysis["growth_trajectory"]
    if "quarters" in gt:
        lines.append("| Period | Videos | Avg Views | Date Range |")
        lines.append("|--------|--------|-----------|------------|")
        for q in gt["quarters"]:
            lines.append(f"| {q['period']} | {q['videos']} | {q['avg_views']:,} | {q['date_range']} |")
    lines.append("")

    # Thumbnail patterns
    lines.append("## Thumbnail Analysis\n")
    lines.append("### Top Performer Thumbnails\n")
    for t in analysis["thumbnail_patterns"]["top_performer_thumbnails"][:10]:
        lines.append(f"- **{t['title']}** ({t['views']:,} views)")
        lines.append(f"  - ![thumbnail]({t['url']})")
    lines.append("")
    lines.append("### Thumbnail Strategy Notes\n")
    for note in analysis["thumbnail_patterns"]["analysis_notes"]:
        lines.append(f"- {note}")
    lines.append("")

    # SOP
    lines.append("---\n")
    lines.append("# FULL SOP / CONTENT WORKFLOW\n")
    lines.append(sop_text)
    lines.append("")

    # Subniches
    lines.append("---\n")
    lines.append("# SUBNICHE OPPORTUNITIES & VIRAL POTENTIAL\n")
    lines.append(subniche_text)
    lines.append("")

    return "\n".join(lines)
