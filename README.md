# Signal / CTI Desk — Labs 7-11

A small Cyber Threat Intelligence research desk that combines the Lab 7 activities with Lab 10 multi-document transactions and Lab 11 sharding demonstrations.

## Run it

1. Install Python 3.10+ and run `python -m pip install -r requirements.txt`.
2. Set `MONGODB_URI` to a MongoDB connection string and `MONGODB_DATABASE` (default `cti_lab`) in `.env`. The app loads `.env` automatically and uses MongoDB live mode when the connection succeeds. Without a URI, it runs in clearly marked demo mode.
3. Start with `python app.py`, then open <http://127.0.0.1:5000>.

## Deploy to Vercel

Vercel can deploy this Flask app as a serverless function. The frontend assets live under `public/static/` so Vercel can serve them from its CDN; `app.py` exposes the Flask `app` entry point.

1. Push this project to a GitHub repository (create a new repository, then use `git init`, `git add .`, `git commit -m "Prepare Lab 7 CTI app"`, and add/push to your repository's remote). `.gitignore` keeps local environments and secrets out of Git.
2. In Vercel, choose **Add New → Project**, import that GitHub repository, and leave the detected Flask framework/build settings as-is. Deploy.
3. For persistent classifications, create a MongoDB Atlas database and add `MONGODB_URI` and `MONGODB_DATABASE` (`cti_lab`) under **Project Settings → Environment Variables** in Vercel. Redeploy after saving the variables. Keep the URI private; do not commit it to GitHub. Without MongoDB, the site works in demo mode, but classification changes are not durable across serverless instances.

Vercel recognizes Flask apps from `app.py` and serves files in `public/`; `vercel.json` includes the templates, documentation, and seed data used at runtime. See [Vercel's Flask deployment guide](https://vercel.com/docs/frameworks/backend/flask). GitHub Pages alone cannot run this Python API, so use Vercel for the complete app.

In MongoDB mode, the app creates useful indexes and seeds the sample intelligence records only when the collection is empty. Classifications are analyst judgments attached to a report-source pair. See `docs/lab-analysis.md` for the design rationale, BSON sizing pipeline, limitations, and activity answers. `scripts/working_set.py` creates and randomly reads 100,000 approximately 2 KB documents; `scripts/report_monitor.py` checks the annual-report repository for new report entries every ten seconds and prints WiredTiger cache hit ratio when MongoDB is configured.

## Lab 10: transactions

Use the unified Docker Compose file to start the app, the Lab 10 replica set, and the Lab 11 sharded cluster: `docker compose up --build -d`. Run the transactions with `docker compose run --rm app python scripts/lab10_transactions.py all`. Lab 10 instructions and concurrency variants are in `docs/lab10.md`.

## Lab 11: sharding

Run the Lab 11 analysis on the same Compose cluster with `docker compose --profile lab11 run --rm lab11`. See `docs/lab11.md` for the key-selection matrix, resharding notes, and observed results. The combined project image is published at [`krish1226/lab10:lab11`](https://hub.docker.com/r/krish1226/lab10). The combined submission sheet is `docs/labs-7-11-submission.pdf`.

## Data provenance

The report catalog is a small hand-curated teaching sample based on public report listings and CTIDigest's public site. It stores metadata and original links only, not report PDFs or copied report text. Each record has a citation URL. The app never asserts that a publisher has called its report a malicious threat: threat determinations are editable local analyst assessments.

## Project layout

- `app.py`, `templates/`, `static/`: search and classification platform.
- `data/reports.json`: offline sample records.
- `scripts/`: working-set generator, cache sampler and discovery monitor.
- `docs/lab-analysis.md`: answers and lab methodology.
