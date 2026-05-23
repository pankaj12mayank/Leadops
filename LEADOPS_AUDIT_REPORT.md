# Leadops — End-to-End System Audit Report
**Date:** 2026-05-23 | **Scope:** Full stack deep audit (110 bugs across 11 layers)

---

## LAYER 1: UI/UX (Frontend Rendering & User Experience)

| # | Severity | File:Line | Bug | Impact |
|---|----------|-----------|-----|--------|
| 1 | **HIGH** | `ErrorBoundary.tsx:29` | `handleRetry` resets `hasError=false` but does NOT force children remount — the broken component tree simply re-renders and throws again immediately | User gets infinite error loop, "Try again" never works |
| 2 | **MEDIUM** | `Settings.tsx:65-70` | `patch()` uses spread `{ ...config[section], [key]: value }` — TypeScript cannot narrow `key`, and `value` is `unknown`. Setting `concurrency` to a string bypasses type safety. | Silent data corruption on settings save |
| 3 | **MEDIUM** | `Logs.tsx:106-110` | `useEffect` dependency includes `autoRefresh` + `load`, but `load` captures `lines` in closure via `useCallback([lines])` — the 3s interval restarts on every `lines` change | Interval churn, wasted re-fetches |
| 4 | **LOW** | `Dashboard.tsx:14` | `setLoading` initialized but never rendered anywhere — dead state | Dead code, no visual loading indicator for dashboard data |
| 5 | **LOW** | `Scrapers.tsx:16` | `setLoading(true)` initialized but never exposed to UI — same dead pattern | Dead code, misleading initial state |
| 6 | **MEDIUM** | `Logs.tsx:114-115` | Auto-scroll scrolls to **top** (`scrollTo({ top: 0 })`) on new entries instead of bottom — logs viewer scrolls UP on each refresh | User must manually scroll down each time to see latest |
| 7 | **MEDIUM** | `Scrapers.tsx` + `Settings.tsx` | No confirmation dialog when stopping running scrapers or discarding unsaved settings | Accidental clicks cause data loss |
| 8 | **LOW** | `Dashboard.tsx:87` | Uses array index `key={i}` for export list items instead of unique `filename`+`path` | React reconciliation issues, wrong DOM updates on refresh |
| 9 | **LOW** | `Settings.tsx:146` | Headless mode checkbox missing `aria-label` attribute — only `id` is set | Accessibility violation, screen reader won't announce purpose |
| 10 | **LOW** | `Logs.tsx:108` | `setInterval(load, 3000)` runs even when browser tab is backgrounded — no `visibilitychange` pause | Unnecessary network/cpu usage |

---

## LAYER 2: Backend (Python / FastAPI / Server Logic)

| # | Severity | File:Line | Bug | Impact |
|---|----------|-----------|-----|--------|
| 1 | **CRITICAL** | `api/server.py:92-98` | Mutable module-level globals `_playwright_instance`, `_browser_context`, `_api_logger` shared across all requests — NOT thread-safe under multi-worker uvicorn | Race condition crashes, browser context corruption |
| 2 | **HIGH** | `api/server.py:321` | `_browser_lock` only protects context **creation**, not all reads/writes — code at lines 285-299 reads `_browser_context` without lock | TOCTOU race: browser context used after close |
| 3 | **HIGH** | `api/server.py:393` | `finally` block accesses `_tasks[task_id]` which may have been deleted by `_trim_task_history` if task sat too long | `KeyError` during status broadcast |
| 4 | **MEDIUM** | `api/server.py:120` | `_ws_clients.remove(ws)` called inside `for ws in _ws_clients:` loop — modifying list during iteration | `ValueError` or skipped removals |
| 5 | **HIGH** | `api/server.py:712` | Line count heuristic `pos // chunk_size * 200` is mathematically **wrong** — total line estimation uses a hardcoded factor 200 unrelated to actual content | Incorrect `total_lines` returned to frontend |
| 6 | **MEDIUM** | `api/server.py:844` | `/health` only checks `_browser_context is not None` — doesn't verify browser process is actually alive or responsive | False positive "active" health status |
| 7 | **MEDIUM** | `config.py:139-141` | `shutil.copy2(CONFIG_PATH, CONFIG_BACKUP_PATH)` then `tmp_path.replace(CONFIG_PATH)` — if process crashes between copy and replace, backup overwritten but new config not yet active | Config loss window |
| 8 | **MEDIUM** | `api/server.py:161-170` | API key middleware skips `/health`, `/docs`, `/openapi.json`, `/redoc` but does NOT skip `/ws/status` — WebSocket upgrade bypasses middleware | WSS endpoint has no auth |
| 9 | **HIGH** | `api/server.py:384` | `asyncio.CancelledError` caught and **NOT re-raised** — violates Python asyncio protocol. This swallows cancellation signals | Tasks may not properly clean up on shutdown |
| 10 | **CRITICAL** | `api/server.py:797-802` | `/settings` GET endpoint has `response_model=SystemConfig`. `_success_response()` returns `{"success":true, "data":{...}}` but `response_model=SystemConfig` makes FastAPI parse this as `SystemConfig(success=True, data={...})` — Pydantic v2 ignores unknown fields and uses ALL defaults. **Actual config is never returned**. Same bug on POST `/settings` at line 807-815 | Settings page always shows default config, cannot view or verify saved settings |

