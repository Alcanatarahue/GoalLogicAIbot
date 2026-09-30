import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ GoalLogic AI is online!\n\n"
        "Send me a football match, for example:\n"
        "Chelsea vs Brentford\n\n"
        "Football analysis will be added next."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    match = update.message.text

    await update.message.reply_text(
        f"📥 Match received:\n{match}\n\n"
        "🔧 Analysis engine is being connected..."
    )


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("GoalLogic AI is running.")

    app.run_polling()


if __name__ == "__main__":
    main()
