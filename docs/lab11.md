# Lab 11 - Sharding and Horizontal Scaling

This lab is integrated into the same `docker-compose.yml` as Labs 7 and 10. The unified stack includes the Flask app, the Lab 10 replica set, and a self-managed MongoDB 7 sharded cluster. The topology follows the supplied scaling diagram: the Lab 11 runner connects to `mongos`, which routes operations to two shards; a config server replica set stores cluster metadata. The compose file uses one MongoDB process per replica set to keep the lab runnable on a laptop. This is a learning topology, not a production availability design.

## Start and run

Start the complete project, including both database topologies, from its folder:

```sh
docker compose up --build -d
docker compose --profile lab11 run --rm lab11
```

The demo inserts 10,000 documents into each collection, prints shard-level `$collStats` counts and sizes, and runs identical-width range queries through `explain()`. It writes the measured output, including MongoDB version and winning plans, to `docs/lab11-results.json`. The collections are dropped and recreated each time, so the demo data is disposable.

Connect to the local router with `mongodb://localhost:27018` (for example, with mongosh). The web app is available at <http://localhost:5000>. Lab 10's replica set remains available at `mongodb://localhost:27017/?replicaSet=rs0`.

## Lab 11.1 - Evaluate shard key choices

The workload is an order system where common operations include reading a customer's order history, fetching an order by ID, and filtering recent orders by date. Cardinality is assessed against all orders, not just unique customers.

| Candidate | Cardinality | Distribution and write risk | Query targeting | Assessment |
|---|---|---|---|---|
| `order_id` (random UUID) | Very high | Even when IDs are random; sequential IDs can instead create an upper-range hotspot | Exact order ID lookups target one shard; customer history and date queries scatter | Strong if point lookups dominate and IDs are random; weaker for customer-centric workload |
| `customer_id` (ranged) | High if the customer base is large | Can be skewed by very active customers; inserts for a customer are colocated | Equality queries for one customer target a shard; customer ranges target relevant chunks | Good customer-history locality, with possible hot customers |
| `order_date` (ranged) | High over time but monotonically increasing | Latest writes target the chunk owning the upper range, creating an insert hotspot | Date range queries can target relevant chunks; current-day writes concentrate | Avoid as a sole key for a write-heavy system unless time-range locality outweighs the write bottleneck |
| `customer_id` (hashed) | High | Hashing spreads distinct customer values across chunks and avoids monotonic-key hotspots; one very frequent customer still maps to one shard | Equality on `customer_id` targets one shard; ranges on customer ID and date-only queries scatter | Recommended for this workload when customer history is the main access pattern and write distribution matters |

Recommendation: use `{customer_id: "hashed"}` when customer-scoped equality lookups and balanced inserts are the main workload. Hashed values retain equality targeting but lose useful range locality on customer IDs. Queries by `order_id` alone and date-only range queries are scatter-gather unless supported by a different design, such as an order lookup collection or a compound/ranged shard key. No shard key is universally best: validate it against query frequency, write rate, cardinality, skew, and growth using representative data.

## Lab 11.2 - Detect a monotonic-key hotspot

`hotspot_data` is sharded on `{ts: 1}` before the inserts and receives timestamps in strictly increasing order. For the small 10,000-document workload, the collection is far below MongoDB's default chunk split size. Therefore, the range collection can remain a single chunk on one shard, and its newest writes continue to that shard. The exact owning shard is reported by the run.

`even_data` is sharded on `{user_id: "hashed"}` before the inserts. MongoDB 7 creates and initially distributes hashed chunks for an empty collection (two chunks per shard by default); random IDs then send writes across those chunks. `$collStats` reports observed per-shard counts and data sizes. It reports metadata estimates and can be temporarily uneven during migrations; do not claim a precise 50/50 split unless the measured output shows it.

