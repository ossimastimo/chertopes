import random
import logging
import json
import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "stats.json"

PHRASES_ON_D = [
    "нахуй надо",
    "не хочу"
]

# Глобальные данные (загружаются из файла при старте)
chat_history = {}      # chat_id (int) -> list[(str, float)]
last_pick_time = {}    # chat_id (int) -> float

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def save_data():
    """Сохраняет данные в stats.json"""
    data = {
        "history": {str(k): v for k, v in chat_history.items()},
        "last_pick": {str(k): v for k, v in last_pick_time.items()}
    }
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info("Данные успешно сохранены в stats.json")
    except Exception as e:
        logging.error(f"Ошибка сохранения данных: {e}")

def load_data():
    """Загружает данные из stats.json"""
    global chat_history, last_pick_time
    if not os.path.exists(DATA_FILE):
        logging.info("Файл stats.json не найден — создаём новый.")
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Преобразуем ключи обратно в int
        chat_history = {int(k): [(u, t) for u, t in v] for k, v in data.get("history", {}).items()}
        last_pick_time = {int(k): t for k, t in data.get("last_pick", {}).items()}
        logging.info("Данные успешно загружены из stats.json")
    except Exception as e:
        logging.error(f"Ошибка загрузки данных: {e}")

# Вспомогательные функции времени
def get_today_start():
    now = datetime.utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)

def get_month_start():
    now = datetime.utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

# ====== /pick ======
async def pick_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text("Пошёл нахуй, урод. Работает только в группах")
        return

    now = datetime.utcnow()
    chat_id = chat.id

    if chat_id in last_pick_time:
        elapsed = now - datetime.utcfromtimestamp(last_pick_time[chat_id])
        if elapsed < timedelta(hours=24):
            today_picks = [p for p in chat_history.get(chat_id, []) if datetime.utcfromtimestamp(p[1]) >= get_today_start()]
            if today_picks:
                u1 = today_picks[-1][0]
                u2 = today_picks[-2][0] if len(today_picks) > 1 else "—"
                hours_left = 24 - int(elapsed.total_seconds() // 3600)
                await update.message.reply_text(
                    f"Пидоры на сегодня: @{u1} и @{u2}.\n"
                    f"Следующий пидороскан возможен через {hours_left} час(ов)."
                )
            else:
                await update.message.reply_text("Выбор уже был, но данные не сохранились.")
            return

    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        human_admins = [
            admin.user for admin in admins
            if not admin.user.is_bot and admin.user.username
        ]

        if len(human_admins) < 2:
            await update.message.reply_text(
                "Недостаточно пидоров(нужно минимум 2)."
            )
            return

        chosen = random.sample(human_admins, 2)
        u1, u2 = chosen[0].username, chosen[1].username
        timestamp = now.timestamp()

        if chat_id not in chat_history:
            chat_history[chat_id] = []
        chat_history[chat_id].extend([(u1, timestamp), (u2, timestamp)])
        last_pick_time[chat_id] = timestamp

        # 🔄 Сразу сохраняем после изменения
        save_data()

        await update.message.reply_text(f"Сегодня пидоры: @{u1} и @{u2}!")

    except Exception as e:
        await update.message.reply_text(f"Ошибка: не удалось получить администраторов. ({e})")

# ====== /stat ======
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text("Команда работает только в группах.")
        return

    chat_id = chat.id
    history = chat_history.get(chat_id, [])

    if not history:
        await update.message.reply_text("Ещё не было ни одного пидора.")
        return

    today_start_ts = get_today_start().timestamp()
    today_names = list({name for name, ts in history if ts >= today_start_ts})
    today_names.sort()

    month_start_ts = get_month_start().timestamp()
    month_picks = [p for p in history if p[1] >= month_start_ts]

    def count_users(picks):
        counts = {}
        for name, _ in picks:
            counts[name] = counts.get(name, 0) + 1
        return sorted(counts.items(), key=lambda x: x[1], reverse=True)

    month_top = count_users(month_picks)
    all_time_top = count_users(history)

    msg = "📊 **Пидорская статистика по чату**\n\n"

    msg += "**Пидоры сегодня:**\n"
    if today_names:
        msg += "\n".join(today_names)
    else:
        msg += "—"

    msg += "\n\n**ТОП-10 пидоров за месяц:**\n"
    if month_top:
        msg += "\n".join(f"{name} — {count} раз(а)" for name, count in month_top[:10])
    else:
        msg += "—"

    msg += "\n\n**ТОП-10 пидоров за всё время:**\n"
    if all_time_top:
        msg += "\n".join(f"{name} — {count} раз(а)" for name, count in all_time_top[:10])
    else:
        msg += "—"

    await update.message.reply_text(msg)

async def handle_admin_triggers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    # Логирование (опционально, можно убрать)
    if message and message.text:
        chat_title = chat.title if chat.title else "Личка"
        username = f"@{user.username}" if user.username else f"ID{user.id}"
        logging.info(f"📩 Сообщение: '{message.text}' | От: {username} ({user.id}) | Чат: {chat_title} ({chat.id})")

    # Только в группах
    if not message or not chat or chat.type == "private":
        return

    text = message.text.strip() if message.text else ""
    # Получаем список админов
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        admin_ids = {admin.user.id for admin in admins}
        is_admin = user.id in admin_ids
    except Exception as e:
        logging.error(f"Не удалось проверить админов в чате {chat.id}: {e}")
        return

    # Реакция на "е" / "Е"
    if text in ("е", "Е") and is_admin:
        await context.bot.send_message(chat_id=chat.id, text=text)
        logging.info(f"✅ Отправлено в чат {chat.id}: '{text}'")
        return

    # Реакция на "Д"
    if text == "Д" and is_admin:
        phrase = random.choice(PHRASES_ON_D)
        await context.bot.send_message(chat_id=chat.id, text=phrase)
        logging.info(f"🎲 Отправлено в чат {chat.id}: '{phrase}'")
        return

# ====== Graceful shutdown (сохранение при остановке) ======
import signal
import sys

def signal_handler(sig, frame):
    logging.info("Получен сигнал завершения. Сохраняем данные...")
    save_data()
    sys.exit(0)

# ====== Запуск ======
def main():
    # Загружаем данные при старте
    load_data()

    # Регистрируем обработчик завершения
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("pick", pick_members))
    app.add_handler(CommandHandler("stat", show_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_triggers))

    logging.info("Бот запущен. Нажмите Ctrl+C для остановки.")
    app.run_polling()

if __name__ == "__main__":
    main()
