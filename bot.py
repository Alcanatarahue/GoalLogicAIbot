import os
import time
import threading
import http.server
from datetime import datetime

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# SETTINGS
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
OPENFOOT_BASE = "https://openfootapi.com"

# Current football season
CURRENT_SEASON = "2026/27"

# Historical API-Football season available on the free plan
HISTORICAL_SEASON = 2024

PORT = int(os.getenv("PORT", "10000"))

# ============================================================
# BASIC CACHE
# ============================================================

CACHE = {}
CACHE_TTL = 300

api_lock = threading.Lock()
last_api_request = 0

openfoot_lock = threading.Lock()
last_openfoot_request = 0


# ============================================================
# RENDER HEALTH SERVER
# ============================================================

class HealthHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        return


def start_health_server():
    server = http.server.HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"GoalLogic AI is running on port {PORT}.")
    server.serve_forever()


# ============================================================
# API-FOOTBALL
# ============================================================

def api_football_get(endpoint, params=None):

    global last_api_request

    if not FOOTBALL_API_KEY:
        return None

    cache_key = "api:" + endpoint + ":" + str(params)

    if cache_key in CACHE:
        saved_time, saved_data = CACHE[cache_key]

        if time.time() - saved_time < CACHE_TTL:
            return saved_data

    with api_lock:

        wait_time = 1.2 - (time.time() - last_api_request)

        if wait_time > 0:
            time.sleep(wait_time)

        url = API_FOOTBALL_BASE + endpoint

        headers = {
            "x-apisports-key": FOOTBALL_API_KEY
        }

        try:

            response = httpx.get(
                url,
                headers=headers,
                params=params or {},
                timeout=20
            )

            last_api_request = time.time()

            if response.status_code != 200:
                print(
                    "API-Football error:",
                    response.status_code,
                    response.text[:500]
                )
                return None

            data = response.json()

            if data.get("errors"):
                print("API-Football errors:", data["errors"])
                return None

            CACHE[cache_key] = (time.time(), data)

            return data

        except Exception as e:
            print("API-Football exception:", e)
            return None


# ============================================================
# OPENFOOT
# ============================================================

def openfoot_get(endpoint, params=None):

    global last_openfoot_request

    if not OPENFOOT_API_KEY:
        print("OPENFOOT_API_KEY is missing.")
        return None

    cache_key = "openfoot:" + endpoint + ":" + str(params)

    if cache_key in CACHE:
        saved_time, saved_data = CACHE[cache_key]

        if time.time() - saved_time < CACHE_TTL:
            return saved_data

    with openfoot_lock:

        wait_time = 0.5 - (time.time() - last_openfoot_request)

        if wait_time > 0:
            time.sleep(wait_time)

        url = OPENFOOT_BASE + endpoint

        headers = {
            "Authorization": f"Bearer {OPENFOOT_API_KEY}",
            "Accept": "application/json",
        }

        try:

            response = httpx.get(
                url,
                headers=headers,
                params=params or {},
                timeout=20
            )

            last_openfoot_request = time.time()

            print(
                "OpenFoot:",
                endpoint,
                response.status_code
            )

            if response.status_code != 200:
                print(
                    "OpenFoot error:",
                    response.text[:500]
                )
                return None

            data = response.json()

            CACHE[cache_key] = (time.time(), data)

            return data

        except Exception as e:
            print("OpenFoot exception:", e)
            return None


# ============================================================
# OPENFOOT DATA HELPERS
# ============================================================

def extract_data(response):

    if response is None:
        return []

    if isinstance(response, dict):

        if "data" in response:
            return response["data"]

        return response

    return response


def find_objects_with_id(value, results=None):

    if results is None:
        results = []

    if isinstance(value, dict):

        if "id" in value and (
            "name" in value
            or "team" in value
            or "teamName" in value
        ):
            results.append(value)

        for item in value.values():
            find_objects_with_id(item, results)

    elif isinstance(value, list):

        for item in value:
            find_objects_with_id(item, results)

    return results


def get_object_name(obj):

    if not isinstance(obj, dict):
        return ""

    if obj.get("name"):
        return str(obj["name"])

    if obj.get("teamName"):
        return str(obj["teamName"])

    team = obj.get("team")

    if isinstance(team, dict):
        return str(team.get("name", ""))

    return ""


