import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from statistics import mean

import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

PORT = int(os.getenv("PORT", "10000"))

OPENFOOT_BASE = "https://openfootapi.com"
CURRENT_SEASON = "2026/27"


# ============================================================
# RENDER HEALTH SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"GoalLogic AI is running.")

    def log_message(self, format, *args):
        return


def start_health_server():
    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    print(f"GoalLogic AI is running on port {PORT}.")

    server.serve_forever()


# ============================================================
# OPENFOOT API
# ============================================================

def openfoot_headers():

    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {OPENFOOT_API_KEY}",
    }


def openfoot_get(endpoint, params=None):

    url = f"{OPENFOOT_BASE}{endpoint}"

    try:

        response = requests.get(
            url,
            headers=openfoot_headers(),
            params=params,
            timeout=20,
        )

        print(
            f"OpenFoot request: {response.status_code} "
            f"{response.url}"
        )

        if response.status_code != 200:

            print(
                "OpenFoot error:",
                response.status_code,
                response.text
            )

            return None

        payload = response.json()

        if "error" in payload:

            print(
                "OpenFoot API error:",
                payload["error"]
            )

            return None

        return payload.get("data", [])

    except Exception as e:

        print(
            "OpenFoot request error:",
            e
        )

        return None


# ============================================================
# TEAM SEARCH
# ============================================================

def search_team(team_name):

    results = openfoot_get(
        "/v1/search",
        {
            "q": team_name
        }
    )

    if not results:
        return None

    query = team_name.lower().strip()

    # Exact match first
    for team in results:

        name = str(
            team.get("name", "")
        ).lower().strip()

        if name == query:
            return team

    # Partial match second
    for team in results:

        name = str(
            team.get("name", "")
        ).lower()

        if query in name or name in query:
            return team

    # Otherwise use first result
    return results[0]


# ============================================================
# MATCH DATE
# ============================================================

def match_date_key(match):

    value = (
        match.get("kickoffAt")
        or match.get("date")
        or match.get("startTime")
        or match.get("scheduledAt")
        or ""
    )

    return str(value)


# ============================================================
# TEAM MATCHES
# ============================================================

def get_team_matches(team_id):

    matches = openfoot_get(
        "/v1/matches",
        {
            "team": team_id,
            "season": CURRENT_SEASON,
        }
    )

    if not matches:
        return []

    finished_statuses = {
        "finished",
        "completed",
        "complete",
        "ft",
        "ended",
        "full_time",
        "full-time",
    }

    finished = []

    for match in matches:

        status = str(
            match.get("status", "")
        ).lower().strip()

        status_code = str(
            match.get("statusCode", "")
        ).lower().strip()

        is_finished = (
            status in finished_statuses
            or status_code in finished_statuses
        )

        if is_finished:
            finished.append(match)

    finished.sort(
        key=match_date_key,
        reverse=True
    )

    return finished


# ============================================================
# SCORE EXTRACTION
# ============================================================

def get_score(match):

    score = match.get("score")

    if isinstance(score, dict):

        home_score = score.get("home")
        away_score = score.get("away")

        if isinstance(home_score, dict):
            home_score = (
                home_score.get("current")
                or home_score.get("display")
                or home_score.get("goals")
            )

        if isinstance(away_score, dict):
            away_score = (
                away_score.get("current")
                or away_score.get("display")
                or away_score.get("goals")
            )

        if (
            home_score is not None
            and away_score is not None
        ):
            return (
                int(home_score),
                int(away_score)
            )

    home_score = (
        match.get("homeScore")
        or match.get("home_score")
    )

    away_score = (
        match.get("awayScore")
        or match.get("away_score")
    )

    if (
        home_score is not None
        and away_score is not None
    ):
        try:
            return (
                int(home_score),
                int(away_score)
            )
        except:
            pass

    return None


# ============================================================
# TEAM RECORD
# ============================================================

def build_team_record(match, team_id):

    home = match.get("home") or {}
    away = match.get("away") or {}

    home_id = (
        home.get("id")
        or home.get("teamId")
    )

    away_id = (
        away.get("id")
        or away.get("teamId")
    )

    score = get_score(match)

    if not score:
        return None

    home_goals, away_goals = score

    if str(home_id) == str(team_id):

        venue = "home"

        goals_for = home_goals
        goals_against = away_goals

    elif str(away_id) == str(team_id):

        venue = "away"

        goals_for = away_goals
        goals_against = home_goals

    else:
        return None

    if goals_for > goals_against:
        result = "W"

    elif goals_for == goals_against:
        result = "D"

    else:
        result = "L"

    return {
        "date": match_date_key(match),
        "venue": venue,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "total_goals": goals_for + goals_against,
        "result": result,
    }


