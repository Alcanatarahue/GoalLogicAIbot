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
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

OPENFOOT_BASE = "https://openfootapi.com"
CURRENT_SEASON = "2026/27"

# Premier League
EPL_ID = "comp_premier_league_eng"

MIN_MATCHES = 3
RECENT_MATCHES = 5


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
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"GoalLogic AI health server running on port {port}")
    server.serve_forever()


# ============================================================
# OPENFOOT API
# ============================================================

def openfoot_get(endpoint, params=None):
    if not OPENFOOT_API_KEY:
        print("OPENFOOT_API_KEY is missing.")
        return []

    url = OPENFOOT_BASE + endpoint

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {OPENFOOT_API_KEY}",
    }

    try:
        print(f"OpenFoot GET: {url}")
        print(f"Parameters: {params}")

        response = requests.get(
            url,
            headers=headers,
            params=params or {},
            timeout=20,
        )

        print(f"OpenFoot HTTP status: {response.status_code}")

        try:
            body = response.json()
        except Exception:
            print("OpenFoot returned non-JSON response.")
            return []

        if response.status_code != 200:
            print(f"OpenFoot error: {body}")
            return []

        data = body.get("data", [])

        if isinstance(data, list):
            return data

        return []

    except Exception as e:
        print(f"OpenFoot request error: {e}")
        return []


def get_team_matches(team_id, team_name):
    """
    Direct team query.

    This avoids the old method of downloading the entire
    Premier League and then trying to filter Chelsea/Arsenal.
    """

    params = {
        "team": team_id,
        "season": CURRENT_SEASON,
        "status": "finished",
    }

    print("")
    print("======================================")
    print(f"TEAM REQUEST: {team_name}")
    print(f"Team ID: {team_id}")
    print(f"Season: {CURRENT_SEASON}")
    print("Status: finished")
    print("======================================")

    matches = openfoot_get("/v1/matches", params)

    completed = []

    for match in matches:
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}

        home_id = home.get("id")
        away_id = away.get("id")

        if home_id != team_id and away_id != team_id:
            continue

        score = match.get("score") or {}

        home_score = score.get("home")
        away_score = score.get("away")

        # Some API versions may expose scores differently.
        if home_score is None:
            home_score = match.get("homeScore")

        if away_score is None:
            away_score = match.get("awayScore")

        if home_score is None or away_score is None:
            continue

        match["_home_score"] = int(home_score)
        match["_away_score"] = int(away_score)

        completed.append(match)

    completed.sort(
        key=lambda x: x.get("kickoffAt", ""),
        reverse=True
    )

    print(
        f"{team_name}: {len(completed)} usable completed matches found."
    )

    return completed


# ============================================================
# TEAM DATA
# ============================================================

TEAM_DATABASE = {
    "chelsea": {
        "id": "team_chelsea_eng",
        "name": "Chelsea",
    },
    "arsenal": {
        "id": "team_arsenal_eng",
        "name": "Arsenal",
    },
    "liverpool": {
        "id": "team_liverpool_eng",
        "name": "Liverpool",
    },
    "manchester city": {
        "id": "team_manchester_city_eng",
        "name": "Manchester City",
    },
    "man city": {
        "id": "team_manchester_city_eng",
        "name": "Manchester City",
    },
    "manchester united": {
        "id": "team_manchester_united_eng",
        "name": "Manchester United",
    },
    "man united": {
        "id": "team_manchester_united_eng",
        "name": "Manchester United",
    },
    "tottenham": {
        "id": "team_tottenham_eng",
        "name": "Tottenham Hotspur",
    },
    "spurs": {
        "id": "team_tottenham_eng",
        "name": "Tottenham Hotspur",
    },
    "newcastle": {
        "id": "team_newcastle_eng",
        "name": "Newcastle United",
    },
    "aston villa": {
        "id": "team_aston_villa_eng",
        "name": "Aston Villa",
    },
    "west ham": {
        "id": "team_west_ham_eng",
        "name": "West Ham United",
    },
    "everton": {
        "id": "team_everton_eng",
        "name": "Everton",
    },
    "crystal palace": {
        "id": "team_crystal_palace_eng",
        "name": "Crystal Palace",
    },
    "brighton": {
        "id": "team_brighton_eng",
        "name": "Brighton",
    },
    "brentford": {
        "id": "team_brentford_eng",
        "name": "Brentford",
    },
    "bournemouth": {
        "id": "team_bournemouth_eng",
        "name": "Bournemouth",
    },
    "fulham": {
        "id": "team_fulham_eng",
        "name": "Fulham",
    },
    "nottingham forest": {
        "id": "team_nottingham_forest_eng",
        "name": "Nottingham Forest",
    },
    "sunderland": {
        "id": "team_sunderland_eng",
        "name": "Sunderland",
    },
    "leeds": {
        "id": "team_leeds_eng",
        "name": "Leeds United",
    },
}


