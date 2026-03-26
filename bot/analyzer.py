"""
Tweet analyzer — uses Claude to study viral tweet patterns.

For each tweet, Claude extracts:
- Format (hook type, structure)
- Primary emotion triggered
- Result / promise made to the reader
- Reusable framework (what made it work)

Returns structured analysis ready for the SOP generator.
"""

import json
import logging
from typing import Any

import anthropic

from config import MODEL, YOUR_NICHE, YOUR_AUDIENCE, TWEETS_TO_ANALYZE

log = logging.getLogger(__name__)
client = anthropic.Anthropic()


def _build_analysis_prompt(tweets: list[dict]) -> str:
    tweet_block = ""
    for i, t in enumerate(tweets, 1):
        tweet_block += (
            f"\n--- TWEET {i} ---\n"
            f"Author: @{t['author']}\n"
            f"Likes: {t['likes']} | Retweets: {t['retweets']}\n"
            f"Text:\n{t['text']}\n"
            f"URL: {t.get('url', 'n/a')}\n"
        )

    return f"""You are an expert X (Twitter) content strategist specialising in the niche:
"{YOUR_NICHE}"

Target audience: {YOUR_AUDIENCE}

Below are {len(tweets)} high-performing tweets from this niche this week.
Study them carefully and extract the content frameworks that made them successful.

{tweet_block}

Analyse ALL {len(tweets)} tweets and return a JSON object with this exact structure:

{{
  "top_tweets": [
    {{
      "rank": 1,
      "author": "@handle",
      "text_excerpt": "first 100 chars of tweet...",
      "url": "https://x.com/...",
      "engagement": {{"likes": 0, "retweets": 0}},
      "format": "What structural format is used? (e.g. numbered list, story, contrarian take, prompt reveal, stat + breakdown, myth vs reality, accidental discovery, step-by-step, build-in-public)",
      "hook_type": "What type of hook opens the tweet? (e.g. bold claim, specific number, relatable struggle, surprising result, question, identity statement)",
      "hook_text": "The actual first sentence or hook phrase",
      "emotion_triggered": "Primary emotion this tweet activates in the reader (e.g. FOMO, curiosity, relief, surprise, validation, urgency, hope)",
      "result_promised": "What specific outcome does this tweet promise or imply the reader can achieve?",
      "why_it_worked": "2-3 sentence explanation of the psychological mechanism that made this tweet perform well",
      "steal_factor": "The single most reusable insight from this tweet — what can be directly applied to a new tweet?"
    }}
  ],
  "patterns": {{
    "dominant_formats": ["list the 3 most common formats found across all tweets"],
    "dominant_emotions": ["list the 3 most triggered emotions"],
    "dominant_hooks": ["list the 3 most effective hook types"],
    "what_gets_shared": "One paragraph: what types of content get retweeted in this niche and why",
    "what_converts": "One paragraph: what content drives clicks/follows/sales vs just likes",
    "niche_specific_insights": "2-3 insights specific to the Claude AI + digital products + make money online niche"
  }},
  "contrarian_observations": [
    "Any surprising or counter-intuitive patterns found (2-3 bullet points)"
  ],
  "this_week_opportunity": "Based on these tweets, what content angle has the highest potential right now that is NOT yet oversaturated?"
}}

Return ONLY the JSON — no markdown fences, no preamble."""


def analyze_tweets(tweets: list[dict]) -> dict[str, Any]:
    """
    Send tweets to Claude for pattern analysis.
    Uses adaptive thinking + streaming for deep analysis.
    Returns structured analysis dict.
    """
    top_tweets = tweets[:TWEETS_TO_ANALYZE]
    log.info(f"Sending {len(top_tweets)} tweets to Claude for analysis...")

    prompt = _build_analysis_prompt(top_tweets)

    # Stream the response — analysis can be long
    full_response = ""
    with client.messages.stream(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for event in stream:
            if (
                event.type == "content_block_delta"
                and event.delta.type == "text_delta"
            ):
                chunk = event.delta.text
                full_response += chunk
                print(chunk, end="", flush=True)
        print()  # newline after streaming

    # Parse JSON response
    try:
        # Strip any accidental markdown fences
        cleaned = full_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        analysis = json.loads(cleaned)
        log.info("Analysis parsed successfully.")
        return analysis
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse Claude response as JSON: {e}")
        log.debug(f"Raw response: {full_response[:500]}")
        # Return a minimal structure so the pipeline doesn't break
        return {
            "top_tweets": [],
            "patterns": {
                "dominant_formats": [],
                "dominant_emotions": [],
                "dominant_hooks": [],
                "what_gets_shared": full_response[:500],
                "what_converts": "",
                "niche_specific_insights": "",
            },
            "contrarian_observations": [],
            "this_week_opportunity": "",
            "raw_response": full_response,
        }