# ============================================================
# STATISTICS
# ============================================================

def calculate_stats(records):

    if not records:
        return {
            "sample": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "avg_for": 0,
            "avg_against": 0,
            "avg_total": 0,
            "over05": 0,
            "over15": 0,
            "over25": 0,
            "under35": 0,
            "btts": 0,
            "clean": 0,
            "scoring": 0,
            "conceding": 0,
            "two_to_four": 0,
        }

    sample = len(records)

    goals_for = [
        r["goals_for"]
        for r in records
    ]

    goals_against = [
        r["goals_against"]
        for r in records
    ]

    total_goals = [
        r["total_goals"]
        for r in records
    ]

    wins = sum(
        r["result"] == "W"
        for r in records
    )

    draws = sum(
        r["result"] == "D"
        for r in records
    )

    losses = sum(
        r["result"] == "L"
        for r in records
    )

    return {

        "sample": sample,

        "wins": wins,
        "draws": draws,
        "losses": losses,

        "goals_for": sum(goals_for),
        "goals_against": sum(goals_against),

        "avg_for": mean(goals_for),
        "avg_against": mean(goals_against),
        "avg_total": mean(total_goals),

        "over05": 100 * sum(
            x >= 1 for x in total_goals
        ) / sample,

        "over15": 100 * sum(
            x >= 2 for x in total_goals
        ) / sample,

        "over25": 100 * sum(
            x >= 3 for x in total_goals
        ) / sample,

        "under35": 100 * sum(
            x <= 3 for x in total_goals
        ) / sample,

        "btts": 100 * sum(
            r["goals_for"] > 0
            and r["goals_against"] > 0
            for r in records
        ) / sample,

        "clean": 100 * sum(
            r["goals_against"] == 0
            for r in records
        ) / sample,

        "scoring": 100 * sum(
            r["goals_for"] > 0
            for r in records
        ) / sample,

        "conceding": 100 * sum(
            r["goals_against"] > 0
            for r in records
        ) / sample,

        "two_to_four": 100 * sum(
            2 <= x <= 4
            for x in total_goals
        ) / sample,
    }


# ============================================================
# SAMPLE RELIABILITY
# ============================================================

def sample_reliability(sample):

    if sample >= 7:
        return 100

    if sample >= 5:
        return 90

    if sample >= 3:
        return 75

    if sample >= 2:
        return 60

    return 40


def agreement_score(value1, value2):

    difference = abs(
        value1 - value2
    )

    if difference <= 10:
        return 100

    if difference <= 20:
        return 85

    if difference <= 30:
        return 70

    if difference <= 40:
        return 55

    return 40


# ============================================================
# MARKET CONFIDENCE
# ============================================================

def combined_confidence(
    overall1,
    overall2,
    venue1,
    venue2,
    market,
):

    rates = {
        "over05": "over05",
        "over15": "over15",
        "over25": "over25",
        "under35": "under35",
        "btts": "btts",
        "two_to_four": "two_to_four",
    }

    key = rates.get(market)

    if not key:
        return 50

    o1 = overall1[key]
    o2 = overall2[key]

    v1 = venue1.get(key, o1)
    v2 = venue2.get(key, o2)

    overall_average = (
        o1 + o2
    ) / 2

    venue_average = (
        v1 + v2
    ) / 2

    agreement = agreement_score(
        o1,
        o2
    )

    reliability1 = sample_reliability(
        venue1.get("sample", 0)
    )

    reliability2 = sample_reliability(
        venue2.get("sample", 0)
    )

    reliability = (
        reliability1 + reliability2
    ) / 2

    # Balanced calculation
    confidence = (
        overall_average * 0.40
        + venue_average * 0.25
        + agreement * 0.10
        + reliability * 0.10
    )

    # Defensive counter-signals
    if market == "over25":

        if (
            venue1.get("under35", 0) >= 80
            and venue2.get("under35", 0) >= 80
        ):
            confidence -= 8

    if market == "under35":

        if (
            venue1.get("over25", 0) >= 70
            or venue2.get("over25", 0) >= 70
        ):
            confidence -= 7

    if market == "btts":

        clean_counter = (
            venue1.get("clean", 0)
            + venue2.get("clean", 0)
        ) / 2

        if clean_counter >= 60:
            confidence -= 8

    # Small venue samples should not dominate
    venue_sample = min(
        venue1.get("sample", 0),
        venue2.get("sample", 0)
    )

    if venue_sample < 2:
        confidence = min(
            confidence,
            72
        )

    elif venue_sample < 3:
        confidence = min(
            confidence,
            78
        )

    elif venue_sample < 5:
        confidence = min(
            confidence,
            84
        )

    elif venue_sample < 7:
        confidence = min(
            confidence,
            88
        )

    return round(
        max(
            0,
            min(90, confidence)
        )
    )


