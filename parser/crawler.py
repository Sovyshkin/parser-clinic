from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from database.models import Clinic, ClinicStatus, utc_now_iso
from parser.contacts import (
    ExtractedContacts,
    clinic_name,
    contact_page_links,
    extract_contacts,
    is_probably_clinic,
)
from parser.normalizer import normalize_domain, root_url, unique_sorted


class CrawlError(RuntimeError):
    pass


class AccessDeniedError(CrawlError):
    pass


@dataclass(slots=True)
class Page:
    url: str
    html: str


class ClinicCrawler:
    def __init__(
        self,
        *,
        timeout: float,
        retries: int,
        user_agent: str,
        max_pages: int = 5,
        playwright_enabled: bool = True,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self.max_pages = min(5, max(1, max_pages))
        self.playwright_enabled = playwright_enabled

    async def crawl(self, website: str) -> Clinic:
        domain = normalize_domain(website)
        home = await self._fetch_http(root_url(website))
        if not is_probably_clinic(home.html, home.url):
            raise CrawlError("Сайт не прошёл проверку на тематику клиники")

        pages = [home]
        links = contact_page_links(
            home.html,
            home.url,
            domain,
            limit=self.max_pages - 1,
        )
        for link in links:
            try:
                pages.append(await self._fetch_http(link))
            except CrawlError:
                continue

        contacts = self._merge_contacts(pages)
        if self.playwright_enabled and self._needs_browser(pages, contacts):
            rendered_pages: list[Page] = []
            for page in pages:
                rendered_pages.append(await self._fetch_playwright(page.url) or page)
            rendered_home = rendered_pages[0]
            known = {page.url for page in rendered_pages}
            extra_links = contact_page_links(
                rendered_home.html,
                rendered_home.url,
                domain,
                limit=self.max_pages - 1,
            )
            for link in extra_links:
                if len(rendered_pages) >= self.max_pages or link in known:
                    continue
                rendered = await self._fetch_playwright(link)
                if rendered:
                    rendered_pages.append(rendered)
                    known.add(rendered.url)
            pages = rendered_pages
            contacts = self._merge_contacts(pages)

        return Clinic(
            domain=domain,
            website=home.url,
            clinic_name=clinic_name(pages[0].html),
            phones=contacts.phones,
            emails=contacts.emails,
            telegram=contacts.telegram,
            whatsapp=contacts.whatsapp,
            vk=contacts.vk,
            address=contacts.address,
            parsed_at=utc_now_iso(),
            status=ClinicStatus.PARSED,
        )

    async def _fetch_http(self, url: str) -> Page:
        last_error = ""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru,en;q=0.8",
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            headers=headers,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        ) as client:
            for attempt in range(self.retries + 1):
                try:
                    response = await client.get(url)
                    if response.status_code in {403, 429}:
                        raise AccessDeniedError(f"Сайт запретил доступ: HTTP {response.status_code}")
                    if response.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"HTTP {response.status_code}", request=response.request, response=response
                        )
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "html" not in content_type.lower() and content_type:
                        raise CrawlError(f"Ответ не является HTML: {content_type}")
                    return Page(str(response.url), response.text)
                except AccessDeniedError:
                    raise
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                    last_error = str(exc)
                    if attempt < self.retries:
                        await asyncio.sleep(0.6 * (attempt + 1))
        raise CrawlError(f"Не удалось загрузить {url}: {last_error}")

    async def _fetch_playwright(self, url: str) -> Page | None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=self.user_agent)
                response = await page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout * 1000))
                if response and response.status in {403, 429}:
                    await browser.close()
                    raise AccessDeniedError(f"Сайт запретил доступ: HTTP {response.status}")
                await page.wait_for_timeout(1000)
                html = await page.content()
                final_url = page.url
                await browser.close()
                return Page(final_url, html)
        except AccessDeniedError:
            raise
        except Exception:
            return None

    @staticmethod
    def _needs_browser(pages: list[Page], contacts: ExtractedContacts) -> bool:
        has_contacts = bool(contacts.phones or contacts.emails or contacts.telegram or contacts.whatsapp)
        home_lower = pages[0].html.lower()
        little_text = len(home_lower) < 3000
        app_shell = any(marker in home_lower for marker in ('id="root"', 'id="app"', "__next_data__"))
        return not has_contacts and (little_text or app_shell)

    @staticmethod
    def _merge_contacts(pages: list[Page]) -> ExtractedContacts:
        phones: list[str] = []
        emails: list[str] = []
        telegram: list[str] = []
        whatsapp: list[str] = []
        vk: list[str] = []
        address = ""
        for page in pages:
            found = extract_contacts(page.html, page.url)
            phones.extend(found.phones)
            emails.extend(found.emails)
            telegram.extend(found.telegram)
            whatsapp.extend(found.whatsapp)
            vk.extend(found.vk)
            address = address or found.address
        return ExtractedContacts(
            phones=unique_sorted(phones),
            emails=unique_sorted(emails),
            telegram=unique_sorted(telegram),
            whatsapp=unique_sorted(whatsapp),
            vk=unique_sorted(vk),
            address=address,
        )