def search_openfoot_team(team_name):

    print("Searching OpenFoot for:", team_name)

    response = openfoot_get(
        "/v1/search",
        {
            "q": team_name
        }
    )

    if response is None:
        return None

    candidates = []

    data = extract_data(response)

    if isinstance(data, list):
        candidates = data

    elif isinstance(data, dict):
        candidates = find_objects_with_id(data)

    # Also inspect the complete response
    if not candidates:
        candidates = find_objects_with_id(response)

    cleaned = []

    seen = set()

    for item in candidates:

        if not isinstance(item, dict):
            continue

        item_id = item.get("id")

        if not item_id:
            continue

        name = get_object_name(item)

        if not name:
            continue

        key = str(item_id)

        if key not in seen:
            seen.add(key)
            cleaned.append(item)

    if not cleaned:
        print("No OpenFoot team found for:", team_name)
        return None

    # Try exact/close match first
    search_lower = team_name.lower().strip()

    for team in cleaned:

        name = get_object_name(team).lower().strip()

        if name == search_lower:
            return team

    for team in cleaned:

        name = get_object_name(team).lower()

        if search_lower in name or name in search_lower:
            return team

    return cleaned[0]


def get_team_matches_openfoot(team_id):

    response = openfoot_get(
        "/v1/matches",
        {
            "team": team_id,
            "season": CURRENT_SEASON
        }
    )

    if response is None:
        return []

    data = extract_data(response)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in [
            "matches",
            "fixtures",
            "results"
        ]:

            if isinstance(data.get(key), list):
                return data[key]

    return []


# ============================================================
# MATCH HELPERS
# ============================================================

def get_team_from_match(match, side):

    if not isinstance(match, dict):
        return None

    possible = []

    if side == "home":
        possible = [
            match.get("homeTeam"),
            match.get("home"),
            match.get("home_team"),
        ]

    else:
        possible = [
            match.get("awayTeam"),
            match.get("away"),
            match.get("away_team"),
        ]

    for item in possible:

        if isinstance(item, dict):
            return item

    return None


def get_match_team_name(match, side):

    team = get_team_from_match(match, side)

    if isinstance(team, dict):
        return (
            team.get("name")
            or team.get("teamName")
            or ""
        )

    if isinstance(team, str):
        return team

    if side == "home":
        return str(
            match.get("homeTeamName")
            or match.get("home")
            or ""
        )

    return str(
        match.get("awayTeamName")
        or match.get("away")
        or ""
    )


def get_score(match, side):

    # score.home / score.away
    score = match.get("score")

    if isinstance(score, dict):

        value = score.get(side)

        if isinstance(value, dict):
            for key in [
                "current",
                "goals",
                "total",
                "score"
            ]:
                if value.get(key) is not None:
                    return value.get(key)

        if isinstance(value, (int, float)):
            return value

    # goals.home / goals.away
    goals = match.get("goals")

    if isinstance(goals, dict):

        value = goals.get(side)

        if isinstance(value, (int, float)):
            return value

        if isinstance(value, dict):

            for key in [
                "current",
                "total",
                "score"
            ]:
                if value.get(key) is not None:
                    return value.get(key)

    # homeScore / awayScore
    direct_key = (
        "homeScore"
        if side == "home"
        else "awayScore"
    )

    if match.get(direct_key) is not None:
        return match.get(direct_key)

    return None


def is_finished_openfoot(match):

    status = str(
        match.get("status")
        or match.get("state")
        or ""
    ).lower()

    finished_words = [
        "finished",
        "complete",
        "completed",
        "closed",
        "ft",
        "final"
    ]

    return any(word in status for word in finished_words)


def get_match_date(match):

    for key in [
        "kickoffAt",
        "kickoff",
        "date",
        "startTime",
        "scheduledAt"
    ]:

        if match.get(key):
            return str(match[key])

    return ""


# ============================================================
# CURRENT FORM
# ============================================================

