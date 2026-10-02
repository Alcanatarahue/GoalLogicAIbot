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
# HEALTH SERVER FOR RENDER
# ============================================================

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

    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    print(
        f"GoalLogic AI is running on port {PORT}."
    )

    server.serve_forever()


# ============================================================
# OPENFOOT API
# ============================================================

def openfoot_headers():

    return {
        "Accept": "application/json",
        "Authorization": (
            f"Bearer {OPENFOOT_API_KEY}"
        ),
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

        return payload.get(
            "data",
            []
        )

    except Exception as e:

        print(
            "OpenFoot request error:",
            e
        )

        return None


# ============================================================
# SEARCH TEAM
# ============================================================

def search_team(team_name):

    data = openfoot_get(
        "/v1/search",
        {"q": team_name}
    )

    if not data:
        return None

    if isinstance(data, dict):

        results = data.get(
            "teams",
            []
        )

    else:

        results = data

    if not isinstance(results, list):
        return None

    team_name_lower = (
        team_name.lower().strip()
    )

    # Exact match
    for team in results:

        name = str(
            team.get(
                "name",
                ""
            )
        ).lower().strip()

        if name == team_name_lower:

            return team

    # Partial match
    for team in results:

        name = str(
            team.get(
                "name",
                ""
            )
        ).lower()

        if (
            team_name_lower in name
            or name in team_name_lower
        ):

            return team

    return results[0] if results else None


# ============================================================
# GET TEAM MATCHES
# ============================================================

def get_team_matches(team_id):

    data = openfoot_get(
        "/v1/matches",
        {
            "team": team_id,
            "season": CURRENT_SEASON,
        }
    )

    if not data:
        return []

    if isinstance(data, dict):

        matches = data.get(
            "matches",
            []
        )

    else:

        matches = data

    if not isinstance(matches, list):
        return []

    finished = []

    for match in matches:

        status = str(
            match.get(
                "status",
                ""
            )
        ).lower()

        if status in [
            "finished",
            "completed",
            "ft",
        ]:

            finished.append(match)

    finished.sort(
        key=lambda x: str(
            x.get(
                "kickoffAt",
                ""
            )
        ),
        reverse=True,
    )

    return finished


# ============================================================
# TEAM INFORMATION
# ============================================================

def get_team_id(team):

    return team.get("id")


def get_team_name(team):

    return team.get(
        "name",
        "Unknown"
    )


# ============================================================
# EXTRACT SCORE
# ============================================================

def extract_score(match):

    home_score = None
    away_score = None

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

    if home_score is None:

        home_score = match.get(
            "homeScore"
        )

    if away_score is None:

        away_score = match.get(
            "awayScore"
        )

    try:

        home_score = int(
            home_score
        )

        away_score = int(
            away_score
        )

    except Exception:

        return None, None

    return home_score, away_score


# ============================================================
# BUILD TEAM RECORDS
# ============================================================

def build_team_records(
    matches,
    team_id
):

    records = []

    for match in matches:

        home_team = match.get(
            "homeTeam",
            {}
        )

        away_team = match.get(
            "awayTeam",
            {}
        )

        home_id = home_team.get("id")
        away_id = away_team.get("id")

        home_score, away_score = (
            extract_score(match)
        )

        if (
            home_score is None
            or away_score is None
        ):

            continue

        if str(home_id) == str(team_id):

            goals_for = home_score
            goals_against = away_score
            venue = "home"

        elif str(away_id) == str(team_id):

            goals_for = away_score
            goals_against = home_score
            venue = "away"

        else:

            continue

        total_goals = (
            goals_for
            + goals_against
        )

        if goals_for > goals_against:

            result = "W"

        elif goals_for == goals_against:

            result = "D"

        else:

            result = "L"

        records.append(
            {
                "goals_for": goals_for,
                "goals_against": goals_against,
                "total_goals": total_goals,
                "result": result,
                "venue": venue,
            }
        )

    return records


# ============================================================
# STATISTICS
# ============================================================

def calculate_stats(records):

    if not records:
        return None

    total = len(records)

    wins = sum(
        1 for r in records
        if r["result"] == "W"
    )

    draws = sum(
        1 for r in records
        if r["result"] == "D"
    )

    losses = sum(
        1 for r in records
        if r["result"] == "L"
    )

    goals_for = sum(
        r["goals_for"]
        for r in records
    )

    goals_against = sum(
        r["goals_against"]
        for r in records
    )

    over_05 = sum(
        1 for r in records
        if r["total_goals"] >= 1
    )

    over_15 = sum(
        1 for r in records
        if r["total_goals"] >= 2
    )

    over_25 = sum(
        1 for r in records
        if r["total_goals"] >= 3
    )

    under_35 = sum(
        1 for r in records
        if r["total_goals"] <= 3
    )

    btts = sum(
        1 for r in records
        if (
            r["goals_for"] >= 1
            and r["goals_against"] >= 1
        )
    )

    clean_sheets = sum(
        1 for r in records
        if r["goals_against"] == 0
    )

    scoring = sum(
        1 for r in records
        if r["goals_for"] >= 1
    )

    conceding = sum(
        1 for r in records
        if r["goals_against"] >= 1
    )

    two_to_four = sum(
        1 for r in records
        if 2 <= r["total_goals"] <= 4
    )

    return {
        "sample": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "avg_for": goals_for / total,
        "avg_against": goals_against / total,
        "avg_total": (
            goals_for + goals_against
        ) / total,
        "over05": (
            over_05 / total * 100
        ),
        "over15": (
            over_15 / total * 100
        ),
        "over25": (
            over_25 / total * 100
        ),
        "under35": (
            under_35 / total * 100
        ),
        "btts": (
            btts / total * 100
        ),
        "clean": (
            clean_sheets / total * 100
        ),
        "scoring": (
            scoring / total * 100
        ),
        "conceding": (
            conceding / total * 100
        ),
        "two_to_four": (
            two_to_four / total * 100
        ),
    }


# ============================================================
# FORM
# ============================================================

def form_string(records):

    return "".join(
        r["result"]
        for r in records
    )


# ============================================================
# FORMAT
# ============================================================

def pct(value):

    return f"{value:.0f}%"


# ============================================================
# ATTACKING PROFILE
# ============================================================

def attacking_profile(
    name,
    overall,
    venue
):

    if not overall:
        return ""

    if overall["avg_for"] >= 1.8:

        attack_level = "🔥 STRONG"

    elif overall["avg_for"] >= 1.3:

        attack_level = "🟢 GOOD"

    elif overall["avg_for"] >= 1.0:

        attack_level = "🟡 MODERATE"

    else:

        attack_level = "🔴 LOW"

    if overall["avg_against"] >= 1.7:

        vulnerability = "⚠️ HIGH"

    elif overall["avg_against"] >= 1.2:

        vulnerability = "🟡 MODERATE"

    else:

        vulnerability = "🟢 LOW"

    text = (
        f"🔥 {name.upper()} — ATTACKING PROFILE\n"
        f"Attack level: {attack_level}\n"
        f"Avg goals scored: "
        f"{overall['avg_for']:.2f}\n"
        f"Scoring consistency: "
        f"{pct(overall['scoring'])}\n"
    )

    if venue:

        text += (
            f"Recent venue avg scored: "
            f"{venue['avg_for']:.2f}\n"
            f"Recent venue scoring: "
            f"{pct(venue['scoring'])}\n"
        )

    text += (
        f"Defensive vulnerability: "
        f"{vulnerability}\n"
        f"Avg goals conceded: "
        f"{overall['avg_against']:.2f}"
    )

    return text


# ============================================================
# DEFENSIVE PROFILE
# ============================================================

def defensive_profile(
    name,
    overall,
    venue
):

    if not overall:
        return ""

    if overall["avg_against"] <= 0.8:

        defense_level = "🛡️ STRONG"

    elif overall["avg_against"] <= 1.2:

        defense_level = "🟢 GOOD"

    elif overall["avg_against"] <= 1.7:

        defense_level = "🟡 MODERATE"

    else:

        defense_level = "🔴 VULNERABLE"

    text = (
        f"🛡️ {name.upper()} — DEFENSIVE PROFILE\n"
        f"Defensive level: {defense_level}\n"
        f"Avg conceded: "
        f"{overall['avg_against']:.2f}\n"
        f"Clean sheets: "
        f"{pct(overall['clean'])}\n"
        f"Conceding rate: "
        f"{pct(overall['conceding'])}\n"
    )

    if venue:

        text += (
            f"Recent venue avg conceded: "
            f"{venue['avg_against']:.2f}\n"
            f"Recent venue clean sheets: "
            f"{pct(venue['clean'])}"
        )

    return text


# ============================================================
# GOAL ENVIRONMENT
# ============================================================

def goal_environment(
    stats1,
    stats2
):

    avg_attack = mean(
        [
            stats1["avg_for"],
            stats2["avg_for"],
        ]
    )

    avg_conceded = mean(
        [
            stats1["avg_against"],
            stats2["avg_against"],
        ]
    )

    combined = (
        avg_attack
        + avg_conceded
    )

    if combined >= 3.0:

        level = "🔥 HIGH"

    elif combined >= 2.5:

        level = "🟢 GOOD"

    elif combined >= 2.0:

        level = "🟡 MODERATE"

    else:

        level = "🔴 LOW"

    return (
        avg_attack,
        avg_conceded,
        combined,
        level,
    )


# ============================================================
# CONFIDENCE ENGINE
# ============================================================

def confidence_score(
    overall,
    venue,
    market
):

    if not overall:
        return 0

    if market == "over05":

        overall_signal = overall["over05"]

        venue_signal = (
            venue["over05"]
            if venue
            else overall_signal
        )

    elif market == "over15":

        overall_signal = overall["over15"]

        venue_signal = (
            venue["over15"]
            if venue
            else overall_signal
        )

    elif market == "over25":

        overall_signal = overall["over25"]

        venue_signal = (
            venue["over25"]
            if venue
            else overall_signal
        )

    elif market == "under35":

        overall_signal = overall["under35"]

        venue_signal = (
            venue["under35"]
            if venue
            else overall_signal
        )

    elif market == "btts":

        overall_signal = overall["btts"]

        venue_signal = (
            venue["btts"]
            if venue
            else overall_signal
        )

    elif market == "score":

        overall_signal = overall["scoring"]

        venue_signal = (
            venue["scoring"]
            if venue
            else overall_signal
        )

    elif market == "two_to_four":

        overall_signal = overall["two_to_four"]

        venue_signal = (
            venue["two_to_four"]
            if venue
            else overall_signal
        )

    else:

        return 0

    # --------------------------------------------------------
    # SAMPLE RELIABILITY
    # --------------------------------------------------------

    if venue:

        sample = venue["sample"]

        if sample >= 7:

            reliability = 100

        elif sample >= 5:

            reliability = 90

        elif sample >= 3:

            reliability = 75

        elif sample >= 2:

            reliability = 60

        else:

            reliability = 40

    else:

        reliability = 50

    # --------------------------------------------------------
    # AGREEMENT
    # --------------------------------------------------------

    difference = abs(
        overall_signal
        - venue_signal
    )

    if difference <= 10:

        agreement = 100

    elif difference <= 20:

        agreement = 85

    elif difference <= 30:

        agreement = 70

    elif difference <= 40:

        agreement = 55

    else:

        agreement = 40

    # --------------------------------------------------------
    # BASE CONFIDENCE
    # --------------------------------------------------------

    confidence = (
        overall_signal * 0.45
        + venue_signal * 0.30
        + reliability * 0.15
        + agreement * 0.10
    )

    # --------------------------------------------------------
    # COUNTER SIGNAL
    # --------------------------------------------------------

    if venue:

        if market == "over05":

            counter_signal = (
                venue["over05"] < 50
            )

        elif market == "over15":

            counter_signal = (
                venue["over15"] < 50
            )

        elif market == "over25":

            counter_signal = (
                venue["over25"] < 50
            )

        elif market == "under35":

            counter_signal = (
                venue["under35"] < 50
            )

        elif market == "btts":

            counter_signal = (
                venue["btts"] < 50
            )

        elif market == "score":

            counter_signal = (
                venue["scoring"] < 50
            )

        elif market == "two_to_four":

            counter_signal = (
                venue["two_to_four"] < 50
            )

        else:

            counter_signal = False

        if counter_signal:

            confidence -= 8

    # --------------------------------------------------------
    # CONSERVATIVE CAPS
    # --------------------------------------------------------

    if venue:

        if venue["sample"] < 3:

            confidence = min(
                confidence,
                75
            )

        elif venue["sample"] < 5:

            confidence = min(
                confidence,
                82
            )

        elif venue["sample"] < 7:

            confidence = min(
                confidence,
                86
            )

        else:

            confidence = min(
                confidence,
                90
            )

    else:

        confidence = min(
            confidence,
            80
        )

    confidence = max(
        0,
        min(90, confidence)
    )

    return round(confidence)


# ============================================================
# SMART MARKET SELECTION ENGINE
# ============================================================

def market_priority_score(
    market,
    confidence
):

    """
    Confidence is not the only factor.

    This function gives each market a usefulness
    adjustment so that very broad markets such as
    Over 0.5 do not automatically become the primary
    signal.
    """

    priority_adjustments = {

        # Broad market.
        # Still displayed, but less useful as the
        # primary statistical signal.
        "Over 0.5 Goals": -12,

        # Strong general goal market.
        "Over 1.5 Goals": -2,

        # Useful goal market.
        "Over 2.5 Goals": 0,

        # Useful defensive/goal-control market.
        "Under 3.5 Goals": 0,

        # Useful attacking market.
        "BTTS — Yes": 0,

        # Team scoring markets.
        # Small neutral adjustment.
        "2–4 Total Goals": -1,
    }

    adjustment = priority_adjustments.get(
        market,
        0
    )

    score = (
        confidence
        + adjustment
    )

    return max(
        0,
        score
    )


def market_selection(markets):

    """
    Rank markets using both confidence and
    market usefulness.
    """

    scored_markets = []

    for market, confidence in markets.items():

        selection_score = (
            market_priority_score(
                market,
                confidence
            )
        )

        scored_markets.append(
            {
                "market": market,
                "confidence": confidence,
                "score": selection_score,
            }
        )

    scored_markets.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    primary = (
        scored_markets[0]
        if scored_markets
        else None
    )

    secondary = (
        scored_markets[1]
        if len(scored_markets) > 1
        else None
    )

    return primary, secondary


def get_risk_flags(markets):

    risks = []

    for market, confidence in markets.items():

        if confidence < 60:

            risks.append(
                f"{market} ({confidence}%)"
            )

    return risks


# ============================================================
# GRADING
# ============================================================

def grade(confidence):

    if confidence >= 80:

        return "🔥 STRONG"

    elif confidence >= 70:

        return "🟢 GOOD"

    elif confidence >= 60:

        return "🟡 MODERATE"

    return "🔴 AVOID"


def advice(confidence):

    if confidence >= 70:

        return "BET"

    elif confidence >= 60:

        return "CAUTION"

    return "AVOID"


# ============================================================
# MARKET REASONS
# ============================================================

def market_reason(
    market,
    team1_name,
    team2_name,
    stats1,
    stats2,
    venue1,
    venue2
):

    reasons = []

    if market == "Over 0.5 Goals":

        if stats1["over05"] >= 80:

            reasons.append(
                f"{team1_name} had goals in "
                f"{stats1['over05']:.0f}% "
                f"of recent matches"
            )

        if stats2["over05"] >= 80:

            reasons.append(
                f"{team2_name} had goals in "
                f"{stats2['over05']:.0f}% "
                f"of recent matches"
            )

        if venue1 and venue1["over05"] >= 80:

            reasons.append(
                f"recent home Over 0.5 rate is "
                f"{venue1['over05']:.0f}%"
            )

        if venue2 and venue2["over05"] >= 80:

            reasons.append(
                f"recent away Over 0.5 rate is "
                f"{venue2['over05']:.0f}%"
            )

    elif market == "Over 1.5 Goals":

        if stats1["over15"] >= 80:

            reasons.append(
                f"{team1_name} has a "
                f"{stats1['over15']:.0f}% recent "
                f"Over 1.5 rate"
            )

        if stats2["over15"] >= 80:

            reasons.append(
                f"{team2_name} has a "
                f"{stats2['over15']:.0f}% recent "
                f"Over 1.5 rate"
            )

        combined = mean(
            [
                stats1["avg_total"],
                stats2["avg_total"],
            ]
        )

        if combined >= 2.5:

            reasons.append(
                f"combined recent goal average "
                f"is {combined:.1f}"
            )

        if venue1 and venue1["over15"] < 50:

            reasons.append(
                f"{team1_name} home Over 1.5 "
                f"rate is only "
                f"{venue1['over15']:.0f}% "
                f"— counter-signal"
            )

        if venue2 and venue2["over15"] < 50:

            reasons.append(
                f"{team2_name} away Over 1.5 "
                f"rate is only "
                f"{venue2['over15']:.0f}% "
                f"— counter-signal"
            )

    elif market == "Over 2.5 Goals":

        if stats1["over25"] >= 70:

            reasons.append(
                f"{team1_name} has a "
                f"{stats1['over25']:.0f}% recent "
                f"Over 2.5 rate"
            )

        if stats2["over25"] >= 70:

            reasons.append(
                f"{team2_name} has a "
                f"{stats2['over25']:.0f}% recent "
                f"Over 2.5 rate"
            )

        combined = mean(
            [
                stats1["avg_total"],
                stats2["avg_total"],
            ]
        )

        if combined >= 2.8:

            reasons.append(
                f"combined recent goal average "
                f"is {combined:.1f}"
            )

        if venue1 and venue1["over25"] < 50:

            reasons.append(
                f"{team1_name} home Over 2.5 "
                f"rate is only "
                f"{venue1['over25']:.0f}% "
                f"— counter-signal"
            )

        if venue2 and venue2["over25"] < 50:

            reasons.append(
                f"{team2_name} away Over 2.5 "
                f"rate is only "
                f"{venue2['over25']:.0f}% "
                f"— counter-signal"
            )

    elif market == "Under 3.5 Goals":

        if stats1["under35"] >= 70:

            reasons.append(
                f"{team1_name} stayed under "
                f"3.5 goals in "
                f"{stats1['under35']:.0f}% "
                f"of recent matches"
            )

        if stats2["under35"] >= 70:

            reasons.append(
                f"{team2_name} stayed under "
                f"3.5 goals in "
                f"{stats2['under35']:.0f}% "
                f"of recent matches"
            )

        if venue1 and venue1["under35"] < 50:

            reasons.append(
                f"{team1_name} home Under 3.5 "
                f"rate is only "
                f"{venue1['under35']:.0f}% "
                f"— counter-signal"
            )

        if venue2 and venue2["under35"] < 50:

            reasons.append(
                f"{team2_name} away Under 3.5 "
                f"rate is only "
                f"{venue2['under35']:.0f}% "
                f"— counter-signal"
            )

    elif market == "BTTS — Yes":

        if stats1["scoring"] >= 80:

            reasons.append(
                f"{team1_name} scores in "
                f"{stats1['scoring']:.0f}% "
                f"of recent matches"
            )

        if stats2["scoring"] >= 80:

            reasons.append(
                f"{team2_name} scores in "
                f"{stats2['scoring']:.0f}% "
                f"of recent matches"
            )

        if venue1 and venue1["btts"] >= 70:

            reasons.append(
                f"recent home BTTS rate is "
                f"{venue1['btts']:.0f}%"
            )

        if venue2 and venue2["btts"] >= 70:

            reasons.append(
                f"recent away BTTS rate is "
                f"{venue2['btts']:.0f}%"
            )

        if venue1 and venue1["clean"] >= 50:

            reasons.append(
                f"{team1_name} recent home "
                f"clean-sheet rate is "
                f"{venue1['clean']:.0f}% "
                f"— counter-signal"
            )

        if venue2 and venue2["clean"] >= 50:

            reasons.append(
                f"{team2_name} recent away "
                f"clean-sheet rate is "
                f"{venue2['clean']:.0f}% "
                f"— counter-signal"
            )

    elif market == f"{team1_name} to Score":

        reasons.append(
            f"{team1_name} scores in "
            f"{stats1['scoring']:.0f}% "
            f"of recent matches"
        )

        if venue1:

            reasons.append(
                f"recent home scoring rate is "
                f"{venue1['scoring']:.0f}%"
            )

            if venue1["scoring"] < 50:

                reasons.append(
                    "home scoring trend is a "
                    "counter-signal"
                )

    elif market == f"{team2_name} to Score":

        reasons.append(
            f"{team2_name} scores in "
            f"{stats2['scoring']:.0f}% "
            f"of recent matches"
        )

        if venue2:

            reasons.append(
                f"recent away scoring rate is "
                f"{venue2['scoring']:.0f}%"
            )

            if venue2["scoring"] < 50:

                reasons.append(
                    "away scoring trend is a "
                    "counter-signal"
                )

    elif market == "2–4 Total Goals":

        if stats1["two_to_four"] >= 70:

            reasons.append(
                f"{team1_name} had 2–4 total goals "
                f"in {stats1['two_to_four']:.0f}% "
                f"of recent matches"
            )

        if stats2["two_to_four"] >= 70:

            reasons.append(
                f"{team2_name} had 2–4 total goals "
                f"in {stats2['two_to_four']:.0f}% "
                f"of recent matches"
            )

        if venue1 and venue1["two_to_four"] >= 70:

            reasons.append(
                f"recent home 2–4 goal rate is "
                f"{venue1['two_to_four']:.0f}%"
            )

        if venue2 and venue2["two_to_four"] >= 70:

            reasons.append(
                f"recent away 2–4 goal rate is "
                f"{venue2['two_to_four']:.0f}%"
            )

    if not reasons:

        reasons.append(
            "Recent statistics provide a mixed "
            "signal for this market"
        )

    return "; ".join(reasons)


# ============================================================
# ANALYSIS
# ============================================================

def analyze_match(
    team1_name,
    team2_name
):

    team1 = search_team(
        team1_name
    )

    team2 = search_team(
        team2_name
    )

    if not team1:

        return (
            f"❌ I couldn't find "
            f"{team1_name} in OpenFoot."
        )

    if not team2:

        return (
            f"❌ I couldn't find "
            f"{team2_name} in OpenFoot."
        )

    team1_id = get_team_id(team1)
    team2_id = get_team_id(team2)

    if not team1_id or not team2_id:

        return (
            "❌ Team information "
            "could not be resolved."
        )

    matches1 = get_team_matches(
        team1_id
    )

    matches2 = get_team_matches(
        team2_id
    )

    records1 = build_team_records(
        matches1,
        team1_id
    )

    records2 = build_team_records(
        matches2,
        team2_id
    )

    records1 = records1[:5]
    records2 = records2[:5]

    stats1 = calculate_stats(
        records1
    )

    stats2 = calculate_stats(
        records2
    )

    if not stats1 or not stats2:

        return (
            "⚠️ Football data could not "
            "be retrieved for both teams.\n"
            "Please try again."
        )

    # --------------------------------------------------------
    # VENUE RECORDS
    # --------------------------------------------------------

    home_records = [
        r for r in records1
        if r["venue"] == "home"
    ]

    away_records = [
        r for r in records2
        if r["venue"] == "away"
    ]

    home_stats = calculate_stats(
        home_records
    )

    away_stats = calculate_stats(
        away_records
    )

    # --------------------------------------------------------
    # GOAL ENVIRONMENT
    # --------------------------------------------------------

    (
        avg_attack,
        avg_conceded,
        combined,
        environment,
    ) = goal_environment(
        stats1,
        stats2
    )

    # --------------------------------------------------------
    # CONFIDENCE
    # --------------------------------------------------------

    over05_1 = confidence_score(
        stats1,
        home_stats,
        "over05"
    )

    over05_2 = confidence_score(
        stats2,
        away_stats,
        "over05"
    )

    over15_1 = confidence_score(
        stats1,
        home_stats,
        "over15"
    )

    over15_2 = confidence_score(
        stats2,
        away_stats,
        "over15"
    )

    over25_1 = confidence_score(
        stats1,
        home_stats,
        "over25"
    )

    over25_2 = confidence_score(
        stats2,
        away_stats,
        "over25"
    )

    under35_1 = confidence_score(
        stats1,
        home_stats,
        "under35"
    )

    under35_2 = confidence_score(
        stats2,
        away_stats,
        "under35"
    )

    btts_1 = confidence_score(
        stats1,
        home_stats,
        "btts"
    )

    btts_2 = confidence_score(
        stats2,
        away_stats,
        "btts"
    )

    score1_conf = confidence_score(
        stats1,
        home_stats,
        "score"
    )

    score2_conf = confidence_score(
        stats2,
        away_stats,
        "score"
    )

    range1_conf = confidence_score(
        stats1,
        home_stats,
        "two_to_four"
    )

    range2_conf = confidence_score(
        stats2,
        away_stats,
        "two_to_four"
    )

    # --------------------------------------------------------
    # COMBINE TEAM SIGNALS
    # --------------------------------------------------------

    over05_conf = round(
        (
            over05_1
            + over05_2
        ) / 2
    )

    over15_conf = round(
        (
            over15_1
            + over15_2
        ) / 2
    )

    over25_conf = round(
        (
            over25_1
            + over25_2
        ) / 2
    )

    under35_conf = round(
        (
            under35_1
            + under35_2
        ) / 2
    )

    btts_conf = round(
        (
            btts_1
            + btts_2
        ) / 2
    )

    range_conf = round(
        (
            range1_conf
            + range2_conf
        ) / 2
    )

    # --------------------------------------------------------
    # GOAL ENVIRONMENT ADJUSTMENTS
    # --------------------------------------------------------

    if combined >= 3.0:

        over05_conf = min(
            90,
            over05_conf + 3
        )

        over15_conf = min(
            90,
            over15_conf + 4
        )

        over25_conf = min(
            90,
            over25_conf + 3
        )

    elif combined < 2.0:

        over05_conf = max(
            0,
            over05_conf - 3
        )

        over15_conf = max(
            0,
            over15_conf - 5
        )

        over25_conf = max(
            0,
            over25_conf - 7
        )

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    team1_display = get_team_name(
        team1
    )

    team2_display = get_team_name(
        team2
    )

    markets = {

        "Over 0.5 Goals":
            over05_conf,

        "Over 1.5 Goals":
            over15_conf,

        "Over 2.5 Goals":
            over25_conf,

        "Under 3.5 Goals":
            under35_conf,

        "BTTS — Yes":
            btts_conf,

        f"{team1_display} to Score":
            score1_conf,

        f"{team2_display} to Score":
            score2_conf,

        "2–4 Total Goals":
            range_conf,
    }

    # --------------------------------------------------------
    # SMART MARKET SELECTION
    # --------------------------------------------------------

    primary, secondary = (
        market_selection(markets)
    )

    if primary:

        primary_market = primary[
            "market"
        ]

        primary_conf = primary[
            "confidence"
        ]

    else:

        primary_market = "No clear signal"
        primary_conf = 0

    if secondary:

        secondary_market = secondary[
            "market"
        ]

        secondary_conf = secondary[
            "confidence"
        ]

    else:

        secondary_market = None
        secondary_conf = 0

    risk_flags = get_risk_flags(
        markets
    )

    # --------------------------------------------------------
    # FORM
    # --------------------------------------------------------

    form1 = form_string(
        records1
    )

    form2 = form_string(
        records2
    )

    if stats1["wins"] > stats2["wins"]:

        form_assessment = (
            f"{team1_display} "
            "has the stronger recent form."
        )

    elif stats2["wins"] > stats1["wins"]:

        form_assessment = (
            f"{team2_display} "
            "has the stronger recent form."
        )

    else:

        form_assessment = (
            "Both teams have similar "
            "recent win totals."
        )

    # ========================================================
    # RESPONSE
    # ========================================================

    output = (
        "⚽ GOALLOGIC AI — ADVANCED ANALYSIS\n\n"
        f"{team1_display} vs {team2_display}\n"
        f"Season: {CURRENT_SEASON}\n\n"
    )

    # --------------------------------------------------------
    # TEAM 1
    # --------------------------------------------------------

    output += (
        f"📊 {team1_display.upper()} — LAST 5\n"
        f"Form: {form1}\n"
        f"W/D/L: "
        f"{stats1['wins']}/"
        f"{stats1['draws']}/"
        f"{stats1['losses']}\n"
        f"Goals scored: "
        f"{stats1['goals_for']}\n"
        f"Goals conceded: "
        f"{stats1['goals_against']}\n"
        f"Avg scored: "
        f"{stats1['avg_for']:.1f}\n"
        f"Avg conceded: "
        f"{stats1['avg_against']:.1f}\n"
        f"Avg total goals: "
        f"{stats1['avg_total']:.1f}\n"
        f"Over 0.5: "
        f"{pct(stats1['over05'])}\n"
        f"Over 1.5: "
        f"{pct(stats1['over15'])}\n"
        f"Over 2.5: "
        f"{pct(stats1['over25'])}\n"
        f"Under 3.5: "
        f"{pct(stats1['under35'])}\n"
        f"BTTS: "
        f"{pct(stats1['btts'])}\n"
        f"Scoring consistency: "
        f"{pct(stats1['scoring'])}\n"
        f"Clean sheets: "
        f"{pct(stats1['clean'])}\n"
        f"Sample: "
        f"{stats1['sample']} matches\n\n"
    )

    # --------------------------------------------------------
    # HOME
    # --------------------------------------------------------

    if home_stats:

        output += (
            f"🏠 {team1_display.upper()} — "
            "RECENT HOME\n"
            f"Form: "
            f"{form_string(home_records)}\n"
            f"W/D/L: "
            f"{home_stats['wins']}/"
            f"{home_stats['draws']}/"
            f"{home_stats['losses']}\n"
            f"Avg scored: "
            f"{home_stats['avg_for']:.1f}\n"
            f"Avg conceded: "
            f"{home_stats['avg_against']:.1f}\n"
            f"Over 1.5: "
            f"{pct(home_stats['over15'])}\n"
            f"Over 2.5: "
            f"{pct(home_stats['over25'])}\n"
            f"BTTS: "
            f"{pct(home_stats['btts'])}\n"
            f"Clean sheets: "
            f"{pct(home_stats['clean'])}\n"
            f"Sample: "
            f"{home_stats['sample']} matches\n"
        )

        if home_stats["sample"] < 3:

            output += (
                "⚠️ Very small sample.\n"
            )

        elif home_stats["sample"] < 5:

            output += (
                "⚠️ Limited sample.\n"
            )

        output += "\n"

    # --------------------------------------------------------
    # TEAM 2
    # --------------------------------------------------------

    output += (
        f"📊 {team2_display.upper()} — LAST 5\n"
        f"Form: {form2}\n"
        f"W/D/L: "
        f"{stats2['wins']}/"
        f"{stats2['draws']}/"
        f"{stats2['losses']}\n"
        f"Goals scored: "
        f"{stats2['goals_for']}\n"
        f"Goals conceded: "
        f"{stats2['goals_against']}\n"
        f"Avg scored: "
        f"{stats2['avg_for']:.1f}\n"
        f"Avg conceded: "
        f"{stats2['avg_against']:.1f}\n"
        f"Avg total goals: "
        f"{stats2['avg_total']:.1f}\n"
        f"Over 0.5: "
        f"{pct(stats2['over05'])}\n"
        f"Over 1.5: "
        f"{pct(stats2['over15'])}\n"
        f"Over 2.5: "
        f"{pct(stats2['over25'])}\n"
        f"Under 3.5: "
        f"{pct(stats2['under35'])}\n"
        f"BTTS: "
        f"{pct(stats2['btts'])}\n"
        f"Scoring consistency: "
        f"{pct(stats2['scoring'])}\n"
        f"Clean sheets: "
        f"{pct(stats2['clean'])}\n"
        f"Sample: "
        f"{stats2['sample']} matches\n\n"
    )

    # --------------------------------------------------------
    # AWAY
    # --------------------------------------------------------

    if away_stats:

        output += (
            f"✈️ {team2_display.upper()} — "
            "RECENT AWAY\n"
            f"Form: "
            f"{form_string(away_records)}\n"
            f"W/D/L: "
            f"{away_stats['wins']}/"
            f"{away_stats['draws']}/"
            f"{away_stats['losses']}\n"
            f"Avg scored: "
            f"{away_stats['avg_for']:.1f}\n"
            f"Avg conceded: "
            f"{away_stats['avg_against']:.1f}\n"
            f"Over 1.5: "
            f"{pct(away_stats['over15'])}\n"
            f"Over 2.5: "
            f"{pct(away_stats['over25'])}\n"
            f"BTTS: "
            f"{pct(away_stats['btts'])}\n"
            f"Clean sheets: "
            f"{pct(away_stats['clean'])}\n"
            f"Sample: "
            f"{away_stats['sample']} matches\n"
        )

        if away_stats["sample"] < 3:

            output += (
                "⚠️ Very small sample.\n"
            )

        elif away_stats["sample"] < 5:

            output += (
                "⚠️ Limited sample.\n"
            )

        output += "\n"

    # --------------------------------------------------------
    # PROFILES
    # --------------------------------------------------------

    output += (
        attacking_profile(
            team1_display,
            stats1,
            home_stats
        )
        + "\n\n"
    )

    output += (
        defensive_profile(
            team2_display,
            stats2,
            away_stats
        )
        + "\n\n"
    )

    # --------------------------------------------------------
    # GOAL ENVIRONMENT
    # --------------------------------------------------------

    output += (
        "🎯 GOAL & DEFENSIVE INTELLIGENCE\n"
        f"Average attacking output: "
        f"{avg_attack:.2f} goals\n"
        f"Average goals conceded: "
        f"{avg_conceded:.2f} goals\n"
        f"Combined goal environment: "
        f"{combined:.2f}\n"
        f"Goal environment: "
        f"{environment}\n\n"
    )

    # --------------------------------------------------------
    # FORM ASSESSMENT
    # --------------------------------------------------------

    output += (
        "📈 FORM ASSESSMENT\n"
        f"{form_assessment}\n\n"
    )

    # --------------------------------------------------------
    # MARKET SIGNALS
    # --------------------------------------------------------

    output += (
        "📊 MARKET SIGNALS\n\n"
    )

    for market, confidence in markets.items():

        reason = market_reason(
            market,
            team1_display,
            team2_display,
            stats1,
            stats2,
            home_stats,
            away_stats
        )

        output += (
            f"{market} — "
            f"Confidence {confidence}%\n"
            f"Grade: "
            f"{grade(confidence)}\n"
            f"Advice: "
            f"{advice(confidence)}\n"
            f"Reason: "
            f"{reason}\n\n"
        )

    # --------------------------------------------------------
    # SMART PRIMARY SIGNAL
    # --------------------------------------------------------

    output += (
        "⭐ PRIMARY STATISTICAL SIGNAL\n"
        f"{primary_market} — "
        f"Confidence {primary_conf}%\n"
        f"Grade: "
        f"{grade(primary_conf)}\n"
        f"Advice: "
        f"{advice(primary_conf)}\n\n"
    )

    # --------------------------------------------------------
    # SECONDARY SIGNAL
    # --------------------------------------------------------

    if secondary_market:

        output += (
            "🥈 SECONDARY STATISTICAL SIGNAL\n"
            f"{secondary_market} — "
            f"Confidence {secondary_conf}%\n"
            f"Grade: "
            f"{grade(secondary_conf)}\n"
            f"Advice: "
            f"{advice(secondary_conf)}\n\n"
        )

    # --------------------------------------------------------
    # RISK FLAGS
    # --------------------------------------------------------

    if risk_flags:

        output += (
            "⚠️ RISK FLAGS\n"
        )

        for risk in risk_flags[:4]:

            output += (
                f"• {risk}\n"
            )

        output += "\n"

    else:

        output += (
            "✅ RISK FLAGS\n"
            "No major low-confidence markets detected.\n\n"
        )

    # --------------------------------------------------------
    # DISCLAIMER
    # --------------------------------------------------------

    output += (
        "⚠️ Statistical analysis is not a guarantee "
        "of the match outcome. Use confidence figures "
        "as indicators, not certainty."
    )

    return output


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = (
        "⚽ GOALLOGIC AI\n\n"
        "Advanced football statistical analysis.\n\n"
        "Send a match like:\n"
        "Chelsea vs Arsenal\n\n"
        "Or use:\n"
        "/analyze Chelsea vs Arsenal\n\n"
        "Use /apitest to check the OpenFoot connection."
    )

    await update.message.reply_text(
        message
    )


async def api_test(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    data = openfoot_get(
        "/v1/search",
        {"q": "Chelsea"}
    )

    if data is not None:

        await update.message.reply_text(
            "✅ OPENFOOT TEST PASSED\n\n"
            "OpenFoot API is connected successfully."
        )

    else:

        await update.message.reply_text(
            "❌ OPENFOOT TEST FAILED\n\n"
            "The API could not be reached "
            "or the API key was rejected."
        )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = " ".join(
        context.args
    ).strip()

    if not text:

        await update.message.reply_text(
            "Use:\n/analyze Chelsea vs Arsenal"
        )

        return

    result = process_match_text(
        text
    )

    await update.message.reply_text(
        result,
        disable_web_page_preview=True
    )


async def normal_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if (
        not update.message
        or not update.message.text
    ):

        return

    text = update.message.text.strip()

    if " vs " not in text.lower():

        await update.message.reply_text(
            "Send a match like:\n"
            "Chelsea vs Arsenal"
        )

        return

    result = process_match_text(
        text
    )

    await update.message.reply_text(
        result,
        disable_web_page_preview=True
    )


# ============================================================
# MATCH PROCESSOR
# ============================================================

def process_match_text(text):

    parts = re.split(
        r"\s+vs\.?\s+|\s+v\.?\s+",
        text,
        flags=re.IGNORECASE
    )

    if len(parts) != 2:

        return (
            "❌ Please use this format:\n"
            "Chelsea vs Arsenal"
        )

    team1 = parts[0].strip()
    team2 = parts[1].strip()

    if not team1 or not team2:

        return (
            "❌ Please provide two teams.\n\n"
            "Example:\n"
            "Chelsea vs Arsenal"
        )

    return analyze_match(
        team1,
        team2
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

    # Start Render health server first
    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    print(
        "Starting GoalLogic AI..."
    )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "apitest",
            api_test
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
            normal_message
        )
    )

    print(
        "GoalLogic AI is ready."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
