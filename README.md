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
nlp/prefilter.py                   Free rule-based pass before enrichment (see below)
scripts/build_audit_sample.py      Samples classified comments for a human accuracy check
scripts/compute_audit_results.py   Scores the filled-in audit sample (see below)
scraper/discovery.py               Auto-finds outlier videos so video_ids.txt fills itself (see below)
scraper/transcripts.py             Fetches what videos actually said (yt-dlp captions)
nlp/gap_analysis.py                Measures whether a comment's question was answered in the video
nlp/run_gap_analysis.py            Applies gap analysis across classified comments (see below)
scripts/run_everything.py          Full pipeline, one command, retries on failure (see below)
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
# populate scraper/video_ids.txt automatically -- see "Automated
# discovery" below instead of editing this file by hand:
python scraper/discovery.py

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

## Run everything automatically (no typing each step)

`run_everything.bat` — double-click to run all six steps in order
(discovery → scrape → prefilter → enrich → transcripts → gap
analysis), with automatic retry (3 attempts, growing delay) if any
step fails. A step that still fails doesn't stop the run — later
steps that can still make progress go ahead anyway.

Every run's full output is saved to `logs\run_TIMESTAMP.log`, so you
can check what happened even if you weren't watching.

By default it runs once and exits. To have it repeat on its own, edit
`run_everything.bat` and add `--repeat-every-hours 6` (or any number)
to the last python line — it will then sleep and run again forever,
until you close the window.

Enrichment auto-detects Claude vs. the free Ollama option based on
whether `ANTHROPIC_API_KEY` in `.env` looks like a real key or is
still the placeholder — force one explicitly with
`python scripts\run_everything.py --enrich-with ollama` (or `claude`,
or `skip`).

## Automated discovery (no manual video IDs)

`scraper/discovery.py` finds videos worth scraping on its own — you
never paste in a link or an ID.

```bash
python scraper/discovery.py --dry-run   # see what it would find, writes nothing
python scraper/discovery.py             # append discovered videos to video_ids.txt
```

Two sources, both against YouTube's own public pages via `yt-dlp`
(same category of tool as `youtube_comment_downloader`, already used
elsewhere in this repo):

- **Channel-based**: checks each seed channel's own recent videos
  against *that channel's own* median views/hour, and flags anything
  running well ahead of its own normal pace (default: 2.5x). A small
  channel's normal day and a big channel's normal day are never
  compared against each other.
- **Search-based**: runs the Hindi query clusters below and pulls
  matching results directly, above a minimum view floor.

Edit `SEED_CHANNELS` and `SEARCH_QUERIES` at the top of the file for
your niche — the handles there are a starting point, not verified;
the script tells you if a handle resolves to zero videos.

```python
SEED_CHANNELS = ["AstroArunPandit", "DrJaiMadaan", "GrahonKaKhel", ...]
SEARCH_QUERIES = ["कुंडली दोष निवारण", "शनि साढ़ेसाती असली उपाय", ...]
```

`tests/test_discovery.py` covers the outlier math itself (what counts
as an outlier, age cutoffs, the minimum-views floor) with synthetic
data — the only part of this script that doesn't need a live YouTube
connection to test.

## Measuring what the video actually left unanswered

Until now "unanswered question" was an assumption. This measures it:
pull the video's own transcript, then check whether the terms in a
viewer's question were actually spoken about.

```bash
python scraper/transcripts.py       # fetch captions for videos that have comments
python nlp/run_gap_analysis.py --dry-run   # see the status breakdown, writes nothing
python nlp/run_gap_analysis.py      # store a `gap` field on each comment
```

This adds a `gap` subdocument per comment (`status`, `coverage`,
`matched_terms`, `missing_terms`) — it never modifies `analysis` and
never deletes anything.

**Three things worth understanding before using the numbers:**

- **It's keyword coverage, not comprehension.** It answers "were these
  concepts spoken about", not "was this person's question answered
  well". `likely_unanswered` is a lead to look at, not a verdict.
- **No transcript ⇒ `unknown`, never `unanswered`.** Missing data is
  not evidence of a gap. Exclude `unknown` from any gap percentage you
  report, or you're counting silence as a finding. Many Hindi astrology
  videos have only auto-generated captions, which are noisy; some have
  none at all.
