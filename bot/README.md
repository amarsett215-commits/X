# X Account Bot

Scrapes viral tweets in the **Claude AI + digital products + make money online** niche, analyzes the patterns with Claude, and generates a weekly SOP + ready-to-post tweet batch.

## Setup

```bash
cd bot
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
```

## Run

```bash
# Full pipeline: scrape → analyze → generate SOP
python main.py

# Specify week number manually
python main.py --week 3

# Skip scraping, re-analyze saved tweets
python main.py --analyze-only

# Skip scraping + analysis, regenerate SOP from last analysis
python main.py --sop-only
```

## Output

Each run produces 3 files in `output/`:

| File | Contents |
|---|---|
| `week_XX_sop_YYYY-MM-DD.md` | Full SOP with framework breakdown + posting schedule |
| `week_XX_tweets_YYYY-MM-DD.md` | 7 standalone tweets + 2 threads (copy-paste ready) |
| `week_XX_analysis_YYYY-MM-DD.json` | Raw Claude analysis (for debugging/reference) |

## How It Works

```
collect_tweets()          # scraper.py
    ├── Nitter profiles   # top niche accounts
    ├── Nitter search     # niche keywords
    ├── DuckDuckGo        # fallback if Nitter is down
    └── Seed tweets       # always-available baseline

analyze_tweets()          # analyzer.py
    └── Claude Opus 4.6   # adaptive thinking + streaming
        ├── Per-tweet: format, emotion, hook, result, steal factor
        └── Patterns: dominant formats, emotions, hooks, opportunities

generate_weekly_sop()     # sop_generator.py
    └── Claude Opus 4.6   # streaming
        ├── Full SOP markdown (research → frameworks → schedule)
        └── Clean tweet batch (7 tweets + 2 threads, copy-paste)
```

## Customise

Edit `config.py` to change:
- `NICHE_KEYWORDS` — what to search for
- `NICHE_ACCOUNTS` — which profiles to monitor
- `YOUR_NICHE` / `YOUR_AUDIENCE` / `YOUR_TONE` — Claude's context for generation
- `MIN_LIKES` / `MIN_RETWEETS` — engagement thresholds

## Schedule (Optional)

Run weekly with cron:

```bash
# Every Monday at 7 AM
0 7 * * 1 cd /home/user/X/bot && python main.py >> output/cron.log 2>&1
```
