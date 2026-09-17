# LRT Kelana Jaya Monitor

> An evidence-aware monitoring starter for the **Kelana Jaya Line** (KL rail transit). Combines **official daily
> ridership data** (data.gov.my) with **public Threads chatter** (crowding / delay / disruption signals) to explain
> *why* the line behaves the way it does - without ever presenting social gossip as official fact.

## Features

- **Bulk Threads collector** - keyword-driven scraping via an Apify SSR actor; ~300 curated queries; checkpointed
  chunk cache; deduplicated, LRT-filtered, classified signals stored in SQLite.
- **Data-quality pipeline** - five-stage filtering (recall → relevance → classification → station detection →
  de-duplication) keeps the corpus clean; re-scrapes never double-count.
- **Ridership x social analysis** - daily panel (Malaysia UTC+8), weekday/monthly seasonality, anomaly days,
  lagged correlation, and a weekday-driven ridge forecast with holdout MAE / MAPE / R².
- **Insights dashboard** - a publishable Streamlit app with five tabs: Overview, Seasonality & Anomalies,
  Social Signals, *Why crowded? & Shah Alam* (evidence-based causality check), Correlation & Forecast.
- **Live/status API** - FastAPI endpoints and an explainable status estimator.

**Disclaimer:** signals are estimates drawn from public posts; official Rapid KL statements take precedence.
Social numbers are sensors, not proof.

## Contents

- [Verified official source](#verified-official-source)
- [Run locally](#run-locally)
- [Collecting Threads posts](#collecting-threads-posts-kelana-jaya-lrt)
- [Bulk collection (2000+ posts)](#bulk-collection-2000-posts)
- [Insights dashboard](#insights-dashboard-social-x-ridership)
- [Data quality: how good posts are separated from bad](#data-quality-how-good-posts-are-separated-from-bad)
- [Project structure](#project-structure)
- [Data integrity](#data-integrity)

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
streamlit run dashboard/insights_app.py   # insights dashboard (recommended)
streamlit run dashboard/app.py            # demo live-status dashboard
uvicorn src.api.main:app --reload         # FastAPI status & signals API
```

API docs: http://127.0.0.1:8000/docs

> **Note:** use the virtual environment's Python (`py -m streamlit run ...` or activation) - the app needs
> the pinned `streamlit` / `altair` / `scikit-learn` versions in `requirements.txt`.

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
# Custom keywords, more depth
py -m src.collectors.threads_scraper -k "lrt kelana jaya" "kelana jaya line" --max-results 100
```

Defaults:

- Actor: `santamaria-automations/threads-search-scraper` (`THREADS_ACTOR_ID`)
  — read from Threads' server-rendered search page, which is more resilient than
  GraphQL `doc_id`-based actors that break when Meta rotates its internal keys
- Keywords: LRT Kelana Jaya variants incl. common misspellings (`THREADS_KEYWORDS`)
- 50 results per query (`THREADS_MAX_RESULTS_PER_QUERY`)
- Output: `data/lrt_monitor.db` + `data/processed/threads_*.json|csv`

What it does per result: keeps only posts whose text matches the LRT keyword
filter, classifies them (crowding/delay/disruption/other) with station mapping,
and deduplicates overlapping search results by author + text. Search is billed
per result by Apify (~$0.50 per 1,000 posts) and Threads keyword search without
login only reaches back about one month, so run it on a schedule for continuous
monitoring.

## Bulk collection (2000+ posts)

`src/collectors/threads_bulk.py` scales the same actor across 270+ keyword
combinations (line terms, commute vocabulary, every Kelana Jaya station, other KL
rail lines) with checkpointed chunk caches and parallel actor runs:

```powershell
py -m src.collectors.threads_bulk --chunk-size 20 --concurrency 3 --sleep 15
```

Flags: `--max-posts` (per query), `--fresh` (re-scrape everything), `--sleep`
(seconds between runs, raise it if Threads starts returning 0-result chunks).

- Raw unique posts are exported to `data/processed/threads_raw_*.csv` (all posts,
  pre-filter) alongside the classified LRT signal set.
- Costs credits on the Apify FREE plan ($5/month cap - the full 270-query pass
  costs ~$1-3). When the cap trips, actors return `x402 payment required` and
  scraping resumes automatically after the monthly reset or a top-up; chunk
  caches make re-runs cheap.

## Insights dashboard (social x ridership)

`dashboard/insights_app.py` merges the Threads corpus with Malaysia's official
daily ridership and is designed for publishing (Streamlit Community Cloud,
Streamlit Enterprise, or any container):

```powershell
streamlit run dashboard/insights_app.py
```

Tabs:

1. **Overview** - rail_lrt_kj headline indicators, YoY comparison, weekday bars.
2. **Seasonality & Anomalies** - weekday pattern, year-month heatmap, unusually
   low ridership days (holidays, MCO, disruptions).
3. **Social Signals** - daily posts by category, most-mentioned stations, most
   active authors, sample text.
4. **Why delays? & Shah Alam** - tests the "Shah Alam line launch caused KJ
   overcrowding" theory against the data (KJ June vs July 2026 vs July 2025,
   Shah Alam line ramp-up, maintenance/signalling mentions in the Sep 2026
   delay spike).
5. **Correlation & Forecast** - lagged Pearson correlation of disruption chatter
   vs ridership, same-day scatter, and a weekday-driven ridge forecast with
   holdout MAE / MAPE / R².

Data plumbing: `src/analysis/merged.py` (signals DB + gov CSV -> daily panel,
Malaysia UTC+8 bucketing) and `src/analysis/insights.py` (seasonality, anomaly
detection, lag correlation, ridge forecast). The official ridership series
(`data/ridership_headline.csv`) is the data.gov.my `ridership_headline`
catalogue (source: anonymous tap-in/out transaction data) and is published
~6-8 weeks behind, so the correlation view fills in automatically once the
series catches up to the Threads window.

## Data quality: how good posts are separated from bad

Every fetched post passes a five-stage pipeline. This is what keeps the corpus
meaningful and the numbers honest:

1. **Search recall** - the Apify actor returns whatever Threads search surfaces
   for a query. This is deliberately *loose*; we never trust the raw feed.
2. **Relevance gate** (`src/nlp/keyword_filter.py`) - a post is dropped unless
   its text mentions the rail line vocabulary: `lrt`, `rapid kl`, `kelana jaya`,
   `lrt kj`, `kuala kaya`. A post about a toast machine or a football crowd that
   happens to contain "lrt" nowhere is junk and never enters the database.
3. **Classification** (`src/nlp/classifier.py`) - surviving text is tagged
   `disruption` / `delay` / `crowding`, otherwise `other`. The `other` bucket is
   kept (it holds useful context) but is clearly separated from incident counts,
   so "delay" numbers are never inflated by casual chat.
4. **Station detection** (`src/processing/station_mapping.py`) - the Kelana Jaya
   station vocabulary is matched against the text, so complaints can be pinned
   to a station or left unassigned rather than guessed.
5. **De-duplication** - within a run, identical (author, text) posts from
   overlapping queries collapse to one. Since mid-2026, `add_signal` also skips
   anything already in the database, so re-scrapes never bloat the store (the
   live database was cleaned from 1,867 to 811 unique postings).

What is **not** filtered: sentiment, sarcasm, and whether the author is right.
A claim like "LRT always breaks on Wednesdays" is stored as a *signal*, never as
a *fact* - the dashboard labels all chatter as estimates and treats Rapid KL
official statements as authoritative.

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
