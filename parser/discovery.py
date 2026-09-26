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


class SearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int) -> list[SearchResult]:
        raise NotImplementedError


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

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        offset = 0
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
            while len(results) < limit and offset <= 9:
                count = min(20, limit - len(results))
                params: dict[str, str | int] = {
                    "q": query,
                    "count": count,
                    "offset": offset,
                    "country": self.country,
                    "search_lang": self.search_lang,
                    "safesearch": "moderate",
                }
                response = await client.get(self.API_URL, params=params)
                response.raise_for_status()
                payload = response.json()
                web = payload.get("web", {})
                page = JsonSearchApiProvider._parse_results(payload)
                if not page:
                    break
                results.extend(page)
                more = bool(payload.get("query", {}).get("more_results_available"))
                if not more or not isinstance(web, dict):
                    break
                offset += 1
        return results[:limit]


class JsonSearchApiProvider(SearchProvider):
    """Configurable JSON Search API provider.

    It understands common response layouts: Google ``items``, Serper ``organic``,
    Bing ``webPages.value`` and a generic ``results`` list.
    """

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

    async def search(self, query: str, limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        start = 1
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        if self.api_key_header:
            headers[self.api_key_header] = self.api_key
        async with httpx.AsyncClient(
            timeout=self.timeout,
            headers=headers,
            follow_redirects=True,
        ) as client:
            while len(results) < limit and start <= 100:
                page_size = min(10, limit - len(results))
                params: dict[str, str | int] = {self.query_param: query}
                if self.api_key_param:
                    params[self.api_key_param] = self.api_key
                if self.limit_param:
                    params[self.limit_param] = page_size
                if self.start_param:
                    params[self.start_param] = start
                if self.engine_id:
                    params["cx"] = self.engine_id
                response = await client.get(self.api_url, params=params)
                response.raise_for_status()
                payload = response.json()
                page = self._parse_results(payload)
                if not page:
                    break
                results.extend(page)
                start += len(page)
                if len(page) < page_size:
                    break
        return results[:limit]

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
        raw = await self.provider.search(query, min(max(limit * 2, limit), 200))
        unique: dict[str, SearchResult] = {}
        for result in raw:
            domain = normalize_domain(result.url)
            if not domain or self._is_excluded(domain) or domain in unique:
                continue
            unique[domain] = SearchResult(url=root_url(result.url), title=result.title)
            if len(unique) >= limit:
                break
        return list(unique.values())

    def _is_excluded(self, domain: str) -> bool:
        return any(domain == item or domain.endswith(f".{item}") for item in self.excluded_domains)
