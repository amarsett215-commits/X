# Automation Setup Guide
## Full pipeline: Research → Generate → Email approval → Auto-post to X

---

## How it works

```
Every Monday 6 AM
       │
       ▼
  n8n triggers
       │
       ▼
  FastAPI bot (api.py)
  ├── Scrapes viral tweets from your niche
  ├── Sends to Claude for deep analysis
  └── Generates 7 tweets + 2 threads
       │
       ▼
  Approval email sent to you
  ├── Shows tweet preview
  └── "Approve & Schedule" button
       │
       ▼ (you click the button)
  FastAPI calls Buffer API
  └── Schedules Mon–Fri at 9 AM
       │
       ▼
  Buffer posts to X automatically
```

---

## Budget breakdown

| Tool | Cost | What it does |
|---|---|---|
| n8n self-hosted | $0 | Cron scheduler + orchestrator |
| Buffer Essentials | $6/mo | Posts to X without X API |
| Server (optional) | $6/mo | DigitalOcean if you want 24/7 uptime |
| Claude API | ~$15–30/mo | Analysis + content generation |
| ngrok (local dev) | $0 | Exposes your Mac to the internet |
| **Total** | **~$30–50/mo** | |

---

## Step 1 — Get a Buffer account

1. Go to **buffer.com** → sign up for Essentials ($6/month)
2. Connect your X (Twitter) account
3. Go to **buffer.com/developers/apps** → Create app
4. Copy the **Access Token** shown on the app page → save it
5. Get your **Profile ID**:
   - Visit: `https://api.bufferapp.com/1/profiles.json?access_token=YOUR_TOKEN`
   - Find the `id` field next to your X profile
   - Copy it → save it

---

## Step 2 — Set up Gmail App Password

Gmail requires an App Password (not your login password) for SMTP access.

1. Go to **myaccount.google.com**
2. Security → 2-Step Verification (must be ON)
3. Security → App Passwords
4. Select app: **Mail** | Select device: **Mac**
5. Click Generate → copy the 16-character password

---

## Step 3 — Configure the bot

```bash
# In your X-bot folder
cp .env.example .env
```

Edit `.env` and fill in:
- `ANTHROPIC_API_KEY` — from console.anthropic.com
- `BUFFER_ACCESS_TOKEN` — from Step 1
- `BUFFER_PROFILE_ID` — from Step 1
- `EMAIL_FROM` — your Gmail
- `EMAIL_APP_PASSWORD` — from Step 2
- `EMAIL_TO` — where approval emails go (can be same)

---

## Step 4A — Run locally (recommended to start)

### Install dependencies

```bash
cd ~/Desktop/X-bot
source bot/venv/bin/activate
pip install -r bot/requirements.txt
```

### Load your .env variables

```bash
export $(cat .env | grep -v '#' | xargs)
```

### Start the bot API server

```bash
cd bot
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000/health** — you should see:
```json
{"status":"ok","api_key_set":true,"buffer_configured":true,"email_configured":true}
```

### Expose it publicly with ngrok (for email approval links to work)

```bash
# In a new terminal
brew install ngrok/ngrok/ngrok   # Mac
ngrok http 8000
```

Copy the `https://...ngrok.io` URL → update `.env`:
```
BOT_BASE_URL=https://abc123.ngrok.io
```

Then restart the uvicorn server.

---

## Step 4B — Run with Docker (for 24/7 uptime)

```bash
# Install Docker Desktop if you don't have it
# docker.com/products/docker-desktop

cd ~/Desktop/X-bot
docker compose up -d

# Check logs
docker compose logs -f bot
```

Access:
- Bot API: http://localhost:8000
- n8n: http://localhost:5678

---

## Step 5 — Install n8n

### Option A: npx (no install, quickest)

```bash
npx n8n
```

Opens at **http://localhost:5678**

### Option B: npm global install

```bash
npm install -g n8n
n8n start
```

### Option C: Docker (included in docker-compose.yml above)

Already running at http://localhost:5678 if you did Step 4B.

---

## Step 6 — Import the workflow into n8n

1. Open n8n at http://localhost:5678
2. Create an account (first time only)
3. Click **+** → **Import from file**
4. Select: `bot/n8n_workflow.json`
5. The workflow will appear with all nodes connected

---

## Step 7 — Configure n8n nodes

### Set environment variables in n8n

In n8n → Settings → Environment Variables, add:
```
BOT_BASE_URL = http://localhost:8000   (or your ngrok URL)
EMAIL_TO     = your@email.com
```

### Connect Gmail

1. Click the **Send Approval Email** node
2. Click "Create new credential" → Gmail OAuth2
3. Follow the OAuth flow to connect your Gmail account

---

## Step 8 — Test the full pipeline

### Manual test (skip the Monday wait)

```bash
# Test just the bot API
curl -X POST http://localhost:8000/run

# Check the response — you should get:
# {"status":"success","week":1,"approval_url":"https://...","email_sent":true}
```

Check your email — you should receive the approval email.

Click **Approve & Schedule** — Buffer should show scheduled tweets.

### Test n8n workflow

In n8n → open the workflow → click **Test workflow**

This runs it immediately without waiting for Monday.

---

## Step 9 — Activate the workflow

Once you're happy with the test:

1. In n8n → toggle the workflow **Active**
2. It will run automatically every Monday at 6 AM

---

## Step 10 — Log your tweet performance (weekly)

After your tweets have been live 24-48 hours, log the data:

```bash
cd ~/Desktop/X-bot
source bot/venv/bin/activate
python bot/main.py --log-tweet
python bot/main.py --log-growth 250
```

This feeds your real engagement data back into the bot's memory so Claude
gets smarter about what formats work for YOUR account specifically.

---

## Upgrade path: DigitalOcean server ($6/month)

When you want 24/7 uptime without keeping your Mac on:

1. Create a $6/month Ubuntu droplet at digitalocean.com
2. SSH in and install Docker + Docker Compose
3. Clone your repo: `git clone https://github.com/amarsett215-commits/X.git`
4. Create `.env` with your credentials
5. `docker compose up -d`
6. Update `BOT_BASE_URL` to your droplet's IP

The bot runs forever, no Mac required.

---

## Multi-account setup (future)

When you want to run this for clients:

1. Each account gets its own `.env` with their Buffer + Anthropic credentials
2. Deploy a separate Docker container per account (or parameterize the API)
3. Charge $97–$497/month per account for "done-for-you X growth"
4. The bot pays for itself after 1 client

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `api_key_set: false` | Run `export ANTHROPIC_API_KEY=...` or add to `.env` |
| `buffer_configured: false` | Check BUFFER_ACCESS_TOKEN + BUFFER_PROFILE_ID in `.env` |
| `email_configured: false` | Check EMAIL_FROM, EMAIL_APP_PASSWORD, EMAIL_TO |
| Approval link doesn't work | Check BOT_BASE_URL is publicly accessible (ngrok) |
| Buffer scheduling fails | Verify profile ID at the /profiles.json endpoint |
| n8n can't reach bot | Use `http://bot:8000` inside Docker, `http://localhost:8000` outside |

---

## Quick reference: all bot commands

```bash
# Run full pipeline manually
python bot/main.py

# Start the API server (for n8n integration)
uvicorn bot/api:app --host 0.0.0.0 --port 8000

# Check bot status
curl http://localhost:8000/status

# Memory report
python bot/main.py --memory

# Log tweet performance (after 24-48h)
python bot/main.py --log-tweet

# Log follower count
python bot/main.py --log-growth 350
```