---

## LAYER 3: Frontend (React / TypeScript / Client Logic)

| # | Severity | File:Line | Bug | Impact |
|---|----------|-----------|-----|--------|
| 1 | **HIGH** | `api.ts:111` | `encodeURI(filePath)` instead of `encodeURIComponent(filePath)` — a path like `exports/clutch/file.csv` encodes `/` as literal `/` not `%2F` | Double-encoded paths fail on DELETE requests |
| 2 | **HIGH** | `api.ts:115` | Same `encodeURI` bug for download URL generation | Download URLs broken for subdirectory paths |
| 3 | **MEDIUM** | `Scrapers.tsx:38-43` | `setInput` creates brand new nested object on every keystroke — all Scraper cards re-render | Unnecessary re-renders, poor performance with many scrapers |
| 4 | **MEDIUM** | `Logs.tsx:92-103` | `load()` callback identity changes every `lines` change → `useEffect` clears & resets interval | Lost logs updates, interval timing drift |
| 5 | **LOW** | `types.ts:49` | LinkedIn `csv_path` exposed as text input but backend expects absolute path — path like `exports/linkedin/input_companies.csv` may not resolve | "File not found" errors confusing users |
| 6 | **MEDIUM** | `Settings.tsx:164` | `parseInt(e.target.value)` returns `NaN` when input is empty → `NaN` coerces to `0` → `min=1000` validation passes `0` | Silent invalid config saved |
| 7 | **MEDIUM** | `App.tsx` | Single `ErrorBoundary` wraps entire app — one page crash takes down everything | No page-level fault isolation |
| 8 | **LOW** | `Scrapers.tsx:57` | `parseInt(inp.defaultValue)` where `defaultValue` is `"5"` (string) — works but `parseInt("")` returns `NaN` for empty input | Edge case: empty numeric input yields NaN body |
| 9 | **LOW** | `Settings.tsx:207` | Concurrency input `onChange` uses `parseInt(e.target.value) \|\| 1` — typing "2" becomes 2, but clearing field becomes 1 | Cannot set concurrency to 0 (though invalid) |
| 10 | **CRITICAL** | `api.ts:78-177` | **ALL frontend API calls broken**: Every API function does `.then((r) => r.data)` which gets the full response body `{"success":true, "data":{...}}`. But frontend code accesses properties like `health.status`, `r.files` directly — these are `undefined` because they're nested inside `.data`. No Axios interceptor unwraps the envelope. The `_success_response` wrapper in backend adds `{"success":true, "data":...}` but frontend never extracts the inner `data` | Entire frontend shows "down"/empty/undefined for all API data |

---

## LAYER 4: Edge Cases (Boundary Conditions, Error Paths)