def find_team(name):
    cleaned = name.lower().strip()

    if cleaned in TEAM_DATABASE:
        return TEAM_DATABASE[cleaned]

    # Partial matching
    for key, team in TEAM_DATABASE.items():
        if cleaned == key or key in cleaned:
            return team

    return None


# ============================================================
# MATCH STATISTICS
# ============================================================

def calculate_stats(matches, team_id):
    matches = matches[:RECENT_MATCHES]

    if not matches:
        return None

    wins = 0
    draws = 0
    losses = 0

    goals_for = []
    goals_against = []

    over05 = 0
    over15 = 0
    over25 = 0
    under35 = 0
    btts = 0

    scoring = 0
    clean_sheets = 0

    home_matches = 0
    away_matches = 0

    venue_goals_for = []
    venue_goals_against = []

    venue_over05 = 0
    venue_over15 = 0
    venue_over25 = 0
    venue_btts = 0
    venue_scoring = 0
    venue_clean = 0

    for match in matches:
        home = match.get("homeTeam") or {}
        away = match.get("awayTeam") or {}

        hs = match["_home_score"]
        aws = match["_away_score"]

        is_home = home.get("id") == team_id

        if is_home:
            gf = hs
            ga = aws
            home_matches += 1
        else:
            gf = aws
            ga = hs
            away_matches += 1

        goals_for.append(gf)
        goals_against.append(ga)

        if gf > ga:
            wins += 1
        elif gf == ga:
            draws += 1
        else:
            losses += 1

        total = hs + aws

        if total > 0:
            over05 += 1

        if total > 1:
            over15 += 1

        if total > 2:
            over25 += 1

        if total < 4:
            under35 += 1

        if hs > 0 and aws > 0:
            btts += 1

        if gf > 0:
            scoring += 1

        if ga == 0:
            clean_sheets += 1

        # Venue-specific statistics
        if is_home:
            venue_goals_for.append(gf)
            venue_goals_against.append(ga)

            if total > 0:
                venue_over05 += 1

            if total > 1:
                venue_over15 += 1

            if total > 2:
                venue_over25 += 1

            if hs > 0 and aws > 0:
                venue_btts += 1

            if gf > 0:
                venue_scoring += 1

            if ga == 0:
                venue_clean += 1

    n = len(matches)

    return {
        "matches": n,
        "wins": wins,
        "draws": draws,
        "losses": losses,

        "gf": sum(goals_for),
        "ga": sum(goals_against),

        "avg_gf": mean(goals_for),
        "avg_ga": mean(goals_against),
        "avg_total": mean(
            [a + b for a, b in zip(
                goals_for,
                goals_against
            )]
        ),

        "over05": 100 * over05 / n,
        "over15": 100 * over15 / n,
        "over25": 100 * over25 / n,
        "under35": 100 * under35 / n,
        "btts": 100 * btts / n,

        "scoring": 100 * scoring / n,
        "clean": 100 * clean_sheets / n,

        "home_matches": home_matches,
        "away_matches": away_matches,

        "venue_gf": mean(venue_goals_for)
        if venue_goals_for else None,

        "venue_ga": mean(venue_goals_against)
        if venue_goals_against else None,

        "venue_over05": 100 * venue_over05 / home_matches
        if home_matches else None,

        "venue_over15": 100 * venue_over15 / home_matches
        if home_matches else None,

        "venue_over25": 100 * venue_over25 / home_matches
        if home_matches else None,

        "venue_btts": 100 * venue_btts / home_matches
        if home_matches else None,

        "venue_scoring": 100 * venue_scoring / home_matches
        if home_matches else None,

        "venue_clean": 100 * venue_clean / home_matches
        if home_matches else None,
    }


