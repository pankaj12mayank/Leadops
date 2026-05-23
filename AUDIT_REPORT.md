# Leadops Project — End-to-End Deep Audit Report

**Date:** 2026-05-23  
**Audit Scope:** Full codebase audit — backend (Python/FastAPI/Playwright), frontend (React/Vite/TypeScript), scrapers, config, project structure, security, performance, maintainability  
**Total Files Analyzed:** 45+ source files  
**Total Lines Analyzed:** ~5,500+ lines of source code  

---

# LAYER 1: CRITICAL — Security & Infrastructure (10 Tasks)

---

### T1.1 [CRITICAL] No `.gitignore` → Sensitive Data Leakage

**Issue:** No `.gitignore` file exists. The following sensitive/transient data is tracked in git:
- `sessions/api_profile/` — Full Chrome profile with cookies, cache, login state, browsing history, localStorage
- `__pycache__/` directories — Python bytecode
- `logs/system.log` — Operational logs with query/session details
- `frontend/node_modules/` — NPM dependencies (already tracked in git history)
- `.vite/` cache directory
- `config.backup.json` / `config.json.bak` — Config backups with potential credential exposure

**Evidence:**
- `git status` shows dozens of session cache files being tracked
- `sessions/api_profile/Default/Cookies`, `Login Data`, `Network/Cookies` tracked
- git commit `729abe6` initial commit includes all of these

**Solution:**
- Create `.gitignore` with entries for: `__pycache__/`, `*.pyc`, `venv/`, `.venv/`, `node_modules/`, `sessions/`, `logs/`, `.env`, `config.backup.json`, `config.json.bak`, `*.tmp.json`, `frontend/dist/`, `.vite/`, `screenshots/`, `temp/`, `exports/`
- Run `git rm --cached` to remove tracked sensitive files from index
- Consider rotating any credentials that were in the session data

---

### T1.2 [CRITICAL] Hardcoded File Paths → Config Loading Fails

**Issue:** `logs/system.log` shows consistent config loading failures:
```
Config load failed ([Errno 2] No such file or directory: 'D:\\Py_Projects\\lead_system\\config.json')
```
The project was moved from `lead_system` to `Leadops` but config backup fallback mechanism has inconsistent behavior. The main.py `_load_config()` uses a different backup strategy than `api/server.py`. Config files contain `strict=True` JSON parsing that fails on backups with strict formatting differences.

**Evidence:** `logs/system.log:1-14` — 7 config load failures in a single session

**Solution:**
- Use relative/resolved paths (already done with `BASE_DIR`) — verify cross-platform compatibility
- Unify config loading strategy between `main.py` and `api/server.py` (currently duplicated)
- Add config schema validation on load with clear error messages
- Remove stale backup files: `config.backup.json` and `config.json.bak` serve the same purpose but diverge in content

---

### T1.3 [CRITICAL] Open CORS with Credentials → CSRF/Security Risk