def calculate_current_form(matches, team_id):

    finished = []

    for match in matches:

        if not is_finished_openfoot(match):
            continue

        home = get_team_from_match(match, "home")
        away = get_team_from_match(match, "away")

        if not home or not away:
            continue

        home_id = str(home.get("id", ""))
        away_id = str(away.get("id", ""))

        if str(team_id) not in [home_id, away_id]:
            continue

        home_goals = get_score(match, "home")
        away_goals = get_score(match, "away")

        if home_goals is None or away_goals is None:
            continue

        try:

            home_goals = int(home_goals)
            away_goals = int(away_goals)

        except:
            continue

        if home_id == str(team_id):

            scored = home_goals
            conceded = away_goals

        else:

            scored = away_goals
            conceded = home_goals

        if scored > conceded:
            result = "W"

        elif scored == conceded:
            result = "D"

        else:
            result = "L"

        finished.append({
            "result": result,
            "scored": scored,
            "conceded": conceded,
            "date": get_match_date(match)
        })

    finished.sort(
        key=lambda x: x["date"],
        reverse=True
    )

    return finished[:5]


def form_summary(form):

    wins = sum(1 for x in form if x["result"] == "W")
    draws = sum(1 for x in form if x["result"] == "D")
    losses = sum(1 for x in form if x["result"] == "L")

    return wins, draws, losses


def average_goals(form):

    if not form:
        return 0, 0

    scored = sum(x["scored"] for x in form)
    conceded = sum(x["conceded"] for x in form)

    return (
        scored / len(form),
        conceded / len(form)
    )


# ============================================================
# HISTORICAL API-FOOTBALL FALLBACK
# ============================================================

def find_team_historical(name):

    data = api_football_get(
        "/teams",
        {
            "search": name
        }
    )

    if not data:
        return None

    teams = data.get("response", [])

    if not teams:
        return None

    search = name.lower().strip()

    for item in teams:

        team = item.get("team", {})

        team_name = str(
            team.get("name", "")
        ).lower()

        if team_name == search:
            return team

    return teams[0].get("team")


def get_historical_fixtures(team_id):

    data = api_football_get(
        "/fixtures",
        {
            "team": team_id,
            "season": HISTORICAL_SEASON
        }
    )

    if not data:
        return []

    return data.get("response", [])


# ============================================================
# ANALYSIS
# ============================================================

def analyze_current_match(home_team, away_team):

    home = search_openfoot_team(home_team)
    away = search_openfoot_team(away_team)

    if not home:
        return f"❌ I couldn't find {home_team}."

    if not away:
        return f"❌ I couldn't find {away_team}."

    home_id = home.get("id")
    away_id = away.get("id")

    home_name = get_object_name(home) or home_team
    away_name = get_object_name(away) or away_team

    home_matches = get_team_matches_openfoot(home_id)
    away_matches = get_team_matches_openfoot(away_id)

    home_form = calculate_current_form(
        home_matches,
        home_id
    )

    away_form = calculate_current_form(
        away_matches,
        away_id
    )

    hw, hd, hl = form_summary(home_form)
    aw, ad, al = form_summary(away_form)

    home_scored, home_conceded = average_goals(home_form)
    away_scored, away_conceded = average_goals(away_form)

    total_home_goals = home_scored + away_conceded
    total_away_goals = away_scored + home_conceded

    signals = []

    # Over 1.5
    if total_home_goals + total_away_goals >= 2.5:
        over15 = 80
    elif total_home_goals + total_away_goals >= 2:
        over15 = 70
    else:
        over15 = 55

    signals.append(
        ("Over 1.5", over15)
    )

    # Over 2.5
    average_total = (
        home_scored
        + home_conceded
        + away_scored
        + away_conceded
    )

    if average_total >= 3:
        over25 = 75
    elif average_total >= 2.5:
        over25 = 65
    else:
        over25 = 50

    signals.append(
        ("Over 2.5", over25)
    )

    # Under 4.5
    if average_total <= 3.5:
        under45 = 85
    elif average_total <= 4:
        under45 = 75
    else:
        under45 = 60

    signals.append(
        ("Under 4.5", under45)
    )

    # BTTS
    if (
        home_scored >= 1
        and away_scored >= 1
    ):
        btts = 75
    elif (
        home_scored >= 0.8
        and away_scored >= 0.8
    ):
        btts = 65
    else:
        btts = 50

    signals.append(
        ("BTTS", btts)
    )

    # Home / Away win signal
    home_strength = hw * 2 + home_scored * 10
    away_strength = aw * 2 + away_scored * 10

    if home_strength > away_strength + 10:
        home_win = 70
    elif home_strength > away_strength:
        home_win = 60
    else:
        home_win = 50

    signals.append(
        ("Home Win", home_win)
    )

    signals.sort(
        key=lambda x: x[1],
        reverse=True
    )

    top_market, top_score = signals[0]

    lines = []

    lines.append(
        f"⚽ {home_name} vs {away_name}"
    )

    lines.append(
        f"📅 Current season: {CURRENT_SEASON}"
    )

    lines.append("")

    lines.append("📊 CURRENT FORM")

    lines.append(
        f"🏠 {home_name}: {hw}W {hd}D {hl}L"
    )

    lines.append(
        f"✈️ {away_name}: {aw}W {ad}D {al}L"
    )

    lines.append("")

    lines.append("⚽ GOAL AVERAGES")

    lines.append(
        f"{home_name}: "
        f"{home_scored:.2f} scored / "
        f"{home_conceded:.2f} conceded"
    )

    lines.append(
        f"{away_name}: "
        f"{away_scored:.2f} scored / "
        f"{away_conceded:.2f} conceded"
    )

    lines.append("")

    lines.append("📈 CURRENT MARKET SIGNALS")

    for market, score in signals:
        lines.append(
            f"• {market}: {score}%"
        )

    lines.append("")

    lines.append("🤖 TOP CURRENT SIGNAL")

    lines.append(
        f"🔥 {top_market} — {top_score}%"
    )

    lines.append("")

    lines.append(
        "ℹ️ These are historical/form-based "
        "signals from available current-season "
        "results. They are not guaranteed "
        "probabilities or predictions."
    )

    return "\n".join(lines)


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 GoalLogic AI is online!\n\n"
        "Send me a match like:\n\n"
        "Chelsea vs Arsenal\n\n"
        "I will analyze the current season "
        "using available football data."
    )


