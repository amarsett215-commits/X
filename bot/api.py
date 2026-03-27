"""
FastAPI server — HTTP interface for the X Account Bot.

n8n calls this server to trigger the pipeline and send approval emails.
The approval link in emails points back here.

START:
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

ENVIRONMENT VARIABLES:
    ANTHROPIC_API_KEY       — required for Claude analysis
    BUFFER_ACCESS_TOKEN     — required for auto-posting to X via Buffer
    BUFFER_PROFILE_ID       — your X profile ID in Buffer
    BOT_BASE_URL            — public URL of this server (for approval links)
                              e.g. https://abc123.ngrok.io  OR  https://yourdomain.com
    EMAIL_FROM              — Gmail address to send from
    EMAIL_APP_PASSWORD      — Gmail app password (not your login password)
    EMAIL_TO                — your email address (where approval emails are sent)
"""

import json
import logging
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from glob import glob
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

sys.path.insert(0, os.path.dirname(__file__))

from memory import log_business_update, get_business_log
from approval import (
    build_approval_email,
    create_approval,
    get_pending,
    mark_approved,
    schedule_to_buffer,
    post_next_from_queue,
    get_queue_status,
)
from config import OUTPUT_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(
    title="X Account Bot API",
    description="HTTP interface for the X content automation pipeline.",
    version="1.0.0",
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _detect_week() -> int:
    existing = glob(os.path.join(OUTPUT_DIR, "week_*_sop_*.md"))
    if not existing:
        return 1
    weeks = []
    for f in existing:
        try:
            weeks.append(int(os.path.basename(f).split("_")[1]))
        except (IndexError, ValueError):
            continue
    return (max(weeks) + 1) if weeks else 1


def _save_raw_tweets(tweets: list, week: int) -> str:
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(OUTPUT_DIR, f"week_{week:02d}_tweets_raw_{date_str}.json")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tweets, f, indent=2, ensure_ascii=False)
    return path


def _send_approval_email(subject: str, html_body: str) -> bool:
    email_from = os.environ.get("EMAIL_FROM", "")
    email_password = os.environ.get("EMAIL_APP_PASSWORD", "")
    email_to = os.environ.get("EMAIL_TO", "")

    if not all([email_from, email_password, email_to]):
        log.warning("Email credentials not set — skipping email send.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = email_from
        msg["To"] = email_to
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_from, email_password)
            server.sendmail(email_from, email_to, msg.as_string())

        log.info(f"Approval email sent to {email_to}")
        return True
    except Exception as e:
        log.error(f"Failed to send email: {e}")
        return False


# ── Routes ────────────────────────────────────────────────────────────────────


@app.post("/update")
def add_business_update(text: str = Query(..., description="Your real business update")):
    """
    Log a daily business update. The bot injects these into Claude prompts
    so generated tweets reference your actual products, numbers, and progress.

    Example:
        curl -X POST "http://localhost:8000/update?text=Just+went+live+with+a+%2419+product.+No+sales+yet."
    """
    week = _detect_week()
    log_business_update(text=text, week=week)
    recent = get_business_log(last_n=5)
    return {
        "status": "logged",
        "entry": text,
        "recent_updates": [e["text"] for e in recent],
    }


@app.get("/updates")
def list_business_updates():
    """Return your last 20 logged business updates."""
    entries = get_business_log(last_n=20)
    return {"updates": entries, "count": len(entries)}


@app.get("/health")
def health():
    """Health check — n8n uses this to verify the bot is running."""
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "x_configured": bool(
            os.environ.get("X_API_KEY") and os.environ.get("X_ACCESS_TOKEN")
        ),
        "email_configured": bool(
            os.environ.get("EMAIL_FROM") and os.environ.get("EMAIL_TO")
        ),
    }