**Issue:** `api/server.py:68-74`:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,  # CRITICAL: Cannot be "*" with credentials=True
    allow_methods=["*"],
    allow_headers=["*"],
)
```
Combining `allow_origins=["*"]` with `allow_credentials=True` is a known security violation. Browsers will reject this (CORS spec violation), but more importantly, during development this opens the API to any origin sending credentialed requests.

**Solution:**
- Set explicit allowed origins for production (e.g., `["http://localhost:5173", "http://localhost:4173"]`)
- For production, use the actual frontend domain
- Document how to configure origins for deployment

---

### T1.4 [CRITICAL] Playwright Security Bypasses Enabled

**Issue:** `main.py:255-257` and `api/server.py:306-308`:
```python
bypass_csp=True,
ignore_https_errors=True,
```
- `bypass_csp=True` disables Content Security Policy — makes browser vulnerable to XSS
- `ignore_https_errors=True` disables SSL verification — susceptible to MITM attacks

**Solution:**
- Set both to `False` unless explicitly needed for specific scraping targets
- If needed, add config-level flags with warnings when enabled
- Document why these are enabled (some scraped sites have broken HTTPS certs)

---

### T1.5 [HIGH] No API Authentication → Unrestricted Access

**Issue:** All API endpoints (`/start/*`, `/settings`, `/download/*`, `/delete/*`) have zero authentication or authorization. Any process on the network can:
- Start/stop scrapers
- Download/delete export files
- Read/modify system configuration
- Execute arbitrary browser automation

**Solution:**
- Add API key authentication via header (`X-API-Key`)
- Add optional basic auth for production deployments
- Implement role-based access for destructive operations
- Add rate limiting middleware

---

### T1.6 [HIGH] No `.env` / Environment Variable Management

**Issue:** No `.env` file, no use of `python-dotenv` or environment variables. All configuration is in `config.json` (plain JSON with no encryption). Hardcoded paths, ports, and settings.

**Evidence:**
- `VITE_API_URL` is checked but never set in any `.env`
- API host/port hardcoded as `127.0.0.1:8000`
- No database URLs, secret keys, or external service credentials management

**Solution:**
- Add `python-dotenv` to requirements
- Create `.env.example` with documented variables
- Migrate secrets and environment-specific values to env vars
- Fall back to `config.json` for non-sensitive defaults

---

### T1.7 [HIGH] Session Cookies Stored in Plaintext JSON

**Issue:** `main.py:263` and `api/server.py:315` — Browser session cookies (including authenticated LinkedIn/Google session tokens) are serialized to `sessions/auth_state.json` in plain, unencrypted JSON. This file could be committed to git (no `.gitignore`) or accessed by any user on the system.

**Solution:**
- Encrypt the stored session state using a key derived from a configurable secret
- Add explicit `.gitignore` entry for sessions directory
- Warn users on first save about the security implications

---

### T1.8 [HIGH] Unused Imports & Dead Code

**Issue:** Multiple files contain unused imports:
- `api/server.py:10`: `from unittest.mock import patch` — Actually used, but import at module level is unusual
- `scrapers/__init__.py` — Empty file (correct for package marker)
- `scrapers/merge.py:2`: `import json` — Used (for config load)
- `frontend/src/pages/Dashboard.tsx:6`: Imports `WifiOff` but never uses it

**Solution:**
- Run `ruff` or `flake8` to clean up unused imports
- Configure VSCode/PyCharm to automatically detect unused imports

---

### T1.9 [HIGH] Path Traversal Protection is Minimal

**Issue:** `api/server.py:724`:
```python
if not str(full_path).startswith(str(BASE_DIR.resolve())):
    raise HTTPException(status_code=403, detail="Path traversal denied")
```
This check can be bypassed if `BASE_DIR` itself contains symlinks. The check also doesn't prevent accessing files outside `BASE_DIR` using `..` within the allowed prefix.

**Solution:**
- Use `Path.relative_to()` to verify the resolved path is truly within BASE_DIR
- Add allowlist-based approach: only allow access to `exports/` subdirectory

---

### T1.10 [MEDIUM] Config Files Out of Sync

**Issue:** Three config files exist with different values:
| Setting | `config.json` | `config.backup.json` | `config.json.bak` |
|---------|:---:|:---:|:---:|
| `headless` | `true` | `false` | `false` |
| `timeout` | `5000` | `5000` | `5000` |
| `logging.level` | `WARN` | `INFO` | `INFO` |

`config.json` uses `"WARN"` which is not a standard Python logging level (should be `"WARNING"`). This means the log level setting may silently fail.

**Solution:**
- Keep only `config.json` as the single source of truth
- Remove `config.backup.json` and `config.json.bak`
- Add config schema validation using Pydantic (already done for API, not for CLI)
- Fix `"WARN"` → `"WARNING"` in the primary config

---

# LAYER 2: ARCHITECTURE & DUPLICATION — 10 Tasks

---

### T2.1 [CRITICAL] Massive Code Duplication Between Clutch & GoodFirms Scrapers

**Issue:** `scrapers/clutch.py` (600 lines) and `scrapers/goodfirms.py` (616 lines) are ~95% identical. The following functions are exact copies with only URL/domain string changes:
- `_scroll_slowly` — identical
- `_accept_cookies` — identical
- `_safe_extract_text` — identical
- `_safe_extract_href` — identical
- `_extract_rating_from_text` — identical pattern
- `_extract_employees` — identical
- `_extract_hourly_rate` — identical
- `_extract_services` — identical
- `_has_results` — identical
- `_go_to_next_page` — identical
- `_extract_all_cards` — identical
- `_export_*_results` — identical export logic
- `run_*_scraper` — identical runner pattern

**Solution:**
- Create `scrapers/base.py` with shared `BaseScraper` class
- Extract common functions into a shared module
- Use a scraper config dict to define platform-specific selectors and URL builders
- Each scraper file should be 100-150 lines of platform-specific code

---

### T2.2 [HIGH] Export Logic Duplicated Across All 4 Scrapers + main.py

**Issue:** The same export function pattern (`_export_*_results`) is copied into:
- `scrapers/clutch.py:409-447`
- `scrapers/goodfirms.py:420-458`
- `scrapers/maps.py:384-422`
- `scrapers/linkedin.py:342-377`
- `main.py:208-239` (standalone export function)

Each function duplicates the same format detection, file naming, and fallback logic. If a new format is added, all 5 locations need updating.

**Solution:**
- Create a single `export_dataframe_to_file(df, filename_prefix, subdir, cfg)` function in a shared module
- Use it across all scrapers and main.py

---

### T2.3 [HIGH] `input()` Prompts in Scrapers → API Integration Hacks

**Issue:** All scrapers use `input()` for user prompts:
- `clutch.py:462,468` — query input and max_pages
- `goodfirms.py:473,479` — same pattern
- `maps.py:436,442` — same pattern
- `linkedin.py:391,431` — CSV path and confirmation
- `merge.py:380` — confirmation prompt

The API server (`api/server.py`) works around this by using `unittest.mock.patch("builtins.input", ...)` which is fragile:
- Mock keyword matching is heuristic (line 507: `"search query": body.query`)
- Fails silently if prompt text changes
- No validation at mock boundaries

**Solution:**
- Refactor scrapers to accept parameters directly as function arguments instead of reading from stdin
- Keep `input()` only in CLI wrapper functions in `main.py`
- Remove the `@patch` hack from `api/server.py`

---

### T2.4 [HIGH] Config Defaults Duplicated Between main.py & server.py

**Issue:** The complete `_DEFAULT_CONFIG` dict (lines 30-67) is literally copied in:
- `main.py:30-67` (38 lines)
- `api/server.py:23-60` (38 lines)

**Evidence:** Both define identical `_DEFAULT_CONFIG`, `GeoLocation`, `BrowserSettings`, `logging`, etc.

**Solution:**
- Create a shared `config.py` module with the default config and loading/saving functions
- Both `main.py` and `server.py` import from the shared module

---

### T2.5 [MEDIUM] Safe Extract Functions Duplicated Across All Scrapers

**Issue:** The following utility functions are duplicated across all 4 scraper files:
- `_safe_extract_text()` — 4 copies
- `_safe_extract_href()` — 2 copies (maps.py has a variant `_safe_extract_href`)
- `_safe_extract_attribute()` — 2 copies (linkedin.py, clutch.py)

**Solution:**
- Extract these into a shared `scrapers/utils.py` or `scrapers/base.py`

---

### T2.6 [MEDIUM] Merge Engine Uses Module-Level State

**Issue:** `scrapers/merge.py:39`:
```python
_EXPORT_BASE = _load_export_base()
```
This runs at import time, not at function call time. If config changes after import (via API settings update), the merge engine still uses the old path.

Also `SOURCE_DIRS` (line 42-47) is computed at module level from `_EXPORT_BASE`.

**Solution:**
- Load export base path at runtime in `run_merge_engine()`
- Re-compute source directories at runtime
- Or use a lazy-loading property

---

### T2.7 [MEDIUM] Hardcoded Value Ranges for Scroll/Extraction

**Issue:** Throughout the scrapers, magic numbers are hardcoded:
- `clutch.py:535`: `steps=10, delay=0.35` — Scroll parameters
- `goodfirms.py:546`: `steps=10, delay=0.35`
- `maps.py:104`: `scroll_amount = random.randint(400, 700)` — Pixel scroll amounts
- `maps.py:105`: `steps = random.randint(3, 6)`
- `linkedin.py:265`: `delay = random.uniform(4.0, 7.0)` — LinkedIn delay
- `linkedin.py:294`: `await asyncio.sleep(random.uniform(2.0, 4.0))`

These values should be configurable and documented.

**Solution:**
- Add scraper-specific tuning parameters to config.json
- Use config values with sensible defaults from `_DEFAULT_CONFIG`
- Document tuning parameters in SETUP.md

---

### T2.8 [MEDIUM] No Centralized Error Handling Strategy

**Issue:** Error handling is inconsistent across the codebase:
- Scrapers use broad `except Exception` (e.g., `clutch.py:586`)
- Some catch `asyncio.CancelledError` separately, others don't
- Playwright `TimeoutError` is caught in some places but not all
- The `finally` block in scrapers doesn't always clean up resources properly

**Solution:**
- Create custom exception hierarchy (`ScraperError`, `NavigationError`, `ExtractionError`, `ExportError`)
- Use a decorator or context manager for standardized try/except/finally in scraper runners
- Ensure all scrapers handle cancellation uniformly

---

### T2.9 [MEDIUM] No Retry Queue for Failed Items

**Issue:** When a scraper fails on a single item (card/page), it logs a warning and continues. There's no mechanism to:
- Retry failed extractions
- Re-process pages that timed out
- Track failure rates per scraper run

**Solution:**
- Add a retry queue per scraper session
- Export failed items to a separate `_failed.csv` for manual review
- Add failure rate threshold configuration (stop if >X% fail)

---

### T2.10 [LOW] No Proper Type Hints for Shared Interfaces

**Issue:** Scrapers accept loosely typed parameters:
```python
async def run_clutch_scraper(context: BrowserContext, logger, cfg: Dict[str, Any]) -> bool:
```
`logger` has no type annotation. `cfg` is `Dict[str, Any]` instead of a typed config model. This makes static analysis impossible and allows runtime type errors.

**Solution:**
- Create a `ScraperConfig` TypedDict or Pydantic model
- Use `logging.Logger` type for logger parameter
- Use Protocol/ABC for scraper interface

---

# LAYER 3: FRONTEND — 10 Tasks

---

### T3.1 [HIGH] Dark-Only Theme — No Light Mode Support

**Issue:** `frontend/src/index.css:6-30` defines only dark theme colors in `:root`:
```css
:root {
  --background: 0 0% 3.9%;
  --foreground: 0 0% 98%;
  /* ... all dark colors ... */
}
```
There is no `.light` or `[data-theme="light"]` selector. The `darkMode: "class"` in tailwind.config.ts suggests the developer intended to support both themes but never implemented the light variant.

**Solution:**
- Add light theme CSS variables under `.light` class or `[data-theme="light"]`
- Add theme toggle in the TopNav component
- Respect `prefers-color-scheme` for initial theme detection

---

### T3.2 [HIGH] Duplicate StatusBadge Component

**Issue:** Two identical `StatusBadge` components exist:
1. `frontend/src/components/shared/StatusBadge.tsx` — imports colors from `@/lib/types`
2. `frontend/src/pages/Dashboard.tsx:119-123` — inline local implementation with hardcoded colors

The inline version doesn't use shared constants, creating two sources of truth for badge styling.

**Solution:**
- Remove the inline `StatusBadge` from Dashboard.tsx
- Use the shared `StatusBadge` from `@/components/shared/StatusBadge`

---

### T3.3 [HIGH] Settings Export Format Mismatch with Backend

**Issue:** `frontend/src/pages/Settings.tsx:42` and `settings.tsx:229-232`:
```typescript
if (!["csv", "xlsx"].includes(cfg.export.format)) errors.push("Export format must be csv or xlsx");
// Only shows CSV and XLSX options
```
But the backend supports 4 formats: `csv`, `json`, `parquet`, `xlsx`. The frontend silently restricts users.

**Solution:**
- Add all 4 format options to the Settings page
- Validate against the actual list of supported formats from the backend

---

### T3.4 [MEDIUM] No Error Boundary / Suspense in React App

**Issue:** `frontend/src/App.tsx` has no error boundary or React.Suspense wrapper. If any component throws during rendering, the entire UI crashes with a blank screen.

```tsx
// Current:
<BrowserRouter>
  <Routes>
    <Route element={<AppLayout />}>
      ...
    </Route>
  </Routes>
  <Toaster />
