import os
import threading
import http.server
import statistics
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
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY")

API_BASE = "https://v3.football.api-sports.io"

FIXTURE_SEASON = 2024
SAMPLE_SIZE = 5


# =========================================================
# RENDER HEALTH SERVER
# =========================================================

class HealthHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = http.server.HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


threading.Thread(
    target=start_health_server,
    daemon=True
).start()


# =========================================================
# API HELPER
# =========================================================

def api_get(endpoint, params=None):

    if not FOOTBALL_API_KEY:
        return None

    headers = {
        "x-apisports-key": FOOTBALL_API_KEY
    }

    try:
        response = httpx.get(
            API_BASE + endpoint,
            headers=headers,
            params=params,
            timeout=30
        )

        if response.status_code != 200:
            print("API ERROR:", response.status_code)
            print(response.text)
            return None

        data = response.json()

        if data.get("errors"):
            print("API ERRORS:", data["errors"])
            return None

        return data

    except Exception as e:
        print("API EXCEPTION:", e)
        return None


# =========================================================
# TEAM SEARCH
# =========================================================

def find_team(team_name):

    data = api_get(
        "/teams",
        {
            "search": team_name
        }
    )

    if not data:
        return None

    teams = data.get("response", [])

    if not teams:
        return None

    return teams[0]


# =========================================================
# GET TEAM FIXTURES
# =========================================================

def get_team_fixtures(team_id):

    data = api_get(
        "/fixtures",
        {
            "team": team_id,
            "season": FIXTURE_SEASON
        }
    )

    if not data:
        return []

    return data.get("response", [])


# =========================================================
# CALCULATE GOAL STATS
# =========================================================

def calculate_stats(fixtures, team_id):

    if not fixtures:
        return {
            "games": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "avg_goals": 0,
            "avg_conceded": 0,
            "over_1_5": 0,
            "over_2_5": 0,
            "btts": 0,
            "scored": 0,
            "clean_sheets": 0
        }

    wins = 0
    draws = 0
    losses = 0

    goals_for = 0
    goals_against = 0

    over_1_5 = 0
    over_2_5 = 0
    btts = 0
    scored = 0
    clean_sheets = 0

    valid_games = 0

    for fixture in fixtures:

        home_id = fixture["teams"]["home"]["id"]
        away_id = fixture["teams"]["away"]["id"]

        home_goals = fixture["goals"]["home"]
        away_goals = fixture["goals"]["away"]

        if home_goals is None or away_goals is None:
            continue

        valid_games += 1

        if team_id == home_id:

            gf = home_goals
            ga = away_goals

            if gf > ga:
                wins += 1
            elif gf == ga:
                draws += 1
            else:
                losses += 1

        else:

            gf = away_goals
            ga = home_goals

            if gf > ga:
                wins += 1
            elif gf == ga:
                draws += 1
            else:
                losses += 1

        goals_for += gf
        goals_against += ga

        total_goals = home_goals + away_goals

        if total_goals >= 2:
            over_1_5 += 1

        if total_goals >= 3:
            over_2_5 += 1

        if home_goals > 0 and away_goals > 0:
            btts += 1

        if gf > 0:
            scored += 1

        if ga == 0:
            clean_sheets += 1

    if valid_games == 0:
        return {
            "games": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "avg_goals": 0,
            "avg_conceded": 0,
            "over_1_5": 0,
            "over_2_5": 0,
            "btts": 0,
            "scored": 0,
            "clean_sheets": 0
        }

    return {
        "games": valid_games,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,

        "avg_goals": round(
            goals_for / valid_games,
            2
        ),

        "avg_conceded": round(
            goals_against / valid_games,
            2
        ),

        "over_1_5": round(
            over_1_5 / valid_games * 100
        ),

        "over_2_5": round(
            over_2_5 / valid_games * 100
        ),

        "btts": round(
            btts / valid_games * 100
        ),

        "scored": round(
            scored / valid_games * 100
        ),

        "clean_sheets": round(
            clean_sheets / valid_games * 100
        )
    }


