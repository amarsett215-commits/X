"""
Bot configuration — edit this to match your niche and targets.
"""

# Claude model
MODEL = "claude-opus-4-6"

# Niche keywords to search on X (used for scraping + analysis)
NICHE_KEYWORDS = [
    "Claude AI digital products",
    "build with Claude make money",
    "Claude AI income online",
    "AI digital products sell",
    "Claude AI side hustle",
    "make money Claude AI",
    "Claude prompt pack sell",
    "AI tools make money online",
]

# Top accounts in your niche to monitor
NICHE_ACCOUNTS = [
    "X_FINALBOSS",
    "EBOOK_FINALBOSS",
    "thisdudelikesAI",
    "ideabrowser",
    "theisaacmed",
    "kmeanskaran",
    "sukh_saroy",
    "claudeai",
    "milesdeutscher",
    "JulianGoldieSEO",
]

# Nitter instances (public X mirrors — no login required)
# If one is down, the bot tries the next
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.lucabased.xyz",
    "https://nitter.nl",
    "https://nitter.1d4.us",
]

# Min engagement to consider a tweet worth analyzing
MIN_LIKES = 20
MIN_RETWEETS = 5

# How many tweets to collect and analyze per run
TWEETS_TO_COLLECT = 30
TWEETS_TO_ANALYZE = 15  # Top N after filtering

# Output directory for generated SOPs and reports
OUTPUT_DIR = "output"

# Your account niche description (used in Claude prompts)
YOUR_NICHE = "helping people build digital products with Claude AI and make money online"
YOUR_AUDIENCE = "beginner to intermediate entrepreneurs who want passive income without coding skills"
YOUR_TONE = "direct, practical, no fluff, occasionally contrarian"
