#!/usr/bin/env python3
"""
Contact Template Bot
====================

Telegram bot that accepts forwarded real-estate announcements, removes the original
contact block, inserts the user-defined template and republishes the post to the
user’s channel. Subscriptions (start/end) and per-user post counters are stored in
SQLite, and a small admin console lets you activate, pause and extend subscriptions.

python-telegram-bot >=21.x (asyncio-native)

Author: OpenAI ChatGPT | June 2025
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Final, Literal, Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
    InputMediaPhoto,
    InputMediaVideo,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
################################################################################
# CONFIGURATION
################################################################################
TG_BOT_TOKEN: Final[str] = "7821959039:AAGCRy5W4uSUB37BRpVqPzIPZ6CPqoQXf4o"
ADMIN_IDS: Final[set[int]]    = {6864823290}
DB_FILE: Final[Path]          = Path("users.db")

# Conversation states
SET_TEMPLATE = 1
ACT_USER_ID, ACT_CHAN_ID, ACT_DAYS = range(3)
EXT_DAYS = 4

################################################################################
# DATABASE LAYER
################################################################################
CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    channel_id  INTEGER NOT NULL,
    template    TEXT    NOT NULL DEFAULT '',
    start_date  TEXT,
    end_date    TEXT,
    status      TEXT    NOT NULL DEFAULT 'inactive'
);
"""