</BrowserRouter>

// Missing:
<ErrorBoundary fallback={<ErrorPage />}>
  <Suspense fallback={<PageLoading />}>
    ...
  </Suspense>
</ErrorBoundary>
```

**Solution:**
- Add React Error Boundary component wrapping the routes
- Add `Suspense` for lazy-loaded page components
- Add a fallback UI for routing errors

---

### T3.5 [MEDIUM] Delete Export Uses Double Encoding

**Issue:** `frontend/src/lib/api.ts:110-112`:
```typescript
export function deleteExport(filePath: string): Promise<...> {
  return api.delete(`/export/${encodeURIComponent(filePath)}`).then((r) => r.data);
}
```
`filePath` is already path-like (e.g., `exports/clutch/file.csv`). `encodeURIComponent` encodes `/` as `%2F`, which the backend receives as a single path segment. The backend `@app.delete("/export/{file_path:path}")` may not decode this correctly.

**Solution:**
- Use `encodeURI` instead of `encodeURIComponent` for path segments
- Or pass the path as a query parameter

---

### T3.6 [MEDIUM] No WebSocket for Real-Time Updates

**Issue:** The frontend polls the API every 3 seconds for status updates (`Scrapers.tsx:30`, `Dashboard.tsx:29`, `Logs.tsx:108`). This creates unnecessary HTTP traffic and adds latency to status updates.

**Solution:**
- Add WebSocket endpoint (`/ws/status`) for real-time task updates
- Fall back to polling if WebSocket is unavailable
- Reduce polling interval as a temporary fix

---

### T3.7 [MEDIUM] Missing `VITE_API_URL` Configuration

**Issue:** `frontend/src/lib/api.ts:3`:
```typescript
const API_BASE = import.meta.env.VITE_API_URL || "/api";
```
The Vite proxy (`vite.config.ts:15-19`) rewrites `/api` to `http://127.0.0.1:8000`, but:
- No `.env.development` or `.env.production` files define `VITE_API_URL`
- Production build serves static files with no proxy — `/api` calls will 404
- The frontend dist/ directory has no backend to serve the API prefix

