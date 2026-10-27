"""Signal CTI Desk: demo-first Flask app with optional MongoDB persistence."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_from_directory

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = Flask(__name__, static_folder=None)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "local-lab-only-change-this")
MONGO_URI = os.getenv("MONGODB_URI", "")
DB_NAME = os.getenv("MONGODB_DATABASE", "cti_lab")
_client = None
_memory = None


def demo_records():
    return json.loads((ROOT / "data" / "reports.json").read_text(encoding="utf-8"))


def collection():
    global _client
    if not MONGO_URI:
        return None
    if _client is None:
        from pymongo import MongoClient, TEXT
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=1500)
        _client.admin.command("ping")
        col = _client[DB_NAME].reports
        col.create_index([("title", TEXT), ("summary", TEXT), ("topics", TEXT)], name="report_text")
        col.create_index([("published", -1), ("source.domain", 1)])
        col.create_index([("assessment.verdict", 1), ("published", -1)])
        if col.count_documents({}) == 0:
            col.insert_many(demo_records())
    return _client[DB_NAME].reports


def records():
    global _memory
    try:
        col = collection()
        if col is not None:
            return list(col.find({}, {"_id": 0}).sort("published", -1))
    except Exception as exc:
        app.logger.warning("MongoDB unavailable; using demo records: %s", exc)
    if _memory is None:
        _memory = demo_records()
    return _memory


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/static/<path:filename>")
def static_files(filename):
    # Local Flask fallback. Vercel serves the same files from public/static via its CDN.
    return send_from_directory(ROOT / "public" / "static", filename)


@app.get("/docs/lab-analysis.md")
def lab_notes():
    return send_from_directory(ROOT / "docs", "lab-analysis.md", mimetype="text/markdown")


@app.get("/api/reports")
def get_reports():
    items = records()
    q = request.args.get("q", "").strip().lower()
    verdict = request.args.get("verdict", "all")
    topic = request.args.get("topic", "all")
    if q:
        items = [r for r in items if q in " ".join([r.get("title", ""), r.get("summary", ""), " ".join(r.get("topics", [])), r.get("source", {}).get("name", "")]).lower()]
    if verdict != "all":
        items = [r for r in items if r.get("assessment", {}).get("verdict") == verdict]
    if topic != "all":
        items = [r for r in items if topic in r.get("topics", [])]
    return jsonify({"reports": items, "count": len(items), "mode": "mongodb" if MONGO_URI and _client is not None else "demo"})


@app.get("/api/analytics")
def analytics():
    items = records()
    by_source = {}
    by_topic = {}
    by_year = {}
    by_verdict = {}
    for report in items:
        source = report.get("source", {}).get("name") or report.get("source", {}).get("domain") or "Unknown"
        by_source[source] = by_source.get(source, 0) + 1
        year = str(report.get("year") or report.get("published", "")[:4] or "Unknown")
        by_year[year] = by_year.get(year, 0) + 1
        verdict = report.get("assessment", {}).get("verdict", "unreviewed")
        by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
        for topic in report.get("topics", []):
            by_topic[topic] = by_topic.get(topic, 0) + 1

    def ranked(values, limit=8):
        return [{"label": key, "value": value} for key, value in sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit]]

    return jsonify({
        "totalRecords": len(items),
        "sources": ranked(by_source),
        "topics": ranked(by_topic),
        "years": [{"label": key, "value": by_year[key]} for key in sorted(by_year)],
        "verdicts": ranked(by_verdict, 10),
        "mode": "mongodb" if MONGO_URI and _client is not None else "demo",
        "refreshedAt": datetime.now(timezone.utc).isoformat(),
    })


@app.patch("/api/reports/<report_id>/assessment")
def classify(report_id):
    body = request.get_json(silent=True) or {}
    verdict = body.get("verdict")
    if verdict not in {"confirmed", "suspicious", "benign", "unreviewed"}:
        return jsonify(error="verdict must be confirmed, suspicious, benign, or unreviewed"), 400
    note = str(body.get("note", ""))[:500]
    assessment = {"verdict": verdict, "note": note, "reviewedAt": datetime.now(timezone.utc).isoformat(), "reviewer": "local analyst"}
    try:
        col = collection()
        if col is not None:
            result = col.update_one({"id": report_id}, {"$set": {"assessment": assessment}})
            if not result.matched_count:
                return jsonify(error="report not found"), 404
        else:
            matches = [r for r in records() if r["id"] == report_id]
            if not matches:
                return jsonify(error="report not found"), 404
            matches[0]["assessment"] = assessment
    except Exception as exc:
        return jsonify(error=f"database unavailable: {exc}"), 503
    return jsonify({"id": report_id, "assessment": assessment})


@app.get("/api/health")
def health():
    mode = "demo"
    try:
        if MONGO_URI:
            collection()
            mode = "mongodb"
    except Exception:
        mode = "demo-fallback"
    return jsonify({"ok": True, "mode": mode, "reportCount": len(records())})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=False)
