# Удаление v.0.1 — Telegram-бот для пересылки сообщений, очистки от личных данных, добавления хэштегов и нумерации объектов.

import logging
import os
import re
import ssl
import asyncio
import sys
import platform
from collections import defaultdict
from contextlib import suppress
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ContentType
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router
from aiogram.types import Message, InputMediaPhoto, InputMediaVideo
from aiogram.utils.markdown import hbold

# Проверка наличия ssl-модуля
if not hasattr(ssl, 'SSLContext'):
    raise RuntimeError("Отсутствует модуль ssl. Убедитесь, что ваша среда поддерживает OpenSSL.")

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Токен и ID канала
BOT_TOKEN = "7947507030:AAEDGga_FOGjiumUvYSq-iDy1UUACUHYOj4"
CHANNEL_ID = "@pravdainedvijimost"

# Путь к файлу счётчика объектов
COUNTER_FILE = "object_counter.txt"

def read_counter():
    if not os.path.exists(COUNTER_FILE):
        return 1
    with open(COUNTER_FILE, "r") as f:
        return int(f.read().strip() or 1)

def write_counter(value):
    with open(COUNTER_FILE, "w") as f:
        f.write(str(value))

# Регулярки для очистки
PHONE_REGEX = r"\+?\d[\d\s\-()]{7,}\d"
TG_USERNAME_REGEX = r"@\w+"
URL_REGEX = r"https?://\S+"
HASHTAG_REGEX = r"#[\wа-яА-ЯёЁ0-9]+"

def clean_text(text):
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        if re.search(PHONE_REGEX, line):
            continue  # удаляем всю строку, содержащую номер
        cleaned_line = re.sub(TG_USERNAME_REGEX, "", line)
        cleaned_line = re.sub(URL_REGEX, "", cleaned_line)
        cleaned_line = re.sub(HASHTAG_REGEX, "", cleaned_line)
        cleaned_lines.append(cleaned_line.strip())
    return "\n".join(cleaned_lines).strip()

# Создание бота и диспетчера
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# Временное хранилище медиа-групп
media_groups = defaultdict(list)

@router.message()
async def handle_message(message: types.Message):
    object_number = read_counter()
    header = f"#Объект {object_number}"
    footer = "\n\n<b>По всем вопросам:</b>\n@Etagi_Oleg\n@Nargiz_Etagi\n@Etagi_Akida\nhttps://t.me/pravdainedvijimost"
    cleaned_text = clean_text(message.caption or message.text or "")
    caption = f"{header}\n{cleaned_text}{footer}"

    try:
        if message.media_group_id:
            media_groups[message.media_group_id].append((message, caption))
            await asyncio.sleep(1.5)  # Ожидание других сообщений из группы
            group = media_groups.pop(message.media_group_id, [])
            if not group:
                return
            media = []
            for i, (msg, _) in enumerate(group):
                if msg.photo:
                    file_id = msg.photo[-1].file_id
                    if i == 0:
                        media.append(InputMediaPhoto(media=file_id, caption=caption))
                    else:
                        media.append(InputMediaPhoto(media=file_id))
                elif msg.video:
                    file_id = msg.video.file_id
                    if i == 0:
                        media.append(InputMediaVideo(media=file_id, caption=caption))
                    else:
                        media.append(InputMediaVideo(media=file_id))
            if media:
                await bot.send_media_group(CHANNEL_ID, media)
                write_counter(object_number + 1)
        else:
            if message.photo:
                await bot.send_photo(CHANNEL_ID, photo=message.photo[-1].file_id, caption=caption)
            elif message.video:
                await bot.send_video(CHANNEL_ID, video=message.video.file_id, caption=caption)
            elif message.text:
                await bot.send_message(CHANNEL_ID, f"{header}\n{cleaned_text}{footer}")
            else:
                await bot.send_message(CHANNEL_ID, f"{header}\n<Unsupported content>{footer}")
            write_counter(object_number + 1)
    except Exception as e:
        logging.error(f"Ошибка при отправке: {e}")

# Основной запуск
if __name__ == "__main__":
    async def main():
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logging.error(f"Ошибка при запуске бота: {e}")

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
