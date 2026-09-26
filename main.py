from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from bot.handlers import BotContext, JobManager, create_router
from config import Settings
from database.db import ClinicRepository
from exporters.excel import ExcelExporter
from parser.crawler import ClinicCrawler
from parser.discovery import BraveSearchProvider, DiscoveryService, JsonSearchApiProvider
from services.parser_service import ParserService


async def main() -> None:
    settings = Settings.from_env()
    settings.validate_for_bot()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    repository = ClinicRepository(settings.database_path)
    await repository.initialize()
    exporter = ExcelExporter(repository, settings.excel_path)

    if settings.search_provider == "brave":
        provider = BraveSearchProvider(
            api_key=settings.search_api_key,
            timeout=settings.request_timeout,
            user_agent=settings.user_agent,
            country=settings.brave_country,
            search_lang=settings.brave_search_lang,
        )
    elif settings.search_provider == "json":
        provider = JsonSearchApiProvider(
            api_url=settings.search_api_url,
            api_key=settings.search_api_key,
            api_key_param=settings.search_api_key_param,
            api_key_header=settings.search_api_key_header,
            query_param=settings.search_query_param,
            limit_param=settings.search_limit_param,
            start_param=settings.search_start_param,
            engine_id=settings.search_engine_id,
            timeout=settings.request_timeout,
            user_agent=settings.user_agent,
        )
    else:
        raise RuntimeError(
            "SEARCH_PROVIDER должен быть 'brave' или 'json'"
        )
    discovery = DiscoveryService(provider, settings.excluded_domains)
    crawler = ClinicCrawler(
        timeout=settings.request_timeout,
        retries=settings.request_retries,
        user_agent=settings.user_agent,
        max_pages=settings.max_pages_per_site,
        playwright_enabled=settings.playwright_enabled,
    )
    service = ParserService(
        discovery=discovery,
        crawler=crawler,
        repository=repository,
        exporter=exporter,
        concurrency=settings.concurrency,
        min_delay=settings.min_delay,
        max_delay=settings.max_delay,
    )

    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(
        create_router(
            BotContext(
                admin_id=settings.admin_telegram_id,
                repository=repository,
                exporter=exporter,
                service=service,
                jobs=JobManager(),
            )
        )
    )
    try:
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
