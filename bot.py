import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        pass


def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


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

    threading.Thread(target=start_health_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print(f"GoalLogic AI is running on port {PORT}.")

    app.run_polling()


if __name__ == "__main__":
    main()