def calculate_away_stats(matches, team_id):
    away_matches = []

    for match in matches:
        away = match.get("awayTeam") or {}

        if away.get("id") == team_id:
            away_matches.append(match)

    if not away_matches:
        return None

    goals_for = []
    goals_against = []

    over05 = 0
    over15 = 0
    over25 = 0
    btts = 0
    scoring = 0
    clean = 0

    for match in away_matches:
        hs = match["_home_score"]
        aws = match["_away_score"]

        gf = aws
        ga = hs

        goals_for.append(gf)
        goals_against.append(ga)

        total = hs + aws

        if total > 0:
            over05 += 1

        if total > 1:
            over15 += 1

        if total > 2:
            over25 += 1

        if hs > 0 and aws > 0:
            btts += 1

        if gf > 0:
            scoring += 1

        if ga == 0:
            clean += 1

    n = len(away_matches)

    return {
        "matches": n,
        "avg_gf": mean(goals_for),
        "avg_ga": mean(goals_against),
        "over05": 100 * over05 / n,
        "over15": 100 * over15 / n,
        "over25": 100 * over25 / n,
        "btts": 100 * btts / n,
        "scoring": 100 * scoring / n,
        "clean": 100 * clean / n,
    }


# ============================================================
# FORM
# ============================================================

def form_string(matches, team_id):
    form = []

    for match in matches[:5]:
        home = match.get("homeTeam") or {}

        hs = match["_home_score"]
        aws = match["_away_score"]

        if home.get("id") == team_id:
            gf = hs
            ga = aws
        else:
            gf = aws
            ga = hs

        if gf > ga:
            form.append("W")
        elif gf == ga:
            form.append("D")
        else:
            form.append("L")

    return "".join(form)


# ============================================================
# CONFIDENCE ENGINE
# ============================================================

def clamp(value, low=5, high=95):
    return max(low, min(high, round(value)))


def confidence_over05(a, b, home_a, away_b):
    values = [
        a["over05"],
        b["over05"],
    ]

    if home_a:
        values.append(home_a["over05"])

    if away_b:
        values.append(away_b["over05"])

    return clamp(mean(values))


def confidence_over15(a, b, home_a, away_b):
    values = [
        a["over15"],
        b["over15"],
    ]

    if home_a:
        values.append(home_a["over15"])

    if away_b:
        values.append(away_b["over15"])

    goal_environment = (
        a["avg_total"] + b["avg_total"]
    ) / 2

    confidence = mean(values) * 0.75

    if goal_environment >= 2.8:
        confidence += 10
    elif goal_environment >= 2.4:
        confidence += 5

    return clamp(confidence)


def confidence_over25(a, b, home_a, away_b):
    values = [
        a["over25"],
        b["over25"],
    ]

    if home_a:
        values.append(home_a["over25"])

    if away_b:
        values.append(away_b["over25"])

    confidence = mean(values) * 0.75

    combined = (
        a["avg_total"] + b["avg_total"]
    ) / 2

    if combined >= 3.2:
        confidence += 10
    elif combined >= 2.8:
        confidence += 5
    elif combined < 2.2:
        confidence -= 8

    return clamp(confidence)


def confidence_under35(a, b, home_a, away_b):
    values = [
        a["under35"],
        b["under35"],
    ]

    if home_a:
        values.append(
            100 - home_a["over25"]
        )

    if away_b:
        values.append(
            100 - away_b["over25"]
        )

    confidence = mean(values) * 0.85

    combined = (
        a["avg_total"] + b["avg_total"]
    ) / 2

    if combined <= 2.5:
        confidence += 8
    elif combined >= 3.5:
        confidence -= 10

    return clamp(confidence)


