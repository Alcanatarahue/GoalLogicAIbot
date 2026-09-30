import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

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

FIXTURE_SEASON = 2024


# ==================================================
# RENDER HEALTH SERVER
# ==================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain"
        )

        self.end_headers()

        self.wfile.write(
            b"GoalLogic AI is running"
        )

    def log_message(self, format, *args):
        return


def start_health_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    server.serve_forever()


# ==================================================
# FOOTBALL API
# ==================================================

async def api_get(endpoint, params=None):

    headers = {
        "x-apisports-key": FOOTBALL_API_KEY
    }

    async with httpx.AsyncClient(
        timeout=30
    ) as client:

        response = await client.get(
            f"{API_BASE}/{endpoint}",
            headers=headers,
            params=params
        )

        return response


# ==================================================
# START
# ==================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "⚽ GoalLogic AI is online!\n\n"

        "Commands:\n\n"

        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/analyze Chelsea vs Arsenal\n"
        "/apitest"
    )


# ==================================================
# API TEST
# ==================================================

async def api_test(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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


# ==================================================
# FIND TEAM
# ==================================================

async def find_team(team_name):

    response = await api_get(
        "teams",
        {
            "search": team_name
        }
    )

    data = response.json()

    if data.get("errors"):
        return None, data.get("errors")

    teams = data.get(
        "response",
        []
    )

    if not teams:
        return None, "Team not found"

    for item in teams:

        name = item.get(
            "team",
            {}
        ).get(
            "name",
            ""
        )

        if name.lower() == team_name.lower():

            return item.get(
                "team",
                {}
            ), None

    return teams[0].get(
        "team",
        {}
    ), None


# ==================================================
# TEAM SEARCH
# ==================================================

async def team_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/team Chelsea"
        )

        return

    team_name = " ".join(context.args)

    try:

        response = await api_get(
            "teams",
            {
                "search": team_name
            }
        )

        data = response.json()

        if data.get("errors"):

            await update.message.reply_text(
                f"❌ API error:\n{data['errors']}"
            )

            return

        teams = data.get(
            "response",
            []
        )

        if not teams:

            await update.message.reply_text(
                f"❌ No team found for {team_name}"
            )

            return

        reply = (
            f"🔎 Teams matching "
            f"'{team_name}':\n\n"
        )

        for item in teams[:10]:

            team = item.get(
                "team",
                {}
            )

            reply += (
                f"⚽ {team.get('name', 'Unknown')}\n"
                f"ID: {team.get('id', 'Unknown')}\n"
                f"Country: {team.get('country', 'Unknown')}\n\n"
            )

        await update.message.reply_text(reply)

    except Exception as e:

        await update.message.reply_text(
            f"⚠️ Error searching team:\n{e}"
        )


# ==================================================
# GET TEAM FIXTURES
# ==================================================

async def get_team_fixtures(team_id):

    response = await api_get(
        "fixtures",
        {
            "team": team_id,
            "season": FIXTURE_SEASON
        }
    )

    data = response.json()

    if data.get("errors"):

        return [], data.get("errors")

    return data.get(
        "response",
        []
    ), None


# ==================================================
# BASIC FIXTURES COMMAND
# ==================================================

async def fixtures(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/fixtures Chelsea"
        )

        return

    team_name = " ".join(context.args)

    try:

        team, error = await find_team(
            team_name
        )

        if error:

            await update.message.reply_text(
                f"❌ {error}"
            )

            return

        matches, error = await get_team_fixtures(
            team.get("id")
        )

        if error:

            await update.message.reply_text(
                f"❌ Fixture API error:\n{error}"
            )

            return

        if not matches:

            await update.message.reply_text(
                "ℹ️ No fixtures returned."
            )

            return

        reply = (
            f"📅 Fixtures for {team.get('name')}\n"
            f"🗓️ Season {FIXTURE_SEASON}\n\n"
        )

        for match in matches[:15]:

            teams = match.get(
                "teams",
                {}
            )

            home = teams.get(
                "home",
                {}
            ).get(
                "name",
                "Unknown"
            )

            away = teams.get(
                "away",
                {}
            ).get(
                "name",
                "Unknown"
            )

            reply += (
                f"⚽ {home} vs {away}\n\n"
            )

        reply += (
            f"Showing up to 15 fixtures.\n"
            f"Total returned: {len(matches)}"
        )

        await update.message.reply_text(
            reply
        )

    except Exception as e:

        await update.message.reply_text(
            f"⚠️ Error fetching fixtures:\n{e}"
        )