@app.post("/run")
def run_pipeline(week: Optional[int] = Query(default=None)):
    """
    Run the full pipeline: scrape → analyze → generate SOP + tweet batch.

    Called by n8n every Monday. Sends approval email automatically if email
    credentials are configured.

    Returns the approval token and tweet preview for n8n to use.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    # Import here to avoid loading heavy modules at startup
    from scraper import collect_tweets
    from analyzer import analyze_tweets
    from sop_generator import generate_weekly_sop

    current_week = week or _detect_week()
    log.info(f"Starting pipeline for Week {current_week}...")

    # Step 1 — Scrape
    tweets = collect_tweets()
    if not tweets:
        raise HTTPException(status_code=500, detail="No tweets collected. Check Nitter availability.")
    _save_raw_tweets(tweets, current_week)
    log.info(f"Collected {len(tweets)} tweets.")

    # Step 2 — Analyze
    analysis = analyze_tweets(tweets, week=current_week)
    log.info("Analysis complete.")

    # Step 3 — Generate SOP + batch
    sop_path, batch_path = generate_weekly_sop(analysis, current_week)
    log.info(f"SOP: {sop_path} | Batch: {batch_path}")

    # Read generated content
    with open(batch_path, encoding="utf-8") as f:
        batch_content = f.read()

    # Create approval token
    token = create_approval(
        week=current_week,
        batch_path=batch_path,
        sop_path=sop_path,
        tweet_content=batch_content,
    )

    # Build approval URL
    base_url = os.environ.get("BOT_BASE_URL", "http://localhost:8000").rstrip("/")
    approval_url = f"{base_url}/approve/{token}"

    # Send approval email automatically
    subject, html_body = build_approval_email(
        {"week": current_week, "tweet_content": batch_content, "token": token},
        approval_url,
    )
    email_sent = _send_approval_email(subject, html_body)

    return {
        "status": "success",
        "week": current_week,
        "tweets_collected": len(tweets),
        "sop_path": sop_path,
        "batch_path": batch_path,
        "approval_token": token,
        "approval_url": approval_url,
        "email_sent": email_sent,
        "tweet_preview": batch_content[:1500],
    }


@app.get("/approve/{token}", response_class=HTMLResponse)
def approve_and_schedule(token: str):
    """
    Approval endpoint — user clicks this link in their email.

    Validates the token, calls Buffer API to schedule all tweets,
    and shows a confirmation page.
    """
    pending = get_pending(token)

    if not pending:
        return HTMLResponse(
            _page("Invalid Link", "<p>This approval link is invalid or has expired.</p>"),
            status_code=404,
        )

    if pending.get("approved"):
        approved_at = pending.get("approved_at", "")[:10]
        return HTMLResponse(
            _page("Already Approved", f"<p>This batch was already approved on {approved_at}.</p>")
        )

    # Save to posting queue (n8n drip-posts Mon–Fri 8am–6pm EST)
    log.info(f"Approving token {token[:8]}... — saving to posting queue")
    results = schedule_to_buffer(pending)
    mark_approved(token, results)

    from approval import get_queue_status
    q = get_queue_status()
    success_count = sum(1 for r in results if r.get("success"))

    rows = ""
    for r in results:
        label = r.get("tweet", "")
        status = r.get("status", "queued")
        rows += f"""
        <tr>
            <td style="padding:12px;border-bottom:1px solid #eee;color:#2e7d32;width:30px;text-align:center">✓</td>
            <td style="padding:12px;border-bottom:1px solid #eee;font-size:14px;line-height:1.5">{label}</td>
            <td style="padding:12px;border-bottom:1px solid #eee;font-size:13px;color:#888">{status}</td>
        </tr>"""

    body = f"""
        <div style="border-left:4px solid #2e7d32;padding-left:16px;margin-bottom:24px">
            <h2 style="margin:0;color:#2e7d32">Week {pending['week']} Queued</h2>
            <p style="margin:4px 0 0;color:#888">{q['pending']} tweets ready · will post Mon–Fri 8am–6pm EST · {datetime.now().strftime('%B %d, %Y')}</p>
        </div>
        <p style="color:#555;font-size:14px">Tweets are in the queue. n8n will post them automatically at scheduled times. You don't need to do anything else.</p>
        <table style="width:100%;border-collapse:collapse;font-size:14px;margin-top:16px">
            <thead>
                <tr style="background:#f5f5f5">
                    <th style="padding:10px;text-align:left"></th>
                    <th style="padding:10px;text-align:left">Content</th>
                    <th style="padding:10px;text-align:left">Status</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    """
    return HTMLResponse(_page("Queued for Posting", body))


@app.post("/post-next")
def post_next():
    """
    Post the next tweet from the queue.
    Called by n8n at scheduled times: Mon–Fri at 8am, 10:30am, 1pm, 3:30pm, 6pm EST.
    """
    result = post_next_from_queue()
    return result


@app.get("/queue")
def queue_status():
    """Check current posting queue status."""
    return get_queue_status()


@app.get("/weekly-summary")
def weekly_summary(send_email: bool = Query(default=True)):
    """
    Generate and optionally email a detailed weekly performance summary.
    Call this Sunday evening or whenever you want a debrief.
    n8n triggers this automatically every Sunday at 7pm EST.
    """
    import anthropic as anth
    from memory import get_memory_context, get_business_log

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    from config import MODEL, YOUR_NICHE
    memory_ctx = get_memory_context(week=99)  # Get all history
    business_log = get_business_log(last_n=20)
    business_text = "\n".join([f"[{e.get('date','?')}] {e['text']}" for e in business_log]) if business_log else "No updates logged yet."

    prompt = f"""You are a strategic advisor for an X (Twitter) account in this niche: {YOUR_NICHE}

