"""Generate a 100k document working set and sample random MongoDB reads."""
import argparse
import random
import string
import time
from datetime import datetime, timezone

from pymongo import MongoClient

N_DOCS = 100_000
TARGET_BYTES = 2_048


def cache_sample(db):
    wt = db.command("serverStatus").get("wiredTiger", {}).get("cache", {})
    aliases = {k.lower().replace("_", " "): v for k, v in wt.items()}
    def get(*names):
        return next((aliases[n] for n in names if n in aliases), 0)
    return {
        "current": get("bytes currently in the cache"),
        "maximum": get("maximum bytes configured"),
        "requested": get("pages requested from the cache", "pages requested from the cache"),
        "read": get("pages read into cache", "pages read into cache"),
        "evicted": get("pages evicted by application threads", "unmodified pages evicted"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default="mongodb://localhost:27017")
    parser.add_argument("--database", default="cti_lab")
    parser.add_argument("--collection", default="working_set")
    parser.add_argument("--reads", type=int, default=250_000)
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--reset", action="store_true", help="drop the target collection before loading")
    args = parser.parse_args()
    client = MongoClient(args.uri, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    db = client[args.database]
    col = db[args.collection]
    if args.reset:
        col.drop()
    if col.count_documents({}) == 0:
        print(f"Inserting {N_DOCS:,} documents (~2 KiB each)…")
        rng = random.Random(7127)
        alphabet = string.ascii_letters + string.digits
        batch = []
        for i in range(N_DOCS):
            # 1850 random bytes + BSON field/document overhead, usually close to 2 KiB.
            payload = "".join(rng.choices(alphabet, k=1850))
            batch.append({"_id": i, "createdAt": datetime.now(timezone.utc), "payload": payload, "sequence": i})
            if len(batch) == 1000:
                col.insert_many(batch, ordered=False)
                batch.clear()
        if batch:
            col.insert_many(batch, ordered=False)
        col.create_index("sequence")
    print(f"Collection contains {col.count_documents({}):,} documents; logical target ~195.3 MiB before indexes/overhead.")
    previous = cache_sample(db)
    start = last = time.monotonic()
    hits = misses = 0
    while hits + misses < args.reads:
        col.find_one({"_id": random.randrange(N_DOCS)}, {"payload": 1})
        hits += 1
        now = time.monotonic()
        if now - last >= args.seconds:
            current = cache_sample(db)
            read_delta = max(0, current["read"] - previous["read"])
            requested_delta = max(0, current["requested"] - previous["requested"])
            ratio = max(0, 1 - read_delta / requested_delta) * 100 if requested_delta else None
            print(f"elapsed={now-start:.0f}s reads={hits+misses:,} cache_hit_est={ratio:.1f}%" if ratio is not None else f"elapsed={now-start:.0f}s reads={hits+misses:,} cache_hit_est=n/a")
            print(f"  cache={current['current']/1048576:.1f}/{current['maximum']/1048576:.1f} MiB; pages-read-delta={read_delta:,}; pages-requested-delta={requested_delta:,}")
            previous, last = current, now
    client.close()


if __name__ == "__main__":
    main()
