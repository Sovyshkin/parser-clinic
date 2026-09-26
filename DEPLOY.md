# Развёртывание на Ubuntu рядом с существующим PM2-проектом

Парсер запускается как отдельный процесс PM2 `clinic-parser-bot`. Он использует Telegram long polling, поэтому отдельный домен, Nginx-конфигурация, SSL-сертификат и входящий TCP-порт ему не нужны. Существующий процесс `angel-wings-telegram` и конфигурацию `/etc/nginx/sites-available/telegram-relay` менять не требуется.

## 1. Проверить сервер

```bash
python3 --version
node --version
pm2 list
free -h
df -h /
```

Нужен Python 3.10 или новее. При памяти меньше 2 GB установите `CONCURRENCY=1`; в остальных случаях начните с `CONCURRENCY=2`.

## 2. Создать отдельную директорию

```bash
mkdir -p /var/www/clinic-parser
```

Скопируйте содержимое проекта в `/var/www/clinic-parser`. Не помещайте его внутрь `/var/www/angel-wings`.

Пример с локального компьютера:

```bash
rsync -av --exclude '.git' --exclude '.venv' --exclude '.env' \
  './' root@SERVER_IP:/var/www/clinic-parser/
```

## 3. Установить Python-окружение

На сервере:

```bash
apt-get update
apt-get install -y python3 python3-venv python3-pip
cd /var/www/clinic-parser
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install --with-deps chromium
```

Команда Playwright установит Chromium и его системные библиотеки. Браузер запускается только как fallback для JavaScript-сайтов.

## 4. Создать `.env`

```bash
cd /var/www/clinic-parser
cp .env.example .env
nano .env
chmod 600 .env
```

Минимальная конфигурация:

```dotenv
TELEGRAM_BOT_TOKEN=токен_от_BotFather
ADMIN_TELEGRAM_ID=числовой_telegram_id

SEARCH_PROVIDER=brave
SEARCH_API_KEY=ключ_Brave_Search_API
BRAVE_COUNTRY=ru
BRAVE_SEARCH_LANG=ru

CONCURRENCY=2
REQUEST_TIMEOUT=20
REQUEST_RETRIES=2
MIN_DELAY=0.7
MAX_DELAY=1.8
MAX_PAGES_PER_SITE=5
PLAYWRIGHT_ENABLED=true
```

Токены должны оставаться только в `.env` на сервере.

## 5. Проверить запуск без PM2

```bash
cd /var/www/clinic-parser
.venv/bin/python main.py
```

Откройте Telegram и отправьте боту `/start`. После проверки остановите процесс через `Ctrl+C`.

## 6. Запустить отдельным процессом PM2

```bash
cd /var/www/clinic-parser
pm2 start ecosystem.config.cjs
pm2 list
pm2 logs clinic-parser-bot --lines 100
```

В списке должны быть два независимых процесса: существующий `angel-wings-telegram` и новый `clinic-parser-bot`.

Сохраните текущий список PM2 для восстановления после перезагрузки:

```bash
pm2 save
```

Не выполняйте `pm2 delete all` или `pm2 restart all`, чтобы не затронуть существующий проект.

## 7. Команды обслуживания

```bash
pm2 status clinic-parser-bot
pm2 logs clinic-parser-bot --lines 200
pm2 restart clinic-parser-bot
pm2 stop clinic-parser-bot
pm2 start clinic-parser-bot
```

После обновления файлов:

```bash
cd /var/www/clinic-parser
.venv/bin/pip install -r requirements.txt
pm2 restart clinic-parser-bot --update-env
pm2 save
```

## 8. Данные и резервная копия

Постоянные данные находятся в:

```text
/var/www/clinic-parser/data/clinics.db
/var/www/clinic-parser/data/clinics.xlsx
```

Для резервной копии достаточно остановить только этот процесс и скопировать каталог `data`:

```bash
pm2 stop clinic-parser-bot
cp -a /var/www/clinic-parser/data /var/backups/clinic-parser-data
pm2 start clinic-parser-bot
```

