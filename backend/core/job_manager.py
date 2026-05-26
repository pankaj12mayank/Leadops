import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

from backend.scrapers.base import (
    run_linkedin_enrichment,
    run_maps_scraper,
    run_search_scraper,
)
from backend.storage.database import (
    create_job,
    get_job,
    get_leads_by_job,
    get_next_queued_job,
    increment_job_retry,
    list_jobs,
    mark_stale_jobs,
    update_job,
    update_job_progress,
)

_MAX_RETRIES = 2
_PAGE_TIMEOUT = 30

JobFunc = Callable[..., Coroutine[Any, Any, bool]]


class JobManager:
    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._current_job_id: Optional[int] = None
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._cancel_requested: set[int] = set()

    async def start(self) -> None:
        mark_stale_jobs()
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        self._logger.info("Job manager started")

        queued = list_jobs(status="queued", limit=100)
        for job in queued:
            self._queue.put_nowait(job["id"])
        if queued:
            self._logger.info("Re-queued %d existing jobs", len(queued))

    async def stop(self) -> None:
        self._running = False
        if self._current_job_id is not None:
            await self.cancel_job(self._current_job_id)
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await asyncio.wait_for(self._worker_task, timeout=10)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    async def enqueue(self, source: str, query: Optional[str] = None) -> int:
        job_id = create_job(source=source, query=query, status="queued")
        await self._queue.put(job_id)
        self._logger.info("Job %d queued: source=%s query=%s", job_id, source, query)
        return job_id

    async def cancel_job(self, job_id: int) -> None:
        self._cancel_requested.add(job_id)
        update_job(job_id, status="cancelled")
        self._logger.info("Job %d cancelled", job_id)

    def get_job(self, job_id: int) -> Optional[dict[str, Any]]:
        return get_job(job_id)

    def list_jobs(self, source: Optional[str] = None, status: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        return list_jobs(source=source, status=status, limit=limit)

    def current_job_id(self) -> Optional[int]:
        return self._current_job_id

    def is_queued(self, job_id: int) -> bool:
        job = get_job(job_id)
        return job is not None and job["status"] == "queued"

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                job_id = await asyncio.wait_for(self._queue.get(), timeout=5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if not self._running:
                break

            self._current_job_id = job_id
            await self._execute_job(job_id)
            self._current_job_id = None
            self._queue.task_done()

    async def _execute_job(self, job_id: int) -> None:
        job = get_job(job_id)
        if job is None:
            self._logger.error("Job %d not found in DB", job_id)
            return

        if job_id in self._cancel_requested:
            self._cancel_requested.discard(job_id)
            update_job(job_id, status="cancelled")
            return

        source = job["source"]
        query = job["query"]
        retry_count = job.get("retry_count", 0)
        self._logger.info("Executing job %d: source=%s query=%s (retry %d)", job_id, source, query, retry_count)
        update_job(job_id, status="running", retry_count=retry_count)

        try:
            success = await self._run_with_timeout(job_id, source, query)
        except asyncio.CancelledError:
            if job_id in self._cancel_requested:
                self._cancel_requested.discard(job_id)
                update_job(job_id, status="cancelled")
            else:
                update_job(job_id, status="failed", error_message="Worker cancelled")
            return
        except Exception as e:
            self._logger.error("Job %d unexpected error: %s", job_id, e)
            success = False

        if job_id in self._cancel_requested:
            self._cancel_requested.discard(job_id)
            update_job(job_id, status="cancelled")
            return

        if success:
            self._logger.info("Job %d completed successfully", job_id)
            update_job(job_id, status="completed")
            leads = get_leads_by_job(job_id)
            if leads:
                from backend.core.exporter import export_job_csv
                export_job_csv(job_id, leads, self._logger)
        else:
            retry_count = increment_job_retry(job_id)
            if retry_count <= _MAX_RETRIES:
                self._logger.info("Job %d will retry (%d/%d)", job_id, retry_count, _MAX_RETRIES)
                await self._queue.put(job_id)
            else:
                self._logger.warning("Job %d failed after %d retries", job_id, retry_count)
                update_job(job_id, status="failed", error_message="Max retries exceeded")

    async def _run_with_timeout(self, job_id: int, source: str, query: Optional[str]) -> bool:
        from backend.core.browser import get_context

        context = await get_context()

        progress_cb = self._make_progress_callback(job_id)

        if source in ("clutch", "goodfirms"):
            return await self._run_search(source, query, context, progress_cb)
        elif source == "maps":
            return await self._run_maps(context, query, progress_cb)
        elif source == "linkedin":
            return await self._run_linkedin(context, query, progress_cb)
        else:
            self._logger.error("Unknown source: %s", source)
            return False

    def _make_progress_callback(self, job_id: int):
        async def cb(current_page: int, total_pages: int, total_found: int):
            pct = min(100.0, (current_page / max(total_pages, 1)) * 100) if total_pages > 0 else 0
            update_job_progress(job_id, progress=pct, current_page=current_page, total_found=total_found)
        return cb

    async def _run_search(self, source: str, query: Optional[str], context, progress_cb) -> bool:
        from backend.config.loader import load_config
        cfg = load_config()

        if source == "clutch":
            from backend.scrapers.agency import clutch
            selectors, build_url, extract_cards = clutch.SELECTORS, clutch.build_search_url, clutch.extract_all_cards
        else:
            from backend.scrapers.agency import goodfirms
            selectors, build_url, extract_cards = goodfirms.SELECTORS, goodfirms.build_search_url, goodfirms.extract_all_cards

        max_pages = int(query.split("|")[1]) if query and "|" in query else 5
        actual_query = query.split("|")[0] if query and "|" in query else (query or "")

        async def search_wrapper():
            return await run_search_scraper(
                context, self._logger, cfg, actual_query, max_pages,
                selectors, build_url, extract_cards, source, "agency",
                progress_callback=progress_cb,
            )

        return await asyncio.wait_for(search_wrapper(), timeout=_PAGE_TIMEOUT * (max_pages + 2))

    async def _run_maps(self, context, query: Optional[str], progress_cb) -> bool:
        from backend.config.loader import load_config
        cfg = load_config()
        actual_query = query or ""
        max_cycles = 30

        async def maps_wrapper():
            return await run_maps_scraper(context, self._logger, cfg, actual_query, max_cycles, progress_callback=progress_cb)

        return await asyncio.wait_for(maps_wrapper(), timeout=_PAGE_TIMEOUT * 10)

    async def _run_linkedin(self, context, query: Optional[str], progress_cb) -> bool:
        from backend.config.loader import load_config
        from pathlib import Path
        cfg = load_config()
        csv_path = Path(query) if query else None

        async def linkedin_wrapper():
            return await run_linkedin_enrichment(context, self._logger, cfg, csv_path, progress_callback=progress_cb)

        return await asyncio.wait_for(linkedin_wrapper(), timeout=_PAGE_TIMEOUT * 50)
