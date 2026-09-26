import asyncio
import tempfile
import unittest
from pathlib import Path

from database.db import ClinicRepository
from database.models import Clinic, ClinicStatus, utc_now_iso
from exporters.excel import ExcelExporter
from parser.discovery import SearchResult
from parser.normalizer import normalize_domain
from services.parser_service import ParserService


class FakeDiscovery:
    async def discover(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult("https://one.example/"),
            SearchResult("https://two.example/"),
        ][:limit]


class FakeCrawler:
    def __init__(self) -> None:
        self.fail_two = True
        self.calls: list[str] = []

    async def crawl(self, website: str) -> Clinic:
        domain = normalize_domain(website)
        self.calls.append(domain)
        if domain == "two.example" and self.fail_two:
            raise RuntimeError("temporary failure")
        return Clinic(
            domain=domain,
            website=website,
            clinic_name=domain,
            parsed_at=utc_now_iso(),
            status=ClinicStatus.PARSED,
        )


class ExtendedDiscovery:
    async def discover(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(f"https://clinic-{index}.example/")
            for index in range(1, 7)
        ][:limit]


class OneFailureCrawler:
    async def crawl(self, website: str) -> Clinic:
        domain = normalize_domain(website)
        if domain == "clinic-3.example":
            raise RuntimeError("temporary failure")
        return Clinic(
            domain=domain,
            website=website,
            clinic_name=domain,
            parsed_at=utc_now_iso(),
            status=ClinicStatus.PARSED,
        )


class ParserServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.repository = ClinicRepository(root / "clinics.db")
        await self.repository.initialize()
        self.crawler = FakeCrawler()
        self.service = ParserService(
            discovery=FakeDiscovery(),
            crawler=self.crawler,
            repository=self.repository,
            exporter=ExcelExporter(self.repository, root / "clinics.xlsx"),
            concurrency=2,
            min_delay=0,
            max_delay=0,
        )

    async def asyncTearDown(self) -> None:
        self.tempdir.cleanup()

    async def test_deduplication_and_failed_retry(self) -> None:
        first = await self.service.run_search("test", 2, asyncio.Event())
        self.assertEqual((first.successful, first.failed), (1, 1))

        second = await self.service.run_search("test", 2, asyncio.Event())
        self.assertEqual(second.duplicates, 2)
        self.assertEqual(second.processed, 0)

        self.crawler.fail_two = False
        retry = await self.service.retry_failed(asyncio.Event())
        self.assertEqual((retry.successful, retry.failed), (1, 0))
        self.assertEqual(await self.repository.get_status("two.example"), ClinicStatus.PARSED)

    async def test_stop_releases_unstarted_reservations(self) -> None:
        stop_event = asyncio.Event()
        stop_event.set()
        stopped = await self.service.run_search("test", 2, stop_event)
        self.assertTrue(stopped.stopped)
        self.assertIsNone(await self.repository.get_status("one.example"))
        self.assertIsNone(await self.repository.get_status("two.example"))

    async def test_continues_until_requested_new_clinics_are_added(self) -> None:
        for index in (1, 2):
            domain = f"clinic-{index}.example"
            await self.repository.reserve_new(domain, f"https://{domain}/")
            await self.repository.mark_parsed(
                Clinic(
                    domain=domain,
                    website=f"https://{domain}/",
                    parsed_at=utc_now_iso(),
                    status=ClinicStatus.PARSED,
                )
            )
        service = ParserService(
            discovery=ExtendedDiscovery(),
            crawler=OneFailureCrawler(),
            repository=self.repository,
            exporter=self.service.exporter,
            concurrency=1,
            min_delay=0,
            max_delay=0,
        )

        progress = await service.run_search("test", 2, asyncio.Event())

        self.assertEqual(progress.duplicates, 2)
        self.assertEqual(progress.successful, 2)
        self.assertEqual(progress.failed, 1)
        self.assertEqual(progress.processed, 3)


if __name__ == "__main__":
    unittest.main()