# ==================================================
# CALCULATE STATISTICS
# ==================================================

def calculate_stats(
    matches,
    team_id,
    limit=5
):

    matches = matches[-limit:]

    played = 0
    wins = 0
    draws = 0
    losses = 0

    goals_for = 0
    goals_against = 0

    over_1_5 = 0
    over_2_5 = 0
    btts = 0

    for match in matches:

        teams = match.get(
            "teams",
            {}
        )

        goals = match.get(
            "goals",
            {}
        )

        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        home_id = teams.get(
            "home",
            {}
        ).get("id")

        away_id = teams.get(
            "away",
            {}
        ).get("id")

        if team_id == home_id:

            gf = home_goals
            ga = away_goals

        elif team_id == away_id:

            gf = away_goals
            ga = home_goals

        else:

            continue

        played += 1

        goals_for += gf
        goals_against += ga

        if gf > ga:
            wins += 1

        elif gf == ga:
            draws += 1

        else:
            losses += 1

        total = gf + ga

        if total >= 2:
            over_1_5 += 1

        if total >= 3:
            over_2_5 += 1

        if gf >= 1 and ga >= 1:
            btts += 1

    if played:

        avg_for = goals_for / played
        avg_against = goals_against / played

        over_1_5_pct = over_1_5 / played * 100
        over_2_5_pct = over_2_5 / played * 100
        btts_pct = btts / played * 100

    else:

        avg_for = 0
        avg_against = 0

        over_1_5_pct = 0
        over_2_5_pct = 0
        btts_pct = 0

    return {
        "played": played,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "avg_for": avg_for,
        "avg_against": avg_against,
        "over_1_5": over_1_5_pct,
        "over_2_5": over_2_5_pct,
        "btts": btts_pct,
    }


# ==================================================
# HOME / AWAY FILTER
# ==================================================

def filter_home_matches(
    matches,
    team_id
):

    result = []

    for match in matches:

        home_id = match.get(
            "teams",
            {}
        ).get(
            "home",
            {}
        ).get("id")

        if home_id == team_id:

            result.append(match)

    return result


def filter_away_matches(
    matches,
    team_id
):

    result = []

    for match in matches:

        away_id = match.get(
            "teams",
            {}
        ).get(
            "away",
            {}
        ).get("id")

        if away_id == team_id:

            result.append(match)

    return result


# ==================================================
# HEAD TO HEAD
# ==================================================

def find_h2h(
    home_matches,
    home_id,
    away_id
):

    h2h = []

    for match in home_matches:

        teams = match.get(
            "teams",
            {}
        )

        home_team_id = teams.get(
            "home",
            {}
        ).get("id")

        away_team_id = teams.get(
            "away",
            {}
        ).get("id")

        if (
            (
                home_team_id == home_id
                and away_team_id == away_id
            )
            or
            (
                home_team_id == away_id
                and away_team_id == home_id
            )
        ):

            h2h.append(match)

    return h2h


def calculate_h2h_stats(
    matches,
    home_id,
    away_id
):

    wins_home = 0
    wins_away = 0
    draws = 0

    goals_home = 0
    goals_away = 0

    over_2_5 = 0
    btts = 0

    for match in matches:

        teams = match.get(
            "teams",
            {}
        )

        goals = match.get(
            "goals",
            {}
        )

        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        fixture_home_id = teams.get(
            "home",
            {}
        ).get("id")

        fixture_away_id = teams.get(
            "away",
            {}
        ).get("id")

        if fixture_home_id == home_id:

            home_team_goals = home_goals
            away_team_goals = away_goals

        else:

            home_team_goals = away_goals
            away_team_goals = home_goals

        goals_home += home_team_goals
        goals_away += away_team_goals

        if home_team_goals > away_team_goals:
            wins_home += 1

        elif home_team_goals < away_team_goals:
            wins_away += 1

        else:
            draws += 1

        if home_team_goals + away_team_goals >= 3:
            over_2_5 += 1

        if (
            home_team_goals >= 1
            and away_team_goals >= 1
        ):
            btts += 1

    total = len(matches)

    if total:

        over_2_5_pct = over_2_5 / total * 100
        btts_pct = btts / total * 100

    else:

        over_2_5_pct = 0
        btts_pct = 0

    return {
        "matches": total,
        "home_wins": wins_home,
        "away_wins": wins_away,
        "draws": draws,
        "home_goals": goals_home,
        "away_goals": goals_away,
        "over_2_5": over_2_5_pct,
        "btts": btts_pct,
    }