**Solution:**
- Create `.env.development` with `VITE_API_URL=http://127.0.0.1:8000`
- Create `.env.production` with the production API URL
- Add documentation on configuring the API URL for deployment

---

### T3.8 [LOW] Unused Import in Dashboard.tsx

**Issue:** `frontend/src/pages/Dashboard.tsx:6`:
```typescript
import { ..., WifiOff } from "lucide-react";
```
`WifiOff` is imported but never used in the component. This is a TypeScript `noUnusedLocals` warning that's suppressed by the config (`noUnusedLocals: false`).

**Solution:**
- Remove unused import
- Enable `noUnusedLocals` and `noUnusedParameters` in tsconfig.json

---

### T3.9 [LOW] No Frontend Tests

**Issue:** Zero test files exist for the React frontend. No Jest/Vitest configuration, no React Testing Library setup.

**Solution:**
- Add Vitest configuration (bundler-agnostic, works with Vite)
- Add basic smoke tests for each page component
- Add API mock tests for the hooks and API layer

---

### T3.10 [LOW] Console Warning in Development

**Issue:** The `toast` hook (`use-toast.ts`) uses a module-level mutable `listeners` array with no cleanup for component unmounts during fast refresh. This can cause:
- Memory leaks in development (React StrictMode double-mounts)
- Stale closure issues with the `setState` callback

**Solution:**
- Use React context for the toast state instead of module-level listeners
- Or use a reducer-based approach with `useReducer` + context

---

# LAYER 4: PERFORMANCE & RELIABILITY — 10 Tasks

---

### T4.1 [HIGH] Log File Entirely Loaded into Memory

**Issue:** `api/server.py:672`:
```python
with open(log_file, "r", encoding="utf-8", errors="replace") as f:
    all_lines = f.readlines()
```
For a 10MB log file, this creates a list of ~100,000 strings in memory — even if the client only requests 200 lines. This happens on every `/logs` request, potentially multiple times per second.

**Solution:**
- Use `mmap` or read from the end using `seek()` with negative offset
- Cache the file size and only re-read when the file changes
- Use `collections.deque` with maxlen for tail reading

---

### T4.2 [HIGH] Single-Threaded Async — No Real Concurrency

**Issue:** Although scrapers use `asyncio`, each scraper executes sequentially:
- `run_clutch_scraper` processes one page at a time
- `run_linkedin_enrichment` processes one company at a time
- `concurrency` setting in config (default 1) is never actually used anywhere
- No concurrent extraction of multiple cards on the same page

