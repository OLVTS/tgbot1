import logging
import os
import re
import ssl
import asyncio
import sys
import platform
from collections import defaultdict
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, InputMediaPhoto, InputMediaVideo

# Проверка SSL
if not hasattr(ssl, 'SSLContext'):
    raise RuntimeError("Отсутствует модуль ssl. Убедитесь, что ваша среда поддерживает OpenSSL.")

# Логирование
logging.basicConfig(level=logging.INFO)

# ✅ Конфигурация
BOT_TOKEN = "7708516529:AAGtx9EE2nI9lvs9iHFioUnwP8NWZlnw-xs"
CHANNEL_ID = "@KhakimovHub"

# Абсолютный путь к счётчику
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COUNTER_FILE = os.path.join(BASE_DIR, "object_counter.txt")

# ====== Подсчёт номера объекта ======
def read_counter():
    if not os.path.exists(COUNTER_FILE):
        return 1
    with open(COUNTER_FILE, "r") as f:
        return int(f.read().strip() or 1)

def write_counter(value):
    with open(COUNTER_FILE, "w") as f:
        f.write(str(value))

# ====== Очистка текста ======
PHONE_REGEX = r"\+?\d[\d\s\-()]{7,}\d"
TG_USERNAME_REGEX = r"@\w+"
URL_REGEX = r"https?://\S+"
HASHTAG_REGEX = r"#[\wа-яА-ЯёЁ0-9]+"

def clean_text(text):
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        if re.search(PHONE_REGEX, line):
            continue
        line = re.sub(TG_USERNAME_REGEX, "", line)
        line = re.sub(URL_REGEX, "", line)
        line = re.sub(HASHTAG_REGEX, "", line)
        cleaned_lines.append(line.strip())
    return "\n".join(cleaned_lines).strip()

# ====== Бот и диспетчер ======
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

media_groups = defaultdict(list)

@router.message()
async def handle_message(message: Message):
    object_number = read_counter()
    header = f"#Объект {object_number}"
    footer = "\n\n<b>По всем вопросам:</b>\n@Khakimov_etagi\nhttps://t.me/+ucdUHFw8S141NzVi"
    cleaned_text_content = clean_text(message.caption or message.text or "")
    caption = f"{header}\n{cleaned_text_content}{footer}"

    try:
        # Группы медиа
        if message.media_group_id:
            media_groups[message.media_group_id].append((message, caption))
            await asyncio.sleep(1.5)
            group = media_groups.pop(message.media_group_id, [])
            if not group:
                return
            media = []
            for i, (msg, _) in enumerate(group):
                if msg.photo:
                    file_id = msg.photo[-1].file_id
                    media.append(InputMediaPhoto(media=file_id, caption=caption if i == 0 else None))
                elif msg.video:
                    file_id = msg.video.file_id
                    media.append(InputMediaVideo(media=file_id, caption=caption if i == 0 else None))
            if media:
                await bot.send_media_group(CHANNEL_ID, media)
                write_counter(object_number + 1)
        else:
            # Одиночные сообщения
            if message.photo:
                await bot.send_photo(CHANNEL_ID, photo=message.photo[-1].file_id, caption=caption)
            elif message.video:
                await bot.send_video(CHANNEL_ID, video=message.video.file_id, caption=caption)
            elif message.text:
                await bot.send_message(CHANNEL_ID, caption)
            else:
                await bot.send_message(CHANNEL_ID, f"{header}\n<Unsupported content>{footer}")
            write_counter(object_number + 1)
    except Exception as e:
        logging.error(f"Ошибка при отправке: {e}")

# ====== Запуск ======
async def main():
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Ошибка при запуске бота: {e}")

if __name__ == "__main__":
    if sys.platform == "win32" and platform.python_version().startswith("3.8"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" in str(e):
            loop = asyncio.get_event_loop()
            loop.run_until_complete(main())
        else:
            raise