def confidence_btts(a, b, home_a, away_b):
    values = [
        a["btts"],
        b["btts"],
    ]

    if home_a:
        values.append(home_a["btts"])

    if away_b:
        values.append(away_b["btts"])

    scoring_strength = mean([
        a["scoring"],
        b["scoring"],
    ])

    confidence = mean(values) * 0.65

    if scoring_strength >= 80:
        confidence += 12

    # Strong clean-sheet teams reduce BTTS
    clean_strength = mean([
        a["clean"],
        b["clean"],
    ])

    if clean_strength >= 55:
        confidence -= 10

    return clamp(confidence)


def confidence_team_score(team_stats, opponent_stats, venue_stats):
    values = [
        team_stats["scoring"],
        100 - opponent_stats["clean"],
    ]

    if venue_stats:
        values.append(venue_stats["scoring"])

    return clamp(mean(values))


# ============================================================
# DOUBLE CHANCE
# ============================================================

def confidence_double_chance(
    home_stats,
    away_stats,
    home_venue,
    away_venue,
):
    """
    Calculates 1X, X2 and 12 from recent W/D/L form.

    Home venue and away venue data receive extra weight when
    available, but tiny samples are not allowed to dominate.
    """

    home_total = home_stats["matches"]
    away_total = away_stats["matches"]

    home_win = home_stats["wins"] / home_total * 100
    home_draw = home_stats["draws"] / home_total * 100

    away_win = away_stats["wins"] / away_total * 100
    away_draw = away_stats["draws"] / away_total * 100

    # Recent overall probabilities
    one_x_base = home_win + home_draw
    x_two_base = away_win + away_draw
    twelve_base = 100 - (
        (
            home_draw +
            away_draw
        ) / 2
    )

    # Venue adjustment
    one_x = one_x_base

    if home_venue and home_venue["matches"] >= 2:
        venue_one_x = (
            home_venue["wins"] +
            home_venue["draws"]
        ) / home_venue["matches"] * 100

        one_x = (
            one_x_base * 0.65 +
            venue_one_x * 0.35
        )

    x_two = x_two_base

    if away_venue and away_venue["matches"] >= 2:
        venue_x_two = (
            away_venue["wins"] +
            away_venue["draws"]
        ) / away_venue["matches"] * 100

        x_two = (
            x_two_base * 0.65 +
            venue_x_two * 0.35
        )

    # 12 uses draw avoidance from both teams
    twelve = twelve_base

    return {
        "1X": clamp(one_x),
        "X2": clamp(x_two),
        "12": clamp(twelve),
    }


# ============================================================
# GRADING
# ============================================================

def grade(confidence):
    if confidence >= 80:
        return "🔥 STRONG", "BET"
    if confidence >= 70:
        return "🟢 GOOD", "BET"
    if confidence >= 60:
        return "🟡 MODERATE", "CAUTION"
    return "🔴 WEAK", "AVOID"


# ============================================================
# TELEGRAM HELPERS
# ============================================================

def market_line(name, confidence, reason):
    g, advice = grade(confidence)

    return (
        f"{name} — Confidence {confidence}%\n"
        f"Grade: {g}\n"
        f"Advice: {advice}\n"
        f"Reason: {reason}\n"
    )


def team_summary(name, stats, form):
    return (
        f"📊 {name.upper()} — LAST {stats['matches']}\n"
        f"Form: {form}\n"
        f"W/D/L: "
        f"{stats['wins']}/"
        f"{stats['draws']}/"
        f"{stats['losses']}\n"
        f"Goals scored: {stats['gf']}\n"
        f"Goals conceded: {stats['ga']}\n"
        f"Avg scored: {stats['avg_gf']:.2f}\n"
        f"Avg conceded: {stats['avg_ga']:.2f}\n"
        f"Avg total goals: {stats['avg_total']:.2f}\n"
        f"Over 0.5: {stats['over05']:.0f}%\n"
        f"Over 1.5: {stats['over15']:.0f}%\n"
        f"Over 2.5: {stats['over25']:.0f}%\n"
        f"Under 3.5: {stats['under35']:.0f}%\n"
        f"BTTS: {stats['btts']:.0f}%\n"
        f"Scoring consistency: {stats['scoring']:.0f}%\n"
        f"Clean sheets: {stats['clean']:.0f}%\n"
    )