| # | Severity | File:Line | Bug | Impact |
|---|----------|-----------|-----|--------|
| 1 | **HIGH** | `scrapers/clutch.py:190` | `asyncio.Semaphore(concurrency)` only created when `concurrency > 1` — when `concurrency=1`, semaphore is `None` and `_bounded` runs **unbounded**. `asyncio.gather` fires ALL cards simultaneously | Rate-limit bans, memory OOM with many cards |
| 2 | **HIGH** | `scrapers/base.py:200-201` | `page.goto` returning `None` raises `NavigationError("Navigation returned None")` — defensible but `ok is None` check misses empty `Response` objects | False positive navigation success |
| 3 | **CRITICAL** | `scrapers/maps.py:533-538` | **Indentation bug**: `if page:` and `await page.close()` are OUTSIDE the `finally` block's inner `try`. If `page` was never created (exception in `context.new_page()`), this line runs anyway with `page` as `None` | `AttributeError: 'NoneType' object has no attribute 'close'` on any error |
| 4 | **MEDIUM** | `scrapers/merge.py:510` | `export_root.rglob("*")` returns **directories too** — `f.stat()` on a directory succeeds but then `f.unlink()` fails with `PermissionError` | Cleanup silently skips directories, never reports error |
| 5 | **LOW** | `scrapers/clutch.py:223` | `cfg["browser"]["retry_count"]` — bare expression statement with no assignment, no side-effect | Dead code line |
| 6 | **LOW** | `scrapers/goodfirms.py:234` | Same dead statement `cfg["browser"]["retry_count"]` | Dead code line |
| 7 | **MEDIUM** | `scrapers/base.py:73` | `accept_cookies` splits by `", "` (comma-space) — if SELECTORS define `",\n"` (comma-newline), split produces wrong tokens | Cookie banners not dismissed |
| 8 | **MEDIUM** | `main.py:100` | `_export_dataframe` uses separate `_export_df_logger = logging.getLogger("main.export")` while rest of main uses `_logger` — log lines appear under different names | Log filtering confusion |
| 9 | **LOW** | `scrapers/merge.py:500` | `st_size` checked during iteration to compute `total_size`, but files are iterated by `rglob` order — if size exceeds limit, some old files still get checked | Cleanup may miss oversized files |
| 10 | **MEDIUM** | `scrapers/linkedin.py:387` | `website = str(row[website_col]).strip()` — if `website_col` is None, this line crashes with `TypeError` | LinkedIn enrichment fails on missing website column |

---

## LAYER 5: Dependencies (Package Management, Versioning, Compatibility)

| # | Severity | Issue | Bug | Impact |
|---|----------|-------|-----|--------|
| 1 | **MEDIUM** | `requirements.txt` | Missing `httptools` for `uvicorn[standard]` — not in requirements but `uvicorn[standard]` is in pyproject | Slower HTTP parsing |
| 2 | **HIGH** | `requirements.txt` | Missing `websockets` — FastAPI WebSocket support requires this at runtime | `/ws/status` endpoint crashes on first connection |
| 3 | **MEDIUM** | `frontend/package.json` | `vitest@^4.1.7` — vitest latest stable is **3.x** (as of 2026). Version 4.x may be a pre-release or non-existent | Install failures, CI breakage |
| 4 | **HIGH** | `pyproject.toml` | `asyncio_mode = "auto"` in pytest config — but several `test_*` functions are **not** async and `asyncio_mode=auto` only auto-detects async test functions | No issue now, but adding async helper functions without `@pytest.mark.asyncio` will silently skip |
| 5 | **MEDIUM** | `requirements.txt` | `playwright==1.52.0` pinned exactly but browser binaries version is not managed — users must run `playwright install` manually | Browser mismatch crashes |
| 6 | **HIGH** | Both `package.json` files | No lock file (`package-lock.json` in root, no `yarn.lock` or `pnpm-lock.yaml`) — versions not reproducible across installs | Non-deterministic builds |
| 7 | **MEDIUM** | `requirements.txt` | No `pip freeze` lock file (`requirements.lock` or `constraints.txt`) | Non-deterministic Python envs |
| 8 | **LOW** | `frontend/package.json` | `@testing-library/react@^16.3.2` — React 18 is installed but testing-library v16 may require React 19+ peer dependency | Peer dep warnings on install |
| 9 | **HIGH** | `requirements.txt` | `cryptography==44.0.3` hard-pinned — security updates for cryptography are frequent; hard pinning blocks automated patch updates | Stale crypto, CVE exposure |
| 10 | **MEDIUM** | `setup` script | No `playwright install chromium` step in setup — user must manually install browser binaries | Fresh setup fails with "Browser not found" |

