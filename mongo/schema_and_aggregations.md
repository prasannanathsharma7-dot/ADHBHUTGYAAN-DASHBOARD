# MongoDB Atlas Schema & Aggregation Pipelines

## Document shape (`raw_comments` collection — single-collection design)

Denormalized: raw scrape fields + enrichment fields live on the same
document. This avoids `$lookup` joins at query time, which is the
single biggest cause of slow dashboard queries at 1M-document scale.

```json
{
  "_id": ObjectId("..."),
  "video_id": "abc123",
  "channel_name": "ExampleAstrologyChannel",
  "author": "user123",
  "author_channel_id": "UC...",
  "text": "Meri shaadi mein bahut delay ho raha hai, Manglik dosh hai kya?",
  "like_count": 4,
  "is_reply": false,
  "content_hash": "sha256...",
  "source": "youtube",
  "scraped_at": ISODate("2026-09-01T10:00:00Z"),

  "enriched": true,
  "enriched_at": ISODate("2026-09-01T12:00:00Z"),
  "topic": "manglik_dosh",
  "detected_dosh": "Manglik Dosh",
  "urgency_score": 4,
  "commercial_intent": "high",
  "recommended_service": "Kundli Milan + Manglik Dosh Nivaran Pooja",
  "language": "hinglish"
}
```

## Indexes

```js
// Uniqueness / dedup (already created at scrape time)
db.raw_comments.createIndex({ content_hash: 1 }, { unique: true })

// Dashboard hot-path compound indexes
db.raw_comments.createIndex({ enriched: 1, topic: 1, urgency_score: -1 })
db.raw_comments.createIndex({ enriched: 1, commercial_intent: 1, scraped_at: -1 })
db.raw_comments.createIndex({ detected_dosh: 1 })
db.raw_comments.createIndex({ channel_name: 1, topic: 1 })

// Text search for the "search leads" TanStack Table view
db.raw_comments.createIndex({ text: "text" })
```

Rule of thumb: build indexes to match the exact field order used in
your aggregation `$match`/`$sort` stages — not "just in case." Every
extra index slows writes, and you're doing ~1M writes.

## Aggregation: Top 50 Problems (by topic + dosh)

```js
db.raw_comments.aggregate([
  { $match: { enriched: true, topic: { $ne: "spam_irrelevant" } } },
  {
    $group: {
      _id: { topic: "$topic", dosh: "$detected_dosh" },
      count: { $sum: 1 },
      avg_urgency: { $avg: "$urgency_score" },
      high_intent_count: {
        $sum: { $cond: [{ $eq: ["$commercial_intent", "high"] }, 1, 0] }
      }
    }
  },
  { $sort: { count: -1 } },
  { $limit: 50 }
])
```

## Aggregation: Top 50 Complaints (low satisfaction / negative sentiment)

If you add a `sentiment` field in the enrichment schema (recommended —
extend `ENRICHMENT_SCHEMA` with `"sentiment": "positive"|"neutral"|"negative"`),
this becomes straightforward:

```js
db.raw_comments.aggregate([
  { $match: { enriched: true, sentiment: "negative" } },
  {
    $group: {
      _id: "$topic",
      count: { $sum: 1 },
      sample_comments: { $push: "$text" }
    }
  },
  { $addFields: { sample_comments: { $slice: ["$sample_comments", 3] } } },
  { $sort: { count: -1 } },
  { $limit: 50 }
])
```

## Aggregation: Dashboard summary via `$facet` (single round-trip)

This is what the `/api/analytics` route calls — one query returns
every widget's data instead of 4-5 separate round trips.

```js
db.raw_comments.aggregate([
  { $match: { enriched: true } },
  {
    $facet: {
      top_topics: [
        { $group: { _id: "$topic", count: { $sum: 1 } } },
        { $sort: { count: -1 } },
        { $limit: 50 }
      ],
      top_doshs: [
        { $match: { detected_dosh: { $ne: null } } },
        { $group: { _id: "$detected_dosh", count: { $sum: 1 } } },
        { $sort: { count: -1 } },
        { $limit: 50 }
      ],
      commercial_intent_breakdown: [
        { $group: { _id: "$commercial_intent", count: { $sum: 1 } } }
      ],
      urgency_distribution: [
        { $group: { _id: "$urgency_score", count: { $sum: 1 } } },
        { $sort: { _id: 1 } }
      ],
      high_intent_leads: [
        { $match: { commercial_intent: "high" } },
        { $sort: { urgency_score: -1, scraped_at: -1 } },
        { $limit: 100 },
        { $project: { text: 1, topic: 1, detected_dosh: 1, urgency_score: 1, channel_name: 1 } }
      ]
    }
  }
])
```

At 1M documents with the compound indexes above, each `$facet` branch
should independently use an index scan rather than a collection scan —
verify with `.explain("executionStats")` before trusting the <200ms
target in production. If `top_topics`/`top_doshs` group-by-scan starts
exceeding budget as data grows past a few million docs, pre-aggregate
these into a `daily_topic_rollup` collection via a scheduled job
(cron/Atlas Trigger) instead of computing live every request.