# =========================================================
# HOME / AWAY FILTERS
# =========================================================

def get_home_fixtures(fixtures, team_id):

    result = []

    for fixture in fixtures:

        if fixture["teams"]["home"]["id"] == team_id:
            result.append(fixture)

    return result


def get_away_fixtures(fixtures, team_id):

    result = []

    for fixture in fixtures:

        if fixture["teams"]["away"]["id"] == team_id:
            result.append(fixture)

    return result


# =========================================================
# MATCH STATISTICS
# =========================================================

def collect_team_match_stats(fixtures, team_id):

    shots = []
    shots_on_target = []
    corners = []
    yellow_cards = []

    for fixture in fixtures:

        fixture_id = fixture["fixture"]["id"]

        data = api_get(
            "/fixtures/statistics",
            {
                "fixture": fixture_id
            }
        )

        if not data:
            continue

        responses = data.get("response", [])

        for team_data in responses:

            current_team_id = team_data["team"]["id"]

            if current_team_id != team_id:
                continue

            stats = team_data.get("statistics", [])

            for item in stats:

                name = item.get("type")
                value = item.get("value")

                if value is None:
                    continue

                if isinstance(value, str):
                    value = value.replace("%", "")

                try:
                    value = float(value)
                except:
                    continue

                if name == "Total Shots":
                    shots.append(value)

                elif name == "Shots on Goal":
                    shots_on_target.append(value)

                elif name == "Corner Kicks":
                    corners.append(value)

                elif name == "Yellow Cards":
                    yellow_cards.append(value)

    return {
        "shots": round(statistics.mean(shots), 1) if shots else 0,
        "shots_on_target": round(
            statistics.mean(shots_on_target), 1
        ) if shots_on_target else 0,
        "corners": round(
            statistics.mean(corners), 1
        ) if corners else 0,
        "yellow_cards": round(
            statistics.mean(yellow_cards), 1
        ) if yellow_cards else 0
    }


# =========================================================
# EVIDENCE QUALITY
# =========================================================

def evidence_quality(rate, sample_size):

    if sample_size <= 2:
        return "VERY LIMITED SAMPLE"

    if sample_size == 3:

        if rate >= 80:
            return "LIMITED — HIGH RATE"

        if rate >= 60:
            return "LIMITED"

        return "LIMITED — LOW RATE"

    if sample_size == 4:

        if rate >= 80:
            return "MODERATE — HIGH RATE"

        if rate >= 60:
            return "MODERATE"

        return "MODERATE — LOW RATE"

    if sample_size >= 5:

        if rate >= 80:
            return "GOOD HISTORICAL SUPPORT"

        if rate >= 60:
            return "MODERATE HISTORICAL SUPPORT"

        return "LOW HISTORICAL SUPPORT"

    return "LIMITED"


# =========================================================
# MARKET ANALYSIS
# =========================================================

def calculate_market_analysis(home_stats, away_stats):

    over_1_5 = round(
        (
            home_stats["over_1_5"]
            + away_stats["over_1_5"]
        ) / 2
    )

    over_2_5 = round(
        (
            home_stats["over_2_5"]
            + away_stats["over_2_5"]
        ) / 2
    )

    btts = round(
        (
            home_stats["btts"]
            + away_stats["btts"]
        ) / 2
    )

    home_to_score = home_stats["scored"]
    away_to_score = away_stats["scored"]

    return {
        "over_1_5": over_1_5,
        "over_2_5": over_2_5,
        "btts": btts,
        "home_to_score": home_to_score,
        "away_to_score": away_to_score
    }


# =========================================================
# NEW MULTI-FACTOR SIGNAL ENGINE
# =========================================================