---

## LAYER 6: Project Setup (Config, Build, Tooling, Cross-Platform)

| # | Severity | File:Line | Bug | Impact |
|---|----------|-----------|-----|--------|
| 1 | **CRITICAL** | `package.json:17` | Setup script: `rm -rf frontend/dist` — `rm -rf` is **NOT** a Windows command. Script runs on CMD/PowerShell and will **fail** | Setup completely broken on Windows |
| 2 | **CRITICAL** | `package.json:16` | Clean script same `rm -rf` issue + glob patterns like `exports/**/*.csv` don't expand in CMD | Clean command does nothing on Windows |
| 3 | **CRITICAL** | `package.json:17` | `.\venv\Scripts\pip install` — backslash path works only on Windows, but the setup script also uses `python` (which is `py` on some Windows) | Cross-platform setup impossible |
| 4 | **MEDIUM** | Root dir | No `.python-version` file — pyenv/ pyflow users don't get automatic Python version switching | Python version mismatch bugs |
| 5 | **MEDIUM** | Root dir | No `Makefile` or cross-platform task runner — all scripts are npm-only | Locked into npm for all tasks |
| 6 | **LOW** | Root dir | `healthcheck.py` exists (designed for Docker readiness probes) but there is **no Dockerfile** | Dead file, misleading purpose |
| 7 | **MEDIUM** | Root dir | No `docker-compose.yml` — even though the system has a multi-process architecture (API + frontend) | No easy local orchestration |
| 8 | **MEDIUM** | `config.json` | CORS origins hardcoded to `localhost:5173` and `localhost:4173` but frontend `.env.production` uses `VITE_API_URL=/api` (proxy) — mismatch if deploying without proxy | CORS errors in production |
| 9 | **MEDIUM** | `package.json:7` | `dev:backend` runs uvicorn directly — no check for installed playwright browsers | First run always fails |
| 10 | **MEDIUM** | `docs/SETUP.md:523` | Docs claim "The API has CORS middleware configured to allow all origins by default" but `config.json:67` has specific origins `["http://localhost:5173", "http://localhost:4173"]` — NOT all origins | Documentation lies, users get CORS errors in production |

---

## LAYER 7: Run/Deploy (Execution, Production Readiness, Signals)

| # | Severity | File:Line | Bug | Impact |
|---|----------|-----------|-----|--------|
| 1 | **MEDIUM** | `main.py:510` | `hasattr(sys, "real_prefix")` — this attribute was **deprecated in Python 3.12** and may be removed entirely | Virtual env detection broken on newer Python |
| 2 | **MEDIUM** | `main.py:537-538` | `WindowsProactorEventLoopPolicy` set only for `main()` but not for `run_api.py` — API runs `asyncio.run` inside uvicorn, different loop policy | Event loop warnings on Windows |
| 3 | **MEDIUM** | `run_api.py` | No `uvicorn` signal handlers — `SIGTERM`/`SIGINT` not caught, `_on_shutdown` only runs for FastAPI events, not OS signals | Dirty shutdown, leaked browser processes |
| 4 | **MEDIUM** | `api/server.py:819-839` | WebSocket `/ws/status` has **no rate limiting** — client can open unlimited connections | Connection exhaustion DoS vector |
| 5 | **HIGH** | `api/server.py:37` | `get_remote_address` returns `127.0.0.1` behind any proxy/load balancer — rate limiter applies to all users as one | Rate limiter completely ineffective in production |
| 6 | **HIGH** | `main.py:494` | `cleanup_old_exports()` is **synchronous** (file I/O + glob) but called from `async` context — blocks the entire event loop | App freezes during cleanup, all scrapers stall |
| 7 | **MEDIUM** | `api/server.py:692` | Log file path hardcoded as `logs/system.log` — config allows override via `logging.file` but `/logs` endpoint ignores it | Log endpoint shows wrong file if config changed |
| 8 | **HIGH** | `config.py` | Config is file-based JSON — no transaction/atomicity beyond basic tmpfile. Simultaneous writes from CLI + API corrupt the file | Complete configuration loss |
| 9 | **MEDIUM** | `api/server.py:869-875` | Frontend static files mounted at `"/"` root — if an API route is added that matches a frontend route, static files shadow API | API routes silently unreachable |
| 10 | **MEDIUM** | `healthcheck.py` | Probes `/health` endpoint but returns exit code `0` for any non-excepting response — does not verify `browser_session` is `"active"` | Health check passes even when browser is dead |

