# Adhbhutgyaan Intelligence Pipeline — Architecture Review

Target: 1,000,000 astrology-related comments/FAQs → structured insights →
Next.js dashboard (Top-50 Problems, Top-50 Complaints, content direction).

---

## 1. Scraping Layer (Python)

### Concurrency model
Don't parallelize video-by-video with a plain `ThreadPoolExecutor` at high
worker counts — YouTube's undocumented endpoint used by
`youtube-comment-downloader` rate-limits aggressively per-IP.

**Recommended shape:**

```
Redis (job queue) --> N worker processes (3-5) --> MongoDB (raw_comments)
                                |
                        proxy pool (rotating residential)
                                |
                     randomized delay: 2-6s between requests
```

- Use **Celery** or **RQ** with Redis as broker — gives you retries,
  resumability, and visibility into what's done/failed/pending.
- **Checkpoint every video_id** in a `scrape_status` collection
  (`{video_id, status: "pending"|"in_progress"|"done"|"failed", last_comment_cursor}`)
  so a crash/restart doesn't re-scrape from zero.
- **Never accumulate in memory.** Stream comments straight to a JSONL file
  per video or bulk-insert in chunks of 500-1000 directly to MongoDB.
  A million comments as Python dicts in a list will OOM most machines.
- **Proxy rotation is not optional at this scale.** Budget for a
  residential proxy service (Bright Data, Oxylabs, or similar). Without
  rotation, expect IP bans well before 100K comments.

### Cloudflare-protected portals (AstroSage/Astroyogi FAQs)
- Try `curl_cffi` with browser TLS impersonation first — cheaper, faster.
- Fall back to Playwright with `playwright-stealth` only for pages that
  return a JS challenge. Keep concurrency to 1-2 browser contexts here —
  headless Chromium is RAM-heavy and Cloudflare fingerprints browser
  concurrency patterns too.
- Respect `robots.txt` and rate limits on these portals — sitemap-based
  crawling of public FAQ pages is generally lower-risk than the YouTube
  comment scraping, but still needs backoff on 429/503.

### Deduplication
Same complaint gets posted across multiple videos by the same or
different users. Create a compound unique index:
```js
db.raw_comments.createIndex(
  { content_hash: 1 },
  { unique: true }
)
// content_hash = sha256(normalized_text + author_channel_id)
```
Insert with `ordered: false` bulk writes so duplicate-key errors on
individual documents don't halt the whole batch.

### Multilingual handling (Hinglish / Devanagari)
- Tag language with `fasttext` (lid.176) or `langdetect` at scrape time —
  cheap, and useful for filtering later.
- **Don't transliterate/normalize before sending to Claude.** Claude
  handles Hindi, Devanagari, and Hinglish natively and normalization
  risks losing meaning (e.g. "Mangal dosh" vs "मंगल दोष" — send raw).
- **Do filter noise pre-NLP** to save batch cost: drop emoji-only
  comments, comments under ~3 words, and obvious spam/promo patterns
  with a simple regex/heuristic pass before anything touches the Batch API.

---

## 2. NLP Enrichment — Claude Batch API

Corrections to your stated stack: **Claude 3.5 Haiku is retired** except
on Bedrock/Google Cloud. Use **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`)
for the direct API — same "cheap classification workhorse" role, current
generation.

**Current batch limits (verify against docs before a real production run):**
- Up to **100,000 requests OR 256 MB** per batch, whichever hits first
- 50% discount on both input and output tokens vs standard pricing
- Most batches finish within an hour; hard cutoff at 24h
- Results retrievable for 29 days
- Batch results come back **unordered** — always match on `custom_id`

For 1M comments: split into ~10-15 batches of ~70-80K requests each
(safely under the 100K/256MB ceiling with typical comment length),
run them with a small stagger so you're not fighting your own
concurrent-batch rate limits.

### Cost-saving tactic: prompt caching inside batches
If your system prompt (the classification instructions + JSON schema)
is identical across all requests, mark it with `cache_control: ephemeral`
in every request in the batch. Cache discount stacks with the batch
discount. Real-world hit rates run 30-98% depending on request density —
submit the whole batch at once rather than trickling requests in.

### Failure handling
- `errored`, `canceled`, `expired` results are not billed — but you still
  need retry logic. Re-queue `errored` (validation-error) custom_ids into
  the next batch after fixing the input; re-submit `expired` ones as-is.
- Never let one malformed comment block a whole batch — each request is
  processed independently, so isolate bad inputs, don't halt the pipeline.

See `nlp/batch_pipeline.py` for the full implementation.

---

## 3. MongoDB Atlas Schema & Indexing

See `mongo/schema_and_aggregations.md` for the full document shape,
indexes, and the aggregation pipelines that power the dashboard's
Top-50 Problems / Top-50 Complaints views in under 200ms at 1M scale.

Key design decision: **denormalize the enrichment fields onto the same
document as the raw comment** (single-collection design) rather than a
separate `enrichments` collection with a join. MongoDB aggregation
`$lookup` joins at 1M-document scale are the single biggest cause of
>200ms dashboard queries — avoid them for the hot path.

---

## 4. Next.js Dashboard

App Router, API route does the aggregation server-side, TanStack Table
does client-side sort/filter/paginate on the already-narrow result set
(never ship all 1M rows to the client — the API route returns pre-
aggregated buckets, not raw documents).

See `dashboard/app/api/analytics/route.ts` and
`dashboard/components/leads-table.tsx`.

---

## 5. Bottlenecks & failure points you're likely underestimating

1. **YouTube scraping throughput is your real ceiling, not MongoDB or
   Claude.** Realistically, unofficial-API scraping at safe rate limits
   gets you maybe 5,000-15,000 comments/hour per proxy IP. To hit 1M in
   a reasonable timeframe you need either a proxy pool of meaningful size
   or you accept this running over days/weeks. Plan the timeline around
   this constraint, not around Batch API throughput (which is comparatively
   trivial — 1M requests split across ~12 batches, done in hours).

2. **Batch API JSON schema drift.** Even with a strict system prompt,
   Haiku will occasionally return malformed JSON at scale (1M requests →
   expect a fraction of a percent failures). Validate every response
   against a JSON schema on ingest; route failures to a dead-letter
   collection for a cheap retry pass, don't silently drop them or crash
   the ingest job.

3. **"Commercial intent" classification without ground truth will drift.**
   Haiku's judgment on "is this person ready to book a pooja or just
   curious" is a proxy signal, not truth. Sample-audit ~200 classified
   comments by hand early on and adjust the prompt — don't trust the
   first pass blindly, this number directly drives your business
   decisions (which doshas to push content on).

4. **MongoDB write throughput at 1M inserts.** Use `insertMany` with
   `ordered: false` in batches of 1000-5000, not per-document inserts.
   Atlas M10+ tier handles this fine; M0/M2/M5 free/shared tiers will
   throttle you hard at this volume — budget for at least an M10 dedicated
   cluster for both write throughput and the aggregation performance
   the dashboard needs.

5. **Index bloat.** Don't index every field "just in case" — each index
   slows writes. Build only the compound indexes the aggregation
   pipelines actually use (see schema doc), and watch this with
   `db.collection.getIndexes()` + Atlas's index-usage stats after the
   first real load.

6. **Legal/ToS surface.** Scraping YouTube comments at this volume via an
   unofficial method carries real terms-of-service risk, separate from
   the technical IP-ban risk — worth being aware of as a business risk,
   not just an engineering one, especially since you're a public-facing
   commercial astrology site.