Both explain plans use ranges of similar width: a 2,000-second interval on `ts`, and a middle 20% range on randomly generated `user_id` values. Ranged `ts` can target the shard owning that timestamp chunk. A range on a hashed key generally cannot be translated into a narrow hash interval, so it broadcasts to shards. Hashed equality predicates do target by hash.

### Findings to report

The measured MongoDB 7.0.45 run is recorded in `docs/lab11-results.json`:

| Collection | Shard counts | Data bytes | Range-query targets |
|---|---|---:|---|
| `hotspot_data` (`ts: 1`) | `shard1RS`: 10,000 | 2,230,000 | `shard1RS` (1 shard) |
| `even_data` (`user_id: "hashed"`) | `shard1RS`: 5,002; `shard2RS`: 4,998 | 2,230,000 | `shard1RS`, `shard2RS` (2 shards) |

In this run the timestamp range query used an index scan and targeted the one shard that owned the key interval. The hashed-key range query was a scatter-gather and its per-shard plan used a collection scan because a hash index cannot preserve the original value's range ordering. Use `docs/lab11-results.json` to compare the detailed winning plans. Counts and targets are measured for this small demo and should not be treated as guaranteed outputs for other MongoDB versions or cluster configurations.

### When a ranged key is still appropriate

A ranged key remains useful when range scans, ordered access, or zone placement dominate and the key does not create an unacceptable hot write boundary. Examples include queries that usually constrain a tenant plus time range using a compound key, or workloads with historical/read-heavy partitions and controlled write rates. Monitor per-shard write load and chunk distribution; adding a high-cardinality prefix or using a hashed strategy may reduce hotspots but changes locality and targeting.

## Activity - MongoDB 5.0+ resharding

MongoDB 5.0 introduced changing a collection's shard key with `reshardCollection`. At a high level:

1. Review query patterns and test the proposed key for cardinality, frequency, and skew. Check existing unique indexes and whether they remain valid with the new shard-key pattern.
2. Check cluster storage, CPU, I/O, and oplog headroom. Resharding copies data and builds indexes, so plan for temporary resource use and extra storage.
3. Start the operation from `mongos` with the target key, for example:

   ```javascript
   db.adminCommand({
     reshardCollection: "lab11.orders",
     key: { customer_id: "hashed" }
   })
   ```

4. Monitor progress with `$currentOp` on the `admin` database and inspect the new distribution after completion. Resharding clones records, builds the new indexes, catches up concurrent changes, then commits a cutover. Writes may pause briefly during cutover.

Important limitations and planning points: reshard one collection at a time; the cluster requires majority write concern behavior; unique constraints must be compatible with the new key; avoid index DDL on the collection while resharding; and ensure sufficient temporary disk, I/O, CPU, and oplog window. Queryable Encryption collections are unsupported. Atlas Search indexes may need rebuilding afterward. Once the operation reaches commit, it cannot be aborted. Details and version-specific behavior vary; check the manual for the MongoDB release you run.

## References

- [MongoDB 7.0 hashed sharding and initial chunks](https://www.mongodb.com/docs/v7.0/core/hashed-sharding/)
- [MongoDB shard key selection](https://www.mongodb.com/docs/v7.0/core/sharding-choose-a-shard-key/)
- [MongoDB resharding command and process](https://www.mongodb.com/docs/manual/reference/command/reshardcollection/)
- [Resharding resource requirements](https://www.mongodb.com/docs/manual/tutorial/resharding-for-adding-and-removing-shards/)
- [Per-shard `$collStats` output](https://www.mongodb.com/docs/manual/reference/operator/aggregation/collstats/)
- [Chapter 11 example repository](https://github.com/sujeetjagtap/NoSQL-Databases-using-MongoDB/tree/main/chapter-11)

## Docker Hub submission

The image containing Labs 7, 10, and 11 is published at [krish1226/lab10](https://hub.docker.com/r/krish1226/lab10), tag `lab11`. Pull it with `docker pull krish1226/lab10:lab11`. The submission PDF is `docs/lab11-submission.pdf`.
