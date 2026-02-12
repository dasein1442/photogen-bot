# Photogen Telegram Bot

Телеграм-бот для нейрофотосессий.

---

## Как запустить

### 1. Создай бота в Telegram

1. Открой Telegram, найди **@BotFather**
2. Напиши `/newbot` и следуй инструкциям
3. Скопируй токен (выглядит как `123456789:ABCdef...`)

### 2. Настрой конфиг

Скопируй файл `.env.example` в `.env`:

```
cp .env.example .env
```

Открой `.env` и вставь свой токен:

```
BOT_TOKEN=123456789:ABCdef...
```

### 3. Установи зависимости

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> На Windows вместо `source .venv/bin/activate` используй `.venv\Scripts\activate`

### 4. Запусти бота

```
python main.py
```

Бот запущен. Открой своего бота в Telegram и напиши `/start`.

---

## Структура проекта

```
telegram-bot/
├── main.py                  — точка входа, запуск бота
├── requirements.txt         — зависимости
├── .env                     — настройки (не попадает в git)
├── .env.example             — пример настроек
└── app/
    ├── config.py            — настройки из .env
    ├── handlers/
    │   └── start.py         — обработчик команды /start
    └── api/
        └── backend.py       — клиент для бэкенда (заготовка)
```
