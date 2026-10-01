import os
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

PORT = int(os.getenv("PORT", "10000"))
OPENFOOT_BASE = "https://openfootapi.com"
CURRENT_SEASON = "2026/27"


# =========================================================
# RENDER HEALTH SERVER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        return


def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"GoalLogic AI is running on port {PORT}.")
    server.serve_forever()


# =========================================================
# OPENFOOT API
# =========================================================

def openfoot_get(endpoint, params=None):

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {OPENFOOT_API_KEY}"
    }

    try:

        response = requests.get(
            OPENFOOT_BASE + endpoint,
            headers=headers,
            params=params,
            timeout=20
        )

        if response.status_code != 200:

            print(
                "OpenFoot error:",
                response.status_code,
                response.text
            )

            return None

        body = response.json()

        return body.get("data")

    except Exception as e:

        print("OpenFoot request error:", e)

        return None


# =========================================================
# SEARCH TEAM
# =========================================================

def search_team(team_name):

    data = openfoot_get(
        "/v1/search",
        {"q": team_name}
    )

    if not data:
        return None

    if isinstance(data, dict):

        results = (
            data.get("teams")
            or data.get("results")
            or data.get("data")
            or []
        )

    else:

        results = data

    # Exact match first
    for item in results:

        if not isinstance(item, dict):
            continue

        team = item.get("team")

        if not isinstance(team, dict):
            team = item

        name = str(
            team.get("name") or ""
        )

        if name.lower() == team_name.lower():

            return team

    # Fallback
    for item in results:

        if not isinstance(item, dict):
            continue

        team = item.get("team")

        if not isinstance(team, dict):
            team = item

        if team.get("id") and team.get("name"):

            return team

    return None


# =========================================================
# TEAM MATCHES
# =========================================================

def get_team_matches(team_id):

    data = openfoot_get(
        "/v1/matches",
        {
            "team": team_id,
            "season": CURRENT_SEASON
        }
    )

    if not data:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        return (
            data.get("matches")
            or data.get("results")
            or data.get("data")
            or []
        )

    return []


# =========================================================
# MATCH HELPERS
# =========================================================

def get_home_team(match):

    value = match.get("homeTeam")

    if isinstance(value, dict):
        return value

    return {}


def get_away_team(match):

    value = match.get("awayTeam")

    if isinstance(value, dict):
        return value

    return {}


def get_status(match):

    return str(
        match.get("status", "")
    ).lower()


def get_score(match):

    score = match.get("score")

    if not isinstance(score, dict):

        return None, None

    home_score = score.get("home")
    away_score = score.get("away")

    if isinstance(home_score, dict):

        home_score = (
            home_score.get("goals")
            or home_score.get("score")
            or home_score.get("current")
        )

    if isinstance(away_score, dict):

        away_score = (
            away_score.get("goals")
            or away_score.get("score")
            or away_score.get("current")
        )

    try:

        return int(home_score), int(away_score)

    except:

        return None, None


def is_finished(match):

    status = get_status(match)

    finished_words = [
        "finished",
        "ft",
        "fulltime",
        "completed",
        "complete"
    ]

    return any(
        word in status
        for word in finished_words
    )


def team_match_result(match, team_id):

    home = get_home_team(match)
    away = get_away_team(match)

    home_id = home.get("id")
    away_id = away.get("id")

    home_score, away_score = get_score(match)

    if home_score is None or away_score is None:
        return None

    if team_id == home_id:

        if home_score > away_score:
            return "W"

        if home_score < away_score:
            return "L"

        return "D"

    if team_id == away_id:

        if away_score > home_score:
            return "W"

        if away_score < home_score:
            return "L"

        return "D"

    return None


# =========================================================
# ANALYZE MATCHES
# =========================================================

