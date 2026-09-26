from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from bot.keyboards import download_menu, limit_menu, main_menu
from bot.states import SearchStates
from database.db import ClinicRepository
from exporters.excel import ExcelExporter
from services.parser_service import ParserService, RunProgress


@dataclass(slots=True)
class JobManager:
    task: asyncio.Task | None = None
    stop_event: asyncio.Event | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def request_stop(self) -> bool:
        if not self.running or self.stop_event is None:
            return False
        self.stop_event.set()
        return True


@dataclass(slots=True)
class BotContext:
    admin_ids: set[int]
    repository: ClinicRepository
    exporter: ExcelExporter
    service: ParserService
    jobs: JobManager


def create_router(context: BotContext) -> Router:
    router = Router(name=__name__)

    def allowed(user_id: int) -> bool:
        return user_id in context.admin_ids

    async def deny_message(message: Message) -> bool:
        if message.from_user and allowed(message.from_user.id):
            return False
        await message.answer("Доступ запрещён.")
        return True

    async def deny_callback(callback: CallbackQuery) -> bool:
        if allowed(callback.from_user.id):
            return False
        await callback.answer("Доступ запрещён.", show_alert=True)
        return True

    @router.message(CommandStart())
    async def command_start(message: Message, state: FSMContext) -> None:
        if await deny_message(message):
            return
        await state.clear()
        await message.answer("Парсер публичных контактов клиник", reply_markup=main_menu())

    @router.callback_query(F.data == "menu")
    async def show_menu(callback: CallbackQuery, state: FSMContext) -> None:
        if await deny_callback(callback):
            return
        await state.clear()
        if callback.message:
            await callback.message.edit_text("Главное меню", reply_markup=main_menu())
        await callback.answer()

    @router.callback_query(F.data == "start_search")
    async def begin_search(callback: CallbackQuery, state: FSMContext) -> None:
        if await deny_callback(callback):
            return
        if context.jobs.running:
            await callback.answer("Сбор уже выполняется.", show_alert=True)
            return
        await state.set_state(SearchStates.waiting_for_query)
        if callback.message:
            await callback.message.answer("Что искать? Например: стоматологии Москва")
        await callback.answer()

    @router.message(SearchStates.waiting_for_query)
    async def accept_query(message: Message, state: FSMContext) -> None:
        if await deny_message(message):
            return
        query = (message.text or "").strip()
        if len(query) < 3:
            await message.answer("Запрос слишком короткий. Введите хотя бы 3 символа.")
            return
        await state.update_data(query=query)
        await state.set_state(SearchStates.waiting_for_limit)
        await message.answer("Сколько сайтов обработать?", reply_markup=limit_menu())

    @router.callback_query(SearchStates.waiting_for_limit, F.data.startswith("limit:"))
    async def accept_limit(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        if await deny_callback(callback):
            return
        if context.jobs.running:
            await callback.answer("Сбор уже выполняется.", show_alert=True)
            return
        data = await state.get_data()
        query = str(data.get("query", "")).strip()
        limit = int((callback.data or "limit:10").split(":", 1)[1])
        await state.clear()
        if not callback.message:
            return
        status = await callback.message.answer(_progress_text(RunProgress(query=query)))
        await callback.answer()
        _start_background_job(
            context,
            bot,
            status.chat.id,
            status.message_id,
            lambda stop, notify: context.service.run_search(query, limit, stop, notify),
        )

    @router.callback_query(SearchStates.waiting_for_limit, F.data == "custom_limit")
    async def request_custom_limit(callback: CallbackQuery, state: FSMContext) -> None:
        if await deny_callback(callback):
            return
        if context.jobs.running:
            await callback.answer("Сбор уже выполняется.", show_alert=True)
            return
        await state.set_state(SearchStates.waiting_for_custom_limit)
        if callback.message:
            await callback.message.answer("Введите количество сайтов от 1 до 200.")
        await callback.answer()

    @router.message(SearchStates.waiting_for_custom_limit)
    async def accept_custom_limit(message: Message, state: FSMContext, bot: Bot) -> None:
        if await deny_message(message):
            return
        if context.jobs.running:
            await message.answer("Сбор уже выполняется.")
            return
        limit = parse_site_limit(message.text or "")
        if limit is None:
            await message.answer("Введите целое число от 1 до 200.")
            return
        data = await state.get_data()
        query = str(data.get("query", "")).strip()
        await state.clear()
        status = await message.answer(_progress_text(RunProgress(query=query)))
        _start_background_job(
            context,
            bot,
            status.chat.id,
            status.message_id,
            lambda stop, notify: context.service.run_search(query, limit, stop, notify),
        )

    @router.callback_query(F.data == "retry_failed")
    async def retry_failed(callback: CallbackQuery, bot: Bot) -> None:
        if await deny_callback(callback):
            return
        if context.jobs.running:
            await callback.answer("Сбор уже выполняется.", show_alert=True)
            return
        failed = await context.repository.list_failed()
        if not failed:
            await callback.answer("Ошибок для повтора нет.", show_alert=True)
            return
        if not callback.message:
            return
        status = await callback.message.answer(_progress_text(RunProgress(query="Повтор ошибок")))
        await callback.answer()
        _start_background_job(
            context,
            bot,
            status.chat.id,
            status.message_id,
            lambda stop, notify: context.service.retry_failed(stop, notify),
        )

    @router.callback_query(F.data == "stop_job")
    async def stop_job(callback: CallbackQuery) -> None:
        if await deny_callback(callback):
            return
        if context.jobs.request_stop():
            await callback.answer("Остановка запрошена. Текущие сайты будут завершены.", show_alert=True)
        else:
            await callback.answer("Активной задачи нет.", show_alert=True)

    @router.callback_query(F.data == "statistics")
    async def statistics(callback: CallbackQuery) -> None:
        if await deny_callback(callback):
            return
        stats = await context.repository.statistics()
        text = (
            "Статистика\n\n"
            f"Всего уникальных доменов: {stats['total']}\n"
            f"Успешно распарсено: {stats['parsed']}\n"
            f"Ошибок: {stats['failed']}\n"
            f"Добавлено сегодня: {stats['today']}\n"
            f"Последний запуск: {stats['last_run'] or 'ещё не было'}"
        )
        if callback.message:
            await callback.message.answer(text, reply_markup=main_menu())
        await callback.answer()

    @router.callback_query(F.data == "download_excel")
    async def download_excel(callback: CallbackQuery) -> None:
        if await deny_callback(callback):
            return
        path = await context.exporter.export_all_to_excel()
        if callback.message:
            await callback.message.answer_document(
                FSInputFile(path, filename="clinics.xlsx"),
                caption="Актуальная выгрузка из SQLite",
            )
        await callback.answer()

    return router


def _start_background_job(context, bot, chat_id, message_id, runner) -> None:
    stop_event = asyncio.Event()
    context.jobs.stop_event = stop_event

    async def work() -> None:
        last_update = 0.0

        async def notify(progress: RunProgress) -> None:
            nonlocal last_update
            now = time.monotonic()
            if now - last_update < 1.5 and progress.processed < progress.discovered:
                return
            last_update = now
            try:
                await bot.edit_message_text(
                    _progress_text(progress), chat_id=chat_id, message_id=message_id
                )
            except TelegramBadRequest:
                pass

        try:
            progress = await runner(stop_event, notify)
            stats = await context.repository.statistics()
            await bot.edit_message_text(
                _finished_text(progress, int(stats["parsed"])),
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=download_menu(),
            )
        except Exception as exc:
            await bot.edit_message_text(
                f"Задача завершилась с ошибкой: {type(exc).__name__}: {exc}",
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=main_menu(),
            )
        finally:
            context.jobs.task = None
            context.jobs.stop_event = None

    context.jobs.task = asyncio.create_task(work())


def parse_site_limit(value: str) -> int | None:
    try:
        limit = int(value.strip())
    except ValueError:
        return None
    return limit if 1 <= limit <= 200 else None


def _progress_text(progress: RunProgress) -> str:
    return (
        "Сбор запущен\n\n"
        f"Найдено сайтов: {progress.discovered}\n"
        f"Уже были в базе: {progress.duplicates}\n"
        f"Новых обработано: {progress.processed}\n"
        f"Успешно: {progress.successful}\n"
        f"Ошибок: {progress.failed}"
    )


def _finished_text(progress: RunProgress, total_parsed: int) -> str:
    title = "Остановлено" if progress.stopped else "Готово"
    return (
        f"{title}\n\n"
        f"Новых клиник: {progress.successful}\n"
        f"Пропущено дублей: {progress.duplicates}\n"
        f"Ошибок: {progress.failed}\n"
        f"Всего клиник в базе: {total_parsed}"
    )