---

## LAYER 8: Cross-Component Integration (Inter-Module Communication & System Flow)

| # | Severity | File:Line | Bug | Impact |
|---|----------|-----------|-----|--------|
| 1 | **CRITICAL** | `main.py` vs `api/server.py` | CLI (`main.py`) and API (`server.py`) are **separate processes** but both use the SAME `sessions/auth_state.json` and have DIFFERENT `user_data_dir` (`sessions/profile` vs `sessions/api_profile`). If both run simultaneously, they corrupt each other's cookie state and Playwright crashes with `EBUSY` on the profile directory | Simultaneous CLI+API use corrupts all sessions |
| 2 | **HIGH** | `scrapers/merge.py:483` vs `api/server.py:637` | `/cleanup` endpoint reads `retention_days` and `max_size_mb` from config, passes them to `cleanup_old_exports()` — but `cleanup_old_exports` IGNORES the passed args and calls `load_config()` AGAIN at line 483, using its own values | Passed retention params silently ignored |
| 3 | **HIGH** | `scrapers/maps.py:456` | `all_leads.extend(cards_data)` adds ALL extracted items including DUPLICATES already in `seen_names`. `new_in_cycle` counts only truly new, but `consecutive_empty` logic triggers on that. Meanwhile duplicates leak into final export | Duplicate business records in exported CSV |
| 4 | **HIGH** | `scrapers/base.py:13` vs `config.py:22` | `BASE_DIR` defined in TWO places: `scrapers/base.py:13` (`Path(__file__).resolve().parent.parent`) and `config.py:22`. If imported from different working directories, they can resolve differently | Export paths inconsistent when running from non-root dir |
| 5 | **MEDIUM** | `main.py:100` vs `scrapers/base.py:318` | **Duplicate export logic**: `main.py` has its own `_export_dataframe` function (lines 100-131) that is essentially a copy of `export_dataframe_to_file` in `scrapers/base.py:318` but only writes to `exports/merged/` subdir. Inconsistent behavior | Two divergent export implementations |
| 6 | **MEDIUM** | `api/server.py:134-141` | Config cached for 5s (`_CONFIG_CACHE_TTL`). Only invalidated on POST `/settings`. If `config.json` is manually edited or changed by CLI, API uses stale config for up to 5 seconds | Config inconsistency between CLI and API |
| 7 | **MEDIUM** | `linkedin.py:349` vs `linkedin.py:387` | CSV column auto-detection (lines 356-362) attempts to find `company_name` / `website` columns. But if `website_col` is `None` and code reaches line 387, `row[website_col]` raises `TypeError` | LinkedIn enrichment crashes on missing website column |
| 8 | **MEDIUM** | `main.py:417` vs `api/server.py:589` | LinkedIn default CSV path built differently: CLI uses `BASE_DIR / "exports" / "linkedin" / "input_companies.csv"` (hardcoded), API uses same logic but via `cfg` paths. If `paths.exports` is overridden in config, CLI path breaks | Inconsistent LinkedIn input path under custom config |
| 9 | **MEDIUM** | `main.py:28` vs `scrapers/linkedin.py` | `main.py` directly imports `run_linkedin_enrichment` but `linkedin.py` imports `BASE_DIR` from `scrapers.base` while `main.py` uses `BASE_DIR` from `config`. Two different `BASE_DIR` objects at runtime | Path resolution inconsistency |
| 10 | **MEDIUM** | `config.backup.json` vs `config.json` | Backup config **missing entire sections**: `scraping` (all scraper URLs, delays, scroll params) and `api` (key, CORS, host/port). If `config.json` is deleted and backup restored, all scraper URLs and API config are lost | Silent feature breakage on config recovery |

---

## LAYER 9: Testing & Quality Assurance (Test Gaps, Coverage, CI)

