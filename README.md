# 🤖 Telegram Media Bot

Многофункциональный Telegram-бот для скачивания медиа и поиска артов.

## ✨ Возможности

| Функция | Описание |
|---------|----------|
| ▶️ YouTube | Видео и аудио (до 50 МБ) |
| 🎵 TikTok | Видео без водяного знака |
| 📸 Instagram | Фото, Reels, Stories |
| 🐦 Twitter/X | Фото и видео из твитов |
| 🤖 Reddit | Видео, фото, GIF |
| 🎨 Pixiv | Иллюстрации |
| 📚 Флибуста | Поиск и скачка книг (EPUB/FB2/MOBI) |
| 🎨 Gelbooru + Rule34 | Поиск артов по тегам |
| 🌫 Размытие | Настраиваемое размытие изображений |

## 📋 Команды

```
/start      — Приветствие и справка
/help       — Справка
/settings   — Настройки (размытие, источник поиска)
/book       — Поиск книг на Флибусте
/book_id    — Скачать книгу по ID
/search     — Поиск до 5 артов по тегу
/searchn    — Поиск N артов по тегу
```

### Примеры
```
/search ushiromiya_battler
/searchn 3 beatrice_(umineko) dress
/book Достоевский идиот
/book_id 12345
```

---

## 🚀 Установка и запуск

### 1. Клонируй репозиторий
```bash
git clone <url>
cd tgbot
```

### 2. Создай `.env`
```bash
cp .env.example .env
# Открой .env и вставь токен от @BotFather
```

### 3. Установи зависимости
```bash
pip install -r requirements.txt
```

Также нужен **ffmpeg** (для склейки видео+аудио с YouTube):
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Windows — скачай с https://ffmpeg.org/download.html
```

### 4. Запусти
```bash
python bot.py
```

---

## ☁️ Бесплатный хостинг

### 🟢 Вариант 1: Railway (рекомендуется)

**Плюсы:** бесплатный tier ~$5/мес кредитов (хватает для лёгкого бота), поддержка Docker, авто-деплой из GitHub.

1. Зарегистрируйся на [railway.app](https://railway.app) через GitHub
2. Нажми **New Project → Deploy from GitHub repo**
3. Выбери форк этого репозитория
4. В разделе **Variables** добавь:
   ```
   BOT_TOKEN=твой_токен
   ```
5. Railway сам соберёт Docker-образ и запустит бота.

**Важно:** бесплатный tier выключается после $5 кредитов (~30 дней). Чтобы не платить — добавь карту для верификации, тогда дают постоянный $5/мес.

---

### 🟡 Вариант 2: Render.com (бесплатно, но "засыпает")

**Плюсы:** действительно бесплатный.  
**Минус:** сервис "засыпает" после 15 мин без запросов (→ задержка первого ответа ~30 сек).

1. Зарегистрируйся на [render.com](https://render.com)
2. **New → Web Service → Connect GitHub repo**
3. Настройки:
   - **Runtime:** Docker
   - **Instance Type:** Free
4. В **Environment Variables** добавь `BOT_TOKEN`
5. Deploy

Чтобы бот не засыпал — используй [UptimeRobot](https://uptimerobot.com) для пинга каждые 5 мин (бесплатно).

---

### 🟡 Вариант 3: Fly.io (бесплатно)

**Плюсы:** щедрый бесплатный tier, не засыпает.

```bash
# Установи flyctl
curl -L https://fly.io/install.sh | sh

# Логин
fly auth login

# Запуск (в папке с Dockerfile)
fly launch --name my-tg-bot --region ams

# Добавь секрет
fly secrets set BOT_TOKEN=твой_токен

# Деплой
fly deploy
```

---

### 🟠 Вариант 4: Oracle Cloud (вечно бесплатно)

Oracle даёт **навсегда бесплатный** VPS (2 CPU, 1 GB RAM).

1. Зарегистрируйся на [cloud.oracle.com](https://cloud.oracle.com)
2. Создай VM: **Compute → Instances → Create**
   - Shape: **VM.Standard.E2.1.Micro** (Always Free)
   - OS: Ubuntu 22.04
3. Подключись по SSH и запусти:
```bash
sudo apt update && sudo apt install -y python3-pip ffmpeg git
git clone <url> && cd tgbot
pip3 install -r requirements.txt
cp .env.example .env && nano .env   # вставь токен

# Запуск как сервис (чтобы работал после перезагрузки)
sudo nano /etc/systemd/system/tgbot.service
```

Содержимое сервиса:
```ini
[Unit]
Description=Telegram Media Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/tgbot
ExecStart=/usr/bin/python3 bot.py
Restart=always
EnvironmentFile=/home/ubuntu/tgbot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable tgbot
sudo systemctl start tgbot
sudo systemctl status tgbot
```

---

## ⚙️ Настройки пользователя

Каждый пользователь может настроить через `/settings`:
- **Размытие** (0, 2, 5, 10, 20 радиус) — применяется ко всем фото
- **Авто-размытие NSFW** — размывает контент с Gelbooru/Rule34
- **Источник поиска** — Gelbooru / Rule34 / Оба

---

## ⚠️ Ограничения

- Telegram: максимум 50 МБ на файл
- Некоторые платформы (Instagram, TikTok) могут требовать куки для приватного контента
- Флибуста может быть заблокирована у провайдера — нужен VPN или прокси

## 📦 Технологии

- **aiogram 3** — Telegram Bot API
- **yt-dlp** — скачивание видео
- **Pillow** — обработка изображений
- **httpx** — HTTP-запросы
- **BeautifulSoup4** — парсинг Флибусты
