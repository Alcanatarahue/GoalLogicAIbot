import os
import time
import threading
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

# =========================================================
# SETTINGS
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

PORT = int(os.getenv("PORT", "10000"))

OPENFOOT_BASE = "https://openfootapi.com"

# =========================================================
# HEALTH SERVER FOR RENDER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(
            b"GoalLogic AI is running."
        )

    def log_message(self, format, *args):
        return


def start_health_server():
    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    print(f"Health server running on port {PORT}")

    server.serve_forever()


# =========================================================
# OPENFOOT API
# =========================================================

def test_openfoot():

    if not OPENFOOT_API_KEY:
        return (
            False,
            "OPENFOOT_API_KEY is missing from Render."
        )

    headers = {
        "Authorization": f"Bearer {OPENFOOT_API_KEY}",
        "Accept": "application/json",
    }

    try:

        url = f"{OPENFOOT_BASE}/v1/search"

        response = httpx.get(
            url,
            params={"q": "Arsenal"},
            headers=headers,
            timeout=20
        )

        print(
            "OPENFOOT STATUS:",
            response.status_code
        )

        print(
            "OPENFOOT RESPONSE:",
            response.text[:1000]
        )

        if response.status_code == 200:

            return (
                True,
                "OpenFoot API is connected successfully."
            )

        if response.status_code == 401:

            return (
                False,
                "OpenFoot returned 401: API key is invalid or not being accepted."
            )

        if response.status_code == 403:

            return (
                False,
                "OpenFoot returned 403: this endpoint is restricted by the current plan."
            )

        if response.status_code == 429:

            return (
                False,
                "OpenFoot returned 429: rate limit or monthly quota reached."
            )

        return (
            False,
            f"OpenFoot returned HTTP {response.status_code}.\n\n"
            f"Response: {response.text[:500]}"
        )

    except Exception as e:

        print(
            "OPENFOOT CONNECTION ERROR:",
            repr(e)
        )

        return (
            False,
            f"Connection error: {str(e)[:500]}"
        )


# =========================================================
# TELEGRAM COMMANDS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 GoalLogic AI is online!\n\n"
        "Send me a football match like:\n\n"
        "Chelsea vs Arsenal\n\n"
        "I will analyze the match using available football data."
    )


async def apitest(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🔎 Testing OpenFoot API...\n\n"
        "Please wait."
    )

    success, message = test_openfoot()

    if success:

        await update.message.reply_text(
            "✅ OPENFOOT TEST PASSED\n\n"
            + message
        )

    else:

        await update.message.reply_text(
            "❌ OPENFOOT TEST FAILED\n\n"
            + message
        )


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "⚽ Match received.\n\n"
        "🔎 Checking football data..."
    )

    success, message = test_openfoot()

    if not success:

        await update.message.reply_text(
            "⚠️ Football data could not be retrieved yet.\n\n"
            + message
        )

        return

    await update.message.reply_text(
        "✅ Football data connection is working.\n\n"
        "🤖 Analysis engine is ready for the next step."
    )


async def handle_match(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text.strip()

    if " vs " in text.lower():

        await analyze(update, context)

    else:

        await update.message.reply_text(
            "⚽ Send a match in this format:\n\n"
            "Chelsea vs Arsenal"
        )


# =========================================================
# MAIN BOT
# =========================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN is missing."
        )

        return

    print("Starting GoalLogic AI...")

    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("apitest", apitest)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_match
        )
    )

    print("GoalLogic AI is running.")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