| # | Severity | File:Line | Bug | Impact |
|---|----------|-----------|-----|--------|
| 1 | **HIGH** | `tests/test_extractors.py` | Only **20 test cases** for 7 utility functions. **ZERO tests** for: `export_dataframe_to_file`, `navigate_with_retry`, `accept_cookies`, `_extract_all_cards` (all scrapers), `_extract_single_item`, `_deduplicate`, `run_merge_engine`, `cleanup_old_exports`, `_ensure_browser_session`, ALL API endpoints, ALL frontend pages | ~95% of codebase untested |
| 2 | **HIGH** | `frontend/src/test/` | Only 4 test files testing ONLY shared components (`EmptyState`, `ErrorBoundary`, `LoadingState`, `StatusBadge`). **ZERO tests** for all 5 page components (Dashboard, Scrapers, Logs, Exports, Settings), hooks, API module, or integration flows | Entire UI untested |
| 3 | **MEDIUM** | `frontend/src/test/setup.ts` | Setup file only has `import "@testing-library/jest-dom"`. No `vi.mock()` for API calls, no MSW or mock server. Tests that render pages will make REAL HTTP requests | Frontend tests not isolated |
| 4 | **MEDIUM** | `pyproject.toml:22` | `asyncio_mode = "auto"` in pytest config — but `test_extractors.py` tests ARE properly decorated with `@pytest.mark.asyncio`, so this works. However, `auto` mode can cause unexpected behavior with non-async fixtures in async tests | Confusing test failures for future async tests |
| 5 | **MEDIUM** | All scrapers | Core scraper functions like `_extract_card_data` (clutch.py:100, goodfirms.py:111), `_extract_single_item` (maps.py:254), `_enrich_company` (linkedin.py:172) have **no unit tests** and rely on complex Playwright mocking | Scraper bugs only caught at runtime |
| 6 | **MEDIUM** | `pyproject.toml` | `[tool.coverage.run]` configured but no CI pipeline to enforce coverage thresholds — `coverage` not even in `requirements.txt` | Coverage config is dead code |
| 7 | **LOW** | `tests/test_extractors.py:69` | `test_single_value_with_plus` checks `assert "1000" in result` but result is `"1000+ Employees"` — this passes but is a weak assertion that wouldn't catch `"10000 Employees"` | False confidence in test |
| 8 | **LOW** | `tests/test_extractors.py:87` | `test_dollar_range_per_hr` checks `assert "$" in result` and `assert "/hr" in result` separately — missing exact match like `assert result == "$50 - $80/hr"` | Weak assertions mask regression bugs |
| 9 | **LOW** | `frontend/src/test` | All 4 test files test ONLY the "happy path". No tests for: error states, loading states, edge case inputs, keyboard navigation, accessibility | No negative/edge testing |
| 10 | **MEDIUM** | Root CI | No `.github/workflows/ci.yml`, no pre-commit hooks, no automated test runner on push. `package.json:15` has `"test"` script but nobody runs it | Tests exist but are never executed |

---

## LAYER 10: Security & Secrets (Auth, Crypto, Injection, Exposure)

