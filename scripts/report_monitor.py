"""Discover report links in the annual-security-reports README and sample cache metrics."""
import argparse
import re
import time
from urllib.parse import unquote

import requests
from pymongo import MongoClient

README_URL = "https://raw.githubusercontent.com/jacobdjwilson/awesome-annual-security-reports/main/README.md"
REPO_URL = "https://github.com/jacobdjwilson/awesome-annual-security-reports/"
LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
REPORT_WORDS = re.compile(r"report|assessment|threat|security|survey|breach|adversary", re.I)


def cache_snapshot(db):
    wt = db.command("serverStatus").get("wiredTiger", {}).get("cache", {})
    normalized = {k.lower().replace("_", " "): v for k, v in wt.items()}
    def get(*keys):
        return next((normalized[k] for k in keys if k in normalized), 0)
    return (get("pages requested from the cache"), get("pages read into cache"),
            get("bytes currently in the cache"), get("maximum bytes configured"))


def discover(session):
    response = session.get(README_URL, timeout=12)
    response.raise_for_status()
    found = {}
    for title, url in LINK_RE.findall(response.text):
        if REPORT_WORDS.search(title) and ("pdf" in url.lower() or "annual-security-reports" in url.lower()):
            found[url] = title.strip()
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default="mongodb://localhost:27017")
    parser.add_argument("--database", default="cti_lab")
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    client = MongoClient(args.uri, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    db = client[args.database]
    reports = db.reports
    session = requests.Session()
    session.headers["User-Agent"] = "Signal-CTI-Lab7/1.0 (educational report discovery)"
    previous = None
    seen = set()
    try:
        while True:
            now = time.strftime("%Y-%m-%d %H:%M:%S %Z")
            try:
                candidates = discover(session)
                stored = {r.get("source", {}).get("url") for r in reports.find({}, {"source.url": 1})}
                fresh = [(u, t) for u, t in candidates.items() if u not in stored and u not in seen]
                print(f"[{now}] source entries={len(candidates)}; newly discovered={len(fresh)}")
                for url, title in fresh[:20]:
                    print(f"  REVIEW: {title} — {url}")
                    seen.add(url)
            except Exception as exc:
                print(f"[{now}] discovery error: {exc}")
            try:
                requested, read, current, maximum = cache_snapshot(db)
                ratio = None
                if previous:
                    req_delta = max(0, requested - previous[0])
                    read_delta = max(0, read - previous[1])
                    if req_delta:
                        ratio = max(0, 1 - read_delta / req_delta) * 100
                ratio_text = f"{ratio:.1f}%" if ratio is not None else "warming up"
                print(f"  WiredTiger interval hit estimate={ratio_text}; cache={current/1048576:.1f}/{maximum/1048576:.1f} MiB; cumulative pages requested/read={requested:,}/{read:,}")
                previous = requested, read
            except Exception as exc:
                print(f"  serverStatus unavailable: {exc}")
            if args.once:
                break
            time.sleep(max(10, args.interval))
    finally:
        client.close()


if __name__ == "__main__":
    main()