**Solution:**
- Implement concurrent card extraction within a page using `asyncio.gather()`
- Use the `concurrency` setting to parallelize page-level scraping (with rate-limit awareness)
- Implement concurrent company enrichment in LinkedIn scraper with a semaphore

---

### T4.3 [MEDIUM] No Request-Level Timeout for API Endpoints

**Issue:** FastAPI endpoints have no timeout middleware. A scraper request (`/start/clutch`) can run for hours without any timeout. The health check endpoint could hang if Playwright is in a bad state.

**Solution:**
- Add `timeout` middleware to FastAPI for request-level timeout
- Set reasonable timeouts for long-running operations
- Implement circuit-breaker pattern for browser session management

---

### T4.4 [MEDIUM] Startup Race Condition in Browser Session

**Issue:** In `api/server.py`, the browser session is created lazily on the first scraper request (`_ensure_browser_session()`). Multiple concurrent requests that trigger this simultaneously could create multiple browser contexts or crash.

**Solution:**
- Use `asyncio.Lock()` to guard browser session initialization
- Initialize the session eagerly on server startup via a startup event
- Add a health check that verifies the session is actually functional

---

### T4.5 [MEDIUM] No Connection Pooling or Keep-Alive

**Issue:** Each API request creates a new HTTP connection to external sites (via Playwright). There's no reuse of TCP connections, no keep-alive configuration, and no connection pooling.

**Solution:**
- This is partially addressed by Playwright's persistent context
- Ensure `networkidle` wait doesn't block unnecessarily
- Add configurable connection timeout and keep-alive settings

---

### T4.6 [MEDIUM] Playwright Browser Context Not Reused Optimally

**Issue:** Both `main.py` and `api/server.py` create a `launch_persistent_context`, but:
- The persistent context is never explicitly closed between scraper runs
- Memory usage grows as pages accumulate in the browser process
- No browser restart mechanism after N scrapes or on crash detection

**Solution:**
- Add browser process health check with auto-restart
- Implement memory usage monitoring and context recycling
- Close pages explicitly after each scraper run

---

### T4.7 [LOW] Large File Handling — No Streaming for Downloads

**Issue:** `api/server.py:730-735`:
```python
return FileResponse(path=str(full_path), ...)
```
FastAPI `FileResponse` streams the file, which is correct. However, the `_scan_export_files()` function scans all export directories on every request, which can be slow with many files.

**Solution:**
- Cache the file listing with a TTL (e.g., 5 seconds)
- Invalidate cache on file delete or export creation
- Use `os.scandir()` instead of `iterdir()` for faster directory listing

---

### T4.8 [LOW] Merge Engine Memory Usage

**Issue:** `scrapers/merge.py` loads all CSV files into pandas DataFrames in memory simultaneously, then concatenates them. For large datasets (100k+ rows), this can cause OOM errors.

**Solution:**
- Use chunked reading for large CSV files
- Deduplicate incrementally instead of loading everything at once
- Add `--memory-efficient` mode that uses SQLite as intermediate storage

---

### T4.9 [LOW] Vite Build Configuration Not Optimized

**Issue:** `frontend/vite.config.ts` has no build optimizations:
- No code splitting
- No manual chunks configuration
- No compression
- No PWA support

**Solution:**
- Add `rollupOptions.output.manualChunks` for vendor splitting
- Enable brotli/gzip compression plugin
- Add lazy loading for page components using `React.lazy()`

---

### T4.10 [LOW] No Caching Headers for Static Assets

**Issue:** The production build (`frontend/dist/`) has no cache-control headers. The HTML entry point and JS/CSS assets would benefit from aggressive caching.

**Solution:**
- Add caching headers when serving from production
- Use hash-based filenames (Vite does this by default)
- Add a service worker for offline support

---

# LAYER 5: CODE QUALITY & MAINTAINABILITY — 10 Tasks

---

### T5.1 [HIGH] No Testing — Zero Test Coverage

**Issue:** The entire project has zero test files:
- No Python tests (no `pytest`, `unittest`, or `pytest-asyncio`)
- No frontend tests (no Jest, Vitest, or React Testing Library)
- No integration tests
- No E2E tests

**Evidence:** No `tests/` directory, no `*.test.py`, no `*.test.tsx` files anywhere in the project.

**Solution:**
- Add `pytest` and `pytest-asyncio` to requirements
- Write unit tests for each scraper's extraction functions (pure functions)
- Write integration tests for the merge engine
- Add frontend component tests with Vitest + React Testing Library

---

### T5.2 [MEDIUM] No Linting or Formatting Configuration

**Issue:** No linting/formatting config files:
- No `.pylintrc` or `ruff.toml` (Python linting)
- No `.eslintrc` or `eslint.config.js` (JavaScript/TypeScript linting)
- No `.prettierrc` (code formatting)
- No `pyproject.toml` with tool configs

**Solution:**
- Add `ruff` configuration in `pyproject.toml` for Python
- Add ESLint + Prettier config for frontend
- Add pre-commit hooks for automatic formatting
- Add CI configuration to run linters on PRs

---

### T5.3 [MEDIUM] No Containerization (Docker)

**Issue:** No `Dockerfile` or `docker-compose.yml` for containerized development/deployment. Setting up the project requires:
1. Python 3.10+ with venv
2. Playwright Chromium installation
3. Node.js 18+ with npm install
4. Manual configuration of both services