# ============================================================
# TEAM TO SCORE CONFIDENCE
# ============================================================

def team_score_confidence(
    team_overall,
    team_venue,
    opponent_overall,
    opponent_venue,
):

    scoring_overall = (
        team_overall["scoring"]
    )

    scoring_venue = (
        team_venue["scoring"]
    )

    opponent_conceding = (
        opponent_overall["conceding"]
    )

    opponent_venue_conceding = (
        opponent_venue["conceding"]
    )

    value = (
        scoring_overall * 0.35
        + scoring_venue * 0.25
        + opponent_conceding * 0.20
        + opponent_venue_conceding * 0.10
        + sample_reliability(
            team_venue["sample"]
        ) * 0.10
    )

    # Strong clean-sheet counter
    if (
        opponent_venue["clean"] >= 67
    ):
        value -= 7

    return round(
        max(
            0,
            min(90, value)
        )
    )


# ============================================================
# BTTS CONFIDENCE
# ============================================================

def btts_confidence(
    team1,
    team2,
    venue1,
    venue2,
):

    scoring_support = (
        team1["scoring"]
        + team2["scoring"]
    ) / 2

    conceding_support = (
        team1["conceding"]
        + team2["conceding"]
    ) / 2

    venue_btts = (
        venue1["btts"]
        + venue2["btts"]
    ) / 2

    clean_counter = (
        venue1["clean"]
        + venue2["clean"]
    ) / 2

    reliability = (
        sample_reliability(
            venue1["sample"]
        )
        + sample_reliability(
            venue2["sample"]
        )
    ) / 2

    confidence = (
        scoring_support * 0.25
        + conceding_support * 0.20
        + venue_btts * 0.30
        + (100 - clean_counter) * 0.15
        + reliability * 0.10
    )

    if clean_counter >= 60:
        confidence -= 8

    return round(
        max(
            0,
            min(90, confidence)
        )
    )


# ============================================================
# GRADES
# ============================================================

def grade(confidence):

    if confidence >= 80:
        return "🔥 STRONG"

    if confidence >= 70:
        return "🟢 GOOD"

    if confidence >= 60:
        return "🟡 MODERATE"

    return "🔴 AVOID"


def advice(
    confidence,
    sample=5
):

    if sample < 2:
        return "AVOID"

    if confidence >= 70:
        return "BET"

    if confidence >= 60:
        return "CAUTION"

    return "AVOID"


# ============================================================
# REASONS
# ============================================================

def market_reason(
    market,
    team1_name,
    team2_name,
    s1,
    s2,
    v1,
    v2,
):

    if market == "over05":

        return (
            f"{team1_name} had Over 0.5 goals in "
            f"{s1['over05']:.0f}% of recent matches; "
            f"{team2_name} had {s2['over05']:.0f}%; "
            f"recent venue rates are "
            f"{v1['over05']:.0f}% and "
            f"{v2['over05']:.0f}%."
        )

    if market == "over15":

        return (
            f"Recent Over 1.5 rates are "
            f"{s1['over15']:.0f}% for {team1_name} "
            f"and {s2['over15']:.0f}% for {team2_name}; "
            f"combined recent goal average is "
            f"{(s1['avg_total'] + s2['avg_total']) / 2:.1f}."
        )

    if market == "over25":

        return (
            f"Over 2.5 rates are "
            f"{s1['over25']:.0f}% and "
            f"{s2['over25']:.0f}%; "
            f"combined recent goal average is "
            f"{(s1['avg_total'] + s2['avg_total']) / 2:.1f}. "
            f"Venue Over 2.5 rates are "
            f"{v1['over25']:.0f}% and "
            f"{v2['over25']:.0f}%."
        )

    if market == "under35":

        return (
            f"Under 3.5 rates are "
            f"{s1['under35']:.0f}% for {team1_name} "
            f"and {s2['under35']:.0f}% for {team2_name}; "
            f"combined recent goal average is "
            f"{(s1['avg_total'] + s2['avg_total']) / 2:.1f}. "
            f"Over 2.5 counter-rates are "
            f"{s1['over25']:.0f}% and "
            f"{s2['over25']:.0f}%."
        )

    if market == "btts":

        return (
            f"{team1_name} scores in "
            f"{s1['scoring']:.0f}% and "
            f"{team2_name} scores in "
            f"{s2['scoring']:.0f}% of recent matches; "
            f"venue BTTS rates are "
            f"{v1['btts']:.0f}% and "
            f"{v2['btts']:.0f}%. "
            f"Venue clean-sheet rates are "
            f"{v1['clean']:.0f}% and "
            f"{v2['clean']:.0f}%."
        )

    if market == "two_to_four":

        return (
            f"{team1_name} recorded 2–4 total goals in "
            f"{s1['two_to_four']:.0f}% of recent matches; "
            f"{team2_name} recorded "
            f"{s2['two_to_four']:.0f}%."
        )

    return "Mixed statistical signals."


