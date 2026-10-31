"""Lab 11 sharded-cluster demo: shard-key targeting and hotspot comparison."""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pymongo import MongoClient
from pymongo.errors import OperationFailure

URI = os.getenv("MONGODB_URI", "mongodb://localhost:27018/?directConnection=true")
DB_NAME = "lab11"
DOCS = 10_000
ROOT = Path(__file__).resolve().parents[1]


def check_mongos(client: MongoClient) -> None:
    hello = client.admin.command("hello")
    if not hello.get("msg") == "isdbgrid":
        raise RuntimeError("Connect this exercise to mongos, not directly to a mongod.")
    shards = client.admin.command("listShards")["shards"]
    if len(shards) < 2:
        raise RuntimeError("Lab 11 requires two registered shards. Start docker-compose.sharding.yml first.")


def prepare_collection(client: MongoClient, db, name: str, key: dict):
    if name in db.list_collection_names():
        db[name].drop()
    try:
        client.admin.command("shardCollection", f"{DB_NAME}.{name}", key=key)
    except OperationFailure as exc:
        if "already sharded" not in str(exc).lower():
            raise
    return db[name]


def shard_counts(collection) -> list[dict]:
    result = list(collection.aggregate([{"$collStats": {"count": {}, "storageStats": {}}}]))
    return [
        {
            "shard": row.get("shard", "unknown"),
            "documents": row.get("count", 0),
            "data_size_bytes": row.get("storageStats", {}).get("size", 0),
        }
        for row in sorted(result, key=lambda row: row.get("shard", ""))
    ]


def explain_targets(collection, query: dict) -> dict:
    explanation = collection.database.command(
        "explain",
        {"find": collection.name, "filter": query},
        verbosity="queryPlanner",
    )
    shard_names: set[str] = set()

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("shardName"), str):
                shard_names.add(value["shardName"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(explanation.get("queryPlanner", {}).get("winningPlan", {}))
    return {
        "targeted_shards": sorted(shard_names),
        "targeted_shard_count": len(shard_names),
        "winning_plan": explanation.get("queryPlanner", {}).get("winningPlan", {}),
    }


def run_demo(client: MongoClient) -> dict:
    check_mongos(client)
    db = client[DB_NAME]
    try:
        client.admin.command("enableSharding", DB_NAME)
    except OperationFailure as exc:
        if "already enabled" not in str(exc).lower():
            raise

    # Ranged timestamps use one initial range; all fresh increasing keys go to
    # its upper end. Hashed empty collections are pre-split across shards in 7.0.
    hotspot = prepare_collection(client, db, "hotspot_data", {"ts": 1})
    even = prepare_collection(client, db, "even_data", {"user_id": "hashed"})

    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    docs_hotspot = []
    docs_even = []
    user_ids = []
    for i in range(DOCS):
        user_id = secrets.token_hex(12)
        user_ids.append(user_id)
        docs_hotspot.append({"ts": base + timedelta(seconds=i), "user_id": user_id, "seq": i, "payload": "x" * 128})
        docs_even.append({"user_id": user_id, "ts": base + timedelta(seconds=i), "seq": i, "payload": "x" * 128})
    hotspot.insert_many(docs_hotspot, ordered=False)
    even.insert_many(docs_even, ordered=False)

    time_filter = {"ts": {"$gte": base + timedelta(seconds=4000), "$lt": base + timedelta(seconds=6000)}}
    ordered_ids = sorted(user_ids)
    hashed_filter = {"user_id": {"$gte": ordered_ids[4000], "$lt": ordered_ids[6000]}}
    report = {
        "mongodb_version": client.server_info()["version"],
        "documents_per_collection": DOCS,
        "collections": {
            "hotspot_data": {
                "shard_key": {"ts": 1},
                "distribution": shard_counts(hotspot),
                "query": time_filter,
                "explain": explain_targets(hotspot, time_filter),
            },
            "even_data": {
                "shard_key": {"user_id": "hashed"},
                "distribution": shard_counts(even),
                "query": hashed_filter,
                "explain": explain_targets(even, hashed_filter),
            },
        },
    }
    return report


def main():
    with MongoClient(URI, serverSelectionTimeoutMS=10_000) as client:
        client.admin.command("ping")
        report = run_demo(client)
    print(json.dumps(report, indent=2, default=str))
    output = ROOT / "docs" / "lab11-results.json"
    output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nSaved measured output to {output}")


if __name__ == "__main__":
    main()
