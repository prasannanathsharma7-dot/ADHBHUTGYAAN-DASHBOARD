# Adhbhutgyaan Astrology Intelligence Pipeline

Proprietary intelligence & lead-generation engine for
[adhbhutgyaan.com](https://adhbhutgyaan.com). Scrapes public YouTube
comments from astrology channels, classifies each one against a
50-node problem/grievance taxonomy using the Claude Batch API, stores
results in an isolated MongoDB database, and surfaces Top-50 Problems
/ Top-50 Vendor Complaints / high-intent leads in a locally-run
Next.js dashboard.

**This system runs 100% locally.** No cloud deployment, no scheduled
cloud jobs — you run the scraper, the enrichment pipeline, and the
dashboard on your own machine, on demand.

Full architecture and bottleneck analysis: [`ARCHITECTURE.md`](./ARCHITECTURE.md).
Taxonomy definitions: [`nlp/taxonomy.py`](./nlp/taxonomy.py).

## ⚠️ Database isolation — non-negotiable

This entire pipeline is hard-locked to a MongoDB database named
`astrology_intelligence`. It must **never** touch `astrokashi` (production, formerly referenced here as `adhbhutgyaan_prod`)
(the live production website database). This is enforced in code via
`mongo/db_guard.py`, which every script imports — if you extend this
pipeline, route any new MongoDB connection through `get_isolated_db()`
rather than instantiating `MongoClient` directly. See that file for
the exact guard logic.

## Structure

```
nlp/taxonomy.py                    The 50-node taxonomy — single source of truth
nlp/batch_pipeline.py              Claude Batch API enrichment
scraper/youtube_worker.py          Celery-based scraper (real video/channel metadata, no API key)
scripts/run_local_pipeline.py      Simple sequential local runner (scrape -> enrich)
mongo/db_guard.py                  Hard-enforced database isolation
mongo/schema_and_aggregations.md   Schema, indexes, aggregation pipelines
dashboard/                         Next.js dashboard (App Router)
```

## Setup

### 1. Environment variables

```bash
cp .env.example .env
# then edit .env — set MONGODB_URI and ANTHROPIC_API_KEY

cp dashboard/.env.local.example dashboard/.env.local
# then edit dashboard/.env.local — set MONGODB_URI
```

Both `.env` and `dashboard/.env.local` are already in `.gitignore` —
never commit real credentials.

### 2. Python dependencies

```bash
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium  # only needed for Cloudflare-protected portal scraping
```

### 3. Redis (only needed for the full-scale Celery run — see below)

```bash
# macOS
brew install redis && brew services start redis
# Linux
sudo apt install redis-server && sudo systemctl start redis
```

### 4. Dashboard dependencies

```bash
cd dashboard
npm install
```

## Running it

### Easiest: double-click .bat files (no PowerShell typing needed)

Once `.env` is set up (step 1 above) and dependencies are installed
(step 2), you can skip PowerShell entirely:

- **`run_scrape_test.bat`** — double-click to scrape only (no Claude API
  cost). Good for testing that video IDs/DB connection work.
- **`run_full_pipeline.bat`** — double-click to scrape + run Claude Batch
  enrichment. This calls the Anthropic API and costs money.

A console window opens, runs the script, and stays open (`pause`) so you
can read the output before it closes.

### Quick local run (small/incremental scraping + enrichment)

```bash
# add video IDs to scraper/video_ids.txt first, one per line:
#   video_id,channel_id

python scripts/run_local_pipeline.py
```

This scrapes the listed videos and runs Claude Batch enrichment on
whatever is un-enriched, all in one process — no Redis required.

### Full-scale run (the real 1M-comment bulk load)

For the initial large bulk scrape, run actual Celery workers so you
get real concurrency, retries, and resumability:

```bash
# terminal 1 — start a worker
celery -A scraper.youtube_worker worker --loglevel=info --concurrency=4

# terminal 2 — enqueue videos (edit the video list in the __main__ block
# of scraper/youtube_worker.py, or call enqueue_channel() from a script)
python -c "from scraper.youtube_worker import enqueue_channel; enqueue_channel(['VIDEO_ID_1','VIDEO_ID_2'], channel_id='UC...')"
```

Then run enrichment separately once scraping has produced a healthy
backlog:

```bash
python nlp/batch_pipeline.py
```

See `ARCHITECTURE.md` for proxy-pool and rate-limiting guidance — at
real scale (1M comments) this is the actual bottleneck, not Claude or MongoDB.

### Dashboard

```bash
cd dashboard
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Free enrichment option (no Anthropic API cost)

`nlp/local_enrich_ollama.py` classifies comments using a local open-source
model via [Ollama](https://ollama.com) instead of Claude — zero API spend,
runs on your own GPU. Trade-off: slower (a few comments/second on a laptop
GPU) and less accurate, especially on `is_crisis_flag` — treat its output
as a rough pass, not a substitute for `nlp/batch_pipeline.py` (Claude) at
real scale or on anything safety-sensitive.

```
# one-time setup
# 1. install Ollama: https://ollama.com/download
# 2. ollama pull qwen2.5:7b-instruct

python nlp\local_enrich_ollama.py --limit 20000
```

Good for a large *free* first pass on a big backlog; switch to the Claude
batch pipeline for the comments that matter most (high-urgency, crisis-
adjacent, or anything informing a real business decision).

## Ethics note: the crisis flag

The taxonomy includes `SUICIDAL_DESPERATION_END_STAGE` and an
`is_crisis_flag` boolean specifically so these comments can be routed
*away* from the sales pipeline, not into it. The dashboard's API route
and `CrisisQueue` component keep this as a separate, human-review-only
view — it is deliberately excluded from `high_intent_leads`. If you
extend the dashboard, keep that separation. Real people in genuine
crisis showing up in your YouTube comments deserve a human response,
not a puja upsell.
