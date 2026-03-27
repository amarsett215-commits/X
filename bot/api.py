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

from approval import (
    build_approval_email,
    create_approval,
    get_pending,
    mark_approved,
    schedule_to_buffer,
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

    # Schedule to Buffer
    log.info(f"Approving token {token[:8]}... — scheduling to Buffer")
    results = schedule_to_buffer(pending)
    mark_approved(token, results)

    success_count = sum(1 for r in results if r.get("success"))
    fail_count = len(results) - success_count

    rows = ""
    for r in results:
        status_icon = "✓" if r.get("success") else "✗"
        status_color = "#2e7d32" if r.get("success") else "#c62828"
        scheduled = r.get("scheduled_at", r.get("error", ""))
        thread_pos = f" (thread tweet {r['thread_position']})" if "thread_position" in r else ""
        rows += f"""
        <tr>
            <td style="padding:10px;border-bottom:1px solid #eee;color:{status_color};width:30px;text-align:center">{status_icon}</td>
            <td style="padding:10px;border-bottom:1px solid #eee;font-size:13px">{r.get('tweet', '')[:60]}{thread_pos}...</td>
            <td style="padding:10px;border-bottom:1px solid #eee;font-size:13px;color:#888">{scheduled}</td>
        </tr>"""

    buffer_note = ""
    if fail_count > 0:
        buffer_note = f"""<div style="background:#fff3e0;padding:12px;border-radius:6px;margin:16px 0;font-size:14px">
            {fail_count} tweet(s) failed to schedule. Check that BUFFER_ACCESS_TOKEN and BUFFER_PROFILE_ID are set correctly.
        </div>"""

    body = f"""
        <div style="border-left:4px solid #2e7d32;padding-left:16px;margin-bottom:24px">
            <h2 style="margin:0;color:#2e7d32">Week {pending['week']} Approved</h2>
            <p style="margin:4px 0 0;color:#888">{success_count} tweets scheduled to Buffer · {datetime.now().strftime('%B %d, %Y')}</p>
        </div>
        {buffer_note}
        <table style="width:100%;border-collapse:collapse;font-size:14px">
            <thead>
                <tr style="background:#f5f5f5">
                    <th style="padding:10px;text-align:left"></th>
                    <th style="padding:10px;text-align:left">Tweet</th>
                    <th style="padding:10px;text-align:left">Scheduled</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        <div style="text-align:center;margin:32px 0">
            <a href="https://buffer.com/app"
               style="display:inline-block;background:#1DA1F2;color:white;padding:12px 24px;border-radius:6px;text-decoration:none;font-size:14px">
                View in Buffer →
            </a>
        </div>
    """
    return HTMLResponse(_page("Approved & Scheduled", body))


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
