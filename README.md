# Парсер публичных контактов клиник

Асинхронное Python-приложение ищет сайты клиник через Brave Search API, проверяет тематику сайта, собирает публичные контакты и сохраняет результат в SQLite. Excel-файл пересобирается из базы после каждого успешно обработанного нового домена. Управление выполняется через Telegram-бота на aiogram 3.

## Что входит в проект

- сменный интерфейс `SearchProvider`, отдельный провайдер Brave Search и универсальный провайдер для других JSON Search API;
- нормализация и постоянная дедупликация доменов через уникальный индекс SQLite;
- статусы `new`, `parsed`, `failed` и отдельный повтор ошибок;
- ограниченный обход главной страницы и максимум четырёх релевантных внутренних страниц;
- извлечение телефонов, email, Telegram, WhatsApp, VK и достоверно размеченного адреса;
- HTTP-запросы с таймаутом, повторами сетевых/серверных ошибок, User-Agent и ограничением параллельности;
- Playwright как fallback для страниц, где контент появляется через JavaScript;
- атомарная пересборка `data/clinics.xlsx` из SQLite;
- Telegram-меню, одно обновляемое сообщение прогресса и мягкая остановка.

Парсер не обходит CAPTCHA и защиту сайтов. Ответы `403` и `429` сохраняются как ошибки без попытки обхода. Сбор предназначен только для опубликованных бизнес-контактов организации. Перед использованием проверьте правила сайтов, Search API и применимое законодательство.

## Установка

Требуется Python 3.10 или новее.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Заполните `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=токен_бота
SEARCH_API_KEY=ключ_brave_search
SEARCH_PROVIDER=brave
ADMIN_TELEGRAM_IDS=ваш_telegram_id
```

`ADMIN_TELEGRAM_IDS` ограничивает управление ботом указанными администраторами. Несколько числовых ID перечисляются через запятую:

```dotenv
ADMIN_TELEGRAM_IDS=123456789,987654321
```

Старое имя `ADMIN_TELEGRAM_ID` для одного администратора также поддерживается.

### Получение ключа Brave Search API

1. Откройте [Brave Search API](https://api-dashboard.search.brave.com/app/keys) и создайте аккаунт.
2. На странице тарифов активируйте план Search. Brave указывает стоимость 5 долларов за 1000 запросов и ежемесячные бесплатные кредиты на 5 долларов. Для активации может потребоваться банковская карта.
3. Откройте раздел API Keys, нажмите Add API Key и скопируйте созданный ключ.
4. Запишите ключ только в локальный `.env`:

```dotenv
SEARCH_PROVIDER=brave
SEARCH_API_KEY=ваш_ключ
BRAVE_COUNTRY=ru
BRAVE_SEARCH_LANG=ru
```

Приложение передаёт ключ в требуемом Brave заголовке `X-Subscription-Token`. Ключ не попадает в URL, исходный код или Excel.

Проверить ключ отдельно можно командой:

```bash
curl -sS "https://api.search.brave.com/res/v1/web/search?q=стоматологии%20Москва&count=5&country=ru&search_lang=ru" \
  -H "Accept: application/json" \
  -H "X-Subscription-Token: ВАШ_КЛЮЧ"
```

Документация: [быстрый старт](https://api-dashboard.search.brave.com/documentation/quickstart), [Web Search API](https://api-dashboard.search.brave.com/app/documentation/web-search), [тарифы](https://brave.com/search/api/).

### Другой JSON Search API

Для другого GET-based JSON Search API установите `SEARCH_PROVIDER=json`. `JsonSearchApiProvider` понимает несколько распространённых форматов ответа:

- `items[].link`;
- `organic[].link`;
- `results[].url` или `results[].link`;
- `webPages.value[].url`.

Имена параметров настраиваются через `SEARCH_QUERY_PARAM`, `SEARCH_API_KEY_PARAM`, `SEARCH_LIMIT_PARAM` и `SEARCH_START_PARAM`. Если API принимает ключ в HTTP-заголовке, задайте имя заголовка в `SEARCH_API_KEY_HEADER`, а `SEARCH_API_KEY_PARAM` оставьте пустым. Пример:

```dotenv
SEARCH_PROVIDER=json
SEARCH_API_URL=https://адрес-api/search
SEARCH_API_KEY=ключ
```

## Запуск

```bash
python main.py
```

При первом запуске автоматически создаётся `data/clinics.db`. Excel-файл появляется после первого успешного сайта или по кнопке скачивания.

## Работа бота

1. Нажмите «Начать поиск».
2. Отправьте запрос, например `стоматологии Москва`.
3. Выберите 10, 50, 100 сайтов или нажмите «Своё количество» и введите число от 1 до 100.
4. Следите за одним обновляемым статусным сообщением.

Кнопка «Остановить» запрещает начинать следующие сайты. Уже начатые запросы корректно завершаются. «Повторить ошибки» обрабатывает только записи со статусом `failed`.

## Данные

SQLite — основной источник данных. Таблица `clinics` имеет уникальный индекс по нормализованному `domain`. Обычный поиск пропускает любой домен, который уже есть в базе. Повторная обработка `failed` выполняется только отдельной командой.

Excel содержит один лист `Clinics` и колонки:

`Domain`, `Website`, `Clinic Name`, `Phones`, `Emails`, `Telegram`, `WhatsApp`, `VK`, `Address`, `Parsed At`.

Полную выгрузку можно восстановить программно:

```python
import asyncio
from pathlib import Path
from database.db import ClinicRepository
from exporters.excel import export_all_to_excel

async def main():
    repository = ClinicRepository(Path("data/clinics.db"))
    await repository.initialize()
    await export_all_to_excel(repository, Path("data/clinics.xlsx"))

asyncio.run(main())
```

## Проверка

```bash
python -m unittest discover -s tests -v
```

Тесты не обращаются к внешней сети. Они проверяют нормализацию, извлечение контактов, дедупликацию между открытиями базы и Excel-экспорт.