def analyze_matches(matches, team_id, limit=5):

    completed = []

    for match in matches:

        if not is_finished(match):
            continue

        result = team_match_result(
            match,
            team_id
        )

        if result is None:
            continue

        home = get_home_team(match)
        away = get_away_team(match)

        home_score, away_score = get_score(match)

        if home_score is None or away_score is None:
            continue

        if team_id == home.get("id"):

            goals_for = home_score
            goals_against = away_score

        else:

            goals_for = away_score
            goals_against = home_score

        completed.append({
            "match": match,
            "result": result,
            "gf": goals_for,
            "ga": goals_against
        })

    completed.sort(
        key=lambda x: x["match"].get(
            "kickoffAt",
            ""
        ),
        reverse=True
    )

    selected = completed[:limit]

    if not selected:
        return None

    wins = sum(
        1 for x in selected
        if x["result"] == "W"
    )

    draws = sum(
        1 for x in selected
        if x["result"] == "D"
    )

    losses = sum(
        1 for x in selected
        if x["result"] == "L"
    )

    goals_for = sum(
        x["gf"] for x in selected
    )

    goals_against = sum(
        x["ga"] for x in selected
    )

    total_goals = [
        x["gf"] + x["ga"]
        for x in selected
    ]

    over15 = sum(
        1 for x in selected
        if x["gf"] + x["ga"] > 1
    )

    over25 = sum(
        1 for x in selected
        if x["gf"] + x["ga"] > 2
    )

    btts = sum(
        1 for x in selected
        if x["gf"] > 0
        and x["ga"] > 0
    )

    clean_sheets = sum(
        1 for x in selected
        if x["ga"] == 0
    )

    scored = sum(
        1 for x in selected
        if x["gf"] > 0
    )

    conceded = sum(
        1 for x in selected
        if x["ga"] > 0
    )

    n = len(selected)

    avg_goals_for = goals_for / n
    avg_goals_against = goals_against / n
    avg_total_goals = sum(total_goals) / n

    return {

        "form":
            "".join(
                x["result"]
                for x in selected
            ),

        "wins": wins,
        "draws": draws,
        "losses": losses,

        "gf": goals_for,
        "ga": goals_against,

        "avg_gf":
            round(avg_goals_for, 2),

        "avg_ga":
            round(avg_goals_against, 2),

        "avg_total":
            round(avg_total_goals, 2),

        "over15":
            round(over15 / n * 100),

        "over25":
            round(over25 / n * 100),

        "btts":
            round(btts / n * 100),

        "clean":
            round(clean_sheets / n * 100),

        "scoring":
            round(scored / n * 100),

        "conceding":
            round(conceded / n * 100),

        "count": n
    }


# =========================================================
# HOME / AWAY
# =========================================================

def analyze_home_away(
    matches,
    team_id,
    venue,
    limit=5
):

    venue_matches = []

    for match in matches:

        home = get_home_team(match)
        away = get_away_team(match)

        if venue == "home":

            if home.get("id") != team_id:
                continue

        elif venue == "away":

            if away.get("id") != team_id:
                continue

        else:

            continue

        if not is_finished(match):
            continue

        venue_matches.append(match)

    return analyze_matches(
        venue_matches,
        team_id,
        limit
    )


# =========================================================
# FORMAT STATISTICS
# =========================================================

def format_stats(stats, title):

    if not stats:

        return f"""
📍 {title}

No recent matches available.
"""

    sample_warning = ""

    if stats["count"] < 4:

        sample_warning = (
            "\n⚠️ Small sample — use caution."
        )

    return f"""
📍 {title}

Form: {stats["form"]}
W/D/L: {stats["wins"]}/{stats["draws"]}/{stats["losses"]}

Goals:
⚽ Scored: {stats["gf"]}
🛡️ Conceded: {stats["ga"]}

Average goals:
⚽ For: {stats["avg_gf"]}
🛡️ Against: {stats["avg_ga"]}
🎯 Total: {stats["avg_total"]}

Over 1.5: {stats["over15"]}%
Over 2.5: {stats["over25"]}%
BTTS: {stats["btts"]}%
Scoring: {stats["scoring"]}%
Clean sheets: {stats["clean"]}%

Sample: {stats["count"]} matches
{sample_warning}
"""


# =========================================================
# GOAL INTELLIGENCE
# =========================================================

def calculate_goal_intelligence(
    team1_overall,
    team2_overall,
    team1_home,
    team2_away
):

    # Attack
    attack_values = [
        team1_overall["avg_gf"],
        team2_overall["avg_gf"]
    ]

    if team1_home:
        attack_values.append(
            team1_home["avg_gf"]
        )

    if team2_away:
        attack_values.append(
            team2_away["avg_gf"]
        )

    average_attack = (
        sum(attack_values)
        / len(attack_values)
    )

    # Defence
    defence_values = [
        team1_overall["avg_ga"],
        team2_overall["avg_ga"]
    ]

    if team1_home:
        defence_values.append(
            team1_home["avg_ga"]
        )

    if team2_away:
        defence_values.append(
            team2_away["avg_ga"]
        )

    average_conceding = (
        sum(defence_values)
        / len(defence_values)
    )

    # Combined expected goal environment
    goal_environment = (
        average_attack
        + average_conceding
    )

    if goal_environment >= 3.2:

        level = "🔥 HIGH"

    elif goal_environment >= 2.5:

        level = "🟢 GOOD"

    elif goal_environment >= 2.0:

        level = "🟡 MODERATE"

    else:

        level = "🔴 LOW"

    return {
        "attack": round(
            average_attack,
            2
        ),

        "conceding": round(
            average_conceding,
            2
        ),

        "environment": round(
            goal_environment,
            2
        ),

        "level": level
    }


# =========================================================
# CONFIDENCE
# =========================================================