# ============================================================
# ANALYSIS
# ============================================================

async def analyze_match(update, team1_name, team2_name):
    team1 = find_team(team1_name)
    team2 = find_team(team2_name)

    if not team1:
        await update.message.reply_text(
            f"❌ I couldn't identify {team1_name}."
        )
        return

    if not team2:
        await update.message.reply_text(
            f"❌ I couldn't identify {team2_name}."
        )
        return

    await update.message.reply_text(
        "🔎 GoalLogic AI is collecting recent completed matches..."
    )

    matches1 = get_team_matches(
        team1["id"],
        team1["name"]
    )

    matches2 = get_team_matches(
        team2["id"],
        team2["name"]
    )

    if len(matches1) < MIN_MATCHES:
        await update.message.reply_text(
            f"⚠️ OpenFoot returned only "
            f"{len(matches1)} usable completed matches "
            f"for {team1['name']}.\n\n"
            f"Team ID: {team1['id']}\n"
            f"Season: {CURRENT_SEASON}"
        )
        return

    if len(matches2) < MIN_MATCHES:
        await update.message.reply_text(
            f"⚠️ OpenFoot returned only "
            f"{len(matches2)} usable completed matches "
            f"for {team2['name']}.\n\n"
            f"Team ID: {team2['id']}\n"
            f"Season: {CURRENT_SEASON}"
        )
        return

    recent1 = matches1[:RECENT_MATCHES]
    recent2 = matches2[:RECENT_MATCHES]

    stats1 = calculate_stats(
        recent1,
        team1["id"]
    )

    stats2 = calculate_stats(
        recent2,
        team2["id"]
    )

    # Home statistics for team 1
    home_matches = [
        m for m in matches1
        if (m.get("homeTeam") or {}).get("id")
        == team1["id"]
    ][:3]

    home_stats = calculate_stats(
        home_matches,
        team1["id"]
    ) if home_matches else None

    # Away statistics for team 2
    away_matches = [
        m for m in matches2
        if (m.get("awayTeam") or {}).get("id")
        == team2["id"]
    ][:3]

    away_stats = calculate_stats(
        away_matches,
        team2["id"]
    ) if away_matches else None

    # Correctly calculated away-specific stats
    away_specific = calculate_away_stats(
        recent2,
        team2["id"]
    )

    # Convert venue data into a form suitable for double chance
    home_dc = {
        "matches": len(home_matches),
        "wins": 0,
        "draws": 0,
    }

    for m in home_matches:
        hs = m["_home_score"]
        aws = m["_away_score"]

        if hs > aws:
            home_dc["wins"] += 1
        elif hs == aws:
            home_dc["draws"] += 1

    away_dc = {
        "matches": len(away_matches),
        "wins": 0,
        "draws": 0,
    }

    for m in away_matches:
        hs = m["_home_score"]
        aws = m["_away_score"]

        if aws > hs:
            away_dc["wins"] += 1
        elif aws == hs:
            away_dc["draws"] += 1

    # Double chance
    dc = confidence_double_chance(
        stats1,
        stats2,
        home_dc,
        away_dc,
    )

    # Goal markets
    over05 = confidence_over05(
        stats1,
        stats2,
        home_stats,
        away_specific,
    )

    over15 = confidence_over15(
        stats1,
        stats2,
        home_stats,
        away_specific,
    )

    over25 = confidence_over25(
        stats1,
        stats2,
        home_stats,
        away_specific,
    )

    under35 = confidence_under35(
        stats1,
        stats2,
        home_stats,
        away_specific,
    )

    btts = confidence_btts(
        stats1,
        stats2,
        home_stats,
        away_specific,
    )

    team1_score = confidence_team_score(
        stats1,
        stats2,
        home_stats,
    )

    team2_score = confidence_team_score(
        stats2,
        stats1,
        away_specific,
    )

    # Combined environment
    combined_avg = (
        stats1["avg_total"] +
        stats2["avg_total"]
    ) / 2

    # Select primary signal from useful markets.
    candidates = {
        "1X": dc["1X"],
        "X2": dc["X2"],
        "12": dc["12"],
        "Over 1.5": over15,
        "Over 2.5": over25,
        "Under 3.5": under35,
        "BTTS": btts,
        f"{team1['name']} to score": team1_score,
        f"{team2['name']} to score": team2_score,
    }

    # Avoid making Over 0.5 the automatic primary signal.
    primary_name = max(
        candidates,
        key=candidates.get
    )

    primary_confidence = candidates[primary_name]

    primary_grade, primary_advice = grade(
        primary_confidence
    )

    form1 = form_string(
        recent1,
        team1["id"]
    )

    form2 = form_string(
        recent2,
        team2["id"]
    )

    # ========================================================
    # BUILD RESPONSE
    # ========================================================

    response = (
        "⚽ GOALLOGIC AI — MATCH ANALYSIS\n\n"
        f"{team1['name']} vs {team2['name']}\n"
        f"Season: {CURRENT_SEASON}\n\n"
    )

    response += team_summary(
        team1["name"],
        stats1,
        form1
    )

    response += "\n"

    response += team_summary(
        team2["name"],
        stats2,
        form2
    )

    response += "\n"

    response += (
        "🏠 HOME / AWAY CONTEXT\n\n"
    )

    if home_stats:
        response += (
            f"{team1['name']} home sample: "
            f"{home_stats['matches']} matches\n"
            f"Home scoring: "
            f"{home_stats['scoring']:.0f}%\n"
            f"Home Over 2.5: "
            f"{home_stats['over25']:.0f}%\n"
            f"Home BTTS: "
            f"{home_stats['btts']:.0f}%\n\n"
        )
    else:
        response += (
            f"{team1['name']} home sample: "
            "Not enough data\n\n"
        )

    if away_specific:
        response += (
            f"{team2['name']} away sample: "
            f"{away_specific['matches']} matches\n"
            f"Away scoring: "
            f"{away_specific['scoring']:.0f}%\n"
            f"Away Over 2.5: "
            f"{away_specific['over25']:.0f}%\n"
            f"Away BTTS: "
            f"{away_specific['btts']:.0f}%\n\n"
        )
    else:
        response += (
            f"{team2['name']} away sample: "
            "Not enough data\n\n"
        )

    response += (
        "🎯 DOUBLE CHANCE\n\n"
    )

    response += market_line(
        "1X — Home Win or Draw",
        dc["1X"],
        (
            f"{team1['name']} recent W/D rate is "
            f"{(stats1['wins'] + stats1['draws']) / stats1['matches'] * 100:.0f}%"
        )
    )

    response += market_line(
        "X2 — Draw or Away Win",
        dc["X2"],
        (
            f"{team2['name']} recent W/D rate is "
            f"{(stats2['wins'] + stats2['draws']) / stats2['matches'] * 100:.0f}%"
        )
    )

    response += market_line(
        "12 — Either Team Wins",
        dc["12"],
        (
            f"Recent draw rates: "
            f"{team1['name']} {stats1['draws'] / stats1['matches'] * 100:.0f}%, "
            f"{team2['name']} {stats2['draws'] / stats2['matches'] * 100:.0f}%"
        )
    )

    response += (
        "⚽ GOAL MARKETS\n\n"
    )

    response += market_line(
        "Over 0.5 Goals",
        over05,
        (
            f"{team1['name']} recent Over 0.5: "
            f"{stats1['over05']:.0f}%; "
            f"{team2['name']}: "
            f"{stats2['over05']:.0f}%"
        )
    )

    response += market_line(
        "Over 1.5 Goals",
        over15,
        (
            f"Combined recent goal environment: "
            f"{combined_avg:.2f}"
        )
    )

    response += market_line(
        "Over 2.5 Goals",
        over25,
        (
            f"{team1['name']}: "
            f"{stats1['over25']:.0f}%; "
            f"{team2['name']}: "
            f"{stats2['over25']:.0f}%; "
            f"combined average: "
            f"{combined_avg:.2f}"
        )
    )

    response += market_line(
        "Under 3.5 Goals",
        under35,
        (
            f"Combined recent goal environment: "
            f"{combined_avg:.2f}"
        )
    )

    response += (
        "🤝 BTTS\n\n"
    )

    response += market_line(
        "BTTS — Yes",
        btts,
        (
            f"{team1['name']} BTTS: "
            f"{stats1['btts']:.0f}%; "
            f"{team2['name']} BTTS: "
            f"{stats2['btts']:.0f}%"
        )
    )

    response += (
        "🎯 TEAM TO SCORE\n\n"
    )

    response += market_line(
        f"{team1['name']} to Score",
        team1_score,
        (
            f"Scoring consistency: "
            f"{stats1['scoring']:.0f}%; "
            f"opponent clean-sheet rate: "
            f"{stats2['clean']:.0f}%"
        )
    )

    response += market_line(
        f"{team2['name']} to Score",
        team2_score,
        (
            f"Scoring consistency: "
            f"{stats2['scoring']:.0f}%; "
            f"opponent clean-sheet rate: "
            f"{stats1['clean']:.0f}%"
        )
    )

    response += (
        "⭐ PRIMARY STATISTICAL SIGNAL\n\n"
        f"{primary_name} — "
        f"Confidence {primary_confidence}%\n"
        f"Grade: {primary_grade}\n"
        f"Advice: {primary_advice}\n\n"
    )

    response += (
        "🧠 GoalLogic AI selects the primary signal "
        "from the available markets instead of automatically "
        "choosing Over 0.5 Goals.\n\n"
        "⚠️ Statistical analysis is not a guarantee of the "
        "match outcome. Confidence figures are indicators, "
        "not certainty."
    )

    return response


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ Welcome to GoalLogic AI.\n\n"
        "Send:\n"
        "/analyze Chelsea vs Arsenal\n\n"
        "I can analyze form, goals, BTTS, team scoring "
        "and Double Chance markets."
    )