def calculate_signal_score(
    market,
    home_stats,
    away_stats,
    home_home_stats,
    away_away_stats,
    home_stat_data,
    away_stat_data
):

    score = 0
    support = []
    caution = []

    # -----------------------------------------------------
    # HOME TEAM TO SCORE
    # -----------------------------------------------------

    if market == "home_to_score":

        if home_home_stats["scored"] >= 80:
            score += 2
            support.append(
                "Home team scored in at least 4/5 home matches"
            )

        elif home_home_stats["scored"] >= 60:
            score += 1
            support.append(
                "Home team scored in most home matches"
            )

        else:
            score -= 2
            caution.append(
                "Home team scoring rate is below 60%"
            )

        if away_away_stats["scored"] >= 80:
            score += 2
            support.append(
                "Away opponent usually scores, indicating an open profile"
            )

        if away_away_stats["avg_conceded"] >= 1.2:
            score += 2
            support.append(
                "Opponent concedes 1.2+ goals per away match"
            )

        elif away_away_stats["avg_conceded"] < 0.8:
            score -= 1
            caution.append(
                "Opponent has a relatively low away goals-conceded average"
            )

        if home_home_stats["avg_goals"] >= 1.5:
            score += 1
            support.append(
                "Home team averages at least 1.5 goals at home"
            )

        elif home_home_stats["avg_goals"] < 1.0:
            score -= 1
            caution.append(
                "Home team averages below 1.0 goal at home"
            )

        if home_stat_data["shots_on_target"] >= 5:
            score += 1
            support.append(
                "Home team averages 5+ shots on target"
            )

    # -----------------------------------------------------
    # AWAY TEAM TO SCORE
    # -----------------------------------------------------

    elif market == "away_to_score":

        if away_away_stats["scored"] >= 80:
            score += 2
            support.append(
                "Away team scored in at least 4/5 away matches"
            )

        elif away_away_stats["scored"] >= 60:
            score += 1
            support.append(
                "Away team scored in most away matches"
            )

        else:
            score -= 2
            caution.append(
                "Away team scoring rate is below 60%"
            )

        if home_home_stats["avg_conceded"] >= 1.2:
            score += 2
            support.append(
                "Home opponent concedes 1.2+ goals per home match"
            )

        elif home_home_stats["avg_conceded"] < 0.8:
            score -= 1
            caution.append(
                "Home opponent has a relatively low goals-conceded average"
            )

        if away_away_stats["avg_goals"] >= 1.5:
            score += 1
            support.append(
                "Away team averages at least 1.5 goals away"
            )

        elif away_away_stats["avg_goals"] < 1.0:
            score -= 1
            caution.append(
                "Away team averages below 1.0 goal away"
            )

        if away_stat_data["shots_on_target"] >= 5:
            score += 1
            support.append(
                "Away team averages 5+ shots on target"
            )

    # -----------------------------------------------------
    # OVER 1.5
    # -----------------------------------------------------

    elif market == "over_1_5":

        if home_home_stats["over_1_5"] >= 80:
            score += 2
            support.append(
                "Home team's home matches frequently clear 1.5 goals"
            )

        elif home_home_stats["over_1_5"] >= 60:
            score += 1
            support.append(
                "Home team's home matches often clear 1.5 goals"
            )

        else:
            score -= 1
            caution.append(
                "Home 1.5-goal rate is below 60%"
            )

        if away_away_stats["over_1_5"] >= 80:
            score += 2
            support.append(
                "Away team's away matches frequently clear 1.5 goals"
            )

        elif away_away_stats["over_1_5"] >= 60:
            score += 1
            support.append(
                "Away team's away matches often clear 1.5 goals"
            )

        else:
            score -= 1
            caution.append(
                "Away 1.5-goal rate is below 60%"
            )

        combined_goals = (
            home_home_stats["avg_goals"]
            + home_home_stats["avg_conceded"]
            + away_away_stats["avg_goals"]
            + away_away_stats["avg_conceded"]
        ) / 2

        if combined_goals >= 2.5:
            score += 2
            support.append(
                "Combined scoring environment is 2.5+ goals per match"
            )

        elif combined_goals < 1.8:
            score -= 1
            caution.append(
                "Combined scoring environment is relatively low"
            )

    # -----------------------------------------------------
    # OVER 2.5
    # -----------------------------------------------------

    elif market == "over_2_5":

        if home_home_stats["over_2_5"] >= 80:
            score += 2
            support.append(
                "Home team's home Over 2.5 rate is 80%+"
            )

        elif home_home_stats["over_2_5"] >= 60:
            score += 1
            support.append(
                "Home team's home Over 2.5 rate is 60%+"
            )

        else:
            caution.append(
                "Home Over 2.5 rate is below 60%"
            )

        if away_away_stats["over_2_5"] >= 80:
            score += 2
            support.append(
                "Away team's away Over 2.5 rate is 80%+"
            )

        elif away_away_stats["over_2_5"] >= 60:
            score += 1
            support.append(
                "Away team's away Over 2.5 rate is 60%+"
            )

        else:
            caution.append(
                "Away Over 2.5 rate is below 60%"
            )

        combined_goals = (
            home_home_stats["avg_goals"]
            + home_home_stats["avg_conceded"]
            + away_away_stats["avg_goals"]
            + away_away_stats["avg_conceded"]
        ) / 2

        if combined_goals >= 3.0:
            score += 2
            support.append(
                "Combined scoring environment is 3.0+ goals per match"
            )

        elif combined_goals >= 2.5:
            score += 1
            support.append(
                "Combined scoring environment is 2.5+ goals per match"
            )

        else:
            score -= 1
            caution.append(
                "Combined scoring environment is below 2.5 goals"
            )

        if home_stat_data["shots_on_target"] >= 5:
            score += 1
            support.append(
                "Home team produces 5+ shots on target"
            )

        if away_stat_data["shots_on_target"] >= 5:
            score += 1
            support.append(
                "Away team produces 5+ shots on target"
            )

    # -----------------------------------------------------
    # BTTS
    # -----------------------------------------------------

    elif market == "btts":

        if home_home_stats["scored"] >= 80:
            score += 2
            support.append(
                "Home team scored in at least 4/5 home matches"
            )

        elif home_home_stats["scored"] >= 60:
            score += 1
            support.append(
                "Home team scored in most home matches"
            )

        else:
            score -= 2
            caution.append(
                "Home team scoring rate is below 60%"
            )

        if away_away_stats["scored"] >= 80:
            score += 2
            support.append(
                "Away team scored in at least 4/5 away matches"
            )

        elif away_away_stats["scored"] >= 60:
            score += 1
            support.append(
                "Away team scored in most away matches"
            )

        else:
            score -= 2
            caution.append(
                "Away team scoring rate is below 60%"
            )

        if home_home_stats["btts"] >= 80:
            score += 1
            support.append(
                "Home team's home BTTS rate is 80%+"
            )

        if away_away_stats["btts"] >= 80:
            score += 1
            support.append(
                "Away team's away BTTS rate is 80%+"
            )

        if home_home_stats["avg_goals"] >= 1.3:
            score += 1
            support.append(
                "Home team has a healthy home scoring average"
            )

        if away_away_stats["avg_goals"] >= 1.3:
            score += 1
            support.append(
                "Away team has a healthy away scoring average"
            )

    # Keep score inside a readable range.
    if score < 0:
        score = 0

    if score > 10:
        score = 10

    return {
        "score": score,
        "support": support,
        "caution": caution
    }


