# LRT Kelana Jaya Monitor

An evidence-aware monitoring starter for the Kelana Jaya LRT Line. It combines historical demand, official operational facts, and public reports without presenting a prediction as official information.

## Current scope

Phase 1 provides a runnable vertical slice with:

- SQLite storage for official facts and public signals
- A deterministic status estimator with explainable rules
- Historical station-hour demand baseline using a labelled demo fixture
- FastAPI endpoints for the current status and recent signals
- Streamlit dashboard for local exploration
- Tests for the estimator and API contract

External data collectors are intentionally adapters only. Add credentials, rate-limit handling, provenance, and terms-of-use review before connecting a live source.

`data/external/demo_ridership.csv` is synthetic demonstration data, not an official Rapid Rail extract. Replace it only with a documented, lawfully obtained public dataset.

## Verified official source

Malaysia's official Open API documents the Prasarana GTFS static feed at `https://api.data.gov.my/gtfs-static/prasarana?category=rapid-rail-kl`. It is a schedule and network feed, not passenger counts. The current GTFS-Realtime documentation states that `rapid-rail-kl` does not yet have a stable realtime vehicle-position feed, so this project must not claim live train coverage until that changes.

The current feed was downloaded and parsed successfully on 2026-08-20: one Kelana Jaya route matched and 37 stations were mapped through `trips.txt` and `stop_times.txt`. The downloaded ZIP is kept under ignored `data/raw/` storage and is not committed as application source data.

The committed `data/external/kelana_jaya_stations.csv` is the derived station vocabulary used by the dashboard and public-signal validation.

The dashboard accepts uploads using `data/external/historical_ridership_template.csv` and `data/external/public_reports_template.csv`. Uploaded files are used for the current Streamlit session and are not automatically committed.

See `data/external/SOURCES.md` for source provenance, verification dates, and current data limitations.

## Run locally

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
uvicorn src.api.main:app --reload
streamlit run dashboard/app.py
```

API docs: http://127.0.0.1:8000/docs

## Collecting Threads posts (Kelana Jaya LRT)

`src/collectors/threads_scraper.py` searches Meta Threads by keyword through an
Apify actor and turns matching public posts into classified, LRT-filtered signals
stored in the SQLite database plus JSON/CSV exports under `data/processed/`.

Setup:

1. Create a free account at https://apify.com and copy your API token.
2. Copy `.env.example` to `.env` and set `APIFY_TOKEN`. Edit
   `THREADS_KEYWORDS` if you want different search phrases.

Run:

```powershell
py -m src.collectors.threads_scraper
```

Useful flags (defaults come from `.env`):

```powershell
# Custom keywords, more depth, include replies
py -m src.collectors.threads_scraper -k "lrt kelana jaya" "kelana jaya line" --max-results 100 --include-replies
```

Defaults:

- Actor: `magicfingers/threads-scraper` (`THREADS_ACTOR_ID`)
- Keywords: LRT Kelana Jaya variants incl. common misspellings (`THREADS_KEYWORDS`)
- 50 results per query (`THREADS_MAX_RESULTS_PER_QUERY`)
- Output: `data/lrt_monitor.db` + `data/processed/threads_*.json|csv`

What it does per result: keeps only posts whose text matches the LRT keyword
filter, classifies them (crowding/delay/disruption/other) with station mapping,
and deduplicates overlapping search results by author + text. Search is billed
per result by Apify ($0.50 per 1,000 posts on the default actor) and Threads
keyword search without login only reaches back about one month, so run it on a
schedule for continuous monitoring.

## Project structure

```text
lrt-kelana-jaya-monitor/
|-- data/raw/              # immutable source extracts
|-- data/processed/        # derived datasets
|-- src/
|   |-- api/main.py        # FastAPI application
|   |-- collectors/        # source-specific adapters
|   |-- nlp/               # signal classification
|   |-- processing/        # cleaning and feature engineering
|   |-- models.py          # facts, signals, and estimates
|   |-- status.py           # explainable status estimator
|   `-- storage.py          # SQLite repository
|-- dashboard/app.py       # Streamlit UI
`-- tests/
```

## Data integrity

- `FACT`: officially reported transport information.
- `SIGNAL`: an observation from a public post or other non-authoritative source.
- `ESTIMATION`: a model output based on available facts and signals.

One post is never treated as proof. Official disruption facts take precedence over social signals. Public data must be collected lawfully and employer or production data must not be uploaded.