**Solution:**
- Create `Dockerfile` for the Python backend
- Create separate `Dockerfile` for the frontend (or use multi-stage build)
- Add `docker-compose.yml` to orchestrate both services
- Use volumes for persistent data (exports, session, logs)

---

### T5.4 [MEDIUM] No CI/CD Pipeline

**Issue:** No GitHub Actions, GitLab CI, or other CI configuration. No automated testing, linting, or deployment.

**Solution:**
- Add GitHub Actions workflow for:
  - Python lint + type check (`ruff`, `mypy`)
  - Frontend lint + type check (`tsc --noEmit`)
  - Run tests
  - Build Docker images

---

### T5.5 [MEDIUM] Monolithic API Server File

**Issue:** `api/server.py` is 781 lines containing:
- Config models (Pydantic)
- Config loading/saving
- Logging setup
- Task management
- All API endpoints
- Middleware
- Startup/shutdown events
- File scanning
- Helper functions

**Solution:**
- Split into modules:
  - `api/config.py` — Config models and loading
  - `api/models.py` — Request/response Pydantic models
  - `api/tasks.py` — Background task management
  - `api/router_*.py` — Route groups
  - `api/main.py` — App factory

---

### T5.6 [LOW] No Documentation in Code

**Issue:** While there are external docs (README.md, SETUP.md), the code has minimal documentation:
- No docstrings on any function (except `_SafeRotatingFileHandler`)
- No type annotations on logger parameters
- Complex regex patterns with no explanation
- Magic numbers with no context

**Solution:**
- Add docstrings to all public functions
- Document CSS selector strategies (why specific patterns)
- Explain the reasoning behind delay values and retry logic
- Add inline comments for complex regex patterns

---

### T5.7 [LOW] No Configuration for TypeScript Strictness

**Issue:** `frontend/tsconfig.json:15-16`:
```json
"noUnusedLocals": false,
"noUnusedParameters": false,
```
These settings defeat the purpose of TypeScript strict mode. Combined with `strict: true`, having these disabled means the compiler won't catch dead code or unused parameters.

**Solution:**
- Enable `noUnusedLocals` and `noUnusedParameters`
- Use `_` prefix for intentionally unused parameters
- Fix all resulting TypeScript errors

---

### T5.8 [LOW] No Package Lockfile for Backend

**Issue:** While `frontend/package-lock.json` exists (for npm), there's no `requirements.lock` or `pip freeze` output for the Python backend. This means installations may get different dependency versions across environments.

**Solution:**
- Generate `requirements.lock` with pinned versions using `pip freeze`
- Or use `pipenv` / `poetry` for deterministic dependency management
- Document minimum and tested versions in README

---

### T5.9 [LOW] Scraper Class Names Inconsistency

**Issue:** Scrapers follow no consistent naming:
- `run_clutch_scraper` (snake_case)
- `run_goodfirms_scraper` (snake_case)
- `run_maps_scraper` (snake_case)
- `run_linkedin_enrichment` (different verb — "enrichment" vs "scraper")
- `run_merge_engine` (different verb — "engine")

API endpoint names:
- `/start/clutch` (noun)
- `/start/goodfirms` (noun)
- `/start/maps` (noun)
- `/start/linkedin` (noun — enrichment implied)
- `/merge` (verb, different pattern)

**Solution:**
- Standardize on `run_<source>_scraper` pattern
- Consistent API endpoints: `/start/<source>` for all, including merge
- Standardize export function names

---

### T5.10 [LOW] No Deprecation Strategy for Scraper Selectors

**Issue:** CSS selectors are hardcoded strings with no versioning or deprecation tracking. When a website updates its HTML, selectors silently stop matching — no warning, just empty results.

**Solution:**
- Add a selector version key in config
- Log warnings when a selector produces zero matches for a complete page
- Add a "selector health" report after each scraper run
- Implement fallback selector sets that are tried in order

---

# LAYER 6: SCRAPER-SPECIFIC EDGE CASES — 10 Tasks

---

### T6.1 [HIGH] LinkedIn — No Pre-Run Session Verification

**Issue:** `run_linkedin_enrichment` doesn't verify the LinkedIn session is valid before starting the batch of up to 50+ companies. If the session expired, the scraper wastes time navigating to each company and detecting "login_required" on every single one.

**Evidence:** `linkedin.py:439` — page is created and the first company is navigated to without any session check.

**Solution:**
- Navigate to `https://www.linkedin.com` first and check if already logged in
- Display a warning if login is required before starting enrichment
- Allow user to abort early if session is expired

---

### T6.2 [HIGH] Google Maps — Address Extraction is Fragile Heuristic

**Issue:** `scrapers/maps.py:298-326` — Address extraction works by removing known fields (name, rating line, website, phone, category) from a raw text blob and taking whatever remains as the address. This fails when:
- A business has no website listed
- Phone number appears differently in text vs extracted value
- Category text is empty or multiline
- Text blob contains multiple unknown lines

**Solution:**
- Use more specific selectors for address elements
- Add fallback to `address` or `data-item-id` attribute parsing
- Accept that address may be None and don't infer it from noise

---

### T6.3 [HIGH] All Scrapers — No Input Validation on Query

**Issue:** User-provided search queries have no validation:
- Empty strings — caught by `if not query:` check
- SQL injection — not applicable (no SQL)
- Extremely long strings — no max length, could cause URL issues
- Special characters — no sanitization beyond `.strip().lower().replace(" ", "+")`
- No rate limit per search (user could submit the same query 100 times)