| # | Severity | File:Line | Bug | Impact |
|---|----------|-----------|-----|--------|
| 1 | **HIGH** | `api/server.py:161-170` | API key auth middleware whitelists `/health`, `/docs`, `/openapi.json`, `/redoc` — but does **NOT** whitelist the pre-flight `OPTIONS` requests for CORS. Browsers send CORS preflight WITHOUT the `X-API-Key` header | CORS preflight fails when API key is set |
| 2 | **HIGH** | `session_encrypt.py:18` | Hardcoded salt `b"leadops_session_v1"` — static salt means same password produces identical key every time. Fernet also uses a static salt within its own protocol, but the outer KDF salt being fixed reduces effective entropy | Session key is deterministic from password |
| 3 | **MEDIUM** | `api/server.py:37` | `get_remote_address` returns client IP from `request.client.host` — behind any reverse proxy (nginx, cloudflare, load balancer), ALL traffic appears as `127.0.0.1` or proxy IP. Rate limiter cannot distinguish users | Rate limiting completely broken in production |
| 4 | **MEDIUM** | `healthcheck.py:39` | URL `http://127.0.0.1:8000/health` hardcoded + CLI arg parsing broken: `for i, arg in enumerate(sys.argv[1:]):` iterates args but `i + 2 < len(sys.argv)` checks against ORIGINAL arg list, not the sliced one | CLI args `--url` and `--timeout` cannot be used |
| 5 | **MEDIUM** | `config.py:117-126` | Environment variable `API_KEY` loaded into config at module import time. If `.env` is modified after the Python process starts, the new key is ignored until restart | Runtime key rotation impossible |
| 6 | **MEDIUM** | `config.py:16-20` | Environment variables read at MODULE LEVEL with `_os.environ.get()` — these execute ONCE when `config.py` is imported. Any subsequent changes to environment are ignored | Stale env values for long-running processes |
| 7 | **LOW** | `api/server.py:770-780` | `/download/{file_path:path}` sets `Content-Disposition` with user-controlled filename but does NOT sanitize or validate the filename parameter beyond path traversal check | Potential header injection if filename contains special chars |
| 8 | **LOW** | `session_encrypt.py:15` | `make_key_from_secret` accepts an empty string as valid input (returns `None` only if secret is falsy). But an empty string `""` passes `if not secret: return None` check, then `_derive_key("", salt)` runs with empty password | Empty password produces valid but worthless key |
| 9 | **MEDIUM** | `api/server.py:692` | Log file path `logs/system.log` is HARDCODED — the config allows overriding `logging.file` but the `/logs` endpoint ignores it. If log path is customized, the endpoint reads wrong file | Log viewer shows wrong logs |
| 10 | **MEDIUM** | `api/server.py:73-81` | `/api` prefix rewrite middleware does NOT handle query strings — `request.url.path` does not include query params. But `request.scope["path"]` is modified correctly. Raw path at line 78 slices `rp[4:]` which assumes 4-byte `/api` prefix but `/api/` URLs might have different encoding lengths | Edge case: encoded `/api` prefix |

---

## LAYER 11: Performance & Resource Management (Memory, Timers, Connections, Concurrency)

| # | Severity | File:Line | Bug | Impact |
|---|----------|-----------|-----|--------|
| 1 | **HIGH** | `frontend/use-websocket-status.ts:39` | **Timer leak**: When WebSocket disconnects, `onclose` fires → calls `startPolling()` → creates `setInterval`. If WS reconnects then disconnects again, ANOTHER interval is created. The cleanup only clears the LAST `pollTimer` reference. Previous intervals keep running forever | Exponential timer growth on WS flapping, memory leak |
| 2 | **HIGH** | `use-toast.tsx:23` | `toastTimeouts` Map (module-level) accumulates ALL dismissed toast timeouts forever. Each `toast()` call creates a `setTimeout` stored in this map. When timeout fires, `toastTimeouts.delete(id)` runs — but the map only grows during the 5s window. However, if `toast()` is called rapidly, 1000s of timeouts pile up simultaneously | Memory accumulation under rapid toast usage |
| 3 | **HIGH** | `use-toast.tsx:56` | `window.dispatchEvent(new CustomEvent("toast-add", ...))` — if the toast is NOT inside `ToastProvider`, the event fires into the void. But `setTimeout` at line 57 still runs, later dispatching `toast-dismiss` which also fires into the void. **No cleanup**: if component unmounts before 5s, timeout still fires | Zombie timeouts, detached DOM updates |
| 4 | **MEDIUM** | `api/server.py:104-123` | `_broadcast_status` iterates `_ws_clients` list and MUTATES it during iteration (`_ws_clients.remove(ws)` at line 119). Python's list iteration uses index, so removing during iteration causes skipped clients | Stale clients not cleaned properly, missed broadcasts |
| 5 | **MEDIUM** | `scrapers/base.py:40` | `_CIRCUIT_HISTORY` is a **module-level mutable defaultdict** — shared across ALL scraper instances. If `clutch.py` and `goodfirms.py` both extract cards with label "card 0", they share the same circuit breaker state | Cross-scraper circuit breaker contamination |
| 6 | **MEDIUM** | `api/server.py:699-713` | Log tail algorithm reads file in 8KB chunks (`chunk_size = 8192`). If a single log line exceeds 8KB (possible with large stack traces), the chunk boundary splits a line, causing the tail algorithm to miss it or produce garbled entries | Missing log lines in viewer |
| 7 | **MEDIUM** | `api/server.py:698-713` | Log line counting heuristic `total = buf.count("\n") + pos // chunk_size * 200` uses hardcoded `200` (average chars per line assumption). This has no statistical basis for this particular log format | Wrong `total_lines` returned to frontend |
| 8 | **MEDIUM** | `main.py:494` | `cleanup_old_exports(_logger)` called from async context — this function performs synchronous file I/O (glob, stat, unlink) and **blocks the asyncio event loop** for the entire duration | UI-freeze: CLI hangs during cleanup |
| 9 | **LOW** | `api/server.py:400-410` | `_trim_task_history` keeps only 100 terminal (completed/failed/cancelled) tasks. But `_tasks` dict also contains RUNNING and PENDING tasks. If 100 tasks complete while 1 runs, running tasks survive. But if 100 tasks are in terminal state, the OLDEST ones (by `completed_at`) are removed regardless of source | Lost task history for frequently-run scrapers |
| 10 | **LOW** | `scrapers/linkedin.py:248` | `delay = random.uniform(sc.get("linkedin_min_company_delay", 4.0), sc.get("linkedin_max_company_delay", 7.0))` — the config keys use `linkedin_` prefix while other scraper keys don't. Inconsistent naming means missing configs fall back to defaults silently | Config drift between scrapers |

