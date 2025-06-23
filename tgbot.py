# Удаление v.0.1 — Telegram-бот для пересылки сообщений, очистки от личных данных, добавления хэштегов и нумерации объектов.

import logging
import os
import re
import ssl  # <--- важно для aiogram/ssl соединения
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ContentType
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram import Router
from aiogram.types import Message
from aiogram.utils.markdown import hbold
from contextlib import suppress

import sys
import platform

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

# Чтение и обновление счётчика объектов
def read_counter():
    if not os.path.exists(COUNTER_FILE):
        return 1
    with open(COUNTER_FILE, "r") as f:
        return int(f.read().strip() or 1)

def write_counter(value):
    with open(COUNTER_FILE, "w") as f:
        f.write(str(value))

# Очистка текста от персональных данных и форматирование
PHONE_REGEX = r"\+?\d[\d\s\-()]{7,}\d"
TG_USERNAME_REGEX = r"@\w+"
URL_REGEX = r"https?://\S+"
HASHTAG_REGEX = r"#[\wа-яА-ЯёЁ0-9]+"

def clean_text(text):
    text = re.sub(PHONE_REGEX, "", text)
    text = re.sub(TG_USERNAME_REGEX, "", text)
    text = re.sub(URL_REGEX, "", text)
    text = re.sub(HASHTAG_REGEX, "", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = text.strip()
    return text

# Создание бота и диспетчера
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

@router.message()
async def handle_message(message: types.Message):
    object_number = read_counter()
    header = f"#Объект {object_number}"
    footer = "\n\n<b>Связаться с нами:</b>\nОлег\n+998 90 123 45 67\n@pravdainedvijimost"

    text = clean_text(message.text or message.caption or "")
    content = f"{header}\n{text}{footer}"

    # Отправка в канал
    try:
        if message.photo:
            await bot.send_photo(CHANNEL_ID, photo=message.photo[-1].file_id, caption=content)
        elif message.video:
            await bot.send_video(CHANNEL_ID, video=message.video.file_id, caption=content)
        elif message.text:
            await bot.send_message(CHANNEL_ID, content)
        else:
            await bot.send_message(CHANNEL_ID, f"{header}\n<Unsupported content>{footer}")

        write_counter(object_number + 1)
    except Exception as e:
        logging.error(f"Ошибка при отправке: {e}")

# Основной запуск
if __name__ == "__main__":
    import asyncio

    async def main():
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logging.error(f"Ошибка при запуске бота: {e}")

    # Обход ошибки asyncio.run() в средах с активным event loop
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
