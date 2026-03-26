"""
Approval and scheduling layer.

Handles:
- Generating one-time approval tokens after a pipeline run
- Storing pending tweet batches
- Scheduling approved tweets to Buffer (no X API required)
- Parsing tweet batches into individual postable units

Environment variables required for Buffer posting:
    BUFFER_ACCESS_TOKEN   — from buffer.com/developers/apps
    BUFFER_PROFILE_ID     — your X profile ID in Buffer
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

import requests

from config import OUTPUT_DIR

log = logging.getLogger(__name__)

APPROVAL_FILE = os.path.join(OUTPUT_DIR, "pending_approval.json")
BUFFER_API_BASE = "https://api.bufferapp.com/1"


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

    # Extract standalone tweets (labelled TWEET 1, TWEET 2, etc.)
    result["standalone"] = _extract_numbered_tweets(standalone_section, limit=7)

    # Extract thread tweets
    result["thread_1"] = _extract_numbered_tweets(thread1_section, limit=7)
    result["thread_2"] = _extract_numbered_tweets(thread2_section, limit=7)

    return result


def _extract_numbered_tweets(section: str, limit: int = 7) -> list[str]:
    """Pull tweet bodies from a section using TWEET N labels."""
    pattern = re.compile(r"TWEET\s+\d+\s*[:\-—]?\s*\n?(.*?)(?=TWEET\s+\d+|$)", re.IGNORECASE | re.DOTALL)
    matches = pattern.findall(section)
    tweets = []
    for m in matches[:limit]:
        text = m.strip()
        # Remove markdown formatting artifacts
        text = re.sub(r"^[-•*]\s+", "", text, flags=re.MULTILINE)
        text = text.strip()
        if len(text) > 10:
            tweets.append(text)
    return tweets


# ── Buffer scheduling ─────────────────────────────────────────────────────────


def schedule_to_buffer(pending: dict) -> list[dict]:
    """
    Schedule the approved tweet batch to Buffer.

    Posts standalone tweets Mon–Fri at 9 AM in the next calendar week.
    Threads are posted as reply chains (Buffer supports this for threads).

    Returns a list of result dicts: [{success, tweet, scheduled_at, error?}]
    """
    access_token = os.environ.get("BUFFER_ACCESS_TOKEN", "")
    profile_id = os.environ.get("BUFFER_PROFILE_ID", "")

    if not access_token or not profile_id:
        log.error("BUFFER_ACCESS_TOKEN or BUFFER_PROFILE_ID not set.")
        return [{"success": False, "error": "Buffer credentials not configured. Set BUFFER_ACCESS_TOKEN and BUFFER_PROFILE_ID."}]

    content = pending.get("tweet_content", "")
    parsed = parse_tweets_from_batch(content)

    # Build Mon–Fri posting schedule for next week
    posting_slots = _next_week_slots(start_hour=9)

    results = []
    slot_index = 0

    # Schedule standalone tweets (Mon–Fri, one per day)
    for tweet_text in parsed["standalone"][:5]:
        if slot_index >= len(posting_slots):
            break
        result = _post_to_buffer(access_token, profile_id, tweet_text, posting_slots[slot_index])
        results.append(result)
        slot_index += 1

    # Schedule Thread 1 (build-in-public) on Wednesday at 10 AM
    if parsed["thread_1"]:
        thread_results = _post_thread_to_buffer(
            access_token, profile_id, parsed["thread_1"],
            base_time=_next_weekday(2, hour=10)  # Wednesday
        )
        results.extend(thread_results)

    # Schedule Thread 2 (framework) on Friday at 10 AM
    if parsed["thread_2"]:
        thread_results = _post_thread_to_buffer(
            access_token, profile_id, parsed["thread_2"],
            base_time=_next_weekday(4, hour=10)  # Friday
        )
        results.extend(thread_results)

    success_count = sum(1 for r in results if r.get("success"))
    log.info(f"Buffer scheduling complete: {success_count}/{len(results)} succeeded.")
    return results


def _post_to_buffer(access_token: str, profile_id: str, text: str, scheduled_at: datetime) -> dict:
    """Post a single tweet to Buffer."""
    try:
        resp = requests.post(
            f"{BUFFER_API_BASE}/updates/create.json",
            data={
                "access_token": access_token,
                "profile_ids[]": profile_id,
                "text": text[:280],
                "scheduled_at": scheduled_at.isoformat(),
                "now": "false",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return {
            "success": True,
            "tweet": text[:60],
            "scheduled_at": scheduled_at.strftime("%a %b %d at %I:%M %p"),
        }
    except requests.HTTPError as e:
        return {"success": False, "tweet": text[:60], "error": str(e), "response": resp.text[:200]}
    except Exception as e:
        return {"success": False, "tweet": text[:60], "error": str(e)}


def _post_thread_to_buffer(
    access_token: str, profile_id: str, tweets: list[str], base_time: datetime
) -> list[dict]:
    """Post a thread to Buffer. Each tweet is spaced 2 minutes apart."""
    results = []
    for i, tweet_text in enumerate(tweets):
        post_time = base_time + timedelta(minutes=i * 2)
        result = _post_to_buffer(access_token, profile_id, tweet_text, post_time)
        result["thread_position"] = i + 1
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
