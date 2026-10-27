# Lab 7 analysis — Signal CTI Desk

## Scope and provenance

This is a teaching design, not a claim that CTIDigest publishes this database schema. The prompt asks the student to create a dataset based on CTIDigest and separately supplies an annual-security-report catalog for Lab 7.2. This project combines public report metadata from that catalog with source links, and keeps all verdicts as clearly labeled local analyst assessments. It stores no copied PDFs or report body. Validate dates, titles, and the destination URL at the original publisher before operational use; the bundled catalog is an illustrative seed, not a live scrape.

## Example production collections and relationship choices

`reports` is the app's read model: `{ _id, id, title, published, year, category, topics[], summary, source:{name,domain,url}, assessment:{verdict,note,reviewedAt,reviewer} }`.

| Relationship | Choice | Why / embedded alternative |
|---|---|---|
| Report → citation/source snapshot | Embed small `source` object in report | Source name/domain/URL are read with report and tiny. If embedded source metadata changed, duplicated snapshots can become stale. Embedding a one-to-one citation costs little and avoids a lookup. |
| Report → topic tags | Embed bounded `topics[]` strings | Tags are small, bounded values read with the report. If tags were shared taxonomy entities with governance, reference `topicIds` and keep canonical names elsewhere. |
| Report → analyst assessment | Embed current single assessment | The UI reads the current verdict with the report and it is one small current state. A full history is a separate `assessment_events` collection referenced by `reportId`; do not grow an unbounded embedded history. |
| Report → publisher organization | Reference `sourceId` to `sources` in a normalized production variant | A publisher is shared across many reports; its canonical profile/contact can change, and is queried independently. Embedding full publisher metadata in every report duplicates updates. Alternative: embed a compact source snapshot `{name,domain,url}` in each report for fast display, as this demo does. |
| Report → indicators of compromise (IOCs) | Reference `indicatorIds` / separate `indicators` | Indicators may be shared by many reports, independently queried, updated, expired, and numerous. Embedding all indicator documents repeats data and causes document growth. Alternative: embed a bounded subset of the most relevant indicators, e.g. `topIndicators:[{type,value,confidence}]`, while keeping the canonical collection. |
| Report ↔ actors / campaigns | References (`actorIds`, `campaignIds`) in separate collections | Many-to-many relationships and independently maintained actor/campaign records benefit from canonical entities. Alternative: embed a small display snapshot per report for the common read view, while retaining references. |
| Report → source files / full report content | Reference object-storage/GridFS location and metadata | PDF/large text is unbounded relative to metadata and commonly fetched separately. Embedding would inflate working set and approach BSON limit. Alternative: embed a short abstract or excerpt with a strict length cap. |
| Report → classifications from multiple analysts | Current decision embedded; append-only events referenced | Dashboard commonly needs current verdict, but decisions/audit history can grow indefinitely. Alternative: keep a bounded recent history array and archive older events. |

The important query pattern drives this design: search and show the report citation and the current judgment in one result row. Embedding the small values keeps this read cheap. Separating shared, high-cardinality, independently queried, or unbounded entities avoids update anomalies and runaway documents. MongoDB's modeling guidance describes references as useful for high cardinality, independent access, and reducing duplication; embedding helps when data is accessed together. See [MongoDB referencing guidance](https://www.mongodb.com/docs/manual/data-modeling/referencing/) and [embedding versus references](https://www.mongodb.com/docs/v7.2/data-modeling/concepts/embedding-vs-references/).

## BSON sizes and 16 MiB check (Lab 7.1)

Run against the seeded `reports` collection in `cti_lab`:

```javascript
db.reports.aggregate([
  { $project: { title: 1, bytes: { $bsonSize: "$$ROOT" } } },
  { $group: { _id: null, documents: { $sum: 1 }, averageBytes: { $avg: "$bytes" }, maxBytes: { $max: "$bytes" }, minBytes: { $min: "$bytes" } } }
])
```

