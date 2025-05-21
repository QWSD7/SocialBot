import feedparser
import json
import asyncio
from datetime import datetime, timezone
from telegram import Bot
import aiohttp
from bs4 import BeautifulSoup
import os


# Настройки
RSS_URL = os.environ.get("RSS_URL")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
STATE_FILE = os.environ.get("STATE_FILE")

bot = Bot(token=TELEGRAM_TOKEN)


# Загрузка последней опубликованной ссылки
def load_last_posted():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except:
        return None


# Сохранение последней опубликованной ссылки
def save_last_posted(link):
    with open(STATE_FILE, "w") as f:
        json.dump(link, f)


# Проверка, находится ли запись в пределах текущих суток
def is_today(published_parsed):
    if not published_parsed:
        return False
    pub_date = datetime(*published_parsed[:6], tzinfo=timezone.utc)
    now = datetime.now(tz=timezone.utc)
    return pub_date.date() == now.date()


# Асинхронная загрузка и очистка текста статьи
async def fetch_article_text(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return "⚠️ Не удалось загрузить статью."
                html = await resp.text()
    except Exception as e:
        return f"⚠️ Ошибка при загрузке: {e}"

    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.find_all(class_="topic-body__content-text")

    if not blocks:
        return "⚠️ Не найден текст статьи."

    result = ""
    for block in blocks:
        for a in block.find_all("a"):
            a.replace_with(a.get_text())  # заменить <a> на обычный текст
        clean_text = block.get_text(strip=False)
        result += clean_text + "\n\n"

    return result.strip()[:4000]  # ограничение Telegram


# Асинхронный парсер и публикация
async def fetch_and_post():
    last_posted_link = load_last_posted()
    feed = feedparser.parse(RSS_URL)

    today_entries = [
        entry for entry in feed.entries if is_today(entry.published_parsed)
    ]

    if not today_entries:
        print("Сегодня нет записей.")
        return

    sorted_entries = sorted(today_entries, key=lambda e: e.published_parsed)

    if last_posted_link is None:
        last_entry = sorted_entries[-1]
        article_text = await fetch_article_text(last_entry.link)
        message = (
            f"📰 <b>{last_entry.title}</b>\n\n{article_text}\n\n🔗 {last_entry.link}"
        )
        await bot.send_message(chat_id=CHANNEL_ID, text=message, parse_mode="HTML")
        save_last_posted(last_entry.link)
        print("Опубликована последняя запись за сегодня (первый запуск).")
        return

    # Найти новые записи
    new_entries = []
    found = False
    for entry in sorted_entries:
        if found:
            new_entries.append(entry)
        elif entry.link == last_posted_link:
            found = True

    if not new_entries:
        print("Новых записей нет.")
        return

    for entry in new_entries:
        article_text = await fetch_article_text(entry.link)
        message = f"📰 <b>{entry.title}</b>\n\n{article_text}\n\n🔗 {entry.link}"
        await bot.send_message(chat_id=CHANNEL_ID, text=message, parse_mode="HTML")
        save_last_posted(entry.link)
        print(f"Опубликовано: {entry.title}")


# Бесконечный цикл запуска
async def scheduler():
    while True:
        try:
            await fetch_and_post()
        except Exception as e:
            print(f"Ошибка: {e}")
        await asyncio.sleep(300)  # каждые 5 минут


# Запуск
if __name__ == "__main__":
    asyncio.run(scheduler())