# =========================================================
# ANALYZE MATCH
# =========================================================

def analyze_match(home_name, away_name):

    home_team = find_team(home_name)
    away_team = find_team(away_name)

    if not home_team or not away_team:
        return None, "One or both teams could not be found."

    home_id = home_team["team"]["id"]
    away_id = away_team["team"]["id"]

    home_fixtures = get_team_fixtures(home_id)
    away_fixtures = get_team_fixtures(away_id)

    if not home_fixtures or not away_fixtures:
        return None, "Football data could not be retrieved."

    home_fixtures = sorted(
        home_fixtures,
        key=lambda x: x["fixture"]["timestamp"],
        reverse=True
    )[:SAMPLE_SIZE]

    away_fixtures = sorted(
        away_fixtures,
        key=lambda x: x["fixture"]["timestamp"],
        reverse=True
    )[:SAMPLE_SIZE]

    home_stats = calculate_stats(
        home_fixtures,
        home_id
    )

    away_stats = calculate_stats(
        away_fixtures,
        away_id
    )

    home_home_fixtures = get_home_fixtures(
        home_fixtures,
        home_id
    )

    away_away_fixtures = get_away_fixtures(
        away_fixtures,
        away_id
    )

    home_home_stats = calculate_stats(
        home_home_fixtures,
        home_id
    )

    away_away_stats = calculate_stats(
        away_away_fixtures,
        away_id
    )

    home_stat_data = collect_team_match_stats(
        home_home_fixtures,
        home_id
    )

    away_stat_data = collect_team_match_stats(
        away_away_fixtures,
        away_id
    )

    markets = calculate_market_analysis(
        home_stats,
        away_stats
    )

    # -----------------------------------------------------
    # SIGNALS
    # -----------------------------------------------------

    signal_data = {}

    signal_data["home_to_score"] = calculate_signal_score(
        "home_to_score",
        home_stats,
        away_stats,
        home_home_stats,
        away_away_stats,
        home_stat_data,
        away_stat_data
    )

    signal_data["away_to_score"] = calculate_signal_score(
        "away_to_score",
        home_stats,
        away_stats,
        home_home_stats,
        away_away_stats,
        home_stat_data,
        away_stat_data
    )

    signal_data["over_1_5"] = calculate_signal_score(
        "over_1_5",
        home_stats,
        away_stats,
        home_home_stats,
        away_away_stats,
        home_stat_data,
        away_stat_data
    )

    signal_data["over_2_5"] = calculate_signal_score(
        "over_2_5",
        home_stats,
        away_stats,
        home_home_stats,
        away_away_stats,
        home_stat_data,
        away_stat_data
    )

    signal_data["btts"] = calculate_signal_score(
        "btts",
        home_stats,
        away_stats,
        home_home_stats,
        away_away_stats,
        home_stat_data,
        away_stat_data
    )

    market_names = {
        "home_to_score": home_team["team"]["name"] + " to score",
        "away_to_score": away_team["team"]["name"] + " to score",
        "over_1_5": "Over 1.5 goals",
        "over_2_5": "Over 2.5 goals",
        "btts": "BTTS"
    }

    market_rates = {
        "home_to_score": markets["home_to_score"],
        "away_to_score": markets["away_to_score"],
        "over_1_5": markets["over_1_5"],
        "over_2_5": markets["over_2_5"],
        "btts": markets["btts"]
    }

    # -----------------------------------------------------
    # SORT SIGNALS
    # -----------------------------------------------------

    sorted_markets = sorted(
        signal_data.keys(),
        key=lambda x: signal_data[x]["score"],
        reverse=True
    )

    top_market = sorted_markets[0]

    return {
        "home_name": home_team["team"]["name"],
        "away_name": away_team["team"]["name"],

        "home_stats": home_stats,
        "away_stats": away_stats,

        "home_home_stats": home_home_stats,
        "away_away_stats": away_away_stats,

        "home_stat_data": home_stat_data,
        "away_stat_data": away_stat_data,

        "markets": markets,
        "signal_data": signal_data,
        "market_names": market_names,
        "market_rates": market_rates,

        "sorted_markets": sorted_markets,
        "top_market": top_market
    }, None