- **Cross-script matching is what makes it work.** Comments are usually
  Hinglish ("shani sade sati") while transcripts are Devanagari ("शनि
  साढ़ेसाती"). `TERM_ALIASES` in `nlp/gap_analysis.py` maps the domain
  vocabulary across both. Without it every comment would look
  unanswered. When you notice a term being missed, add it there — the
  script warns you if too many comments are falling back to plain word
  overlap.

**Crisis comments are excluded entirely** (`is_crisis_flag = True` are
skipped, never scored). Someone in real distress is not a content gap
to mine for a video hook — they belong in the existing human-review
CrisisQueue and nowhere else.

## Free enrichment option (no Anthropic API cost)

`nlp/local_enrich_ollama.py` classifies comments using a small local
model via [Ollama](https://ollama.com) instead of Claude — zero API
spend, runs on your own GPU, uses a compact output format and a few
concurrent requests so it's fast enough for large free runs. Trade-off:
less accurate than Claude, especially on `is_crisis_flag` — treat its
output as a rough pass, not a substitute for `nlp/batch_pipeline.py`
(Claude) on anything safety-sensitive or high-stakes.

```
# one-time setup
# 1. install Ollama: https://ollama.com/download
# 2. ollama pull qwen2.5:3b-instruct

# ALWAYS test throughput on a small slice first — the script prints
# your measured rate and the real ETA for 1M comments at that rate:
python nlp\local_enrich_ollama.py --limit 500

# then the real run, sized to what you measured:
python nlp\local_enrich_ollama.py --workers 4
```

It's fully resumable — if the laptop sleeps, restarts, or you stop the
script, re-running the same command picks up exactly where it left off.
For a multi-day unattended run on Windows, turn off sleep while plugged
in (Settings > System > Power & battery > Screen and sleep) and leave it
plugged in.

## Optional: rule-based pre-filter (saves Claude/Ollama cost on obvious junk)

`nlp/prefilter.py` runs before either enrichment script and marks purely
devotional/greeting/emoji-only comments (e.g. "Jai Shri Ram 🙏" with
nothing else) as low-signal, using the exact same fallback shape
`nlp/batch_pipeline.py` already uses for junk — for free, instantly.
Both enrichment scripts query `{"analysis": None}`, so anything this
marks is automatically skipped by both; no changes to either script.

```bash
python nlp/prefilter.py --dry-run   # see counts first, writes nothing
python nlp/prefilter.py             # apply
```

**It is deliberately conservative on purpose.** It only skips content
that is *purely* devotional/greeting/emoji — never based on length or
on whether an astrology keyword is present — because a keyword list
can never fully enumerate every way someone might express real
distress, and this pipeline's crisis handling (below) only runs inside
the real classifiers. See the safety note at the top of the file
before changing what counts as skippable, and run
`tests/test_prefilter.py` (`pytest tests/`) after any change — it
includes the crisis-phrasing cases that must never be skipped.

## Checking classifier accuracy (do this before trusting the numbers)

ARCHITECTURE.md already flags this: "Sample-audit ~200 classified
comments by hand early on and adjust the prompt — don't trust the
first pass blindly, this number directly drives your business
decisions." These two scripts do that:

```bash
python scripts/build_audit_sample.py --out audit_sample.csv --n 200
# open audit_sample.csv in Excel/Sheets, fill in every human_* column
# for every row (including ones you agree with -- blanks are treated
# as "not reviewed", never as a match)
python scripts/compute_audit_results.py --in audit_sample.csv
```

`human_agrees_crisis_flag` needs its own pass over a *crisis-only*
sample too, since a plain random sample will contain very few (or
zero) `is_crisis_flag=True` comments to check:

```bash
python scripts/build_audit_sample.py --crisis-only --n 50 --out audit_crisis.csv
python scripts/compute_audit_results.py --in audit_crisis.csv
```

Any disagreement on `is_crisis_flag` is printed out in full — a
missed crisis is not a rounding error, and this is the one number in
the whole pipeline that should never just be a percentage you skim.

## Ethics note: the crisis flag

The taxonomy includes `SUICIDAL_DESPERATION_END_STAGE` and an
`is_crisis_flag` boolean specifically so these comments can be routed
*away* from the sales pipeline, not into it. The dashboard's API route
and `CrisisQueue` component keep this as a separate, human-review-only
view — it is deliberately excluded from `high_intent_leads`. If you
extend the dashboard, keep that separation. Real people in genuine
crisis showing up in your YouTube comments deserve a human response,
not a puja upsell.
