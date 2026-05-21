# Lead Extraction System

A comprehensive lead generation and data enrichment platform that scrapes business data from multiple online directories, enriches it via LinkedIn, and merges everything into a unified master lead sheet. Built with Python (Playwright, FastAPI, Pandas) and a React-based frontend.

---

## Architecture

```
lead_system/
├── main.py                 # CLI entry point (interactive menu)
├── run_api.py              # API launcher for the FastAPI server
├── config.json             # System configuration (browser, logging, export)
├── api/
│   └── server.py           # FastAPI server with REST endpoints
├── scrapers/
│   ├── clutch.py           # Clutch.co scraper
│   ├── goodfirms.py        # GoodFirms.co scraper
│   ├── maps.py             # Google Maps scraper
│   ├── linkedin.py         # LinkedIn company enrichment
│   └── merge.py            # Master merge engine (dedup + normalize)
├── frontend/               # React + Vite + Tailwind CSS SPA
│   ├── src/                # Application source
│   └── dist/               # Production build
├── exports/                # Scraped output organized by source
│   ├── clutch/
│   ├── goodfirms/
│   ├── maps/
│   ├── linkedin/
│   └── merged/
├── logs/                   # Rotating log files
├── screenshots/            # Debug screenshots
├── sessions/               # Browser authentication state
└── temp/                   # Temporary working files
```

---

## Features

### Data Sources
- **Clutch.co** — Scrape business profiles, services, ratings, hourly rates, employee size, location
- **GoodFirms.co** — Scrape provider listings with detailed metadata
- **Google Maps** — Scrape local business listings with name, phone, address, rating, reviews, website
- **LinkedIn** — Enrich existing company lists with LinkedIn profile URLs, founder info, company size

### Data Processing
- **Merge Engine** — Combines all scraped data into a normalized schema
- **Smart Deduplication** — Removes duplicates by website, phone, and company name
- **Statistics** — Per-platform breakdown, coverage analysis, export summary
- **Export Formats** — CSV, JSON, Parquet, Excel (XLSX)

### Interfaces

| Interface | Description |
|-----------|-------------|
| **CLI** (`main.py`) | Interactive text menu with guided workflows |
| **REST API** (`run_api.py`) | FastAPI server with full CRUD for scrapers, config, exports, logs |
| **Web Frontend** (`frontend/`) | React SPA with real-time task monitoring |

---

## Installation

### Prerequisites

- Python 3.10+
- Node.js 18+ (for frontend development)
- Google Chrome / Chromium (required by Playwright)

### Backend Setup

```bash
# Clone the repository
cd lead_system

# Create a virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\Activate
# Linux/macOS:
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### Frontend Setup (Optional)

```bash
cd frontend
npm install
npm run build      # Production build
# or
npm run dev        # Development server
```

---

## Configuration

All system settings are managed through `config.json`:

```json
{
  "browser": {
    "headless": true,
    "timeout": 5000,
    "retry_count": 2,
    "min_delay": 1.0,
    "max_delay": 5.0,
    "concurrency": 2,
    "viewport_width": 1920,
    "viewport_height": 1080,
    "locale": "en-US",
    "timezone_id": "America/New_York"
  },
  "session": {
    "storage_path": "sessions",
    "state_file": "auth_state.json",
    "auto_save": true
  },
  "export": {
    "format": "csv",
    "encoding": "utf-8-sig"
  },
  "logging": {
    "level": "WARN",
    "file": "logs/system.log",
    "max_bytes": 10485760,
    "backup_count": 5
  },
  "paths": {
    "exports": "exports",
    "screenshots": "screenshots",
    "temp": "temp",
    "sessions": "sessions"
  }
}
```

### Key Settings

| Setting | Description |
|---------|-------------|
| `browser.headless` | Run browser in headless mode (no GUI) |
| `browser.timeout` | Navigation timeout in milliseconds |
| `browser.min_delay` / `max_delay` | Random delay range between actions (human-like behavior) |
| `browser.retry_count` | Number of navigation retries on failure |
| `export.format` | Output format: `csv`, `json`, `parquet`, `xlsx` |
| `logging.level` | Log level: `DEBUG`, `INFO`, `WARN`, `ERROR` |

---

## Usage

### CLI Mode

```bash
python main.py
```

Navigates the interactive menu:

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

**Workflow:**
1. Start with **Option 1** to create a browser session
2. Optionally perform **manual login** for authenticated sites (LinkedIn)
3. Run scrapers (**Options 2-4**) — each prompts for query and pagination limits
4. Run LinkedIn enrichment (**Option 5**) — reads a CSV of companies
5. Merge everything (**Option 6**) — deduplicates and exports master_leads.csv

### API Server

```bash
python run_api.py
```

Starts the FastAPI server (default: `http://127.0.0.1:8000`).

#### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/start/clutch` | Start Clutch.co scraping |
| `POST` | `/start/goodfirms` | Start GoodFirms.co scraping |
| `POST` | `/start/maps` | Start Google Maps scraping |
| `POST` | `/start/linkedin` | Start LinkedIn enrichment |
| `POST` | `/start/merge` | Start merge pipeline |
| `POST` | `/stop/{source}` | Stop a running scraper |
| `GET`  | `/status` | Task status (all or by task_id) |
| `GET`  | `/logs` | Tail system logs |
| `GET`  | `/exports` | List exported files |
| `GET`  | `/download/{path}` | Download an export file |
| `DELETE` | `/export/{path}` | Delete an export file |
| `GET`  | `/settings` | Get current configuration |
| `POST` | `/settings` | Update configuration |
| `GET`  | `/health` | Health check |

#### Example: Start Clutch Scraper

```bash
curl -X POST "http://127.0.0.1:8000/start/clutch" \
  -H "Content-Type: application/json" \
  -d '{"query": "marketing agencies USA", "max_pages": 5}'
```

### Frontend

```bash
cd frontend
npm run dev
```

Access the web interface at `http://localhost:5173` (or the Vite dev server URL). The frontend communicates with the API server and provides a dashboard for running scrapers, monitoring tasks, and downloading exports.

---

## Scrapers Detail

### Clutch.co Scraper
- **Source:** `scrapers/clutch.py`
- Searches Clutch.co for service providers
- Extracts: company name, website, profile URL, location, employee size, hourly rate, services, rating
- Supports pagination up to a configurable maximum

### GoodFirms.co Scraper
- **Source:** `scrapers/goodfirms.py`
- Searches GoodFirms.co for company listings
- Same data fields as Clutch plus platform-specific metadata
- Configurable pagination, cookie consent handling

### Google Maps Scraper
- **Source:** `scrapers/maps.py`
- Searches Google Maps using natural language queries
- Extracts: business name, website, phone, address, rating, review count, category
- Infinite-scroll support with configurable scroll cycles
- Captcha detection with graceful degradation

### LinkedIn Enrichment
- **Source:** `scrapers/linkedin.py`
- Reads a CSV with `company_name` (and optional `website`) columns
- Searches LinkedIn for each company
- Extracts: LinkedIn company URL, founder name/role, company size
- Deliberately throttled to avoid rate-limiting
- Detects login walls, rate limits, and challenge pages

### Merge Engine
- **Source:** `scrapers/merge.py`
- Scans all export directories for CSV files
- Normalizes data into a unified schema
- Deduplicates by website → phone → company name priority
- Generates per-platform statistics and coverage report
- Outputs `master_leads.csv` to `exports/merged/`

---

## Export Schema

After merging, the master file contains these normalized columns:

| Column | Description |
|--------|-------------|
| `company_name` | Business name |
| `website` | Website URL (normalized) |
| `phone` | Phone number (stripped) |
| `email` | Email address (if available) |
| `linkedin` | LinkedIn company URL |
| `location` | Geographic location / address |
| `source_platform` | Origin: `clutch`, `goodfirms`, `maps`, or `linkedin` |

---

## Logging

- **File:** `logs/system.log` (rotating, 10 MB per file, 5 backups)
- **Console:** stdout with INFO+ level
- **Format:** `YYYY-MM-DD HH:MM:SS | LEVEL | LoggerName | Message`

---

## Development

### Frontend Build

```bash
cd frontend
npm run build       # Production build to dist/
npm run preview     # Preview the production build
```

### Adding a New Scraper

1. Create `scrapers/<name>.py` with an `async def run_<name>_scraper(context, logger, cfg)` function
2. Import and register it in `main.py` (menu) and `api/server.py` (endpoint)
3. Add the export subdirectory to `REQUIRED_DIRS` in `main.py`

---

## Dependencies

### Python
- **playwright** — Browser automation (Chromium)
- **pandas** — Data processing and export
- **fastapi / uvicorn** — REST API server
- **openpyxl** — Excel export support
- **pydantic** — Request/response validation

### Frontend (Node.js)
- **React 18** — UI framework
- **Vite 5** — Build tool
- **Tailwind CSS 3** — Utility-first styling
- **Axios** — HTTP client
- **React Router v6** — Client-side routing
- **Lucide React** — Icons

---

## License

This project is for internal use. All scraping activities must comply with the terms of service of the respective platforms.
