import os
import threading
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
PORT = int(os.getenv("PORT", "10000"))

API_URL = "https://v3.football.api-sports.io/status"


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
        "Send /apitest to test the football API."
    )


async def api_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not FOOTBALL_API_KEY:
        await update.message.reply_text(
            "❌ FOOTBALL_API_KEY is missing from Render."
        )
        return

    await update.message.reply_text("🔄 Testing Football API...")

    try:
        headers = {
            "x-apisports-key": FOOTBALL_API_KEY
        }

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(API_URL, headers=headers)

        if response.status_code == 200:
            data = response.json()

            await update.message.reply_text(
                "✅ Football API connection works!\n\n"
                f"API response received successfully.\n"
                f"Requests used today: {data.get('response', {}).get('requests', {}).get('current', 'unknown')}"
            )
        else:
            await update.message.reply_text(
                f"❌ API test failed.\n\n"
                f"HTTP Status: {response.status_code}\n"
                f"Response: {response.text[:500]}"
            )

    except Exception as e:
        await update.message.reply_text(
            f"❌ Connection error:\n{str(e)[:500]}"
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

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("apitest", api_test))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print(f"GoalLogic AI is running on port {PORT}.")

    app.run_polling()


if __name__ == "__main__":
    main()
