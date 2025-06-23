import re
import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InputMediaPhoto, InputMediaVideo
from aiogram.utils import executor

API_TOKEN = '7947507030:AAEDGga_FOGjiumUvYSq-iDy1UUACUHYOj4'
CHANNEL_ID = '@pravdainedvijimost'
CONTACT_INFO = 'по всем вопросам:\n+998 93 801 32 04 Олег\n@pravdainedvijimost\n@et_olv'

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
media_groups = {}

COUNTER_FILE = 'counter.txt'

# Чтение счётчика из файла
def load_counter():
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE, 'r') as f:
            return int(f.read())
    return 1

# Сохранение счётчика в файл
def save_counter(counter):
    with open(COUNTER_FILE, 'w') as f:
        f.write(str(counter))

post_counter = load_counter()

# Очистка текста от лишнего
def clean_text(text: str, number: int) -> str:
    if not text:
        text = ''

    lines = text.strip().split('\n')
    cleaned_lines = []

    for line in lines:
        if re.search(r'\+?\d[\d\s\-\(\)]{7,}\d', line):  # Телефон
            continue
        if re.search(r'@\w{4,}', line):  # Юзернеймы
            continue
        if re.search(r'https?://t\.me/\S+', line):  # Ссылки
            continue
        line = re.sub(r'#\S+', '', line)  # Удаление хештегов (#4к и т.п.)
        line = re.sub(r'\s+', ' ', line).strip()  # Сжатие пробелов
        cleaned_lines.append(line if line else '')

    # Удаление лишних подряд идущих пустых строк
    final_lines = []
    last_empty = False
    for line in cleaned_lines:
        if line == '':
            if not last_empty:
                final_lines.append('')
                last_empty = True
        else:
            final_lines.append(line)
            last_empty = False

    final_lines.insert(0, f'#Объект {number}')
    final_lines.append('')
    final_lines.append(CONTACT_INFO)

    return '\n'.join(final_lines)

@dp.message_handler(content_types=types.ContentType.ANY)
async def handle_media(message: types.Message):
    global post_counter

    if message.media_group_id:
        media_group = media_groups.setdefault(message.media_group_id, [])
        media_group.append(message)
        await asyncio.sleep(1.5)

        if media_groups.get(message.media_group_id):
            group = media_groups.pop(message.media_group_id)
            media = []

            for i, msg in enumerate(group):
                caption = clean_text(msg.caption, post_counter) if i == 0 else None
                if msg.photo:
                    media.append(InputMediaPhoto(media=msg.photo[-1].file_id, caption=caption))
                elif msg.video:
                    media.append(InputMediaVideo(media=msg.video.file_id, caption=caption))

            await bot.send_media_group(chat_id=CHANNEL_ID, media=media)
            await message.answer(f"Подборка #{post_counter} отправлена в канал.")
            post_counter += 1
            save_counter(post_counter)

    elif message.photo:
        caption = clean_text(message.caption, post_counter)
        await bot.send_photo(chat_id=CHANNEL_ID, photo=message.photo[-1].file_id, caption=caption)
        await message.answer(f"Фото #{post_counter} отправлено в канал.")
        post_counter += 1
        save_counter(post_counter)

    elif message.video:
        caption = clean_text(message.caption, post_counter)
        await bot.send_video(chat_id=CHANNEL_ID, video=message.video.file_id, caption=caption)
        await message.answer(f"Видео #{post_counter} отправлено в канал.")
        post_counter += 1
        save_counter(post_counter)

    elif message.text:
        text = clean_text(message.text, post_counter)
        await bot.send_message(chat_id=CHANNEL_ID, text=text)
        await message.answer(f"Текст #{post_counter} отправлен в канал.")
        post_counter += 1
        save_counter(post_counter)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
