from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Начать поиск", callback_data="start_search")],
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="statistics"),
                InlineKeyboardButton(text="📁 Скачать Excel", callback_data="download_excel"),
            ],
            [
                InlineKeyboardButton(text="🔁 Повторить ошибки", callback_data="retry_failed"),
                InlineKeyboardButton(text="⛔ Остановить", callback_data="stop_job"),
            ],
        ]
    )


def limit_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="10", callback_data="limit:10"),
                InlineKeyboardButton(text="50", callback_data="limit:50"),
                InlineKeyboardButton(text="100", callback_data="limit:100"),
            ],
            [InlineKeyboardButton(text="✏️ Своё количество", callback_data="custom_limit")],
        ]
    )


def download_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 Скачать Excel", callback_data="download_excel")],
            [InlineKeyboardButton(text="В меню", callback_data="menu")],
        ]
    )