# =========================================================
# START COMMAND
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = """
⚽ Welcome to GoalLogic AI!

I analyze football matches using historical statistics.

Commands:

/team Chelsea
/fixtures Chelsea
/analyze Chelsea vs Arsenal
/apitest

⚠️ Current API plan provides historical 2024 data.
"""

    await update.message.reply_text(message)


# =========================================================
# API TEST
# =========================================================

async def api_test(update: Update, context: ContextTypes.DEFAULT_TYPE):

    data = api_get(
        "/status"
    )

    if data:
        await update.message.reply_text(
            "✅ FOOTBALL API CONNECTION WORKING"
        )
    else:
        await update.message.reply_text(
            "❌ Football API connection failed."
        )


# =========================================================
# TEAM COMMAND
# =========================================================

async def team_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/team Chelsea"
        )

        return

    team_name = " ".join(context.args)

    team = find_team(team_name)

    if not team:

        await update.message.reply_text(
            "❌ Team not found."
        )

        return

    team_info = team["team"]

    message = (
        "⚽ TEAM FOUND\n\n"
        "🏟️ "
        + team_info["name"]
        + "\n"
        "🌍 "
        + team_info.get("country", "Unknown")
    )

    await update.message.reply_text(message)


# =========================================================
# FIXTURES COMMAND
# =========================================================