# ============================================================
# FORMATTING
# ============================================================

def form_string(records):

    return "".join(
        r["result"]
        for r in records
    )


def format_stats_block(
    name,
    stats,
    emoji="📊",
):

    return (
        f"{emoji} {name.upper()} — LAST 5\n"
        f"Form: {form_string([]) if stats['sample'] == 0 else ''}\n"
        f"W/D/L: "
        f"{stats['wins']}/"
        f"{stats['draws']}/"
        f"{stats['losses']}\n"
        f"Goals scored: "
        f"{stats['goals_for']}\n"
        f"Goals conceded: "
        f"{stats['goals_against']}\n"
        f"Avg scored: "
        f"{stats['avg_for']:.1f}\n"
        f"Avg conceded: "
        f"{stats['avg_against']:.1f}\n"
        f"Avg total goals: "
        f"{stats['avg_total']:.1f}\n"
        f"Over 0.5: "
        f"{stats['over05']:.0f}%\n"
        f"Over 1.5: "
        f"{stats['over15']:.0f}%\n"
        f"Over 2.5: "
        f"{stats['over25']:.0f}%\n"
        f"Under 3.5: "
        f"{stats['under35']:.0f}%\n"
        f"BTTS: "
        f"{stats['btts']:.0f}%\n"
        f"Scoring consistency: "
        f"{stats['scoring']:.0f}%\n"
        f"Clean sheets: "
        f"{stats['clean']:.0f}%\n"
        f"Sample: "
        f"{stats['sample']} matches"
    )


def venue_block(
    name,
    venue,
    stats,
    emoji,
):

    return (
        f"{emoji} {name.upper()} — RECENT {venue.upper()}\n"
        f"Form: "
        f"{stats['wins']}W/"
        f"{stats['draws']}D/"
        f"{stats['losses']}L\n"
        f"Avg scored: "
        f"{stats['avg_for']:.1f}\n"
        f"Avg conceded: "
        f"{stats['avg_against']:.1f}\n"
        f"Over 1.5: "
        f"{stats['over15']:.0f}%\n"
        f"Over 2.5: "
        f"{stats['over25']:.0f}%\n"
        f"Under 3.5: "
        f"{stats['under35']:.0f}%\n"
        f"BTTS: "
        f"{stats['btts']:.0f}%\n"
        f"Scoring: "
        f"{stats['scoring']:.0f}%\n"
        f"Clean sheets: "
        f"{stats['clean']:.0f}%\n"
        f"Sample: "
        f"{stats['sample']} matches"
    )


# ============================================================
# MAIN ANALYSIS
# ============================================================

