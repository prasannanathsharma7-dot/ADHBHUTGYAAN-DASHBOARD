# Adhbhutgyaan Dashboard

End-to-end intelligence pipeline for [adhbhutgyaan.com](https://adhbhutgyaan.com):
scrapes public astrology comments/FAQs, classifies them with Claude
(topic, dosh, urgency, commercial intent) via the Batch API, stores
results in MongoDB Atlas, and surfaces Top-50 Problems / Top-50
Complaints in a Next.js analytics dashboard.

Full architecture, bottlenecks, and design rationale: see
[`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Structure

```
scraper/        YouTube comment scraper (Celery worker + Actions-friendly runner)
nlp/            Claude Batch API enrichment pipeline
mongo/          Schema, indexes, aggregation pipelines
dashboard/      Next.js App Router dashboard (API route + TanStack Table UI)
.github/workflows/scraper.yml   Scheduled cloud run of the scraper + enrichment
```

## Setup — 3 things you need to configure

### 1. MongoDB Atlas connection string
Copy `.env.example` to `.env` and set `MONGODB_URI` there for local runs.
For the GitHub Actions scheduled workflow, add it as a **repo secret**
instead (Settings -> Secrets and variables -> Actions -> New repository
secret, name it `MONGODB_URI`) -- the workflow reads it from
`secrets.MONGODB_URI`, never commit the real connection string to the repo.

### 2. Anthropic API key (Batch API)
Same pattern: set `ANTHROPIC_API_KEY` in your local `.env` for manual
runs of `nlp/batch_pipeline.py`, and as a **repo secret** named
`ANTHROPIC_API_KEY` for the scheduled workflow.

### 3. Vercel deployment (dashboard)
The Next.js app lives in `dashboard/`. In Vercel: New Project -> Import
this GitHub repo -> set **Root Directory** to `dashboard` -> add an
environment variable `MONGODB_URI` in Vercel's project settings
(Settings -> Environment Variables) -> Deploy.

## Notes on the scheduled workflow

`.github/workflows/scraper.yml` runs on a daily cron and is meant for
**steady incremental scraping** (a few hundred/thousand comments per
run) via `scraper/run_scheduled.py`, which reads video IDs from
`scraper/video_ids.txt`.

It is **not** meant for the initial 1M-comment bulk load -- GitHub
Actions runners are ephemeral (no persistent Redis broker across runs)
and have job timeouts. Run the full Celery-based pipeline
(`scraper/youtube_worker.py`) once from a machine you control, with a
real Redis broker and a proxy pool, for the initial bulk scrape. See
`ARCHITECTURE.md` for why.