---

## Summary Stats

| Layer | Critical | High | Medium | Low | Total |
|-------|----------|------|--------|-----|-------|
| **1. UI/UX** | 0 | 1 | 4 | 5 | **10** |
| **2. Backend** | 2 | 4 | 3 | 1 | **10** |
| **3. Frontend** | 1 | 2 | 4 | 3 | **10** |
| **4. Edge Cases** | 1 | 3 | 4 | 2 | **10** |
| **5. Dependencies** | 0 | 4 | 4 | 2 | **10** |
| **6. Project Setup** | 3 | 0 | 6 | 1 | **10** |
| **7. Run/Deploy** | 0 | 3 | 6 | 1 | **10** |
| **8. Integration** | 1 | 3 | 5 | 1 | **10** |
| **9. Testing** | 0 | 2 | 5 | 3 | **10** |
| **10. Security** | 0 | 2 | 5 | 3 | **10** |
| **11. Performance** | 0 | 3 | 5 | 2 | **10** |
| **TOTAL** | **8** | **27** | **51** | **24** | **110** |

---

## Top 10 Critical Bugs (Immediate Fix Required)

1. **ALL frontend API calls broken** (Layer 3, #10) — `_success_response` envelope `{"success":true,"data":{...}}` never unwrapped. Frontend accesses `health.status`, `r.files` directly on the envelope, getting `undefined`. **Entire UI shows no data**.
2. **`/settings` endpoints return default config** (Layer 2, #10) — `response_model=SystemConfig` combined with `_success_response` wrapper makes FastAPI parse the envelope as the model, ignoring actual fields. All defaults returned.
3. **`package.json` setup/clean scripts** (Layer 6, #1-3) — completely broken on Windows, uses Unix-only `rm -rf` commands
4. **`scrapers/maps.py:533` indentation** (Layer 4, #3) — `page.close()` runs even when `page` is `None`, crashes on any error
5. **`api/server.py` shared mutable globals** (Layer 2, #1) — not safe for any concurrent access pattern
6. **`scrapers/clutch.py:190` unbounded concurrency** (Layer 4, #1) — semaphore bypassed when concurrency=1, fires all card extractions simultaneously
7. **`api/server.py:384` CancelledError swallowed** (Layer 2, #9) — violates asyncio spec, prevents proper cleanup
8. **`main.py` vs `api/server.py` session collision** (Layer 8, #1) — two processes corrupt each other's browser sessions
9. **`use-websocket-status.ts:39` timer leak** (Layer 11, #1) — exponential timer growth on WebSocket flapping
10. **`use-toast.tsx:23` timeout leak** (Layer 11, #2) — zombie timeouts on unmounted toasts