def weighted_confidence(
    overall1,
    overall2,
    venue1,
    venue2,
    market
):

    values = []

    if market == "over15":

        keys = ["over15"]

    elif market == "over25":

        keys = ["over25"]

    else:

        keys = ["btts"]

    key = keys[0]

    overall_values = [
        overall1.get(key),
        overall2.get(key)
    ]

    overall_values = [
        x for x in overall_values
        if x is not None
    ]

    venue_values = []

    if venue1:
        venue_values.append(
            venue1.get(key)
        )

    if venue2:
        venue_values.append(
            venue2.get(key)
        )

    venue_values = [
        x for x in venue_values
        if x is not None
    ]

    if not overall_values:
        return None

    overall_average = (
        sum(overall_values)
        / len(overall_values)
    )

    if venue_values:

        venue_average = (
            sum(venue_values)
            / len(venue_values)
        )

    else:

        venue_average = overall_average

    # Balanced weighting
    confidence = (
        overall_average * 0.45
        + venue_average * 0.35
    )

    venue_sample = 0

    if venue1:
        venue_sample += venue1["count"]

    if venue2:
        venue_sample += venue2["count"]

    # Reliability bonus
    if venue_sample >= 8:

        reliability = 20

    elif venue_sample >= 6:

        reliability = 15

    elif venue_sample >= 4:

        reliability = 10

    elif venue_sample >= 2:

        reliability = 5

    else:

        reliability = 0

    confidence += reliability

    confidence = round(confidence)

    # Conservative caps
    if venue_sample <= 2:

        confidence = min(
            confidence,
            78
        )

    elif venue_sample <= 4:

        confidence = min(
            confidence,
            82
        )

    elif venue_sample <= 6:

        confidence = min(
            confidence,
            85
        )

    else:

        confidence = min(
            confidence,
            88
        )

    return confidence


# =========================================================
# MARKET GRADE
# =========================================================

def grade_market(
    confidence,
    sample,
    goal_environment=None
):

    if confidence >= 80 and sample >= 4:

        return "🔥 STRONG"

    if confidence >= 70:

        return "🟢 GOOD"

    if confidence >= 60:

        return "🟡 MODERATE"

    return "🔴 AVOID"


# =========================================================
# MARKET ENGINE
# =========================================================

def calculate_markets(
    team1_overall,
    team2_overall,
    team1_home,
    team2_away,
    goal_data
):

    markets = []

    venue_sample = 0

    if team1_home:
        venue_sample += team1_home["count"]

    if team2_away:
        venue_sample += team2_away["count"]

    # -----------------------------------------------------
    # OVER 1.5
    # -----------------------------------------------------

    confidence = weighted_confidence(
        team1_overall,
        team2_overall,
        team1_home,
        team2_away,
        "over15"
    )

    if confidence is not None:

        if goal_data["environment"] >= 2.5:

            confidence = min(
                confidence + 3,
                88
            )

        if confidence >= 70:

            advice = "BET"

        elif confidence >= 60:

            advice = "CAUTION"

        else:

            advice = "AVOID"

        markets.append({

            "market":
                "Over 1.5 Goals",

            "confidence":
                confidence,

            "grade":
                grade_market(
                    confidence,
                    venue_sample
                ),

            "advice":
                advice,

            "reason":
                "Recent goal rates, home/away trends and the combined goal environment were considered."
        })

    # -----------------------------------------------------
    # OVER 2.5
    # -----------------------------------------------------

    confidence = weighted_confidence(
        team1_overall,
        team2_overall,
        team1_home,
        team2_away,
        "over25"
    )

    if confidence is not None:

        if goal_data["environment"] >= 3.0:

            confidence = min(
                confidence + 4,
                88
            )

        elif goal_data["environment"] < 2.2:

            confidence = max(
                confidence - 4,
                0
            )

        if confidence >= 70:

            advice = "BET"

        elif confidence >= 60:

            advice = "CAUTION"

        else:

            advice = "AVOID"

        markets.append({

            "market":
                "Over 2.5 Goals",

            "confidence":
                confidence,

            "grade":
                grade_market(
                    confidence,
                    venue_sample
                ),

            "advice":
                advice,

            "reason":
                "The engine combines Over 2.5 frequency with recent attacking and defensive goal averages."
        })

    # -----------------------------------------------------
    # BTTS
    # -----------------------------------------------------

    confidence = weighted_confidence(
        team1_overall,
        team2_overall,
        team1_home,
        team2_away,
        "btts"
    )

    if confidence is not None:

        if confidence >= 70:

            advice = "BET"

        elif confidence >= 60:

            advice = "CAUTION"

        else:

            advice = "AVOID"

        markets.append({

            "market":
                "BTTS — Yes",

            "confidence":
                confidence,

            "grade":
                grade_market(
                    confidence,
                    venue_sample
                ),

            "advice":
                advice,

            "reason":
                "Both teams' scoring and conceding consistency were combined with their relevant home/away records."
        })

    return markets


# =========================================================
# MAIN ANALYSIS
# =========================================================