async def fixtures_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/fixtures Chelsea"
        )

        return

    team_name = " ".join(context.args)

    team = find_team(team_name)

    if not team:

        await update.message.reply_text(
            "❌ Team not found."
        )

        return

    team_id = team["team"]["id"]

    fixtures = get_team_fixtures(team_id)

    fixtures = sorted(
        fixtures,
        key=lambda x: x["fixture"]["timestamp"],
        reverse=True
    )[:5]

    if not fixtures:

        await update.message.reply_text(
            "❌ No fixtures found."
        )

        return

    message = (
        "📅 "
        + team["team"]["name"]
        + " — LAST 5 FIXTURES\n\n"
    )

    for fixture in fixtures:

        home = fixture["teams"]["home"]["name"]
        away = fixture["teams"]["away"]["name"]

        home_goals = fixture["goals"]["home"]
        away_goals = fixture["goals"]["away"]

        message += (
            "⚽ "
            + home
            + " "
            + str(home_goals)
            + "-"
            + str(away_goals)
            + " "
            + away
            + "\n"
        )

    message += (
        "\n📊 Data season: "
        + str(FIXTURE_SEASON)
    )

    await update.message.reply_text(message)


# =========================================================
# ANALYZE COMMAND
# =========================================================

async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use:\n/analyze Chelsea vs Arsenal"
        )

        return

    text_input = " ".join(context.args)

    parts = text_input.split(" vs ")

    if len(parts) != 2:

        await update.message.reply_text(
            "Please use this format:\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    home_name = parts[0].strip()
    away_name = parts[1].strip()

    await update.message.reply_text(
        "🔎 Analyzing historical data...\n"
        "Please wait."
    )

    result, error = analyze_match(
        home_name,
        away_name
    )

    if error:

        await update.message.reply_text(
            "❌ " + error
        )

        return

    home = result["home_stats"]
    away = result["away_stats"]

    home_home = result["home_home_stats"]
    away_away = result["away_away_stats"]

    home_stat = result["home_stat_data"]
    away_stat = result["away_stat_data"]

    markets = result["markets"]

    signal_data = result["signal_data"]
    market_names = result["market_names"]
    market_rates = result["market_rates"]

    sorted_markets = result["sorted_markets"]
    top_market = result["top_market"]

    # Evidence labels
    home_score_evidence = evidence_quality(
        markets["home_to_score"],
        home_home["games"]
    )

    away_score_evidence = evidence_quality(
        markets["away_to_score"],
        away_away["games"]
    )

    over15_evidence = evidence_quality(
        markets["over_1_5"],
        min(
            home_home["games"],
            away_away["games"]
        )
    )

    over25_evidence = evidence_quality(
        markets["over_2_5"],
        min(
            home_home["games"],
            away_away["games"]
        )
    )

    btts_evidence = evidence_quality(
        markets["btts"],
        min(
            home_home["games"],
            away_away["games"]
        )
    )

    evidence_labels = {
        "home_to_score": home_score_evidence,
        "away_to_score": away_score_evidence,
        "over_1_5": over15_evidence,
        "over_2_5": over25_evidence,
        "btts": btts_evidence
    }

    # -----------------------------------------------------
    # BUILD MESSAGE
    # -----------------------------------------------------

    message = (
        "⚽ GOALLOGIC AI ANALYSIS\n\n"
        "🏟️ "
        + result["home_name"]
        + " vs "
        + result["away_name"]
        + "\n\n"

        "📊 DATA PERIOD\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Season: "
        + str(FIXTURE_SEASON)
        + "\n"
        "Sample: Last "
        + str(SAMPLE_SIZE)
        + " available matches\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "📈 RECENT FORM\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🏠 "
        + result["home_name"]
        + "\n"
        "✅ Wins: "
        + str(home["wins"])
        + "\n"
        "🤝 Draws: "
        + str(home["draws"])
        + "\n"
        "❌ Losses: "
        + str(home["losses"])
        + "\n"
        "⚽ Avg goals: "
        + str(home["avg_goals"])
        + "\n"
        "🥅 Avg conceded: "
        + str(home["avg_conceded"])
        + "\n"
        "🔥 Over 2.5: "
        + str(home["over_2_5"])
        + "%\n"
        "🎯 BTTS: "
        + str(home["btts"])
        + "%\n\n"

        "✈️ "
        + result["away_name"]
        + "\n"
        "✅ Wins: "
        + str(away["wins"])
        + "\n"
        "🤝 Draws: "
        + str(away["draws"])
        + "\n"
        "❌ Losses: "
        + str(away["losses"])
        + "\n"
        "⚽ Avg goals: "
        + str(away["avg_goals"])
        + "\n"
        "🥅 Avg conceded: "
        + str(away["avg_conceded"])
        + "\n"
        "🔥 Over 2.5: "
        + str(away["over_2_5"])
        + "%\n"
        "🎯 BTTS: "
        + str(away["btts"])
        + "%\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🏠 HOME / AWAY\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🏠 "
        + result["home_name"]
        + " HOME\n"
        "Games: "
        + str(home_home["games"])
        + "\n"
        "⚽ Avg scored: "
        + str(home_home["avg_goals"])
        + "\n"
        "🥅 Avg conceded: "
        + str(home_home["avg_conceded"])
        + "\n"
        "🔥 Over 2.5: "
        + str(home_home["over_2_5"])
        + "%\n"
        "🎯 BTTS: "
        + str(home_home["btts"])
        + "%\n\n"

        "✈️ "
        + result["away_name"]
        + " AWAY\n"
        "Games: "
        + str(away_away["games"])
        + "\n"
        "⚽ Avg scored: "
        + str(away_away["avg_goals"])
        + "\n"
        "🥅 Avg conceded: "
        + str(away_away["avg_conceded"])
        + "\n"
        "🔥 Over 2.5: "
        + str(away_away["over_2_5"])
        + "%\n"
        "🎯 BTTS: "
        + str(away_away["btts"])
        + "%\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 MATCH STATISTICS\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "🏠 "
        + result["home_name"]
        + "\n"
        "🎯 Shots: "
        + str(home_stat["shots"])
        + "\n"
        "🎯 Shots on target: "
        + str(home_stat["shots_on_target"])
        + "\n"
        "🚩 Corners: "
        + str(home_stat["corners"])
        + "\n"
        "🟨 Yellow cards: "
        + str(home_stat["yellow_cards"])
        + "\n\n"

        "✈️ "
        + result["away_name"]
        + "\n"
        "🎯 Shots: "
        + str(away_stat["shots"])
        + "\n"
        "🎯 Shots on target: "
        + str(away_stat["shots_on_target"])
        + "\n"
        "🚩 Corners: "
        + str(away_stat["corners"])
        + "\n"
        "🟨 Yellow cards: "
        + str(away_stat["yellow_cards"])
        + "\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "📊 MARKET ANALYSIS\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "⚽ Over 1.5 goals: "
        + str(markets["over_1_5"])
        + "%\n"
        "   Historical record based on selected sample\n"
        "   Evidence: "
        + over15_evidence
        + "\n\n"

        "🔥 Over 2.5 goals: "
        + str(markets["over_2_5"])
        + "%\n"
        "   Historical record based on selected sample\n"
        "   Evidence: "
        + over25_evidence
        + "\n\n"

        "🎯 BTTS: "
        + str(markets["btts"])
        + "%\n"
        "   Historical record based on selected sample\n"
        "   Evidence: "
        + btts_evidence
        + "\n\n"

        "🏠 "
        + result["home_name"]
        + " to score: "
        + str(markets["home_to_score"])
        + "%\n"
        "   Evidence: "
        + home_score_evidence
        + "\n\n"

        "✈️ "
        + result["away_name"]
        + " to score: "
        + str(markets["away_to_score"])
        + "%\n"
        "   Evidence: "
        + away_score_evidence
        + "\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🤖 GOALLOGIC AI SIGNAL ENGINE\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )

    # -----------------------------------------------------
    # TOP 5 SIGNALS
    # -----------------------------------------------------

    for index, market_key in enumerate(sorted_markets):

        signal = signal_data[market_key]

        message += (
            str(index + 1)
            + ". "
            + market_names[market_key]
            + "\n"
            "   🧠 Signal score: "
            + str(signal["score"])
            + "/10\n"
            "   📈 Historical hit rate: "
            + str(market_rates[market_key])
            + "%\n"
            "   📊 Evidence: "
            + evidence_labels[market_key]
            + "\n\n"
        )

    # -----------------------------------------------------
    # PRIMARY SIGNAL
    # -----------------------------------------------------

    top_signal = signal_data[top_market]

    message += (
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 TOP HISTORICAL SIGNAL\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "📌 "
        + market_names[top_market]
        + "\n"
        "🧠 Signal score: "
        + str(top_signal["score"])
        + "/10\n"
        "📈 Historical hit rate: "
        + str(market_rates[top_market])
        + "%\n"
        "📊 Evidence: "
        + evidence_labels[top_market]
        + "\n\n"

        "✅ SUPPORTING FACTORS\n"
    )

    if top_signal["support"]:

        for item in top_signal["support"][:5]:

            message += (
                "• "
                + item
                + "\n"
            )

    else:

        message += (
            "• No strong supporting factor identified.\n"
        )

    message += (
        "\n⚠️ CAUTION FACTORS\n"
    )

    if top_signal["caution"]:

        for item in top_signal["caution"][:5]:

            message += (
                "• "
                + item
                + "\n"
            )

    else:

        message += (
            "• No major caution factor identified.\n"
        )

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "⚠️ DATA NOTICE\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "The percentages are historical hit rates, "
        "not guaranteed probabilities of the next match.\n\n"
        "The signal score is a multi-factor historical "
        "screening score, not a guaranteed prediction.\n\n"
        "Data uses the 2024 season because the current "
        "API plan does not provide the current 2026 fixture season."
    )

    await update.message.reply_text(message)


# =========================================================
# NORMAL TEXT
# =========================================================

async def normal_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "⚽ GoalLogic AI\n\n"
        "Use:\n"
        "/analyze Chelsea vs Arsenal\n\n"
        "Other commands:\n"
        "/team Chelsea\n"
        "/fixtures Chelsea\n"
        "/apitest"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        print("ERROR: TELEGRAM_BOT_TOKEN is missing.")
        return

    if not FOOTBALL_API_KEY:

        print("ERROR: FOOTBALL_API_KEY is missing.")
        return

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
        CommandHandler("team", team_command)
    )

    application.add_handler(
        CommandHandler("fixtures", fixtures_command)
    )

    application.add_handler(
        CommandHandler("analyze", analyze_command)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            normal_message
        )
    )

    print("GoalLogic AI is running.")

    application.run_polling()


if __name__ == "__main__":
    main()
