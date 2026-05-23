# Lead Extraction System — Setup & Usage Guide

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Folder Structure](#3-folder-structure)
4. [Prerequisites](#4-prerequisites)
5. [Backend Setup](#5-backend-setup)
6. [Frontend Setup](#6-frontend-setup)
7. [Browser Session Setup](#7-browser-session-setup)
8. [Running Scrapers](#8-running-scrapers)
9. [Export System](#9-export-system)
10. [Logs System](#10-logs-system)
11. [Common Errors](#11-common-errors)
12. [Safe Scraping Guidelines](#12-safe-scraping-guidelines)
13. [Recommended Workflow](#13-recommended-workflow)
14. [Production Notes](#14-production-notes)

---

## 1. Project Overview

### System Purpose

The Lead Extraction System automates business data collection from multiple online directories. It scrapes company profiles, contact details, and metadata from Clutch.co, GoodFirms.co, Google Maps, and LinkedIn. All collected data is normalized, deduplicated, and merged into a single master lead sheet for export.

### Architecture

The system has three interfaces that share the same scraping engine and configuration:

| Interface | Entry Point | Purpose |
|-----------|-------------|---------|
| CLI | `main.py` | Interactive menu for manual operation |
| REST API | `run_api.py` | HTTP server for remote control |
| Web Frontend | `frontend/` | Browser-based dashboard (talks to the API) |

The scraping engine uses Playwright to control a Chromium browser instance. Browser sessions are persisted to disk so authentication state survives restarts. Exported data lands in organized folders under `exports/`.

### Supported Scrapers

| Scraper | Source | Data Extracted |
|---------|--------|----------------|
| Clutch | clutch.co | Company name, website, profile URL, location, employee size, hourly rate, services, rating |
| GoodFirms | goodfirms.co | Same fields as Clutch plus platform-specific metadata |
| Google Maps | google.com/maps | Business name, website, phone, address, rating, review count, category |
| LinkedIn | linkedin.com | Company URL, founder name/role, company size (enrichment from existing CSV) |
| Merge | — | Combines all scraped outputs, deduplicates, generates master lead sheet |

---

## 2. Tech Stack

### Backend

| Layer | Technology | Role |
|-------|-----------|------|
| Language | Python 3.10+ | Core logic and automation |
| Browser Automation | Playwright (Chromium) | Drives browser for data extraction |
| Data Processing | Pandas | CSV/JSON/Parquet/Excel export and normalization |
| API Framework | FastAPI | REST endpoints for scraper control |
| Server | Uvicorn | ASGI server for FastAPI |
| Validation | Pydantic v2 | Request/response models |
| Excel Support | OpenPyXL | XLSX export fallback |
| Parquet Support | PyArrow | Parquet export |

### Frontend

| Layer | Technology |
|-------|-----------|
| Framework | React 18 |
| Build Tool | Vite 5 |
| Styling | Tailwind CSS 3 |
| HTTP Client | Axios |
| Routing | React Router v6 |
| Icons | Lucide React |

---

## 3. Folder Structure

```
lead_system/
├── main.py                     # CLI entry point — interactive menu
├── run_api.py                  # API server launcher
├── config.json                 # System configuration
├── config.backup.json          # Auto-generated backup of config
├── requirements.txt            # Python dependencies
│
├── api/
│   ├── __init__.py
│   └── server.py               # FastAPI application (all endpoints)
│
├── scrapers/
│   ├── __init__.py
│   ├── clutch.py               # Clutch.co scraper
│   ├── goodfirms.py            # GoodFirms.co scraper
│   ├── maps.py                 # Google Maps scraper
│   ├── linkedin.py             # LinkedIn enrichment
│   └── merge.py                # Merge engine — dedup + normalization
│
├── exports/
│   ├── clutch/                 # Raw Clutch scrapes (CSV)
│   ├── goodfirms/              # Raw GoodFirms scrapes (CSV)
│   ├── maps/                   # Raw Maps scrapes (CSV)
│   ├── linkedin/               # Raw LinkedIn enrichments (CSV)
│   └── merged/                 # Master merged lead sheets (CSV)
│
├── logs/
│   └── system.log              # Rotating application log
│
├── sessions/
│   └── auth_state.json         # Saved browser cookies/auth state
│
├── screenshots/                # Debug screenshots from scrapers
│
├── frontend/
│   ├── src/                    # React application source
│   │   ├── components/         # UI components
│   │   ├── pages/              # Route pages
│   │   └── App.tsx             # Root component
│   ├── dist/                   # Production build output
│   ├── package.json
│   └── vite.config.ts
│
├── temp/                       # Temporary working files
│
└── docs/
    └── SETUP.md                # This document
```

### What Each Folder Does

**`exports/`** — All scraped output lands here, organized by source. Each subfolder contains timestamped CSV files. The `merged/` folder holds the final deduplicated master sheet.

**`logs/`** — Contains `system.log` with rotating file handlers (10 MB per file, 5 backups). Both CLI and API write to the same log file.

**`sessions/`** — Stores browser authentication state (`auth_state.json`). After you log into LinkedIn or Google manually once, the cookies are saved here and reloaded on subsequent runs.

**`screenshots/`** — Scrapers can capture screenshots for debugging. Each file is named with a timestamp and a label.

**`frontend/`** — Standalone React application. The development server runs on port 5173. The production build in `dist/` can be served statically.

**`api/`** — Single-file FastAPI application. All routes, models, and background task management live in `server.py`.

**`scrapers/`** — One file per data source plus the merge engine. Each scraper exports an async function that accepts a Playwright browser context, logger, and config dict.

---

## 4. Prerequisites

### Windows

```powershell
# Verify Python (3.10 or higher)
python --version

# Verify Node.js (18 or higher)
node --version

# Verify npm
npm --version
```

### macOS / Linux

```bash
python3 --version
node --version
npm --version
```

### Install Python (if missing)

Download from https://www.python.org/downloads/. On Windows, check **"Add Python to PATH"** during installation.

### Install Node.js (if missing)

Download from https://nodejs.org/. The LTS version is recommended.

---

## 5. Backend Setup

### Step 1: Navigate to the project

```bash
cd lead_system
```

### Step 2: Create a virtual environment

```bash
# Windows (PowerShell)
python -m venv venv

# macOS / Linux
python3 -m venv venv
```

### Step 3: Activate the virtual environment

```bash
# Windows (PowerShell)
venv\Scripts\Activate

# Windows (Command Prompt)
venv\Scripts\activate.bat

# macOS / Linux
source venv/bin/activate
```

Your terminal prompt should now show `(venv)`.

### Step 4: Install Python dependencies

```bash
pip install -r requirements.txt
```

This installs Playwright, Pandas, FastAPI, Uvicorn, Pydantic, OpenPyXL, and PyArrow.

### Step 5: Install Playwright browser

```bash
playwright install chromium
```

This downloads the Chromium browser binary that Playwright controls. The download is roughly 300 MB.

### Step 6: Verify the installation

```bash
python -c "import playwright; import pandas; import fastapi; print('All dependencies OK')"
```

---

## 6. Frontend Setup

### Step 1: Install frontend dependencies

```bash
cd frontend
npm install
```

### Step 2: Start the development server

```bash
npm run dev
```

The Vite dev server starts at `http://localhost:5173`. It proxies API requests to `http://127.0.0.1:8000`.

### Production Build

```bash
npm run build
```

Output goes to `frontend/dist/`. You can serve this folder with any static file server.

---

## 7. Browser Session Setup

The system uses a persistent Chromium browser profile. This means cookies, local storage, and authentication state are saved to disk and reused across runs.

### First-Time Manual Login

1. Start the CLI: `python main.py`
2. Select option **1 — Setup Browser Session**
3. A Chromium window opens
4. Type `y` when asked about manual login
5. You have **120 seconds** to log into any sites you plan to scrape:
   - For **LinkedIn**: navigate to linkedin.com and sign in
   - For **Google Maps**: sign into your Google account if needed
   - Press **Ctrl+C** when done, or wait for the timer to expire
6. The session state (cookies) is saved to `sessions/auth_state.json`

### Session Reuse

On subsequent runs, saved cookies are automatically loaded. You do not need to log in again unless the session expires.

The API server (`run_api.py`) also uses the same session state file, so authentication works across both CLI and web interfaces.

### When to Re-Login

- LinkedIn session expires after a few hours of inactivity
- Google sessions may require re-authentication after browser updates
- If scrapers start hitting login walls or redirects to login pages

To re-login, simply run the CLI, set up a new browser session, and choose manual login again.

---

## 8. Running Scrapers

### Via the CLI Menu

```bash
python main.py
```

The menu shows:

```
=======================================================
   LEAD EXTRACTION SYSTEM — MAIN MENU
=======================================================
   Browser Session: INACTIVE
-------------------------------------------------------
   1. Setup Browser Session
   2. Run Clutch Scraper
   3. Run GoodFirms Scraper
   4. Run Google Maps Scraper
   5. Run LinkedIn Enrichment
   6. Merge All Leads
   7. Exit
=======================================================
```

**Standard workflow:**

1. Select **1** to start the browser session
2. Optionally complete manual login when prompted
3. Select a scraper (**2-5**)
4. Enter your search query and page limits when prompted
5. Let the scraper run — progress appears in the console
6. Select **6** to merge all collected data
7. Find the output in `exports/merged/`

### Via the API Server

```bash
python run_api.py
```

The server starts on `http://127.0.0.1:8000`. Available endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/start/clutch` | Start Clutch scraper |
| POST | `/start/goodfirms` | Start GoodFirms scraper |
| POST | `/start/maps` | Start Maps scraper |
| POST | `/start/linkedin` | Start LinkedIn enrichment |
| POST | `/merge` | Start merge pipeline |
| POST | `/stop/{source}` | Stop a running scraper |
| GET | `/status` | Task status |
| GET | `/logs` | Tail system logs |
| GET | `/exports` | List export files |
| GET | `/download/{path}` | Download a file |
| DELETE | `/export/{path}` | Delete an export |
| GET | `/settings` | View config |
| POST | `/settings` | Update config |
| GET | `/health` | Health check |

**Example — start Clutch scraper:**

```bash
curl -X POST "http://127.0.0.1:8000/start/clutch" \
  -H "Content-Type: application/json" \
  -d '{"query": "web development agencies USA", "max_pages": 5}'
```

**Example — check task status:**

```bash
curl "http://127.0.0.1:8000/status"
```

**Example — download merged export:**

```bash
# Get the file listing
curl "http://127.0.0.1:8000/exports"

# Download a specific file (use the path from the listing)
curl -OJ "http://127.0.0.1:8000/download/exports/merged/20260210_123456_master_leads.csv"
```

### Via the Web Frontend

1. Start the API server: `python run_api.py`
2. Start the frontend dev server: `cd frontend && npm run dev`
3. Open `http://localhost:5173` in your browser
4. The dashboard shows scraper cards for each source
5. Enter your search query and page count
6. Click **Start** to begin scraping
7. Monitor progress in the task status panel
8. Download exports from the exports list

---

## 9. Export System

### Raw Exports

Each scraper writes timestamped CSV files to its dedicated folder:

```
exports/clutch/     → 20260210_143021_clutch_results.csv
exports/goodfirms/  → 20260210_150012_goodfirms_results.csv
exports/maps/       → 20260210_154523_maps_results.csv
exports/linkedin/   → 20260210_160045_linkedin_enrichment.csv
```

### Merge Engine

The merge engine (`scrapers/merge.py`) performs the following steps:

1. Scans all four export directories for CSV files
2. Normalizes column names to a common schema
3. Deduplicates rows using this priority:
   - Exact website match (primary)
   - Exact phone number match (secondary)
   - Fuzzy company name match (tertiary)
4. Adds a `source_platform` column indicating origin
5. Generates per-platform statistics
6. Outputs the master file to `exports/merged/`

### Master Export Schema

| Column | Description |
|--------|-------------|
| `company_name` | Business name |
| `website` | Website URL (normalized) |
| `phone` | Phone number (stripped of formatting) |
| `email` | Email address (if available) |
| `linkedin` | LinkedIn company URL |
| `location` | Geographic address |
| `source_platform` | Origin: clutch, goodfirms, maps, or linkedin |

### Supported Formats

The export format is controlled by `export.format` in `config.json`:

- `csv` (default) — UTF-8 with BOM for Excel compatibility
- `json` — Array of records, pretty-printed
- `parquet` — Columnar format for large datasets
- `xlsx` — Excel workbook (requires openpyxl)

---

## 10. Logs System

### Log Location

All logs write to `logs/system.log`. Both the CLI and API server use the same file.

### Log Format

```
2026-02-10 14:30:21 | INFO     | lead_system | Browser context created successfully
2026-02-10 14:30:22 | INFO     | scrapers.clutch | Starting Clutch scraper for query: web agencies
2026-02-10 14:30:25 | WARNING  | scrapers.maps | Captcha detected on page 3, retrying...
2026-02-10 14:31:00 | INFO     | main.export | Exported 47 rows to exports/merged/...
```

### Log Levels

| Level | When It Appears |
|-------|-----------------|
| DEBUG | Detailed scraper step info (configurable) |
| INFO | Normal operation — session creation, scraper start/end, exports |
| WARNING | Non-fatal issues — retry attempts, missing session state, config fallback |
| ERROR | Failures — navigation errors, export failures, scraper crashes |

### Viewing Logs

**Via the CLI:** Open `logs/system.log` in any text editor.

**Via the API:** `GET /logs?lines=200` returns the last 200 lines as JSON. Supports filtering by source:

```bash
curl "http://127.0.0.1:8000/logs?lines=100&source=clutch"
```

**Via the frontend:** The dashboard has a log viewer panel that tails the log file.

### Log Rotation

- Maximum file size: 10 MB
- Backup count: 5
- When the log reaches 10 MB, it is renamed to `system.log.1`, and a new `system.log` is created
- The five most recent rotated files are kept

---

## 11. Common Errors

### Playwright browser errors

**"Playwright module not found"**

The `playwright install chromium` step was skipped. Run it from your virtual environment.

**"Browser closed unexpectedly"**

- The Chromium process crashed. This is usually a resource issue.
- Reduce `browser.concurrency` to 1 in `config.json`
- Restart the system

**"Playwright executable not found"**

```bash
playwright install chromium
```

If that fails, try:

```bash
playwright install --force chromium
```

### CORS issues

**Frontend cannot reach API (CORS errors in browser console)**

- Ensure the API server is running on port 8000
- The API has CORS middleware configured to allow specific origins (see `config.json` `api.allowed_origins`)
- If running on a different port, update the Vite proxy config in `frontend/vite.config.ts`

### Session expiration

**Scrapers are redirected to login pages**

- The saved session has expired
- Re-run manual login via the CLI menu
- LinkedIn sessions typically expire after a few hours of inactivity

**"No active browser session"**

- You must select option **1** (Setup Browser Session) before running scrapers
- Or, if using the API, the server auto-creates a session on the first request

### CSV locked errors

**"Permission denied" or "File in use" when exporting**

- You (or another process) have the CSV file open in Excel
- Close Excel and re-run the scraper
- The system retries exports but cannot overwrite an open file

### Scraper timeout issues

**Scrapers hang or take too long**

Check `config.json`:

```json
{
  "browser": {
    "timeout": 30000,
    "retry_count": 3,
    "min_delay": 1.0,
    "max_delay": 3.0
  }
}
```

- Increase `timeout` (value is in milliseconds) for slow connections
- Reduce `max_pages` or `max_cycles` to limit total run time
- Reduce `max_delay` to speed up between-page waits

### Frontend API connection issues

**"Failed to fetch" or "Network Error" in the browser**

- Verify the API is running on `http://127.0.0.1:8000`
- Verify the frontend is running on `http://localhost:5173`
- Check that no firewall is blocking the connection
- Restart both servers

**Blank page or white screen in frontend**

- Open the browser developer console (F12) to see errors
- Common cause: the API server URL is misconfigured in the proxy settings
- Try rebuilding the frontend: `npm run build`

---

## 12. Safe Scraping Guidelines

### Respect rate limits

The system includes built-in random delays between actions (`min_delay` / `max_delay` in config.json). Do not set these below 1 second. Aggressive scraping will get your IP blocked.

### Keep the browser visible

Set `browser.headless` to `false` during development. This lets you see what the scraper is doing and detect CAPTCHAs or layout changes immediately.

### Limit pagination

| Scraper | Recommended Max |
|---------|----------------|
| Clutch.co | 10 pages |
| GoodFirms.co | 10 pages |
| Google Maps | 30 scroll cycles |
| LinkedIn | 50 companies per batch |

Exceeding these limits increases the chance of detection without significantly improving data quality.

### Avoid peak hours

Run scrapers during off-peak hours (evenings, weekends) to reduce load on target sites and avoid triggering rate limits.

### Monitor the logs

Check `logs/system.log` after each run. Look for:

- Repeated WARNING messages — may indicate site structure changes
- ERROR messages — investigate and fix before scaling up
- CAPTCHA detections — take a break or rotate IP

---

## 13. Recommended Workflow

A complete lead generation cycle using this system:

1. **Configure settings** — Edit `config.json`. Set `headless: false`, adjust delays, confirm export format.

2. **Set up browser session** — Run the CLI, start a browser session, and complete manual login for LinkedIn and Google.

3. **Run Clutch scraper** — Search for providers in your target industry and location (e.g., "mobile app developers London"). Limit to 5-10 pages.

4. **Run GoodFirms scraper** — Same query. GoodFirms often returns different results even for the same keyword.

5. **Run Google Maps scraper** — Use natural language queries ("web design agencies in Chicago"). Set scroll cycles to 20-30.

6. **Verify raw exports** — Check `exports/clutch/`, `exports/goodfirms/`, and `exports/maps/` for the CSV files.

7. **Run LinkedIn enrichment** — The merge engine can feed company names into LinkedIn lookup. Alternatively, prepare a CSV with company names and run the LinkedIn scraper.

8. **Merge all leads** — Select option 6 in the CLI or call `POST /merge` via the API. The merge engine deduplicates and produces the master file.

9. **Download the master sheet** — Find it in `exports/merged/`. The filename contains a timestamp for version tracking.

10. **Start outreach** — The final CSV contains company name, website, phone, LinkedIn URL, and location — ready for CRM import or email campaigns.

---

## 14. Production Notes

### Selector fragility

Scrapers rely on CSS selectors and XPath expressions that match the current HTML structure of target sites. These break when sites update their markup. If a scraper stops finding data, check for:

- Changed class names or HTML structure
- New cookie consent dialogs
- Different pagination mechanisms
- JavaScript-rendered content that requires different wait strategies

Fixing a broken selector usually requires inspecting the page in Chrome DevTools and updating a handful of strings in the scraper file.

### LinkedIn scraping limitations

LinkedIn aggressively protects its data. The LinkedIn enrichment scraper:

- Requires a valid, logged-in session
- Uses longer delays between profile lookups
- May hit rate limits after 50-100 lookups
- Cannot bypass LinkedIn's login walls or challenge pages
- Works best for enrichment (looking up known companies) rather than bulk discovery

### Google Maps anti-bot behavior

Google Maps may show CAPTCHAs or rate-limit notifications after sustained scraping. The maps scraper detects some of these and logs warnings, but you may need to:

- Reduce `max_cycles` to stay under the radar
- Switch to a residential IP
- Wait 15-30 minutes between heavy scraping sessions
- Use the visible browser mode to solve CAPTCHAs manually when they appear

### Maintenance expectations

- Target sites change their HTML regularly — expect selectors to break every few months
- Playwright browser updates may change behavior — pin the version in requirements.txt
- LinkedIn's authentication flow changes frequently — session management may need updates
- Google Maps API changes may affect infinite scroll behavior

### Configuration backups

The system automatically copies `config.json` to `config.backup.json` before overwriting settings via the API. If a config update corrupts the file, restore from the backup.