The account owner is in the early stages (< 10 followers, just starting out).

MEMORY & PERFORMANCE DATA:
{memory_ctx}

BUSINESS LOG FROM THIS WEEK:
{business_text}

Generate a detailed, honest weekly summary email. Include:

1. **What Worked This Week** — specific formats, hooks, or angles that performed
2. **What Didn't Work** — honest assessment of what flopped and why
3. **Your Build-in-Public Score** — how authentic and raw was the content this week (1-10)
4. **Growth Analysis** — follower movement, engagement patterns, what's attracting people
5. **Top Insight** — the single most important thing learned this week
6. **Next Week's Strategy** — 3 specific, actionable changes to make
7. **Content Angles to Avoid** — what's oversaturated or not working in the niche right now
8. **The One Tweet to Write** — give them one specific tweet to write this weekend as a momentum builder

Be direct. No fluff. If they had a bad week, say so clearly and explain why.
Write like a smart advisor who genuinely wants them to grow, not a cheerleader."""

    client_ai = anth.Anthropic()
    summary_text = ""
    with client_ai.messages.stream(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for event in stream:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                summary_text += event.delta.text

    email_sent = False
    if send_email:
        subject = f"[X Bot] Weekly Summary — {datetime.now().strftime('%B %d, %Y')}"
        html = f"""<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:700px;margin:0 auto;padding:20px;color:#333">
        <div style="border-left:4px solid #1DA1F2;padding-left:16px;margin-bottom:24px">
            <h2 style="margin:0;color:#1DA1F2">Weekly Summary</h2>
            <p style="margin:4px 0 0;color:#888">X Account Bot · {datetime.now().strftime('%B %d, %Y')}</p>
        </div>
        <div style="font-size:15px;line-height:1.7;white-space:pre-wrap">{summary_text}</div>
        <hr style="border:none;border-top:1px solid #eee;margin:32px 0">
        <p style="color:#aaa;font-size:12px">X Account Bot — Weekly Debrief</p>
        </body></html>"""
        email_sent = _send_approval_email(subject, html)

    return {"summary": summary_text, "email_sent": email_sent}


@app.get("/status")
def status():
    """Current bot status — last run, pending approvals, memory summary."""
    sop_files = sorted(glob(os.path.join(OUTPUT_DIR, "week_*_sop_*.md")))
    last_run = None
    if sop_files:
        last_file = os.path.basename(sop_files[-1])
        parts = last_file.split("_")
        last_run = {"week": parts[1], "date": parts[3].replace(".md", "")}

    pending_file = os.path.join(OUTPUT_DIR, "pending_approval.json")
    pending_count = 0
    pending_items = []
    if os.path.exists(pending_file):
        with open(pending_file) as f:
            data = json.load(f)
        pending_items = [
            {"week": v["week"], "created": v["created"][:10], "approved": v["approved"]}
            for v in data.values()
        ]
        pending_count = sum(1 for v in data.values() if not v["approved"])

    return {
        "last_run": last_run,
        "pending_approvals": pending_count,
        "history": pending_items[-5:],
        "x_configured": bool(
            os.environ.get("X_API_KEY") and os.environ.get("X_ACCESS_TOKEN")
        ),
    }


# ── HTML helper ───────────────────────────────────────────────────────────────


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{title} — X Account Bot</title>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:700px;margin:40px auto;padding:20px;color:#333">
    {body}
    <hr style="border:none;border-top:1px solid #eee;margin:32px 0">
    <p style="color:#aaa;font-size:12px">X Account Bot</p>
</body>
</html>"""