# ==================================================
# ANALYZE
# ==================================================

async def analyze(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if len(context.args) < 3:

        await update.message.reply_text(
            "Use:\n\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    message = " ".join(context.args)

    parts = message.lower().split(" vs ")

    if len(parts) != 2:

        await update.message.reply_text(
            "❌ Use:\n\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    home_name = parts[0].strip()
    away_name = parts[1].strip()

    try:

        await update.message.reply_text(
            "🔎 Analyzing match...\n\n"
            f"⚽ {home_name.title()} vs "
            f"{away_name.title()}\n\n"
            "Collecting form, home/away and H2H data..."
        )

        home_team, home_error = await find_team(
            home_name
        )

        away_team, away_error = await find_team(
            away_name
        )

        if home_error:

            await update.message.reply_text(
                f"❌ Home team error:\n{home_error}"
            )

            return

        if away_error:

            await update.message.reply_text(
                f"❌ Away team error:\n{away_error}"
            )

            return

        home_id = home_team.get("id")
        away_id = away_team.get("id")

        home_official = home_team.get(
            "name",
            home_name
        )

        away_official = away_team.get(
            "name",
            away_name
        )

        home_matches, home_error = await get_team_fixtures(
            home_id
        )

        away_matches, away_error = await get_team_fixtures(
            away_id
        )

        if home_error:

            await update.message.reply_text(
                f"❌ {home_error}"
            )

            return

        if away_error:

            await update.message.reply_text(
                f"❌ {away_error}"
            )

            return

        # ------------------------------------------
        # RECENT FORM
        # ------------------------------------------

        home_stats = calculate_stats(
            home_matches,
            home_id,
            5
        )

        away_stats = calculate_stats(
            away_matches,
            away_id,
            5
        )

        # ------------------------------------------
        # HOME / AWAY
        # ------------------------------------------

        home_home_matches = filter_home_matches(
            home_matches,
            home_id
        )

        away_away_matches = filter_away_matches(
            away_matches,
            away_id
        )

        home_home_stats = calculate_stats(
            home_home_matches,
            home_id,
            5
        )

        away_away_stats = calculate_stats(
            away_away_matches,
            away_id,
            5
        )

        # ------------------------------------------
        # H2H
        # ------------------------------------------

        h2h_matches = find_h2h(
            home_matches,
            home_id,
            away_id
        )

        h2h_matches = h2h_matches[-5:]

        h2h_stats = calculate_h2h_stats(
            h2h_matches,
            home_id,
            away_id
        )

        reply = (

            "⚽ GOALLOGIC AI ANALYSIS\n\n"

            f"🏟️ {home_official} vs "
            f"{away_official}\n\n"

            "📊 DATA PERIOD\n"
            f"Season: {FIXTURE_SEASON}\n"
            "Recent sample: Last 5 available\n\n"

            "━━━━━━━━━━━━━━━━━━\n"
            "📈 RECENT FORM\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            f"🏠 {home_official}\n"
            f"✅ Wins: {home_stats['wins']}\n"
            f"🤝 Draws: {home_stats['draws']}\n"
            f"❌ Losses: {home_stats['losses']}\n"
            f"⚽ Avg goals: {home_stats['avg_for']:.2f}\n"
            f"🥅 Avg conceded: {home_stats['avg_against']:.2f}\n"
            f"🔥 Over 2.5: {home_stats['over_2_5']:.0f}%\n"
            f"🎯 BTTS: {home_stats['btts']:.0f}%\n\n"

            f"✈️ {away_official}\n"
            f"✅ Wins: {away_stats['wins']}\n"
            f"🤝 Draws: {away_stats['draws']}\n"
            f"❌ Losses: {away_stats['losses']}\n"
            f"⚽ Avg goals: {away_stats['avg_for']:.2f}\n"
            f"🥅 Avg conceded: {away_stats['avg_against']:.2f}\n"
            f"🔥 Over 2.5: {away_stats['over_2_5']:.0f}%\n"
            f"🎯 BTTS: {away_stats['btts']:.0f}%\n\n"

            "━━━━━━━━━━━━━━━━━━\n"
            "🏠 HOME / AWAY\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            f"🏠 {home_official} HOME\n"
            f"Games: {home_home_stats['played']}\n"
            f"✅ Wins: {home_home_stats['wins']}\n"
            f"🤝 Draws: {home_home_stats['draws']}\n"
            f"❌ Losses: {home_home_stats['losses']}\n"
            f"⚽ Avg scored: {home_home_stats['avg_for']:.2f}\n"
            f"🥅 Avg conceded: {home_home_stats['avg_against']:.2f}\n"
            f"🔥 Over 2.5: {home_home_stats['over_2_5']:.0f}%\n"
            f"🎯 BTTS: {home_home_stats['btts']:.0f}%\n\n"

            f"✈️ {away_official} AWAY\n"
            f"Games: {away_away_stats['played']}\n"
            f"✅ Wins: {away_away_stats['wins']}\n"
            f"🤝 Draws: {away_away_stats['draws']}\n"
            f"❌ Losses: {away_away_stats['losses']}\n"
            f"⚽ Avg scored: {away_away_stats['avg_for']:.2f}\n"
            f"🥅 Avg conceded: {away_away_stats['avg_against']:.2f}\n"
            f"🔥 Over 2.5: {away_away_stats['over_2_5']:.0f}%\n"
            f"🎯 BTTS: {away_away_stats['btts']:.0f}%\n\n"

            "━━━━━━━━━━━━━━━━━━\n"
            "🤝 HEAD-TO-HEAD\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
        )

        if h2h_stats["matches"] > 0:

            reply += (

                f"Games found: "
                f"{h2h_stats['matches']}\n\n"

                f"🏠 {home_official} wins: "
                f"{h2h_stats['home_wins']}\n"

                f"✈️ {away_official} wins: "
                f"{h2h_stats['away_wins']}\n"

                f"🤝 Draws: "
                f"{h2h_stats['draws']}\n\n"

                f"⚽ {home_official} H2H goals: "
                f"{h2h_stats['home_goals']}\n"

                f"⚽ {away_official} H2H goals: "
                f"{h2h_stats['away_goals']}\n\n"

                f"🔥 H2H Over 2.5: "
                f"{h2h_stats['over_2_5']:.0f}%\n"

                f"🎯 H2H BTTS: "
                f"{h2h_stats['btts']:.0f}%\n\n"
            )

        else:

            reply += (
                "No H2H meetings were found "
                "inside the available 2024 data.\n\n"
            )

        reply += (

            "━━━━━━━━━━━━━━━━━━\n"
            "📊 GOALLOGIC SUMMARY\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            f"🏠 Home team: {home_official}\n"
            f"✈️ Away team: {away_official}\n\n"

            "The analysis now combines recent "
            "form, home/away performance and "
            "available H2H information.\n\n"

            "⚠️ DATA LIMITATION\n"
            "Your current API plan only provides "
            "fixture seasons 2022-2024. Therefore "
            "these are historical 2024 statistics, "
            "not current 2026 statistics.\n\n"

            "⚠️ BETTING NOTE\n"
            "Statistics describe past performance "
            "and do not guarantee a future result.\n\n"

            "🔧 NEXT UPGRADE\n"
            "Shots • Shots on Target • Corners • "
            "Cards • xG • Market analysis"
        )

        await update.message.reply_text(
            reply
        )

    except Exception as e:

        await update.message.reply_text(
            f"⚠️ Analysis error:\n\n{e}"
        )


# ==================================================
# NORMAL MESSAGES
# ==================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message.text.strip()

    if " vs " in message.lower():

        await update.message.reply_text(
            "⚽ Match received!\n\n"
            f"{message}\n\n"
            f"Use:\n/analyze {message}"
        )

    else:

        await update.message.reply_text(
            "⚽ GoalLogic AI received your message.\n\n"
            "Try:\n\n"
            "/team Chelsea\n"
            "/fixtures Chelsea\n"
            "/analyze Chelsea vs Arsenal\n"
            "/apitest"
        )


# ==================================================
# MAIN
# ==================================================

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
        CommandHandler("analyze", analyze)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print(
        f"GoalLogic AI is running "
        f"on port {PORT}."
    )

    application.run_polling()


if __name__ == "__main__":
    main()
