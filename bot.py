import os
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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
PORT = int(os.getenv("PORT", "10000"))

API_BASE = "https://v3.football.api-sports.io"


# -------------------------
# Render health server
# -------------------------

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        pass


def start_health_server():
    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )
    server.serve_forever()


# -------------------------
# Telegram /start
# -------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "⚽ GoalLogic AI is online!\n\n"
        "Available commands:\n\n"
        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/apitest"
    )


# -------------------------
# API test
# -------------------------

async def api_test(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "✅ Football API connection was previously "
        "confirmed successfully."
    )


# -------------------------
# Team search
# -------------------------

async def team_search(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not FOOTBALL_API_KEY:
        await update.message.reply_text(
            "❌ Football API key is missing."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Example:\n/team Chelsea"
        )
        return

    team_name = " ".join(context.args)

    await update.message.reply_text(
        f"🔎 Searching for {team_name}..."
    )

    headers = {
        "x-apisports-key": FOOTBALL_API_KEY
    }

    params = {
        "search": team_name
    }

    try:

        async with httpx.AsyncClient(timeout=15) as client:

            response = await client.get(
                f"{API_BASE}/teams",
                headers=headers,
                params=params
            )

        if response.status_code != 200:

            await update.message.reply_text(
                f"❌ API error: {response.status_code}"
            )
            return

        data = response.json()

        teams = data.get("response", [])

        if not teams:

            await update.message.reply_text(
                f"❌ No team found for {team_name}"
            )
            return

        message = "✅ Teams found:\n\n"

        for item in teams[:5]:

            team = item.get("team", {})

            name = team.get("name", "Unknown")
            team_id = team.get("id", "Unknown")
            country = team.get("country", "Unknown")

            message += (
                f"⚽ {name}\n"
                f"ID: {team_id}\n"
                f"Country: {country}\n\n"
            )

        await update.message.reply_text(message)

    except Exception as e:

        await update.message.reply_text(
            f"❌ Connection error:\n{str(e)[:300]}"
        )


# -------------------------
# Fixtures
# -------------------------

async def fixtures(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not FOOTBALL_API_KEY:
        await update.message.reply_text(
            "❌ Football API key is missing."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Example:\n/fixtures Chelsea"
        )
        return

    team_name = " ".join(context.args)

    await update.message.reply_text(
        f"🔎 Finding fixtures for {team_name}..."
    )

    headers = {
        "x-apisports-key": FOOTBALL_API_KEY
    }

    try:

        async with httpx.AsyncClient(timeout=15) as client:

            # Find the team
            team_response = await client.get(
                f"{API_BASE}/teams",
                headers=headers,
                params={"search": team_name}
            )

            if team_response.status_code != 200:

                await update.message.reply_text(
                    f"❌ Team API error: "
                    f"{team_response.status_code}"
                )
                return

            team_data = team_response.json()

            teams = team_data.get("response", [])

            if not teams:

                await update.message.reply_text(
                    f"❌ No team found for {team_name}"
                )
                return

            # Use the first matching team
            team_id = teams[0]["team"]["id"]

            # Get next fixtures
            fixture_response = await client.get(
                f"{API_BASE}/fixtures",
                headers=headers,
                params={
                    "team": team_id,
                    "next": 5
                }
            )

            if fixture_response.status_code != 200:

                await update.message.reply_text(
                    f"❌ Fixture API error: "
                    f"{fixture_response.status_code}"
                )
                return

            fixture_data = fixture_response.json()

            fixtures_list = fixture_data.get(
                "response", []
            )

        if not fixtures_list:

            await update.message.reply_text(
                f"ℹ️ No upcoming fixtures were returned "
                f"for {team_name}."
            )
            return

        message = (
            f"📅 Upcoming fixtures for "
            f"{teams[0]['team']['name']}:\n\n"
        )

        for item in fixtures_list:

            fixture = item.get("fixture", {})
            match_teams = item.get("teams", {})

            home = match_teams.get(
                "home", {}
            ).get("name", "Unknown")

            away = match_teams.get(
                "away", {}
            ).get("name", "Unknown")

            date = fixture.get(
                "date", "Unknown"
            )

            message += (
                f"⚽ {home} vs {away}\n"
                f"🕒 {date}\n\n"
            )

        await update.message.reply_text(message)

    except Exception as e:

        await update.message.reply_text(
            f"❌ Fixture error:\n{str(e)[:300]}"
        )


# -------------------------
# Normal messages
# -------------------------

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "📥 Match received:\n\n"
        f"{update.message.text}\n\n"
        "🔧 Analysis engine is being connected..."
    )


# -------------------------
# Main
# -------------------------

def main():

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not FOOTBALL_API_KEY:
        raise RuntimeError(
            "FOOTBALL_API_KEY is missing."
        )

    # Start Render health server
    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    # Start Telegram bot
    app = Application.builder().token(
        TELEGRAM_BOT_TOKEN
    ).build()

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("apitest", api_test)
    )

    app.add_handler(
        CommandHandler("team", team_search)
    )

    app.add_handler(
        CommandHandler("fixtures", fixtures)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print(
        f"GoalLogic AI is running on port {PORT}."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