def analyze_match(team1_name, team2_name):

    team1 = search_team(team1_name)
    team2 = search_team(team2_name)

    if not team1:
        return (
            f"❌ I couldn't find {team1_name}."
        )

    if not team2:
        return (
            f"❌ I couldn't find {team2_name}."
        )

    team1_id = (
        team1.get("id")
        or team1.get("teamId")
    )

    team2_id = (
        team2.get("id")
        or team2.get("teamId")
    )

    matches1 = get_team_matches(
        team1_id
    )

    matches2 = get_team_matches(
        team2_id
    )

    if not matches1 or not matches2:

        return (
            "⚠️ Football data could not be retrieved.\n\n"
            "Please try another match."
        )

    # --------------------------------------------------------
    # Use last 5 overall matches
    # --------------------------------------------------------

    recent1 = [
        r
        for r in (
            build_team_record(m, team1_id)
            for m in matches1
        )
        if r
    ][:5]

    recent2 = [
        r
        for r in (
            build_team_record(m, team2_id)
            for m in matches2
        )
        if r
    ][:5]

    if len(recent1) < 2 or len(recent2) < 2:

        return (
            "⚠️ Not enough completed matches "
            "to produce a reliable analysis."
        )

    stats1 = calculate_stats(
        recent1
    )

    stats2 = calculate_stats(
        recent2
    )

    # --------------------------------------------------------
    # Get up to 5 recent home matches for team 1
    # and away matches for team 2.
    # --------------------------------------------------------

    all_records1 = [
        r
        for r in (
            build_team_record(m, team1_id)
            for m in matches1
        )
        if r
    ]

    all_records2 = [
        r
        for r in (
            build_team_record(m, team2_id)
            for m in matches2
        )
        if r
    ]

    home_records = [
        r
        for r in all_records1
        if r["venue"] == "home"
    ][:5]

    away_records = [
        r
        for r in all_records2
        if r["venue"] == "away"
    ][:5]

    home_stats = calculate_stats(
        home_records
    )

    away_stats = calculate_stats(
        away_records
    )

    # --------------------------------------------------------
    # Market confidence
    # --------------------------------------------------------

    markets = {}

    markets["Over 0.5 Goals"] = combined_confidence(
        stats1,
        stats2,
        home_stats,
        away_stats,
        "over05",
    )

    markets["Over 1.5 Goals"] = combined_confidence(
        stats1,
        stats2,
        home_stats,
        away_stats,
        "over15",
    )

    markets["Over 2.5 Goals"] = combined_confidence(
        stats1,
        stats2,
        home_stats,
        away_stats,
        "over25",
    )

    markets["Under 3.5 Goals"] = combined_confidence(
        stats1,
        stats2,
        home_stats,
        away_stats,
        "under35",
    )

    markets["BTTS — Yes"] = btts_confidence(
        stats1,
        stats2,
        home_stats,
        away_stats,
    )

    team1_score = team_score_confidence(
        stats1,
        home_stats,
        stats2,
        away_stats,
    )

    team2_score = team_score_confidence(
        stats2,
        away_stats,
        stats1,
        home_stats,
    )

    markets[
        f"{team1.get('name', team1_name)} to Score"
    ] = team1_score

    markets[
        f"{team2.get('name', team2_name)} to Score"
    ] = team2_score

    markets["2–4 Total Goals"] = combined_confidence(
        stats1,
        stats2,
        home_stats,
        away_stats,
        "two_to_four",
    )

    # --------------------------------------------------------
    # Primary signal
    #
    # Do NOT automatically select Over 0.5.
    # --------------------------------------------------------

    preferred_markets = [
        "Over 1.5 Goals",
        "Over 2.5 Goals",
        "Under 3.5 Goals",
        "BTTS — Yes",
        f"{team1.get('name', team1_name)} to Score",
        f"{team2.get('name', team2_name)} to Score",
        "2–4 Total Goals",
    ]

    eligible = {
        market: confidence
        for market, confidence in markets.items()
        if market in preferred_markets
        and confidence >= 60
    }

    if eligible:

        primary_market = max(
            eligible,
            key=eligible.get
        )

    else:

        primary_market = "Over 0.5 Goals"

    primary_confidence = markets[
        primary_market
    ]

    # --------------------------------------------------------
    # Recent form comparison
    # --------------------------------------------------------

    wins1 = stats1["wins"]
    wins2 = stats2["wins"]

    draws1 = stats1["draws"]
    draws2 = stats2["draws"]

    losses1 = stats1["losses"]
    losses2 = stats2["losses"]

    # --------------------------------------------------------
    # Goal environment
    # --------------------------------------------------------

    combined_avg = (
        stats1["avg_total"]
        + stats2["avg_total"]
    ) / 2

    if combined_avg >= 3.0:
        environment = "🔥 HIGH"

    elif combined_avg >= 2.3:
        environment = "🟡 MODERATE"

    else:
        environment = "🛡️ LOW"

    # --------------------------------------------------------
    # Build response
    # --------------------------------------------------------

    t1_display = team1.get(
        "name",
        team1_name
    )

    t2_display = team2.get(
        "name",
        team2_name
    )

    response = []

    response.append(
        "⚽ GOALLOGIC AI — ADVANCED ANALYSIS"
    )

    response.append("")

    response.append(
        f"{t1_display} vs {t2_display}"
    )

    response.append(
        f"Season: {CURRENT_SEASON}"
    )

    response.append("")

    # --------------------------------------------------------
    # Team 1
    # --------------------------------------------------------

    response.append(
        f"📊 {t1_display.upper()} — LAST 5"
    )

    response.append(
        f"Form: {form_string(recent1)}"
    )

    response.append(
        f"W/D/L: "
        f"{wins1}/{draws1}/{losses1}"
    )

    response.append(
        f"Goals scored: "
        f"{stats1['goals_for']}"
    )

    response.append(
        f"Goals conceded: "
        f"{stats1['goals_against']}"
    )

    response.append(
        f"Avg scored: "
        f"{stats1['avg_for']:.1f}"
    )

    response.append(
        f"Avg conceded: "
        f"{stats1['avg_against']:.1f}"
    )

    response.append(
        f"Avg total goals: "
        f"{stats1['avg_total']:.1f}"
    )

    response.append(
        f"Over 0.5: "
        f"{stats1['over05']:.0f}%"
    )

    response.append(
        f"Over 1.5: "
        f"{stats1['over15']:.0f}%"
    )

    response.append(
        f"Over 2.5: "
        f"{stats1['over25']:.0f}%"
    )

    response.append(
        f"Under 3.5: "
        f"{stats1['under35']:.0f}%"
    )

    response.append(
        f"BTTS: "
        f"{stats1['btts']:.0f}%"
    )

    response.append(
        f"Scoring consistency: "
        f"{stats1['scoring']:.0f}%"
    )

    response.append(
        f"Clean sheets: "
        f"{stats1['clean']:.0f}%"
    )

    response.append(
        f"Sample: {stats1['sample']} matches"
    )

    response.append("")

    # --------------------------------------------------------
    # Team 1 home
    # --------------------------------------------------------

    response.append(
        f"🏠 {t1_display.upper()} — RECENT HOME"
    )

    response.append(
        f"Form: "
        f"{form_string(home_records)}"
    )

    response.append(
        f"Avg scored: "
        f"{home_stats['avg_for']:.1f}"
    )

    response.append(
        f"Avg conceded: "
        f"{home_stats['avg_against']:.1f}"
    )

    response.append(
        f"Over 1.5: "
        f"{home_stats['over15']:.0f}%"
    )

    response.append(
        f"Over 2.5: "
        f"{home_stats['over25']:.0f}%"
    )

    response.append(
        f"Under 3.5: "
        f"{home_stats['under35']:.0f}%"
    )

    response.append(
        f"BTTS: "
        f"{home_stats['btts']:.0f}%"
    )

    response.append(
        f"Scoring: "
        f"{home_stats['scoring']:.0f}%"
    )

    response.append(
        f"Clean sheets: "
        f"{home_stats['clean']:.0f}%"
    )

    response.append(
        f"Sample: {home_stats['sample']} matches"
    )

    if home_stats["sample"] < 3:

        response.append(
            "⚠️ Small home sample."
        )

    response.append("")

    # --------------------------------------------------------
    # Team 2
    # --------------------------------------------------------

    response.append(
        f"📊 {t2_display.upper()} — LAST 5"
    )

    response.append(
        f"Form: {form_string(recent2)}"
    )

    response.append(
        f"W/D/L: "
        f"{wins2}/{draws2}/{losses2}"
    )

    response.append(
        f"Goals scored: "
        f"{stats2['goals_for']}"
    )

    response.append(
        f"Goals conceded: "
        f"{stats2['goals_against']}"
    )

    response.append(
        f"Avg scored: "
        f"{stats2['avg_for']:.1f}"
    )

    response.append(
        f"Avg conceded: "
        f"{stats2['avg_against']:.1f}"
    )

    response.append(
        f"Avg total goals: "
        f"{stats2['avg_total']:.1f}"
    )

    response.append(
        f"Over 0.5: "
        f"{stats2['over05']:.0f}%"
    )

    response.append(
        f"Over 1.5: "
        f"{stats2['over15']:.0f}%"
    )

    response.append(
        f"Over 2.5: "
        f"{stats2['over25']:.0f}%"
    )

    response.append(
        f"Under 3.5: "
        f"{stats2['under35']:.0f}%"
    )

    response.append(
        f"BTTS: "
        f"{stats2['btts']:.0f}%"
    )

    response.append(
        f"Scoring consistency: "
        f"{stats2['scoring']:.0f}%"
    )

    response.append(
        f"Clean sheets: "
        f"{stats2['clean']:.0f}%"
    )

    response.append(
        f"Sample: {stats2['sample']} matches"
    )

    response.append("")

    # --------------------------------------------------------
    # Team 2 away
    # --------------------------------------------------------

    response.append(
        f"✈️ {t2_display.upper()} — RECENT AWAY"
    )

    response.append(
        f"Form: "
        f"{form_string(away_records)}"
    )

    response.append(
        f"Avg scored: "
        f"{away_stats['avg_for']:.1f}"
    )

    response.append(
        f"Avg conceded: "
        f"{away_stats['avg_against']:.1f}"
    )

    response.append(
        f"Over 1.5: "
        f"{away_stats['over15']:.0f}%"
    )

    response.append(
        f"Over 2.5: "
        f"{away_stats['over25']:.0f}%"
    )

    response.append(
        f"Under 3.5: "
        f"{away_stats['under35']:.0f}%"
    )

    response.append(
        f"BTTS: "
        f"{away_stats['btts']:.0f}%"
    )

    response.append(
        f"Scoring: "
        f"{away_stats['scoring']:.0f}%"
    )

    response.append(
        f"Clean sheets: "
        f"{away_stats['clean']:.0f}%"
    )

    response.append(
        f"Sample: {away_stats['sample']} matches"
    )

    if away_stats["sample"] < 3:

        response.append(
            "⚠️ Small away sample."
        )

    response.append("")

    # --------------------------------------------------------
    # Attacking profile
    # --------------------------------------------------------

    response.append(
        f"🔥 {t1_display.upper()} — ATTACKING PROFILE"
    )

    if stats1["avg_for"] >= 1.7:
        attack_level = "🔥 STRONG"

    elif stats1["avg_for"] >= 1.2:
        attack_level = "🟡 MODERATE"

    else:
        attack_level = "🔴 LOW"

    response.append(
        f"Attack level: {attack_level}"
    )

    response.append(
        f"Avg goals scored: "
        f"{stats1['avg_for']:.2f}"
    )

    response.append(
        f"Scoring consistency: "
        f"{stats1['scoring']:.0f}%"
    )

    response.append(
        f"Recent home scoring: "
        f"{home_stats['scoring']:.0f}%"
    )

    response.append("")

    # --------------------------------------------------------
    # Defensive profile
    # --------------------------------------------------------

    response.append(
        f"🛡️ {t2_display.upper()} — DEFENSIVE PROFILE"
    )

    if stats2["avg_against"] <= 1.0:

        defense_level = "🛡️ STRONG"

    elif stats2["avg_against"] <= 1.5:

        defense_level = "🟡 MODERATE"

    else:

        defense_level = "⚠️ VULNERABLE"

    response.append(
        f"Defensive level: {defense_level}"
    )

    response.append(
        f"Avg conceded: "
        f"{stats2['avg_against']:.2f}"
    )

    response.append(
        f"Clean sheets: "
        f"{stats2['clean']:.0f}%"
    )

    response.append(
        f"Conceding rate: "
        f"{stats2['conceding']:.0f}%"
    )

    response.append("")

    # --------------------------------------------------------
    # Goal intelligence
    # --------------------------------------------------------

    response.append(
        "🎯 GOAL & DEFENSIVE INTELLIGENCE"
    )

    response.append(
        f"Average attacking output: "
        f"{(stats1['avg_for'] + stats2['avg_for']) / 2:.2f} goals"
    )

    response.append(
        f"Average goals conceded: "
        f"{(stats1['avg_against'] + stats2['avg_against']) / 2:.2f} goals"
    )

    response.append(
        f"Combined goal environment: "
        f"{combined_avg:.2f}"
    )

    response.append(
        f"Goal environment: "
        f"{environment}"
    )

    response.append("")

    # --------------------------------------------------------
    # Form assessment
    # --------------------------------------------------------

    response.append(
        "📈 RECENT FORM ASSESSMENT"
    )

    response.append(
        f"{t1_display}: "
        f"{wins1} wins, "
        f"{draws1} draws, "
        f"{losses1} losses"
    )

    response.append(
        f"{t2_display}: "
        f"{wins2} wins, "
        f"{draws2} draws, "
        f"{losses2} losses"
    )

    response.append("")

    # --------------------------------------------------------
    # Markets
    # --------------------------------------------------------

    response.append(
        "📊 MARKET SIGNALS"
    )

    response.append("")

    for market, confidence in markets.items():

        # Give Over 0.5 a slightly different status
        # because it is a broad market.
        market_advice = advice(
            confidence,
            min(
                stats1["sample"],
                stats2["sample"]
            )
        )

        response.append(
            f"{market} — "
            f"Confidence {confidence}%"
        )

        response.append(
            f"Grade: {grade(confidence)}"
        )

        response.append(
            f"Advice: {market_advice}"
        )

        if market == "BTTS — Yes":

            reason = market_reason(
                "btts",
                t1_display,
                t2_display,
                stats1,
                stats2,
                home_stats,
                away_stats,
            )

        elif market == "Over 0.5 Goals":

            reason = market_reason(
                "over05",
                t1_display,
                t2_display,
                stats1,
                stats2,
                home_stats,
                away_stats,
            )

        elif market == "Over 1.5 Goals":

            reason = market_reason(
                "over15",
                t1_display,
                t2_display,
                stats1,
                stats2,
                home_stats,
                away_stats,
            )

        elif market == "Over 2.5 Goals":

            reason = market_reason(
                "over25",
                t1_display,
                t2_display,
                stats1,
                stats2,
                home_stats,
                away_stats,
            )

        elif market == "Under 3.5 Goals":

            reason = market_reason(
                "under35",
                t1_display,
                t2_display,
                stats1,
                stats2,
                home_stats,
                away_stats,
            )

        elif market == "2–4 Total Goals":

            reason = market_reason(
                "two_to_four",
                t1_display,
                t2_display,
                stats1,
                stats2,
                home_stats,
                away_stats,
            )

        elif market.startswith(t1_display):

            reason = (
                f"{t1_display} scores in "
                f"{stats1['scoring']:.0f}% of recent matches; "
                f"home scoring rate is "
                f"{home_stats['scoring']:.0f}%; "
                f"{t2_display} concedes in "
                f"{stats2['conceding']:.0f}% of recent matches."
            )

        else:

            reason = (
                f"{t2_display} scores in "
                f"{stats2['scoring']:.0f}% of recent matches; "
                f"away scoring rate is "
                f"{away_stats['scoring']:.0f}%; "
                f"{t1_display} concedes in "
                f"{stats1['conceding']:.0f}% of recent matches."
            )

        response.append(
            f"Reason: {reason}"
        )

        response.append("")

    # --------------------------------------------------------
    # Primary signal
    # --------------------------------------------------------

    response.append(
        "⭐ PRIMARY STATISTICAL SIGNAL"
    )

    response.append(
        f"{primary_market} — "
        f"Confidence {primary_confidence}%"
    )

    response.append(
        f"Grade: {grade(primary_confidence)}"
    )

    response.append(
        f"Advice: "
        f"{advice(primary_confidence)}"
    )

    response.append("")

    # --------------------------------------------------------
    # Data quality
    # --------------------------------------------------------

    response.append(
        "🔎 DATA QUALITY"
    )

    response.append(
        f"{t1_display}: "
        f"{stats1['sample']} recent matches; "
        f"{home_stats['sample']} recent home matches."
    )

    response.append(
        f"{t2_display}: "
        f"{stats2['sample']} recent matches; "
        f"{away_stats['sample']} recent away matches."
    )

    if (
        home_stats["sample"] < 3
        or away_stats["sample"] < 3
    ):

        response.append(
            "⚠️ Venue-specific samples are limited, "
            "so venue statistics receive less weight."
        )

    response.append("")

    response.append(
        "⚠️ Statistical analysis is not a guarantee "
        "of the match outcome. Confidence figures "
        "are indicators, not certainty."
    )

    return "\n".join(response)


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "⚽ Welcome to GoalLogic AI!\n\n"
        "Send me a match like:\n\n"
        "Chelsea vs Arsenal\n\n"
        "I will analyze recent form, "
        "home/away data, goals, BTTS, "
        "team scoring and market signals."
    )


