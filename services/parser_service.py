from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, replace
from typing import Awaitable, Callable

from database.db import ClinicRepository
from exporters.excel import ExcelExporter
from parser.crawler import ClinicCrawler
from parser.discovery import DiscoveryService
from parser.normalizer import normalize_domain


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunProgress:
    query: str
    discovered: int = 0
    duplicates: int = 0
    processed: int = 0
    successful: int = 0
    failed: int = 0
    stopped: bool = False


ProgressCallback = Callable[[RunProgress], Awaitable[None]]


class ParserService:
    def __init__(
        self,
        *,
        discovery: DiscoveryService,
        crawler: ClinicCrawler,
        repository: ClinicRepository,
        exporter: ExcelExporter,
        concurrency: int,
        min_delay: float,
        max_delay: float,
    ) -> None:
        self.discovery = discovery
        self.crawler = crawler
        self.repository = repository
        self.exporter = exporter
        self.concurrency = max(1, concurrency)
        self.min_delay = min_delay
        self.max_delay = max(max_delay, min_delay)

    async def run_search(
        self,
        query: str,
        limit: int,
        stop_event: asyncio.Event,
        on_progress: ProgressCallback | None = None,
    ) -> RunProgress:
        run_id = await self.repository.start_run(query)
        progress = RunProgress(query=query)
        try:
            results = await self.discovery.discover(query, limit)
            progress.discovered = len(results)
            targets: list[tuple[str, str]] = []
            for result in results:
                domain = normalize_domain(result.url)
                if await self.repository.reserve_new(domain, result.url):
                    targets.append((domain, result.url))
                else:
                    progress.duplicates += 1
            await self._notify(on_progress, progress)
            await self._process_targets(targets, progress, stop_event, on_progress)
            return progress
        finally:
            progress.stopped = stop_event.is_set()
            await self.repository.finish_run(
                run_id,
                discovered=progress.discovered,
                duplicates=progress.duplicates,
                successful=progress.successful,
                failed=progress.failed,
                stopped=progress.stopped,
            )

    async def retry_failed(
        self,
        stop_event: asyncio.Event,
        on_progress: ProgressCallback | None = None,
    ) -> RunProgress:
        failed = await self.repository.list_failed()
        progress = RunProgress(query="Повтор ошибок", discovered=len(failed))
        run_id = await self.repository.start_run(progress.query)
        try:
            targets = [(clinic.domain, clinic.website) for clinic in failed]
            await self._notify(on_progress, progress)
            await self._process_targets(targets, progress, stop_event, on_progress)
            return progress
        finally:
            progress.stopped = stop_event.is_set()
            await self.repository.finish_run(
                run_id,
                discovered=progress.discovered,
                duplicates=0,
                successful=progress.successful,
                failed=progress.failed,
                stopped=progress.stopped,
            )

    async def _process_targets(
        self,
        targets: list[tuple[str, str]],
        progress: RunProgress,
        stop_event: asyncio.Event,
        on_progress: ProgressCallback | None,
    ) -> None:
        semaphore = asyncio.Semaphore(self.concurrency)
        progress_lock = asyncio.Lock()

        async def process(domain: str, url: str) -> None:
            async with semaphore:
                if stop_event.is_set():
                    await self.repository.release_new(domain)
                    return
                try:
                    clinic = await self.crawler.crawl(url)
                    await self.repository.mark_parsed(clinic)
                    await self.exporter.export_all_to_excel()
                    success = True
                except Exception as exc:
                    await self.repository.mark_failed(domain, f"{type(exc).__name__}: {exc}")
                    success = False
                async with progress_lock:
                    progress.processed += 1
                    if success:
                        progress.successful += 1
                    else:
                        progress.failed += 1
                    snapshot = replace(progress)
                await self._notify(on_progress, snapshot)
                if not stop_event.is_set():
                    await asyncio.sleep(random.uniform(self.min_delay, self.max_delay))

        tasks = [asyncio.create_task(process(domain, url)) for domain, url in targets]
        if tasks:
            await asyncio.gather(*tasks)
        progress.stopped = stop_event.is_set()

    @staticmethod
    async def _notify(callback: ProgressCallback | None, progress: RunProgress) -> None:
        if callback:
            try:
                await callback(replace(progress))
            except Exception:
                logger.exception("Не удалось обновить сообщение о прогрессе")
