#!/usr/bin/env python3
"""
YouTube Channel Analyzer Bot
Analyzes any YouTube channel and generates:
- Script format analysis
- Top/bottom video breakdowns with diagnostics
- Thumbnail pattern analysis
- Full SOP/workflow for content creation
- Viral sub-niche opportunities

Usage:
    python main.py <channel_url_or_handle>
    python main.py @MrBeast
    python main.py https://youtube.com/@MrBeast
    python main.py UCX6OQ3DkcsbYNE6H8uQQuVA
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from youtube_analyzer.youtube_api import resolve_channel_id, get_channel_info, get_all_videos
from youtube_analyzer.analyzer import analyze_channel
from youtube_analyzer.sop_generator import generate_sop, generate_subniche_ideas
from youtube_analyzer.report import generate_full_report


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    channel_input = sys.argv[1]
    max_videos = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    print(f"\n{'='*60}")
    print(f"  YOUTUBE CHANNEL ANALYZER BOT")
    print(f"{'='*60}\n")

    # Step 1: Resolve channel
    print(f"[1/6] Resolving channel: {channel_input}")
    try:
        channel_id = resolve_channel_id(channel_input)
        print(f"      Found channel ID: {channel_id}")
    except ValueError as e:
        print(f"      ERROR: {e}")
        sys.exit(1)

    # Step 2: Fetch channel info
    print(f"[2/6] Fetching channel info...")
    channel_info = get_channel_info(channel_id)
    print(f"      Channel: {channel_info['title']}")
    print(f"      Subscribers: {channel_info['subscriber_count']:,}")
    print(f"      Total videos: {channel_info['video_count']:,}")

    # Step 3: Fetch videos
    print(f"[3/6] Fetching up to {max_videos} videos...")
    videos = get_all_videos(channel_id, max_videos=max_videos)
    print(f"      Retrieved {len(videos)} videos")

    # Step 4: Analyze
    print(f"[4/6] Running analysis...")
    analysis = analyze_channel(channel_info, videos)
    print(f"      Avg views: {analysis['avg_views']:,}")
    print(f"      Formats detected: {len(analysis['script_formats'])}")
    print(f"      Duration sweet spot: {analysis['duration_analysis'].get('sweet_spot', 'N/A')}")

    # Step 5: Generate SOP with AI
    print(f"[5/6] Generating SOP with Claude AI...")
    sop_text = generate_sop(analysis)
    print(f"      SOP generated ({len(sop_text)} chars)")

    # Step 6: Generate subniche ideas
    print(f"[6/6] Generating sub-niche opportunities...")
    subniche_text = generate_subniche_ideas(analysis)
    print(f"      Subniches generated ({len(subniche_text)} chars)")

    # Save report
    report_path = generate_full_report(analysis, sop_text, subniche_text)
    print(f"\n{'='*60}")
    print(f"  COMPLETE!")
    print(f"  Report saved to: {report_path}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