**Solution:**
- Add max length validation (e.g., 200 chars)
- Add query deduplication check (same query within short time)
- Sanitize all URL inputs
- Add query history tracking

---

### T6.4 [MEDIUM] Clutch/GoodFirms — No Result Card Verification

**Issue:** `_extract_card_data` checks visibility but doesn't verify that extracted data belongs to a legitimate result card (vs. ads, headers, or navigation elements). The selector-based approach can pick up:
- Navigation items that match "provider" class
- Sidebar elements
- Ad cards with different structure

**Solution:**
- Add a minimum required fields check (must have name + at least one of: website, location, profile URL)
- Exclude items based on parent element role
- Check that cards are within the main content area

---

### T6.5 [MEDIUM] Maps — Captcha Detection is Limited

**Issue:** `scrapers/maps.py:62-76` — Captcha detection checks for specific strings:
```python
clues = ["captcha", "unusual traffic", "verify you're human", "automated queries"]
```
Google's captcha pages change frequently and may not contain these specific strings. Also, Google Maps can silently serve empty results without any error indication when rate-limited.

**Solution:**
- Use Playwright's `page.route` to detect redirects to `google.com/sorry/`
- Add page title / URL checks for known captcha patterns
- Monitor `response.status` for 429 (Too Many Requests)
- Detect zero results across >5 consecutive scrolls with high suspicion

---

### T6.6 [MEDIUM] LinkedIn — Founder Regex is Language-Specific

**Issue:** `scrapers/linkedin.py:18-24`:
```python
FOUNDER_REGEX = re.compile(
    r"(?:Founded|Co-founded|Founder|Founded by|Co-founded by)\s*[:\-]?\s*([^.!]*)",
    re.IGNORECASE,
)
```
This only matches English-language patterns. LinkedIn profiles in other languages use different phrasing (e.g., "Fondateur" in French, "Gründer" in German). Companies with non-English about sections will never have founder data extracted.

**Solution:**
- Add multi-language founder patterns
- Or use LinkedIn's structured data (if available)
- Add a note in documentation about language limitations

---

### T6.7 [MEDIUM] Merge Engine — Only Scans CSV Files

**Issue:** `scrapers/merge.py:344`:
```python
files = sorted(directory.glob("*.csv"))
```
If users export to JSON, Parquet, or XLSX format, merge engine silently ignores those files. However, the export functions write in the configured format, so this is only an issue if format is changed between runs.

**Solution:**
- Support multiple input formats in merge engine
- Auto-detect file format by extension
- Add a note that merge engine reads all formats, not just CSV

---

### T6.8 [LOW] Clutch/GoodFirms — Pagination Duplication Risk

**Issue:** The `_go_to_next_page` function (`clutch.py:343-348`) constructs page URLs:
```python
if "page=" in url:
    new_url = re.sub(r"page=\d+", f"page={next_page}", url)
```
This assumes the page number appears only once in the URL. If the URL has query parameters with "page" in the key name, this regex could corrupt the URL. Also, it doesn't handle infinite scroll pagination that Clutch may use.

**Solution:**
- Use URL parser (`urllib.parse`) for robust query parameter manipulation
- Add support for both URL-based and click-based pagination
- Verify the new URL is different from the current URL before navigating

---

### T6.9 [LOW] LinkedIn — No CSV Column Validation

**Issue:** `run_linkedin_enrichment` checks for known column names but doesn't validate the actual data:
- Doesn't check if all company names are unique (waste of requests)
- Doesn't process the website column to extract company name if name is missing
- Doesn't validate URL format in website column

**Solution:**
- Deduplicate input companies before enrichment
- Attempt to extract company name from website URL if name is empty
- Show a preview of the first 10 rows before confirming

---

### T6.10 [LOW] All Scrapers — No Graceful Degradation for Missing Data

**Issue:** When an expected element is not found on a page, scrapers log "Skipping card" and move on. There's no:
- Alternative extraction strategy for partially loaded pages
- Waiting for dynamic content to appear
- Detecting when JavaScript failed to execute

**Solution:**
- Add configurable wait strategies for dynamic content
- Implement fallback extraction via body text parsing when selectors fail
- Log structured data about extraction failures for debugging

---

# LAYER 7: LOGGING & MONITORING — 6 Tasks

---

### T7.1 [HIGH] Log File Shows Past Project Path Errors

**Issue:** `logs/system.log:1,7,9` shows:
```
Config load failed ([Errno 2] No such file or directory: 'D:\\Py_Projects\\lead_system\\config.json')
```
The system is looking for config in the wrong directory. This happens because config files reference the old project path and the backup fallback mechanism kicks in.

**Solution:**
- Clean the log file after fixing the path issue
- Add startup validation that the config file exists in the expected location
- Add a clear error message with the expected and actual paths

---

### T7.2 [MEDIUM] No Structured Logging

**Issue:** All logging uses f-strings and `%` formatting with no structured fields. Log analysis requires regex parsing (already implemented in `api/server.py:635-637` with `_LOG_PATTERN`).

**Solution:**
- Use structured logging (JSON format) with fields: `timestamp`, `level`, `logger`, `message`, `scraper`, `task_id`, `duration_ms`, `items_count`
- Add correlation IDs across scraper runs
- Use `python-json-logger` for JSON output

