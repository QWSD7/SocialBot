import feedparser
import json
import html
import asyncio
from datetime import datetime, timezone, timedelta
from telegram import Bot
import aiohttp
from bs4 import BeautifulSoup
import os
from paraphraser_ai import paraphrase_rut5

# Настройки
RSS_URL = os.environ.get("RSS_URL")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHANNEL_IDS = os.environ.get("CHANNEL_ID").split(",")
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

    pub_date_utc = datetime(*published_parsed[:6], tzinfo=timezone.utc)
    pub_date_moscow = pub_date_utc + timedelta(hours=3)  # переводим в МСК
    now_moscow = datetime.now(timezone.utc) + timedelta(hours=3)

    return pub_date_moscow.date() == now_moscow.date()


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
            a.replace_with(a.get_text())
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

    if not sorted_entries:
        print("Нет подходящих записей на сегодня.")
        return

    if last_posted_link is None:
        last_entry = sorted_entries[-1]
        article_text = await fetch_article_text(last_entry.link)
        image_url = None

        try:
            chunks = chunk_text(article_text, max_len=512)
            paraphrased_chunks = []
            for i, chunk in enumerate(chunks):
                print(f"Перефразируем часть {i+1}/{len(chunks)}...")
                try:
                    paraphrased = paraphrase_rut5(chunk)
                    paraphrased_chunks.append(paraphrased)
                except Exception as inner_e:
                    print(
                        f"⚠️ Ошибка в части {i+1}, используем оригинал. Ошибка: {inner_e}"
                    )
                    paraphrased_chunks.append(chunk)
                await asyncio.sleep(1)  # Пауза между запросами
            article_text = "\n\n".join(paraphrased_chunks)
        except Exception as e:
            print(f"⚠️ Ошибка при перефразировании текста: {e}")

        # Получение изображения из enclosure
        if "enclosures" in last_entry and last_entry.enclosures:
            for enclosure in last_entry.enclosures:
                if enclosure.get("type", "").startswith("image/"):
                    image_url = enclosure.get("url")
                    break

        message = f"📰 <b>{html.escape(last_entry.title)}</b>\n\n{html.escape(article_text)}\n\n🔗 {last_entry.link}"

        for channel_id in CHANNEL_IDS:
            if image_url:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=image_url,
                    caption=message[:1024],  # Telegram ограничение
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    chat_id=channel_id,
                    text=message,
                    parse_mode="HTML",
                )

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

        try:
            chunks = chunk_text(article_text, max_len=512)
            paraphrased_chunks = []
            for i, chunk in enumerate(chunks):
                print(f"Перефразируем часть {i+1}/{len(chunks)}...")
                try:
                    paraphrased = paraphrase_rut5(chunk)
                    paraphrased_chunks.append(paraphrased)
                except Exception as inner_e:
                    print(
                        f"⚠️ Ошибка в части {i+1}, используем оригинал. Ошибка: {inner_e}"
                    )
                    paraphrased_chunks.append(chunk)
                await asyncio.sleep(1)  # Пауза между запросами
            article_text = "\n\n".join(paraphrased_chunks)
        except Exception as e:
            print(f"⚠️ Ошибка при перефразировании текста: {e}")

        image_url = None
        if "enclosures" in entry and entry.enclosures:
            for enclosure in entry.enclosures:
                if enclosure.get("type", "").startswith("image/"):
                    image_url = enclosure.get("url")
                    break

        message = f"📰 <b>{html.escape(entry.title)}</b>\n\n{html.escape(article_text)}\n\n🔗 {entry.link}"

        for channel_id in CHANNEL_IDS:
            if image_url:
                await bot.send_photo(
                    chat_id=channel_id,
                    photo=image_url,
                    caption=message[:1024],  # Telegram ограничение
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    chat_id=channel_id,
                    text=message,
                    parse_mode="HTML",
                )

        save_last_posted(entry.link)
        print(f"Опубликовано: {entry.title}")


# Функция для разбивки текста на части
def chunk_text(text, max_len=512):
    sentences = text.split(". ")
    chunks, chunk = [], ""
    for sentence in sentences:
        if len(chunk) + len(sentence) + 2 < max_len:
            chunk += sentence + ". "
        else:
            chunks.append(chunk.strip())
            chunk = sentence + ". "
    if chunk:
        chunks.append(chunk.strip())
    return chunks


# Бесконечный цикл запуска
async def main_loop():
    while True:
        try:
            await fetch_and_post()
        except Exception as e:
            print(f"Ошибка при выполнении: {e}")
        await asyncio.sleep(60 * 10)  # каждые 30 минут


# Запуск
if __name__ == "__main__":
    asyncio.run(main_loop())