async def apitest_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not OPENFOOT_API_KEY:

        await update.message.reply_text(
            "❌ OPENFOOT_API_KEY is missing."
        )

        return

    result = openfoot_get(
        "/v1/search",
        {
            "q": "Chelsea"
        }
    )

    if result:

        await update.message.reply_text(
            "✅ OPENFOOT TEST PASSED\n\n"
            "OpenFoot API is connected successfully."
        )

    else:

        await update.message.reply_text(
            "❌ OPENFOOT TEST FAILED\n\n"
            "OpenFoot could not return data."
        )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "Use:\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    text = " ".join(
        context.args
    )

    await process_match_text(
        update,
        text
    )


# ============================================================
# MATCH MESSAGE PROCESSING
# ============================================================

async def process_match_text(
    update,
    text
):

    pattern = re.compile(
        r"^\s*(.+?)\s+(?:vs\.?|v\.?)\s+(.+?)\s*$",
        re.IGNORECASE
    )

    match = pattern.match(text)

    if not match:

        await update.message.reply_text(
            "⚽ Send a match like:\n\n"
            "Chelsea vs Arsenal"
        )

        return

    team1 = match.group(1).strip()
    team2 = match.group(2).strip()

    await update.message.reply_text(
        "🔎 Analyzing the match...\n\n"
        f"{team1} vs {team2}"
    )

    try:

        result = analyze_match(
            team1,
            team2
        )

        await update.message.reply_text(
            result
        )

    except Exception as e:

        print(
            "Analysis error:",
            e
        )

        await update.message.reply_text(
            "❌ An error occurred while "
            "analyzing the match.\n\n"
            "Please try again."
        )


async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    text = (
        update.message.text
        or ""
    ).strip()

    if not text:
        return

    if re.search(
        r"\s+(?:vs\.?|v\.?)\s+",
        text,
        re.IGNORECASE
    ):

        await process_match_text(
            update,
            text
        )

    else:

        await update.message.reply_text(
            "⚽ Send a match like:\n\n"
            "Chelsea vs Arsenal"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    if not TELEGRAM_BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not OPENFOOT_API_KEY:

        raise RuntimeError(
            "OPENFOOT_API_KEY is missing."
        )

    # Start Render health server
    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    print(
        "Starting GoalLogic AI Telegram bot..."
    )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    application.add_handler(
        CommandHandler(
            "apitest",
            apitest_command
        )
    )

    application.add_handler(
        CommandHandler(
            "analyze",
            analyze_command
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            message_handler
        )
    )

    print(
        "GoalLogic AI Telegram bot is live."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