async def apitest(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if OPENFOOT_API_KEY:

        response = openfoot_get(
            "/v1/search",
            {"q": "Arsenal"}
        )

        if response is not None:

            await update.message.reply_text(
                "✅ OpenFoot API is connected.\n\n"
                "I can access the OpenFoot search endpoint."
            )

            return

    await update.message.reply_text(
        "❌ OpenFoot API could not be reached.\n\n"
        "Check OPENFOOT_API_KEY in Render."
    )


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = " ".join(context.args)

    if " vs " not in text.lower():
        await update.message.reply_text(
            "Use this format:\n\n"
            "/analyze Chelsea vs Arsenal"
        )
        return

    parts = text.split(" vs ")

    if len(parts) != 2:
        parts = text.split(" VS ")

    if len(parts) != 2:
        await update.message.reply_text(
            "Please use:\n\n"
            "Chelsea vs Arsenal"
        )
        return

    home = parts[0].strip()
    away = parts[1].strip()

    await update.message.reply_text(
        "🔎 Searching current football data..."
    )

    result = analyze_current_match(
        home,
        away
    )

    await update.message.reply_text(result)


# ============================================================
# NORMAL MATCH MESSAGE
# ============================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = update.message.text.strip()

    lower = text.lower()

    if " vs " not in lower:
        await update.message.reply_text(
            "Send a match like:\n\n"
            "Chelsea vs Arsenal"
        )
        return

    parts = text.split(" vs ")

    if len(parts) != 2:

        parts = text.split(" VS ")

    if len(parts) != 2:

        # Case-insensitive fallback
        index = lower.find(" vs ")

        if index == -1:
            await update.message.reply_text(
                "Please use:\n\n"
                "Chelsea vs Arsenal"
            )
            return

        home = text[:index].strip()
        away = text[index + 4:].strip()

    else:

        home = parts[0].strip()
        away = parts[1].strip()

    await update.message.reply_text(
        "🔎 Searching current 2026/27 data..."
    )

    result = analyze_current_match(
        home,
        away
    )

    await update.message.reply_text(result)


# ============================================================
# MAIN
# ============================================================

def main():

    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is missing.")
        return

    print("Starting GoalLogic AI...")

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
        CommandHandler("apitest", apitest)
    )

    application.add_handler(
        CommandHandler("analyze", analyze_command)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("🤖 GoalLogic AI is running.")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