async def apitest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OPENFOOT_API_KEY:
        await update.message.reply_text(
            "❌ OPENFOOT_API_KEY is missing from Render."
        )
        return

    test = openfoot_get(
        "/v1/matches",
        {
            "season": CURRENT_SEASON,
            "competition": EPL_ID,
        }
    )

    if test:
        await update.message.reply_text(
            "✅ OPENFOOT TEST PASSED\n\n"
            "OpenFoot API is connected successfully."
        )
    else:
        # Health endpoint is not used as proof of API auth.
        # We keep this message simple for Telegram testing.
        await update.message.reply_text(
            "⚠️ OpenFoot connection was reached, "
            "but the test returned no match data."
        )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    text = " ".join(context.args).strip()

    if not text:
        await update.message.reply_text(
            "Use:\n"
            "/analyze Chelsea vs Arsenal"
        )
        return

    parts = re.split(
        r"\s+vs\s+|\s+v\s+|\s+-\s+",
        text,
        flags=re.IGNORECASE
    )

    if len(parts) != 2:
        await update.message.reply_text(
            "❌ Please use this format:\n"
            "/analyze Chelsea vs Arsenal"
        )
        return

    team1 = parts[0].strip()
    team2 = parts[1].strip()

    try:
        result = await analyze_match(
            update,
            team1,
            team2
        )

        if result:
            await update.message.reply_text(result)

    except Exception as e:
        print(f"Analysis error: {e}")

        await update.message.reply_text(
            "❌ An error occurred while analyzing "
            "the match.\n\n"
            "Please try again."
        )


async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    text = update.message.text.strip()

    parts = re.split(
        r"\s+vs\s+|\s+v\s+",
        text,
        flags=re.IGNORECASE
    )

    if len(parts) == 2:
        await analyze_match(
            update,
            parts[0].strip(),
            parts[1].strip()
        )
    else:
        await update.message.reply_text(
            "Use:\n"
            "/analyze Chelsea vs Arsenal"
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

    print("======================================")
    print("GOALLOGIC AI")
    print("Starting...")
    print("OpenFoot enabled")
    print(f"Season: {CURRENT_SEASON}")
    print("Double Chance enabled")
    print("======================================")

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
            text_handler
        )
    )

    print("GoalLogic AI is running.")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