def init_channel_table() -> None:
    """Вызываем один раз при старте бота."""
    with closing(_open_db()) as con, con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id INTEGER PRIMARY KEY,
                post_seq   INTEGER NOT NULL DEFAULT 0
            );
        """)

def _open_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    return con

def init_db() -> None:
    with closing(_open_db()) as con, con:
        con.execute(CREATE_USERS_SQL)

def next_post_number(channel_id: int) -> int:
    """Увеличить счётчик для канала и вернуть новое значение."""
    with closing(_open_db()) as con, con:
        # если канала нет — создаём строку
        con.execute(
            "INSERT INTO channels(channel_id) VALUES(?) ON CONFLICT DO NOTHING;",
            (channel_id,)
        )
        cur = con.execute(
            "UPDATE channels SET post_seq = post_seq + 1 WHERE channel_id = ? RETURNING post_seq;",
            (channel_id,)
        )
        return cur.fetchone()[0]

def add_or_update_user(user_id: int, channel_id: int, days: int = 0, *, template: str = "") -> None:
    start = dt.date.today()
    end = start + dt.timedelta(days=days) if days else None
    with closing(_open_db()) as con, con:
        con.execute(
            """
            INSERT INTO users(user_id, channel_id, template, start_date, end_date, status)
            VALUES(?,?,?,?,?,'active')
            ON CONFLICT(user_id) DO UPDATE SET
                channel_id=excluded.channel_id,
                template=COALESCE(excluded.template, users.template),
                start_date=COALESCE(excluded.start_date, users.start_date),
                end_date=COALESCE(excluded.end_date, users.end_date),
                status='active';
            """,
            (user_id, channel_id, template, start.isoformat(), end.isoformat() if end else None),
        )

def get_user(user_id: int) -> Optional[sqlite3.Row]:
    with closing(_open_db()) as con, con:
        return con.execute("SELECT * FROM users WHERE user_id = ?;", (user_id,)).fetchone()

def set_template(user_id: int, template: str) -> None:
    with closing(_open_db()) as con, con:
        con.execute("UPDATE users SET template = ? WHERE user_id = ?;", (template, user_id))

def set_status(user_id: int, status: Literal['active','paused','inactive']) -> None:
    with closing(_open_db()) as con, con:
        con.execute("UPDATE users SET status = ? WHERE user_id = ?;", (status, user_id))

def extend_subscription(user_id: int, days: int) -> None:
    with closing(_open_db()) as con, con:
        row = con.execute("SELECT end_date FROM users WHERE user_id = ?;", (user_id,)).fetchone()
        if not row or not row[0]:
            new_end = dt.date.today() + dt.timedelta(days=days)
        else:
            new_end = dt.date.fromisoformat(row[0]) + dt.timedelta(days=days)
        con.execute("UPDATE users SET end_date = ?, status = 'active' WHERE user_id = ?;",
                    (new_end.isoformat(), user_id))

def list_users(with_subscription: bool | None = None):
    sql = "SELECT user_id, channel_id, status, start_date, end_date FROM users"
    if with_subscription is True:
        sql += " WHERE status = 'active'"
    elif with_subscription is False:
        sql += " WHERE status != 'active'"
    with closing(_open_db()) as con, con:
        return con.execute(sql).fetchall()

_NUM_RE = re.compile(
    r"""
    ^\s*                  # возможные пробелы слева
    (?:                   # затем либо
      \#.*                #  - любая строка, начинающаяся с "#"
      | \d+\s*[\.\)\-]    #  - или цифры + точка/скобка/дефис
    )\s*$                 # и больше ничего
    """,
    re.I | re.X
)

def clean_numbering(text: str) -> str:
    """
    Убирает:
      - строки, которые полностью состоят из "#..." или "N.", "N)", "N-"
      - все пустые (или содержащие только пробелы) строки
    Оставляет все прочие.
    """
    lines = text.splitlines()
    kept: list[str] = []
    for ln in lines:
        if not ln.strip():
            # пропускаем пустые или содержащие только пробелы строки
            continue
        if _NUM_RE.match(ln):
            # пропускаем строки с хеш-номером или "N.", "N)"
            continue
        kept.append(ln)
    return "\n".join(kept).rstrip()

CONTACT_START_RE = re.compile(r"^(?:По всем вопросам|Контакт(?:ы)?|Телефон|☎️)", re.I)
PHONE_LINE_RE    = re.compile(r"^\+?\d[\d\-\s\(\)]{6,}\d(?:\s+\S+)?$")  # строка, начинающаяся с +998...
HANDLE_RE        = re.compile(r"^@\w+")

def is_probably_real_contact(line: str) -> bool:
    digits = sum(c.isdigit() for c in line)
    letters = sum(c.isalpha() for c in line)
    return digits >= 7 and letters <= 3  # мало букв, много цифр = скорее всего номер

def swap_contact_block(text: str, new_template: str) -> str:
    """
    Удаляет контактные строки внизу текста — только те, которые выглядят как настоящие контакты:
      • начинаются с "Контакты", "Телефон" и т.п.
      • строка = @username
      • строка = номер (и почти без текста)
    Остальное (✅, описания, текст) — оставляет.
    """
    lines = text.splitlines()
    cut_at = len(lines)

    # идём снизу вверх — удаляем только контактные блоки внизу
    for i in range(len(lines) - 1, -1, -1):
        ln = lines[i].strip()
        if (
            CONTACT_START_RE.match(ln)
            or HANDLE_RE.match(ln)
            or PHONE_LINE_RE.match(ln)
            or is_probably_real_contact(ln)
        ):
            cut_at = i
        else:
            break  # первая не-контактная строка — стоп

    body = "\n".join(lines[:cut_at]).rstrip()
    if body:
        return f"{body}\n\n{new_template}"
    else:
        return new_template

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

################################################################################
# MESSAGE HANDLERS
################################################################################

_media_buffer: dict[str, list[Update]] = {}

def _check_subscription(update: Update) -> Optional[sqlite3.Row]:
    row = get_user(update.effective_user.id)
    if not row or row["status"] != "active":
        asyncio.create_task(update.message.reply_text("Подписка не активна или истекла."))
        return None
    if not row["template"]:
        asyncio.create_task(update.message.reply_text("Сначала задайте шаблон через /template."))
        return None
    return row

async def _publish_single(update, context, *, text_only=False, photo=False):
    row = _check_subscription(update)
    if not row:
        return
    chan = row["channel_id"]
    tpl  = row["template"]

    # 1) чистим нумерацию и контакт-блок
    raw = update.message.text or update.message.caption or ""
    body = clean_numbering(raw)
    # 2) заменяем контакты
    no_contacts = swap_contact_block(body, tpl)
    # 3) получаем номер по каналу
    seq = next_post_number(chan)
    header = f"#Объект {seq}"
    final = f"{header}\n\n{no_contacts}"

    if text_only:
        await context.bot.send_message(chan, final, parse_mode=ParseMode.HTML)
    else:
        # для фото аналогично:
        file_id = update.message.photo[-1].file_id
        await context.bot.send_photo(chan, file_id, caption=final, parse_mode=ParseMode.HTML)

    await update.message.reply_text(f"Опубликовано. №{seq}")

async def handle_media(update: Update, context: CallbackContext) -> None:
    msg = update.message
    user_id = msg.from_user.id
    row = _check_subscription(update)
    if not row:
        return
    tpl = row["template"]
    chan = row["channel_id"]

    mgid = msg.media_group_id
    if mgid:
        # buffer the part
        buf = _media_buffer.setdefault(mgid, [])
        buf.append(msg)
        # schedule once when first arrives
        if len(buf) == 1:
            context.job_queue.run_once(
                publish_group,
                when=1.0,
                data={"media_group_id": mgid, "user_id": user_id, "channel_id": chan, "template": tpl},
                name=str(mgid),
            )
        return

    # single photo/video
    if msg.photo:
        await _publish_single(update, context, photo=True)
    elif msg.video:
        # treat video like photo
        cap = swap_contact_block(msg.caption or "", tpl)
        file_id = msg.video.file_id
        await context.bot.send_video(chat_id=chan, video=file_id,
                                     caption=cap, parse_mode=ParseMode.HTML)
        num = next_post_number(user_id)
        await update.message.reply_text(f"Опубликовано. №{num}")
    else:
        # plain text
        await _publish_single(update, context, text_only=True)

async def publish_group(context: CallbackContext):
    data = context.job.data
    msgs = _media_buffer.pop(data["media_group_id"], [])
    if not msgs:
        return

    chan = data["channel_id"]
    tpl  = data["template"]

    # 1) собираем весь текст первого кадра
    raw = msgs[0].caption or ""
    body       = clean_numbering(raw)
    no_contacts = swap_contact_block(body, tpl)

    # 2) новый seq и заголовок
    seq     = next_post_number(chan)
    header  = f"#Объект {seq}"
    new_caption = f"{header}\n\n{no_contacts}"

    # 3) готовим media_group
    media = []
    for i, m in enumerate(msgs):
        if m.photo:
            file_id = m.photo[-1].file_id
            if i == 0:
                im = InputMediaPhoto(media=file_id, caption=new_caption, parse_mode=ParseMode.HTML)
            else:
                im = InputMediaPhoto(media=file_id)
        elif m.video:
            file_id = m.video.file_id
            if i == 0:
                im = InputMediaVideo(media=file_id, caption=new_caption, parse_mode=ParseMode.HTML)
            else:
                im = InputMediaVideo(media=file_id)
        else:
            # пропускаем другие типы, если необходимо — добавьте Document, etc.
            continue
        media.append(im)

    # отправляем группу
    await context.bot.send_media_group(chat_id=chan, media=media)

    # уведомляем пользователя
    await context.bot.send_message(
        chat_id=msgs[0].from_user.id,
        text=f"Альбом опубликован. №{seq}"
    )

async def start_cmd(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text(
        "Этот бот пересылает ваши объявления в канал и вставляет ваши контакты из шаблона.\n"
        "Команда /template — задать или изменить шаблон."
    )

async def template_cmd(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text(
        "Пришлите текст шаблона контактов, который будет вставляться в публикации.\n"
        "Например: ☎️ +998 90 123-45-67 (Мария)"
    )
    return SET_TEMPLATE

async def save_template(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    tpl = update.message.text.strip()
    set_template(user_id, tpl)
    await update.message.reply_text("Шаблон контактов сохранён.")
    return ConversationHandler.END

async def cancel_conv(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("Действие отменено.")
    return ConversationHandler.END

################################################################################
# ADMIN HANDLERS
################################################################################

async def users_cmd(update: Update, context: CallbackContext) -> None:
    if not is_admin(update.effective_user.id):
        return
    rows = list_users()
    if not rows:
        await update.message.reply_text("Нет зарегистрированных пользователей.")
        return
    for r in rows:
        uid, cid, status, sd, ed = r
        kb = ReplyKeyboardMarkup([
            [KeyboardButton(f"Деактивировать {uid}"), KeyboardButton(f"Приостановить {uid}")],
            [KeyboardButton(f"Продлить {uid}"),        KeyboardButton(f"Возобновить {uid}")],
        ], resize_keyboard=True, one_time_keyboard=True)
        text = (
            f"Пользователь <code>{uid}</code> → канал <code>{cid}</code>\n"
            f"Статус: <b>{status}</b>\nС: {sd or '—'}  До: {ed or '—'}"
        )
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

async def admin_keyboard_handler(update: Update, context: CallbackContext) -> None:
    if not is_admin(update.effective_user.id):
        return
    txt = update.message.text or ""
    m = re.match(r"(Деактивировать|Приостановить|Возобновить|Продлить) (\d+)", txt)
    if not m:
        return
    action, uid_s = m.groups()
    uid = int(uid_s)
    if action == "Деактивировать":
        set_status(uid, "inactive")
        await update.message.reply_text("Деактивировано.")
    elif action == "Приостановить":
        set_status(uid, "paused")
        await update.message.reply_text("Приостановлено.")
    elif action == "Возобновить":
        set_status(uid, "active")
        await update.message.reply_text("Возобновлено.")
    elif action == "Продлить":
        context.user_data["ext_uid"] = uid
        await update.message.reply_text("Введите количество дней продления:")
        return EXT_DAYS

async def ext_days(update: Update, context: CallbackContext) -> int:
    uid = context.user_data.get("ext_uid")
    try:
        days = int(update.message.text.strip())
        extend_subscription(uid, days)
        await update.message.reply_text("Подписка продлена.")
    except ValueError:
        await update.message.reply_text("Введите число дней.")
        return EXT_DAYS
    return ConversationHandler.END

async def activateuser_cmd(update: Update, context: CallbackContext) -> int:
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text("Введите ID пользователя:")
    return ACT_USER_ID

async def act_get_user(update: Update, context: CallbackContext) -> int:
    try:
        context.user_data["new_uid"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Это должно быть число.")
        return ACT_USER_ID
    await update.message.reply_text("Введите ID канала для публикаций:")
    return ACT_CHAN_ID

async def act_get_channel(update: Update, context: CallbackContext) -> int:
    try:
        context.user_data["new_chan"] = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Это должно быть число.")
        return ACT_CHAN_ID
    kb = ReplyKeyboardMarkup([
        [KeyboardButton("Пробный период (3 дня)"), KeyboardButton("Активировать (ввести дни)")]
    ], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Выберите действие:", reply_markup=kb)
    return ACT_DAYS

async def act_days_choice(update: Update, context: CallbackContext) -> int:
    choice = update.message.text
    uid = context.user_data["new_uid"]
    chan = context.user_data["new_chan"]
    if "Пробный" in choice:
        add_or_update_user(uid, chan, days=3)
        await update.message.reply_text("Пробная подписка на 3 дня активирована.")
        return ConversationHandler.END
    else:
        await update.message.reply_text("Введите срок подписки в днях:")
        return ACT_DAYS

async def act_set_days(update: Update, context: CallbackContext) -> int:
    try:
        days = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Введите число дней.")
        return ACT_DAYS
    uid = context.user_data["new_uid"]
    chan = context.user_data["new_chan"]
    add_or_update_user(uid, chan, days=days)
    await update.message.reply_text("Пользователь активирован.")
    return ConversationHandler.END

################################################################################
# MAIN
################################################################################

def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    init_channel_table()

    app: Application = ApplicationBuilder().token(TG_BOT_TOKEN).build()

    # User flows
    app.add_handler(CommandHandler("start", start_cmd))
    tpl_conv = ConversationHandler(
        entry_points=[CommandHandler("template", template_cmd)],
        states={ SET_TEMPLATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_template)] },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    app.add_handler(tpl_conv)

    # Forwarded media/text
    app.add_handler(MessageHandler(filters.FORWARDED & (filters.PHOTO | filters.VIDEO), handle_media))
    app.add_handler(MessageHandler(filters.FORWARDED & filters.TEXT & ~filters.COMMAND, handle_media))

    # Admin flows
    app.add_handler(CommandHandler("users", users_cmd))
    ext_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r"^(Деактивировать|Приостановить|Возобновить|Продлить) ") & filters.TEXT, admin_keyboard_handler)],
        states={ EXT_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ext_days)] },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    app.add_handler(ext_conv)

    act_conv = ConversationHandler(
        entry_points=[CommandHandler("activateuser", activateuser_cmd)],
        states={
            ACT_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, act_get_user)],
            ACT_CHAN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, act_get_channel)],
            ACT_DAYS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, act_days_choice)],
            EXT_DAYS:    [MessageHandler(filters.TEXT & ~filters.COMMAND, act_set_days)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )
    app.add_handler(act_conv)

    # Run
    app.run_polling()

if __name__ == "__main__":
    main()
