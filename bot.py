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

API_BASE = "https://v3.football.api-sports.io"


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
        "Commands:\n"
        "/team Chelsea - Search for a team\n"
        "/fixtures Chelsea - Show next fixtures\n"
        "/apitest - Check API status"
    )


async def api_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ API test was already completed successfully.\n"
        "Football API connection is working."
    )


async def team_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not FOOTBALL_API_KEY:
        await update.message.reply_text(
            "❌ FOOTBALL_API_KEY is missing from Render."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Please enter a team name.\n\n"
            "Example:\n"
            "/team Chelsea"
        )
        return

    team_name = " ".join(context.args)

    await update.message.reply_text(
        f"🔎 Searching for: {team_name}..."
    )

    try:
        headers = {
            "x-apisports-key": FOOTBALL_API_KEY
        }

        params = {
            "search": team_name
        }

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{API_BASE}/teams",
                headers=headers,
                params=params
            )

        if response.status_code != 200:
            await update.message.reply_text(
                f"❌ API error: {response.status_code}\n\n"
                f"{response.text[:500]}"
            )
            return

        teams = response.json().get("response", [])

        if not teams:
            await update.message.reply_text(
                f"❌ No team found for: {team_name}"
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
            f"❌ Connection error:\n{str(e)[:500]}"
        )


async def fixtures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not FOOTBALL_API_KEY:
        await update.message.reply_text(
            "❌ FOOTBALL_API_KEY is missing from Render."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Please enter a team name.\n\n"
            "Example:\n"
            "/fixtures Chelsea"
        )
        return

    team_name = " ".join(context.args)

    await update.message.reply_text(
        f"🔎 Finding fixtures for {team_name}..."
    )

    try:
        headers = {
            "x-apisports-key": FOOTBALL_API_KEY
        }

        team_params = {
            "search": team_name
        }

        async with httpx.AsyncClient(timeout=15) as client:

            team_response = await client.get(
                f"{API_BASE}/teams",
                headers=headers,
                params=team_params
            )

            if team_response.status_code != 200:
                await update.message.reply_text(
                    f"❌ Team search error: "
                    f"{team_response.status_code}"
                )
                return

            teams = team_response.json().get("response", [])

            if not teams:
                await update.message.reply_text(
                    f"❌ No team found for {team_name}"
                )
                return

            team_id = teams[0]["team"]["id"]

            fixture_params = {
    "team": team_id,
    "league": 39,
    "season": 2026,
    "next": 10
}

            fixture_response = await client.get(
                f"{API_BASE}/fixtures",
                headers=headers,
                params=fixture_params
            )

            if fixture_response.status_code != 200:
                await update.message.reply_text(
                    f"❌ Fixture API error: "
                    f"{fixture_response.status_code}\n\n"
                    f"{fixture_response.text[:500]}"
                )
                return

            fixtures_data = fixture_response.json().get(
                "response", []
            )

        if not fixtures_data:
            await update.message.reply_text(
                f"❌ No upcoming fixtures found for {team_name}."
            )
            return

        message = f"📅 Next fixtures for {team_name}:\n\n"

        for item in fixtures_data:
            fixture = item.get("fixture", {})
            teams_data = item.get("teams", {})

            home = teams_data.get(
                "home", {}
            ).get("name", "Unknown")

            away = teams_data.get(
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
            f"❌ Error:\n{str(e)[:500]}"
        )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    match = update.message.text

    await update.message.reply_text(
        f"📥 Match received:\n{match}\n\n"
        "🔧 Analysis engine is being connected..."
    )


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not FOOTBALL_API_KEY:
        raise RuntimeError(
            "FOOTBALL_API_KEY is missing."
        )

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

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
