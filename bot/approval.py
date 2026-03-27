"""
Approval and scheduling layer.

Handles:
- Generating one-time approval tokens after a pipeline run
- Storing pending tweet batches
- Posting approved tweets directly to X via the API
- Parsing tweet batches into individual postable units

Environment variables required for X posting:
    X_API_KEY             — Consumer Key from console.x.com
    X_API_SECRET          — Secret Key (Consumer Secret) from console.x.com
    X_ACCESS_TOKEN        — Access Token from console.x.com
    X_ACCESS_TOKEN_SECRET — Access Token Secret from console.x.com
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

import tweepy

from config import OUTPUT_DIR

log = logging.getLogger(__name__)

APPROVAL_FILE = os.path.join(OUTPUT_DIR, "pending_approval.json")
QUEUE_FILE = os.path.join(OUTPUT_DIR, "posting_queue.json")


# ── Queue storage ─────────────────────────────────────────────────────────────


def _load_queue() -> list:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_queue(queue: list) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)


def save_to_queue(items: list[dict], week: int) -> int:
    """
    Save tweet items to the posting queue.
    Each item: {"type": "standalone"|"thread", "text": str} or {"type": "thread", "tweets": [str]}
    Returns total items queued.
    """
    queue = _load_queue()
    for item in items:
        entry = {
            "id": str(uuid.uuid4()),
            "week": week,
            "type": item.get("type", "standalone"),
            "status": "pending",
            "queued_at": datetime.now().isoformat(),
            "posted_at": None,
            "tweet_id": None,
        }
        if item["type"] == "thread":
            entry["tweets"] = item["tweets"]
        else:
            entry["text"] = item["text"]
        queue.append(entry)
    _save_queue(queue)
    return len(items)


def post_next_from_queue() -> dict:
    """
    Post the next pending item from the queue.
    Called by n8n at scheduled times (8am, 10:30am, 1pm, 3:30pm, 6pm EST Mon–Fri).
    """
    client = _get_x_client()
    if not client:
        return {"success": False, "error": "X API credentials not configured", "remaining": 0}

    queue = _load_queue()
    pending = [t for t in queue if t["status"] == "pending"]
    if not pending:
        return {"success": False, "empty": True, "message": "Queue is empty", "remaining": 0}

    item = pending[0]

    if item["type"] == "thread":
        results = _post_thread(client, item["tweets"])
        success = all(r.get("success") for r in results)
        for q in queue:
            if q["id"] == item["id"]:
                q["status"] = "posted" if success else "failed"
                q["posted_at"] = datetime.now().isoformat()
        _save_queue(queue)
        remaining = len([t for t in queue if t["status"] == "pending"])
        return {"success": success, "type": "thread", "tweets_posted": len(results), "remaining": remaining}
    else:
        result = _post_tweet(client, item["text"])
        for q in queue:
            if q["id"] == item["id"]:
                q["status"] = "posted" if result["success"] else "failed"
                q["posted_at"] = datetime.now().isoformat()
                if result.get("tweet_id"):
                    q["tweet_id"] = result["tweet_id"]
        _save_queue(queue)
        remaining = len([t for t in queue if t["status"] == "pending"])
        return {**result, "type": "standalone", "remaining": remaining}


def get_queue_status() -> dict:
    """Return current queue status."""
    queue = _load_queue()
    pending = [t for t in queue if t["status"] == "pending"]
    posted = [t for t in queue if t["status"] == "posted"]
    return {
        "total": len(queue),
        "pending": len(pending),
        "posted": len(posted),
        "next_up": pending[0].get("text", "thread")[:80] if pending else None,
    }


# ── Storage ───────────────────────────────────────────────────────────────────


def _load() -> dict:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(APPROVAL_FILE):
        return {}
    with open(APPROVAL_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(APPROVAL_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Token management ──────────────────────────────────────────────────────────


def create_approval(week: int, batch_path: str, sop_path: str, tweet_content: str) -> str:
    """Create a pending approval entry and return the unique token."""
    token = str(uuid.uuid4())
    approvals = _load()
    approvals[token] = {
        "token": token,
        "week": week,
        "created": datetime.now().isoformat(),
        "batch_path": batch_path,
        "sop_path": sop_path,
        "tweet_content": tweet_content,
        "approved": False,
        "approved_at": None,
        "schedule_results": [],
    }
    _save(approvals)
    log.info(f"Approval token created: {token[:8]}...")
    return token


def get_pending(token: str) -> Optional[dict]:
    """Retrieve pending approval entry by token. Returns None if not found."""
    return _load().get(token)


def mark_approved(token: str, results: list) -> None:
    """Mark a token as approved and store scheduling results."""
    approvals = _load()
    if token in approvals:
        approvals[token]["approved"] = True
        approvals[token]["approved_at"] = datetime.now().isoformat()
        approvals[token]["schedule_results"] = results
        _save(approvals)


# ── Tweet parsing ─────────────────────────────────────────────────────────────


def parse_tweets_from_batch(content: str) -> dict:
    """
    Parse the generated tweet batch markdown into structured posts.

    Returns:
        {
          "standalone": ["tweet text", ...],   # up to 7
          "thread_1": ["tweet 1", ...],         # build-in-public, 7 tweets
          "thread_2": ["tweet 1", ...],         # framework, 7 tweets
        }
    """
    result = {"standalone": [], "thread_1": [], "thread_2": []}

    # Split into sections by looking for STANDALONE / THREAD markers
    standalone_section = ""
    thread1_section = ""
    thread2_section = ""

    # Try to split by known section headers
    lower = content.lower()
    t1_markers = ["thread 1", "thread 2"]

    # Find thread boundaries
    idx_t1 = -1
    idx_t2 = -1
    for marker in ["thread 1 —", "thread 1—", "thread 1:", "thread 1\n", "## thread 1"]:
        idx = lower.find(marker)
        if idx != -1:
            idx_t1 = idx
            break
    for marker in ["thread 2 —", "thread 2—", "thread 2:", "thread 2\n", "## thread 2"]:
        idx = lower.find(marker)
        if idx != -1:
            idx_t2 = idx
            break

    if idx_t1 > 0:
        standalone_section = content[:idx_t1]
    else:
        standalone_section = content

    if idx_t1 > 0 and idx_t2 > idx_t1:
        thread1_section = content[idx_t1:idx_t2]
        thread2_section = content[idx_t2:]
    elif idx_t1 > 0:
        thread1_section = content[idx_t1:]

    # Extract standalone tweets (labelled STANDALONE N or TWEET N)
    result["standalone"] = _extract_standalone_tweets(standalone_section, limit=7)

    # Extract thread tweets
    result["thread_1"] = _extract_numbered_tweets(thread1_section, limit=7)
    result["thread_2"] = _extract_numbered_tweets(thread2_section, limit=7)

    return result


def _extract_standalone_tweets(section: str, limit: int = 7) -> list[str]:
    """Pull tweet bodies from standalone section using STANDALONE N or TWEET N labels."""
    # Try STANDALONE N first (e.g. **STANDALONE 1**)
    pattern = re.compile(r"\*{0,2}STANDALONE\s+\d+\*{0,2}\s*\n(.*?)(?=\*{0,2}STANDALONE\s+\d+|##|$)", re.IGNORECASE | re.DOTALL)
    matches = pattern.findall(section)
    if not matches:
        # Fall back to TWEET N labels
        return _extract_numbered_tweets(section, limit)
    tweets = []
    for m in matches[:limit]:
        text = m.strip()
        text = re.sub(r"^[-•*]\s+", "", text, flags=re.MULTILINE)
        text = text.strip()
        if len(text) > 10:
            tweets.append(text)
    return tweets


def _extract_numbered_tweets(section: str, limit: int = 7) -> list[str]:
    """Pull tweet bodies from a section using TWEET N labels."""
    pattern = re.compile(r"\*{0,2}TWEET\s+\d+\*{0,2}\s*\n?(.*?)(?=\*{0,2}TWEET\s+\d+\*{0,2}|##|$)", re.IGNORECASE | re.DOTALL)
    matches = pattern.findall(section)
    tweets = []
    for m in matches[:limit]:
        text = m.strip()
        text = re.sub(r"^[-•*]\s+", "", text, flags=re.MULTILINE)
        text = text.strip()
        if len(text) > 10:
            tweets.append(text)
    return tweets


# ── X API posting ─────────────────────────────────────────────────────────────


def _get_x_client() -> Optional[tweepy.Client]:
    """Build and return an authenticated Tweepy client, or None if credentials missing."""
    api_key = os.environ.get("X_API_KEY", "")
    api_secret = os.environ.get("X_API_SECRET", "")
    access_token = os.environ.get("X_ACCESS_TOKEN", "")
    access_token_secret = os.environ.get("X_ACCESS_TOKEN_SECRET", "")

    if not all([api_key, api_secret, access_token, access_token_secret]):
        log.error("X API credentials not set. Need: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET")
        return None

    return tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_token_secret,
    )


def schedule_to_buffer(pending: dict) -> list[dict]:
    """
    Save approved tweet batch to the posting queue.
    n8n will drip-post Mon–Fri at 8am, 10:30am, 1pm, 3:30pm, 6pm EST.
    Threads are queued as groups and posted as reply chains when their slot comes.
    """
    content = pending.get("tweet_content", "")
    week = pending.get("week", 1)
    parsed = parse_tweets_from_batch(content)

    items = []
    for text in parsed["standalone"]:
        items.append({"type": "standalone", "text": text})
    if parsed["thread_1"]:
        items.append({"type": "thread", "tweets": parsed["thread_1"]})
    if parsed["thread_2"]:
        items.append({"type": "thread", "tweets": parsed["thread_2"]})

    count = save_to_queue(items, week)
    log.info(f"Queued {count} items for Week {week}. Bot will post Mon–Fri 8am–6pm EST.")

    results = []
    for item in items:
        if item["type"] == "thread":
            results.append({"success": True, "tweet": f"Thread ({len(item['tweets'])} tweets)", "status": "queued"})
        else:
            results.append({"success": True, "tweet": item["text"][:60], "status": "queued"})
    return results


def _post_tweet(client: tweepy.Client, text: str, reply_to_id: Optional[str] = None) -> dict:
    """Post a single tweet. Optionally as a reply."""
    try:
        kwargs = {"text": text}  # X Premium — no character limit
        if reply_to_id:
            kwargs["in_reply_to_tweet_id"] = reply_to_id
        response = client.create_tweet(**kwargs)
        tweet_id = response.data["id"]
        return {
            "success": True,
            "tweet": text[:60],
            "tweet_id": tweet_id,
            "posted_at": datetime.now().strftime("%a %b %d at %I:%M %p"),
        }
    except Exception as e:
        return {"success": False, "tweet": text[:60], "error": str(e)}


def _post_thread(client: tweepy.Client, tweets: list[str]) -> list[dict]:
    """Post a list of tweets as a reply chain (thread)."""
    results = []
    last_id = None
    for i, tweet_text in enumerate(tweets):
        result = _post_tweet(client, tweet_text, reply_to_id=last_id)
        result["thread_position"] = i + 1
        if result.get("success"):
            last_id = result["tweet_id"]
        results.append(result)
    return results


def _next_week_slots(start_hour: int = 9) -> list[datetime]:
    """Return Mon–Fri datetimes for next calendar week at start_hour."""
    today = datetime.now()
    days_to_monday = (7 - today.weekday()) % 7
    if days_to_monday == 0:
        days_to_monday = 7
    next_monday = today + timedelta(days=days_to_monday)
    return [
        next_monday.replace(hour=start_hour, minute=0, second=0, microsecond=0) + timedelta(days=i)
        for i in range(5)
    ]


def _next_weekday(weekday: int, hour: int = 9) -> datetime:
    """Return next occurrence of a weekday (0=Mon, 4=Fri) at given hour."""
    today = datetime.now()
    days_ahead = weekday - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    target = today + timedelta(days=days_ahead)
    return target.replace(hour=hour, minute=0, second=0, microsecond=0)


# ── Email HTML builder ────────────────────────────────────────────────────────


def build_approval_email(pending: dict, approval_url: str) -> tuple[str, str]:
    """
    Build the approval email subject and HTML body.

    Returns (subject, html_body)
    """
    week = pending["week"]
    content = pending.get("tweet_content", "")
    parsed = parse_tweets_from_batch(content)

    subject = f"[X Bot] Week {week} content ready — tap to approve and schedule"

    tweet_rows = ""
    for i, tweet in enumerate(parsed["standalone"][:5], 1):
        day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"][i - 1]
        preview = tweet[:200].replace("\n", "<br>")
        tweet_rows += f"""
        <tr>
            <td style="padding:12px;border-bottom:1px solid #eee;color:#888;width:80px;vertical-align:top">{day}</td>
            <td style="padding:12px;border-bottom:1px solid #eee;font-size:14px;line-height:1.5">{preview}</td>
        </tr>"""

    thread_preview = ""
    if parsed["thread_1"]:
        first = parsed["thread_1"][0][:160].replace("\n", "<br>")
        thread_preview = f"""
        <h3 style="color:#333;margin-top:24px">Thread 1 — Build in Public (Wed 10 AM)</h3>
        <p style="color:#555;font-size:14px;background:#f9f9f9;padding:12px;border-radius:6px">{first}...</p>
        <p style="color:#888;font-size:13px">+ {len(parsed['thread_1']) - 1} more tweets in thread</p>
        """

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:640px;margin:0 auto;padding:20px;color:#333">

<div style="border-left:4px solid #1DA1F2;padding-left:16px;margin-bottom:24px">
    <h2 style="margin:0;color:#1DA1F2">Week {week} Content Ready</h2>
    <p style="margin:4px 0 0;color:#888">Generated by X Account Bot · {datetime.now().strftime('%B %d, %Y')}</p>
</div>

<p>Your weekly content batch is ready. Review the tweets below, then click <strong>Approve & Schedule</strong> to post them automatically via Buffer.</p>

<h3 style="color:#333">Standalone Tweets (Mon–Fri, 9 AM)</h3>
<table style="width:100%;border-collapse:collapse;background:#fff;border:1px solid #eee;border-radius:8px;overflow:hidden">
    {tweet_rows}
</table>

{thread_preview}

<div style="text-align:center;margin:32px 0">
    <a href="{approval_url}"
       style="display:inline-block;background:#1DA1F2;color:white;padding:16px 32px;border-radius:8px;text-decoration:none;font-size:16px;font-weight:bold">
        Approve &amp; Schedule All Tweets →
    </a>
</div>

<p style="color:#888;font-size:13px">
    This will schedule 5 standalone tweets (Mon–Fri) + 2 threads (Wed &amp; Fri) to Buffer.<br>
    Buffer will post them automatically at the scheduled times.
</p>

<hr style="border:none;border-top:1px solid #eee;margin:24px 0">
<p style="color:#aaa;font-size:12px">
    X Account Bot · Week {week} · Token: {pending['token'][:8]}...
</p>

</body>
</html>"""

    return subject, html
