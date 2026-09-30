import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

PORT = int(os.getenv("PORT", "10000"))
API_BASE = "https://v3.football.api-sports.io"


# =========================
# RENDER HEALTH SERVER
# =========================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running")

    def log_message(self, format, *args):
        return


def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


# =========================
# API HELPER
# =========================

async def api_get(endpoint, params=None):

    headers = {
        "x-apisports-key": FOOTBALL_API_KEY
    }

    async with httpx.AsyncClient(timeout=20) as client:

        response = await client.get(
            f"{API_BASE}/{endpoint}",
            headers=headers,
            params=params
        )

        return response


# =========================
# /START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "⚽ GoalLogic AI is online!\n\n"
        "Available commands:\n\n"
        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/apitest\n\n"
        "You can also send a match such as:\n"
        "Chelsea vs Arsenal"
    )


# =========================
# /APITEST
# =========================

async def api_test(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:

        response = await api_get("status")

        await update.message.reply_text(
            "🔧 FOOTBALL API TEST\n\n"
            f"HTTP Status: {response.status_code}\n\n"
            f"Response:\n{response.text[:2500]}"
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ API test failed:\n{e}"
        )


# =========================
# /TEAM
# =========================

async def team_search(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/team Chelsea"
        )

        return

    team_name = " ".join(context.args)

    try:

        response = await api_get(
            "teams",
            {"search": team_name}
        )

        data = response.json()

        if data.get("errors"):

            await update.message.reply_text(
                f"❌ API error:\n{data['errors']}"
            )

            return

        teams = data.get("response", [])

        if not teams:

            await update.message.reply_text(
                f"❌ No team found for: {team_name}"
            )

            return

        reply = f"🔎 Teams matching '{team_name}':\n\n"

        for item in teams[:10]:

            team = item.get("team", {})

            name = team.get("name", "Unknown")
            team_id = team.get("id", "Unknown")
            country = team.get("country", "Unknown")

            reply += (
                f"⚽ {name}\n"
                f"ID: {team_id}\n"
                f"Country: {country}\n\n"
            )

        await update.message.reply_text(reply)

    except Exception as e:

        await update.message.reply_text(
            f"⚠️ Error searching team:\n{e}"
        )


# =========================
# /FIXTURES
# =========================

async def fixtures(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text(
            "Use:\n/fixtures Chelsea"
        )
        return

    team_name = " ".join(context.args)

    try:
        # Find the team
        team_response = await api_get(
            "teams",
            {"search": team_name}
        )

        team_data = team_response.json()

        if team_data.get("errors"):
            await update.message.reply_text(
                f"❌ Team search error:\n{team_data['errors']}"
            )
            return

        teams = team_data.get("response", [])

        if not teams:
            await update.message.reply_text(
                f"❌ Team not found: {team_name}"
            )
            return

        # Prefer exact team name
        selected_team = None

        for item in teams:
            name = item.get("team", {}).get("name", "")

            if name.lower() == team_name.lower():
                selected_team = item
                break

        if selected_team is None:
            selected_team = teams[0]

        team = selected_team.get("team", {})

        team_id = team.get("id")
        official_name = team.get("name", team_name)

        # Current date
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 30-day date range
        from_date = today

        future_date = datetime.now(timezone.utc).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0
        )

        future_date = future_date.timestamp() + (30 * 24 * 60 * 60)

        to_date = datetime.fromtimestamp(
            future_date,
            timezone.utc
        ).strftime("%Y-%m-%d")

        # Get fixtures using date 
fixture_response = await api_get(
    "fixtures",
    {
        "team": team_id,
        "season": 2026,
        "from": from_date,
        "to": to_date
    }
)
        fixture_data = fixture_response.json()

        if fixture_data.get("errors"):
            await update.message.reply_text(
                f"❌ Fixture API error:\n{fixture_data['errors']}"
            )
            return

        matches = fixture_data.get("response", [])

        if not matches:
            await update.message.reply_text(
                f"ℹ️ No fixtures found for {official_name} "
                f"between {from_date} and {to_date}."
            )
            return

        reply = (
            f"📅 Fixtures for {official_name}\n"
            f"🗓️ {from_date} → {to_date}\n\n"
        )

        for match in matches:

            fixture = match.get("fixture", {})
            teams_info = match.get("teams", {})
            league = match.get("league", {})

            home = teams_info.get("home", {}).get(
                "name", "Unknown"
            )

            away = teams_info.get("away", {}).get(
                "name", "Unknown"
            )

            date_string = fixture.get("date")

            if date_string:
                try:
                    date_object = datetime.fromisoformat(
                        date_string.replace("Z", "+00:00")
                    )

                    date_display = date_object.strftime(
                        "%d %b %Y, %H:%M UTC"
                    )

                except Exception:
                    date_display = date_string
            else:
                date_display = "Date unavailable"

            league_name = league.get(
                "name",
                "Unknown competition"
            )

            reply += (
                f"📅 {date_display}\n"
                f"⚽ {home} vs {away}\n"
                f"🏆 {league_name}\n\n"
            )

        await update.message.reply_text(reply)

    except Exception as e:

        await update.message.reply_text(
            f"⚠️ Error fetching fixtures:\n{e}"
        )


# =========================
# NORMAL MESSAGES
# =========================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message.text.strip()

    if " vs " in message.lower():

        await update.message.reply_text(
            "⚽ Match received!\n\n"
            f"{message}\n\n"
            "🔧 Match analysis engine will be connected next."
        )

    else:

        await update.message.reply_text(
            "⚽ GoalLogic AI received your message.\n\n"
            "Try:\n"
            "/team Chelsea\n"
            "/fixtures Chelsea\n"
            "/apitest"
        )


# =========================
# MAIN
# =========================

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

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("apitest", api_test)
    )

    application.add_handler(
        CommandHandler("team", team_search)
    )

    application.add_handler(
        CommandHandler("fixtures", fixtures)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print(
        f"GoalLogic AI is running on port {PORT}."
    )

    application.run_polling()


if __name__ == "__main__":
    main()