To identify the largest records and their fraction of MongoDB's 16 MiB BSON document limit:

```javascript
db.reports.aggregate([
  { $project: { title: 1, bytes: { $bsonSize: "$$ROOT" } } },
  { $sort: { bytes: -1 } }, { $limit: 10 },
  { $project: { title: 1, bytes: 1, kibibytes: { $divide: ["$bytes", 1024] }, limitPercent: { $multiply: [{ $divide: ["$bytes", 16777216] }, 100] } } }
])
```

The exact average must be reported from the student's database output; it depends on the BSON encoding, MongoDB version, and records inserted. The provided seed fields are short strings and small arrays, so each should be in the low single-digit KiB range, many thousands of times below 16 MiB. Do not report a guessed average as a measured result. `$bsonSize` returns BSON bytes. MongoDB's documented maximum BSON document size is 16 mebibytes (16,777,216 bytes): [limits](https://www.mongodb.com/docs/manual/reference/limits/) and [`$bsonSize`](https://www.mongodb.com/docs/manual/reference/operator/aggregation/bsonsize/).

## Redesign: decide which source is an actual threat

Move the current assessment into an embedded `sourceAssessment` snapshot on each report-source association, e.g. `{ sourceAssessment:{ verdict:"suspicious", confidence:0.72, rationale:"...", reviewer:"...", reviewedAt:ISODate(...) } }`. In a richer model, the actual assessed entity belongs to a report-source pair: one public report can mention many sources, and multiple analysts can judge each one. Embed a bounded `sourceAssessments[]` on a report if those few decisions are always read with its detail page. Keep canonical `indicators` or `sources` referenced; do not conflate a publisher's trustworthiness with whether an item described by that publisher is a threat.

Faster: report detail with its source verdict, confidence, and rationale; filters such as `{"sourceAssessments.verdict":"confirmed"}` with a matching multikey index; dashboard display needs no `$lookup`.

Harder: concurrent edits to the same embedded assessment, auditing every change, and querying global histories by reviewer/time. The array needs a cap/archive policy and multikey-index tradeoffs. If unbounded audit history or high write volume matters, store immutable assessment events separately, reference `reportId`/`sourceId`, and optionally retain a small current-state snapshot on the report. In all cases a human-reviewed evidence-based decision is needed; the sample labels are only teaching fixtures.

## Lab 7.2: working set

Estimated raw logical payload: `100,000 × 2,048 bytes = 204,800,000 bytes ≈ 195.3 MiB`. Actual disk/cache footprint differs because documents have BSON overhead, indexes, compression, page granularity, and internal WiredTiger metadata. The working set is the frequently used data and indexes; a dataset larger than cache does not mean every byte must stay cached. Run `python scripts/working_set.py --uri "$MONGODB_URI"` to create `cti_lab.working_set` with 100,000 near-2-KiB payloads and random reads. It reports cache capacity/current bytes and a per-interval approximate cache-hit ratio using deltas of `pages requested from the cache` and `pages read into the cache` from `db.serverStatus().wiredTiger.cache`.

`python scripts/report_monitor.py --uri "$MONGODB_URI"` polls the annual reports repository README and WiredTiger every 10 seconds. It compares report links against `cti_lab.reports`, reports newly discovered entries, and displays cache metrics. The cache ratio is a simple interval estimate `(requested - readIntoCache) / requested`, not a universal server health score. It can be distorted by counter resets, page reuse, workload mix, and MongoDB version; inspect cache bytes, pages read, eviction, and latency together. `serverStatus` exposes the cache's current bytes, maximum bytes, page reads, and writes. See [serverStatus](https://www.mongodb.com/docs/manual/reference/command/serverstatus/) and [diagnostics](https://www.mongodb.com/docs/manual/faq/diagnostics/).

The monitor reads a public GitHub README endpoint at runtime. It inserts no discovered records automatically: a new entry is only surfaced for analyst review, and the original link is preserved. Test the two scripts with a disposable MongoDB database.
