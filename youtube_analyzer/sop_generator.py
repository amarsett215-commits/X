"""AI-powered SOP and workflow generator using Claude API."""

import json
import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()


def generate_sop(analysis: dict) -> str:
    """Generate a comprehensive SOP/workflow using Claude based on the channel analysis."""
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = _build_sop_prompt(analysis)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


def generate_subniche_ideas(analysis: dict) -> str:
    """Generate viral subniche ideas using Claude based on the channel analysis."""
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = _build_subniche_prompt(analysis)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    )

    return response.content[0].text


def _build_sop_prompt(analysis: dict) -> str:
    channel = analysis["channel"]
    top_titles = [v["title"] for v in analysis["top_videos"][:10]]
    bottom_titles = [v["title"] for v in analysis["bottom_videos"][:10]]
    formats = analysis["script_formats"]
    title_patterns = analysis["title_patterns"]
    duration = analysis["duration_analysis"]
    posting = analysis["posting_patterns"]
    engagement = analysis["engagement_ratios"]

    # Summarize format performance
    format_summary = ""
    for fmt, data in formats.items():
        format_summary += f"  - {fmt}: {data['count']} videos, avg {data['avg_views']:,} views\n"

    return f"""You are a YouTube content strategy expert. Based on this channel analysis data, create a COMPREHENSIVE SOP (Standard Operating Procedure) and content workflow.

## Channel: {channel['title']}
- Subscribers: {channel['subscriber_count']:,}
- Total views: {channel['view_count']:,}
- Videos analyzed: {analysis['total_videos_analyzed']}
- Average views per video: {analysis['avg_views']:,}
- Median views: {analysis['median_views']:,}

## Top 10 Performing Videos:
{json.dumps(top_titles, indent=2)}

## Bottom 10 Performing Videos:
{json.dumps(bottom_titles, indent=2)}

## Content Formats Found:
{format_summary}

## Title Patterns (Top Performers):
{json.dumps(title_patterns['top_performer_patterns'], indent=2)}

## Title Patterns (Bottom Performers):
{json.dumps(title_patterns['bottom_performer_patterns'], indent=2)}

## Duration Sweet Spot: {duration.get('sweet_spot', 'N/A')}
{json.dumps({k: v for k, v in duration.items() if k != 'sweet_spot'}, indent=2)}

## Posting Schedule:
- Avg days between uploads: {posting['avg_days_between_uploads']}
- Uploads per week: {posting['uploads_per_week']}

## Engagement:
- Avg like ratio: {engagement['avg_like_ratio']}%
- Avg comment ratio: {engagement['avg_comment_ratio']}%

---

Create a FULL SOP document with these sections:

### 1. CONTENT STRATEGY OVERVIEW
- What makes this channel's top videos work
- Core content pillars identified from the data
- Target audience profile (inferred from content)

### 2. SCRIPT FRAMEWORK
- Provide 3-5 proven script templates based on the top-performing formats
- Include: Hook (first 30 seconds), Structure, Retention techniques, CTA placement
- Each template should reference specific successful videos as examples

### 3. TITLE FORMULA
- Exact title templates that work for this channel (fill-in-the-blank style)
- Do's and don'ts based on top vs bottom performer comparison
- Provide 10 ready-to-use title templates

### 4. THUMBNAIL STRATEGY
- Based on the patterns, describe the ideal thumbnail style
- Color palette, text rules, face/expression guidelines
- Provide 5 thumbnail concepts for different content types

### 5. VIDEO PRODUCTION WORKFLOW
- Step-by-step from idea to published video
- Ideal video length based on data
- Editing style notes

### 6. UPLOAD & OPTIMIZATION CHECKLIST
- Best posting days/times from the data
- SEO checklist (tags, description, title)
- First 24-hour promotion strategy

### 7. CONTENT CALENDAR TEMPLATE
- Weekly schedule based on the channel's upload frequency
- Content mix recommendations (which formats and how often)

### 8. WHAT TO AVOID
- Specific patterns from underperforming videos
- Common mistakes this channel makes on low-view videos
- Anti-patterns to avoid

Be specific, actionable, and reference the actual data provided. This should be a document someone can immediately start following."""


def _build_subniche_prompt(analysis: dict) -> str:
    channel = analysis["channel"]
    top_titles = [v["title"] for v in analysis["top_videos"][:10]]
    formats = analysis["script_formats"]
    tags = analysis["tag_analysis"]

    top_tags = [t[0] for t in tags["top_performer_tags"][:15]]
    format_names = list(formats.keys())

    return f"""You are a YouTube growth strategist who specializes in finding untapped sub-niches with viral potential.

## Channel Analyzed: {channel['title']}
- Niche: (infer from content below)
- Subscribers: {channel['subscriber_count']:,}
- Avg views: {analysis['avg_views']:,}

## Top Performing Content:
{json.dumps(top_titles, indent=2)}

## Content Formats That Work:
{json.dumps(format_names, indent=2)}

## Top Tags:
{json.dumps(top_tags, indent=2)}

## Channel Keywords: {channel.get('keywords', 'N/A')}

---

Based on this analysis, generate:

### 1. NICHE CLASSIFICATION
- Primary niche
- Secondary niche
- Content style category

### 2. SUB-NICHE OPPORTUNITIES (List 15-20)
For each sub-niche provide:
- **Sub-niche name**
- **Why it has viral potential** (audience size, search trends, competition gap)
- **Content angle** - specific video ideas for this sub-niche
- **Difficulty level** (Easy/Medium/Hard) based on competition and production needs
- **Estimated audience interest** (1-10 scale)
- **3 ready-to-film video titles** for each sub-niche

### 3. BLUE OCEAN OPPORTUNITIES
- 5 completely untapped angles that no one in this niche is covering
- Why each has potential based on adjacent audience interests

### 4. CROSS-POLLINATION IDEAS
- 5 ideas that blend this niche with trending topics from OTHER niches
- Each with a specific video concept

### 5. VIRAL TRIGGER ANALYSIS
- What psychological triggers make this niche's top videos go viral
- How to engineer these triggers into new sub-niche content
- Pattern interrupts and curiosity gaps specific to this niche

### 6. 90-DAY SUBNICHE TESTING PLAN
- Week-by-week plan for testing 3 sub-niches
- Metrics to track
- Decision framework for doubling down vs pivoting

Be specific and creative. Every sub-niche should have real viral potential, not generic suggestions."""
