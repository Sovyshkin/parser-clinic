from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from parser.normalizer import normalize_domain, root_url


@dataclass(frozen=True, slots=True)
class SearchResult:
    url: str
    title: str = ""


@dataclass(frozen=True, slots=True)
class SearchPage:
    results: tuple[SearchResult, ...]
    has_more: bool


class SearchProvider(ABC):
    page_size = 20

    @abstractmethod
    async def search_page(self, query: str, page: int, page_size: int) -> SearchPage:
        raise NotImplementedError

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        page_number = 0
        while len(results) < limit:
            requested = min(self.page_size, limit - len(results))
            page = await self.search_page(query, page_number, requested)
            if not page.results:
                break
            results.extend(page.results)
            if not page.has_more:
                break
            page_number += 1
        return results[:limit]


class BraveSearchProvider(SearchProvider):
    API_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(
        self,
        *,
        api_key: str,
        timeout: float,
        user_agent: str,
        country: str = "ru",
        search_lang: str = "ru",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.user_agent = user_agent
        self.country = country
        self.search_lang = search_lang
        self.transport = transport

    async def search_page(self, query: str, page: int, page_size: int) -> SearchPage:
        if not 0 <= page <= 9:
            return SearchPage((), False)
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": self.user_agent,
            "X-Subscription-Token": self.api_key,
        }
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers=headers,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            params: dict[str, str | int] = {
                "q": query,
                "count": min(20, max(1, page_size)),
                "offset": page,
                "country": self.country,
                "search_lang": self.search_lang,
                "safesearch": "moderate",
            }
            response = await client.get(self.API_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        results = tuple(JsonSearchApiProvider._parse_results(payload))
        more = bool(payload.get("query", {}).get("more_results_available"))
        return SearchPage(results, more and page < 9)


class JsonSearchApiProvider(SearchProvider):
    """Configurable JSON Search API provider.

    It understands common response layouts: Google ``items``, Serper ``organic``,
    Bing ``webPages.value`` and a generic ``results`` list.
    """

    page_size = 10

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        api_key_param: str = "key",
        api_key_header: str = "",
        query_param: str = "q",
        limit_param: str = "num",
        start_param: str = "start",
        engine_id: str = "",
        timeout: float = 20.0,
        user_agent: str,
    ) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.api_key_param = api_key_param
        self.api_key_header = api_key_header
        self.query_param = query_param
        self.limit_param = limit_param
        self.start_param = start_param
        self.engine_id = engine_id
        self.timeout = timeout
        self.user_agent = user_agent

    async def search_page(self, query: str, page: int, page_size: int) -> SearchPage:
        start = page * self.page_size + 1
        if start > 100:
            return SearchPage((), False)
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if self.api_key_header:
            headers[self.api_key_header] = self.api_key
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers=headers,
            follow_redirects=True,
        ) as client:
            params: dict[str, str | int] = {self.query_param: query}
            if self.api_key_param:
                params[self.api_key_param] = self.api_key
            if self.limit_param:
                params[self.limit_param] = min(self.page_size, max(1, page_size))
            if self.start_param:
                params[self.start_param] = start
            if self.engine_id:
                params["cx"] = self.engine_id
            response = await client.get(self.api_url, params=params)
            response.raise_for_status()
            payload = response.json()
        results = tuple(self._parse_results(payload))
        explicit_more = payload.get("query", {}).get("more_results_available")
        has_more = bool(explicit_more) if explicit_more is not None else len(results) >= page_size
        return SearchPage(results, has_more and start + len(results) <= 100)

    @staticmethod
    def _parse_results(payload: dict[str, Any]) -> list[SearchResult]:
        candidates: list[dict[str, Any]] = []
        web = payload.get("web")
        if isinstance(web, dict) and isinstance(web.get("results"), list):
            candidates = web["results"]
        for key in ("items", "organic", "results"):
            if not candidates and isinstance(payload.get(key), list):
                candidates = payload[key]
                break
        if not candidates:
            web_pages = payload.get("webPages")
            if isinstance(web_pages, dict) and isinstance(web_pages.get("value"), list):
                candidates = web_pages["value"]
        parsed: list[SearchResult] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            url = item.get("link") or item.get("url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                parsed.append(SearchResult(url=url, title=str(item.get("title", ""))))
        return parsed


class DiscoveryService:
    def __init__(self, provider: SearchProvider, excluded_domains: set[str]) -> None:
        self.provider = provider
        self.excluded_domains = {domain.lower().removeprefix("www.") for domain in excluded_domains}

    async def discover(self, query: str, limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        async for result in self.iter_discover(query, limit):
            results.append(result)
        return results

    async def iter_discover(self, query: str, limit: int):
        unique: dict[str, SearchResult] = {}
        page_number = 0
        raw_count = 0
        while raw_count < limit:
            requested = min(self.provider.page_size, limit - raw_count)
            page = await self.provider.search_page(query, page_number, requested)
            if not page.results:
                break
            raw_count += len(page.results)
            for result in page.results:
                domain = normalize_domain(result.url)
                if not domain or self._is_excluded(domain) or domain in unique:
                    continue
                normalized = SearchResult(url=root_url(result.url), title=result.title)
                unique[domain] = normalized
                yield normalized
            if not page.has_more:
                break
            page_number += 1

    def _is_excluded(self, domain: str) -> bool:
        return any(domain == item or domain.endswith(f".{item}") for item in self.excluded_domains)
