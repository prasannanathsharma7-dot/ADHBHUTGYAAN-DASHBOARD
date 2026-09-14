# MongoDB Schema & Aggregations — astrology_intelligence

> **Database isolation — read this first.**
> This entire pipeline is hard-locked to the `astrology_intelligence`
> database. It must never connect to, query, or reference
> `adhbhutgyaan_prod` (the live website's database). Every script goes
> through `mongo/db_guard.py`'s `get_isolated_db()`, which refuses to
> connect anywhere else. Do not bypass this by hardcoding a different
> `MongoClient(...)` call somewhere new — route everything through the
> guard.

## Document shape (`comments` collection)

```json
{
  "_id": ObjectId("..."),
  "comment_id": "UgxAbC123...",
  "video_id": "abc123",
  "video_title": "Manglik Dosh Explained | ...",
  "channel_title": "ExampleAstrologyChannel",
  "channel_id": "UC...",
  "published_at": ISODate("2025-11-02T10:00:00Z"),
  "author_name": "user123",
  "author_channel_url": "https://www.youtube.com/channel/UC...",
  "comment_text": "Meri shaadi mein bahut delay ho raha hai, Manglik dosh hai kya?",
  "language_detected": "hinglish",
  "scraped_at": ISODate("2026-09-14T10:00:00Z"),

  "analysis": {
    "primary_problem_code": "SEVERE_MANGLIK_KUNDLI_MISMATCH",
    "secondary_problem_code": "LATE_MARRIAGE_ALLIANCE_COLLAPSE",
    "primary_dosh": "Manglik",
    "exact_user_complaint": "Shaadi mein delay ho raha hai, Manglik dosh se pareshan",
    "sentiment": "Distressed",
    "urgency_score": 7,
    "is_crisis_flag": false,
    "commercial_intent": "MEDIUM",
    "commercial_signals": ["asking_puja_cost"],
    "recommended_service": "Personal Kundli Diagnosis",
    "lead_status": "NEW",
    "analyzed_at": ISODate("2026-09-14T12:00:00Z"),
    "model_version": "claude-sonnet-5-batch-v1"
  }
}
```

Before enrichment runs, `analysis` is `null` on a freshly scraped
document — the enrichment pipeline's query for un-enriched comments is
`{ "analysis": null }`.

## Indexes

```js
db.comments.createIndex({ comment_id: 1 }, { unique: true })
db.comments.createIndex({ video_id: 1 })
db.comments.createIndex({ channel_id: 1 })
db.comments.createIndex({ "analysis.primary_problem_code": 1, "analysis.urgency_score": -1 })
db.comments.createIndex({ "analysis.commercial_intent": 1, "analysis.lead_status": 1 })
db.comments.createIndex({ "analysis.is_crisis_flag": 1 })
db.comments.createIndex({ "analysis.primary_dosh": 1 })
db.comments.createIndex({ comment_text: "text" })
```

Build only what the aggregations below actually use — extra indexes
slow down writes without helping read performance if nothing queries them.

## Aggregation: Top 50 Problems (full 1-50 taxonomy)

```js
db.comments.aggregate([
  { $match: { analysis: { $ne: null } } },
  { $group: { _id: "$analysis.primary_problem_code", count: { $sum: 1 } } },
  { $sort: { count: -1 } },
  { $limit: 50 }
])
```

## Aggregation: Top 50 Complaints (vendor/service grievances, codes 44-50)

```js
const VENDOR_COMPLAINT_CODES = [
  "FAKE_ASTROLOGER_LOOT_COMPLAINT",
  "GEMSTONE_INEFFECTIVE_ADVERSE_REACTION",
  "TEMPLE_PUJA_NO_EFFECT_COMPLAINT",
  "PANDIT_NO_SHOW_FAKE_SANKALP",
  "CONTRADICTORY_PREDICTIONS_CONFUSION",
  "REMEDY_TOO_EXPENSIVE_INACCESSIBLE",
  "UNANSWERED_CONSULTATION_GHOSTED",
];

db.comments.aggregate([
  { $match: { "analysis.primary_problem_code": { $in: VENDOR_COMPLAINT_CODES } } },
  { $group: { _id: "$analysis.primary_problem_code", count: { $sum: 1 } } },
  { $sort: { count: -1 } },
  { $limit: 50 }
])
```

## Aggregation: Crisis queue (human review, never a sales list)

```js
db.comments.aggregate([
  { $match: { "analysis.is_crisis_flag": true } },
  { $sort: { "analysis.urgency_score": -1, scraped_at: -1 } },
  { $limit: 50 }
])
```

Do not join this query's output into any commercial/lead-gen view.
See the ethics note at the top of `nlp/batch_pipeline.py`.

## Aggregation: full dashboard payload via `$facet`

This is exactly what `dashboard/app/api/analytics/route.ts` runs —
one round trip for every widget, including the vendor-complaints and
crisis-queue facets above. See that file for the complete pipeline.

At 1M documents with the indexes above, verify each `$facet` branch
hits an index scan via `.explain("executionStats")` rather than trusting
theoretical performance. If `top_problems` group-by-scan gets slow as
data grows well past 1M, pre-aggregate into a `daily_taxonomy_rollup`
collection via a scheduled local cron job instead of computing live.