---

### T7.3 [MEDIUM] No Metrics Collection

**Issue:** No metrics are collected about scraper performance:
- Items extracted per second
- Success/failure rates per source
- Average page load time
- Memory usage
- Browser crash frequency

**Solution:**
- Add `prometheus_client` for metrics endpoint
- Track: extraction count, error count, duration, memory usage
- Add `/metrics` endpoint for Prometheus scraping

---

### T7.4 [LOW] Console Logging Not Configurable in API Mode

**Issue:** In `api/server.py`, console handler is always set to `INFO` level (line 168). In production, console logging may need to be `WARNING` only, while file logging stays at `DEBUG`.

**Solution:**
- Make console log level configurable
- Support different log levels for console vs file
- Add environment variable overrides for log levels

---

### T7.5 [LOW] No Alerting on Scraper Failures

**Issue:** When a scraper fails, the system logs the error and returns `False`. There's no:
- Webhook/email notification on failure
- Slack/Discord integration
- Automatic retry mechanism

**Solution:**
- Add optional webhook URL in config for failure notifications
- Implement automatic retry (X times with exponential backoff)
- Export failure reports

---

### T7.6 [LOW] No Audit Trail for Configuration Changes

**Issue:** Config changes via the API are logged as "Settings updated by user" with no information about what changed. There's no version history or rollback capability.

**Solution:**
- Log the diff of config changes
- Keep the last N config backups with timestamps
- Add a config change history endpoint (`GET /settings/history`)

---

# LAYER 8: PROJECT MANAGEMENT & TOOLING — 6 Tasks

---

### T8.1 [MEDIUM] No Virtual Environment Tracking

**Issue:** No `venv/` or `.venv/` directory exists. The project has no mechanism to verify the user is running in a virtual environment before starting.

**Solution:**
- Create `venv/` (add to `.gitignore`)
- Add Python version check at startup (3.10+)
- Add `#!` check for virtual environment path

---

### T8.2 [MEDIUM] No Type Checking in CI

**Issue:** The frontend builds with `tsc -b` but there's no CI to catch TypeScript errors. On the Python side, no `mypy` or `pyright` configuration exists.

**Solution:**
- Add `mypy` to requirements-dev.txt
- Add `pyproject.toml` with mypy configuration
- Add type checking to CI workflow

---

### T8.3 [LOW] No Editor Config (`.editorconfig`)

**Issue:** No `.editorconfig` file to standardize indentation, line endings, and charset across different editors and IDEs. The project uses a mix of:
- 4-space indentation in Python files (PEP 8)
- 2-space indentation in frontend files (JS/TS convention)
- No trailing newline consistency

**Solution:**
- Add `.editorconfig` with project-wide settings

---

### T8.4 [LOW] No Development Scripts for Common Tasks

**Issue:** No Makefile, `justfile`, or `npm run` scripts for common development tasks:
- Starting both frontend and backend simultaneously
- Running lint/format
- Running tests
- Building for production

**Solution:**
- Add `concurrently` or `npm-run-all` for running frontend + backend
- Create a Makefile or add scripts to package.json
- Add `run dev`, `run lint`, `run test` commands

---

### T8.5 [LOW] No Health Check Script for Readiness

**Issue:** There's a `/health` endpoint but no script or config to verify the system is ready (browser session created, exports directory writable).

**Solution:**
- Add a `healthcheck.sh` or Python script for Docker health checks
- Add startup probe that waits for browser session initialization
- Add readiness check for all export directories

---

### T8.6 [LOW] No Data Cleanup Strategy

**Issue:** Export files accumulate indefinitely. Logs rotate at 10MB but exports do not. There's no:
- Automated cleanup of old export files
- Archive mechanism for completed runs
- Storage quota enforcement

**Solution:**
- Add configurable export retention policy (e.g., keep last 30 days)
- Add archive/compress option for old exports
- Add disk space warning in health check

---

# SUMMARY

| Layer | Layer Name          | Critical | High | Medium | Low | Total |
|-------|---------------------|:--------:|:----:|:------:|:---:|:-----:|
| 1     | Security & Infrastructure | 4 | 5 | 1 | – | **10** |
| 2     | Architecture & Duplication | 1 | 4 | 4 | 1 | **10** |
| 3     | Frontend             | – | 3 | 4 | 3 | **10** |
| 4     | Performance & Reliability | – | 2 | 5 | 3 | **10** |
| 5     | Code Quality & Maintainability | – | 1 | 5 | 4 | **10** |
| 6     | Scraper Edge Cases   | – | 3 | 4 | 3 | **10** |
| 7     | Logging & Monitoring | – | 1 | 2 | 3 | **6** |
| 8     | Project Management   | – | – | 2 | 4 | **6** |
| **Total** | — | **5** | **19** | **27** | **21** | **72** |

## Immediate Action Items (Top 5 Priority)

1. **Create `.gitignore`** — Remove session data, logs, and cache from version control
2. **Fix CORS config** — Remove `allow_origins=["*"]` with `allow_credentials=True`
3. **Refactor scrapers** — Extract shared code from clutch.py / goodfirms.py into a base module
4. **Fix config loading** — Remove stale backups, unify config strategy, fix `WARN` → `WARNING`
5. **Add API authentication** — At minimum an API key check on destructive endpoints
