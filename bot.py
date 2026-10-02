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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

OPENFOOT_BASE = "https://openfootapi.com"
CURRENT_SEASON = "2026/27"

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

    try:
        response = requests.get(
            OPENFOOT_BASE + endpoint,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {OPENFOOT_API_KEY}",
            },
            params=params or {},
            timeout=20,
        )

        print(f"OpenFoot {endpoint} -> HTTP {response.status_code}")

        try:
            body = response.json()
        except Exception:
            print("OpenFoot returned non-JSON.")
            return []

        if response.status_code != 200:
            print("OpenFoot error:", body)
            return []

        data = body.get("data", [])

        if isinstance(data, list):
            return data

        return []

    except Exception as e:
        print("OpenFoot request error:", e)
        return []


# ============================================================
# TEAM DATABASE
# ============================================================

TEAM_IDS = {
    "chelsea": "team_chelsea_eng",
    "arsenal": "team_arsenal_eng",
    "liverpool": "team_liverpool_eng",
    "manchester city": "team_manchester_city_eng",
    "man city": "team_manchester_city_eng",
    "manchester united": "team_manchester_united_eng",
    "man united": "team_manchester_united_eng",
    "man utd": "team_manchester_united_eng",
    "tottenham": "team_tottenham_eng",
    "spurs": "team_tottenham_eng",
    "newcastle": "team_newcastle_eng",
    "aston villa": "team_aston_villa_eng",
    "west ham": "team_west_ham_eng",
    "everton": "team_everton_eng",
    "crystal palace": "team_crystal_palace_eng",
    "brighton": "team_brighton_eng",
    "brentford": "team_brentford_eng",
    "bournemouth": "team_bournemouth_eng",
    "fulham": "team_fulham_eng",
    "nottingham forest": "team_nottingham_forest_eng",
    "sunderland": "team_sunderland_eng",
    "leeds": "team_leeds_eng",
}

ALIASES = {
    "chelsea fc": "chelsea",
    "arsenal fc": "arsenal",
    "liverpool fc": "liverpool",
    "manchester city fc": "manchester city",
    "manchester united fc": "manchester united",
    "tottenham hotspur": "tottenham",
    "tottenham hotspur fc": "tottenham",
    "newcastle united": "newcastle",
    "aston villa fc": "aston villa",
    "west ham united": "west ham",
    "everton fc": "everton",
    "crystal palace fc": "crystal palace",
    "brighton & hove albion": "brighton",
    "brighton and hove albion": "brighton",
    "brentford fc": "brentford",
    "afc bournemouth": "bournemouth",
    "fulham fc": "fulham",
    "nottingham forest fc": "nottingham forest",
    "sunderland afc": "sunderland",
    "leeds united": "leeds",
    "leeds united fc": "leeds",
}


def normalize_team(name):
    name = name.strip().lower()
    return re.sub(r"\s+", " ", name)


def find_team_id(name):
    key = normalize_team(name)

    if key in TEAM_IDS:
        return TEAM_IDS[key]

    alias = ALIASES.get(key)

    if alias:
        return TEAM_IDS.get(alias)

    return None


# ============================================================
# MATCH DATA
# ============================================================

def get_team_matches(team_id, team_name):
    matches = openfoot_get(
        "/v1/matches",
        {
            "team": team_id,
            "season": CURRENT_SEASON,
            "status": "finished",
        },
    )

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

        if home_score is None:
            home_score = score.get("homeGoals")

        if away_score is None:
            away_score = score.get("awayGoals")

        if home_score is None:
            home_score = match.get("homeScore")

        if away_score is None:
            away_score = match.get("awayScore")

        if home_score is None or away_score is None:
            continue

        try:
            match["_home_score"] = int(home_score)
            match["_away_score"] = int(away_score)
        except (TypeError, ValueError):
            continue

        match["_is_home"] = home_id == team_id

        match["_kickoff"] = (
            match.get("kickoffAt")
            or match.get("kickoff")
            or match.get("date")
            or ""
        )

        completed.append(match)

    completed.sort(
        key=lambda x: x.get("_kickoff", ""),
        reverse=True
    )

    print(
        f"{team_name}: {len(completed)} usable completed matches."
    )

    return completed


# ============================================================
# BASIC STATISTICS
# ============================================================

def result_for(match):
    home_score = match["_home_score"]
    away_score = match["_away_score"]

    if match["_is_home"]:
        gf = home_score
        ga = away_score
    else:
        gf = away_score
        ga = home_score

    if gf > ga:
        result = "W"
    elif gf < ga:
        result = "L"
    else:
        result = "D"

    return result, gf, ga


def calculate_stats(matches):
    sample = matches[:RECENT_MATCHES]

    if not sample:
        return None

    rows = [result_for(match) for match in sample]

    results = [row[0] for row in rows]
    goals_for = [row[1] for row in rows]
    goals_against = [row[2] for row in rows]

    totals = [
        gf + ga
        for gf, ga in zip(goals_for, goals_against)
    ]

    count = len(sample)

    return {
        "sample": count,
        "form": "".join(results),

        "wins": results.count("W"),
        "draws": results.count("D"),
        "losses": results.count("L"),

        "gf": sum(goals_for),
        "ga": sum(goals_against),

        "avg_gf": mean(goals_for),
        "avg_ga": mean(goals_against),
        "avg_total": mean(totals),

        "over05": sum(x >= 1 for x in totals) / count * 100,
        "over15": sum(x >= 2 for x in totals) / count * 100,
        "over25": sum(x >= 3 for x in totals) / count * 100,

        "under35": sum(x <= 3 for x in totals) / count * 100,

        "btts": sum(
            gf > 0 and ga > 0
            for gf, ga in zip(goals_for, goals_against)
        ) / count * 100,

        "scoring": sum(
            gf > 0 for gf in goals_for
        ) / count * 100,

        "clean": sum(
            ga == 0 for ga in goals_against
        ) / count * 100,

        "wd": sum(
            result in ("W", "D")
            for result in results
        ) / count * 100,

        "draw_rate": sum(
            result == "D"
            for result in results
        ) / count * 100,
    }


def venue_stats(matches, want_home):
    selected = [
        match
        for match in matches
        if match["_is_home"] == want_home
    ]

    return calculate_stats(selected[:RECENT_MATCHES])


# ============================================================
# CALIBRATED CONFIDENCE SYSTEM
# ============================================================

def sample_weight(sample):
    if sample <= 0:
        return 0.0

    if sample == 1:
        return 0.45

    if sample == 2:
        return 0.65

    if sample == 3:
        return 0.78

    if sample == 4:
        return 0.90

    return 1.00


def confidence_from_base(
    base,
    support=0,
    counter=0,
    sample=5
):
    """
    Converts raw statistical percentages into a more conservative
    confidence figure.

    Small samples are automatically discounted.
    Confidence is capped below 90% so the bot does not imply certainty.
    """

    weight = sample_weight(sample)

    adjusted = 50 + ((base - 50) * 0.55 * weight)

    adjusted += support * 0.15
    adjusted -= counter * 0.15

    return round(
        max(52, min(88, adjusted))
    )


def confidence_from_base(
    base,
    support=0,
    counter=0,
    sample=5
):
    """
    Calibrated confidence model.

    Uses:
    - Base statistical probability
    - Supporting evidence
    - Contradicting evidence
    - Sample-size reliability

    The model avoids excessive confidence from one statistic alone.
    """

    weight = sample_weight(sample)

    # Pull raw probability toward 50% when the sample is small.
    adjusted = 50 + ((base - 50) * 0.50 * weight)

    # Supporting evidence helps, but cannot dominate the calculation.
    adjusted += support * 0.20

    # Contradicting evidence receives a slightly stronger penalty.
    adjusted -= counter * 0.25

    # Additional reliability penalty for very small samples.
    if sample < 3:
        adjusted -= 2

    # Keep confidence within a realistic statistical range.
    return round(
        max(50, min(85, adjusted))
    )

# ============================================================
# FULL MATCH ANALYSIS
# ============================================================

def analyze_match(team1_name, team2_name):

    team1_id = find_team_id(team1_name)
    team2_id = find_team_id(team2_name)

    if not team1_id:
        return (
            f"❌ I couldn't find {team1_name} "
            f"in the team database."
        )

    if not team2_id:
        return (
            f"❌ I couldn't find {team2_name} "
            f"in the team database."
        )

    team1_matches = get_team_matches(
        team1_id,
        team1_name
    )

    team2_matches = get_team_matches(
        team2_id,
        team2_name
    )

    if len(team1_matches) < MIN_MATCHES:
        return (
            f"⚠️ OpenFoot returned only "
            f"{len(team1_matches)} usable completed "
            f"matches for {team1_name}."
        )

    if len(team2_matches) < MIN_MATCHES:
        return (
            f"⚠️ OpenFoot returned only "
            f"{len(team2_matches)} usable completed "
            f"matches for {team2_name}."
        )

    team1 = calculate_stats(team1_matches)
    team2 = calculate_stats(team2_matches)

    home = venue_stats(team1_matches, True)
    away = venue_stats(team2_matches, False)

    lines = []

    lines.append("⚽ GOALLOGIC AI — MATCH ANALYSIS")
    lines.append("")
    lines.append(
        f"{team1_name} vs {team2_name}"
    )
    lines.append(
        f"Season: {CURRENT_SEASON}"
    )
    lines.append("")

    # --------------------------------------------------------
    # TEAM STATISTICS
    # --------------------------------------------------------

    def add_team_stats(name, stats):

        lines.extend([
            f"📊 {name.upper()} — LAST {stats['sample']}",
            f"Form: {stats['form']}",
            (
                f"W/D/L: {stats['wins']}/"
                f"{stats['draws']}/"
                f"{stats['losses']}"
            ),
            f"Goals scored: {stats['gf']}",
            f"Goals conceded: {stats['ga']}",
            f"Avg scored: {stats['avg_gf']:.2f}",
            f"Avg conceded: {stats['avg_ga']:.2f}",
            f"Avg total goals: {stats['avg_total']:.2f}",
            f"Over 0.5: {stats['over05']:.0f}%",
            f"Over 1.5: {stats['over15']:.0f}%",
            f"Over 2.5: {stats['over25']:.0f}%",
            f"Under 3.5: {stats['under35']:.0f}%",
            f"BTTS: {stats['btts']:.0f}%",
            f"Scoring consistency: {stats['scoring']:.0f}%",
            f"Clean sheets: {stats['clean']:.0f}%",
            "",
        ])

    add_team_stats(team1_name, team1)
    add_team_stats(team2_name, team2)

    # --------------------------------------------------------
    # HOME / AWAY
    # --------------------------------------------------------

    lines.append("🏠 HOME / AWAY CONTEXT")
    lines.append("")

    if home:

        lines.extend([
            (
                f"{team1_name} home sample: "
                f"{home['sample']} matches"
            ),
            f"Home scoring: {home['scoring']:.0f}%",
            f"Home Over 2.5: {home['over25']:.0f}%",
            f"Home BTTS: {home['btts']:.0f}%",
            "",
        ])

    else:

        lines.extend([
            f"{team1_name} home sample: 0 matches",
            "",
        ])

    if away:

        lines.extend([
            (
                f"{team2_name} away sample: "
                f"{away['sample']} matches"
            ),
            f"Away scoring: {away['scoring']:.0f}%",
            f"Away Over 2.5: {away['over25']:.0f}%",
            f"Away BTTS: {away['btts']:.0f}%",
            "",
        ])

    else:

        lines.extend([
            f"{team2_name} away sample: 0 matches",
            "",
        ])

    # --------------------------------------------------------
    # DOUBLE CHANCE
    # --------------------------------------------------------

    one_x_base_values = [
        team1["wd"]
    ]

    if home:
        one_x_base_values.append(home["wd"])

    one_x_base = mean(one_x_base_values)

    one_x = confidence_from_base(
        one_x_base,
        support=8 if home and home["wd"] >= 67 else 0,
        counter=(100 - team2["wd"]) / 5,
        sample=(
            min(
                team1["sample"],
                home["sample"]
            )
            if home
            else team1["sample"]
        ),
    )

    x2_base_values = [
        team2["wd"]
    ]

    if away:
        x2_base_values.append(away["wd"])

    x2_base = mean(x2_base_values)

    x2 = confidence_from_base(
        x2_base,
        support=8 if away and away["wd"] >= 67 else 0,
        counter=(100 - team1["wd"]) / 5,
        sample=(
            min(
                team2["sample"],
                away["sample"]
            )
            if away
            else team2["sample"]
        ),
    )

    no_draw_base = 100 - mean([
        team1["draw_rate"],
        team2["draw_rate"]
    ])

    no_draw = confidence_from_base(
        no_draw_base,
        support=8
        if (
            team1["draw_rate"] <= 20
            and team2["draw_rate"] <= 20
        )
        else 0,
        counter=0,
        sample=min(
            team1["sample"],
            team2["sample"]
        ),
    )

    lines.extend([
        "🎯 DOUBLE CHANCE",
        "",
        f"1X — Home Win or Draw — Confidence {one_x}%",
        f"Grade: {grade(one_x)}",
        f"Advice: {advice(one_x)}",
        (
            f"Reason: {team1_name} recent W/D rate "
            f"is {team1['wd']:.0f}%"
        ),
        "",
        f"X2 — Draw or Away Win — Confidence {x2}%",
        f"Grade: {grade(x2)}",
        f"Advice: {advice(x2)}",
        (
            f"Reason: {team2_name} recent W/D rate "
            f"is {team2['wd']:.0f}%"
        ),
        "",
        f"12 — Either Team Wins — Confidence {no_draw}%",
        f"Grade: {grade(no_draw)}",
        f"Advice: {advice(no_draw)}",
        (
            f"Reason: Recent draw rates: "
            f"{team1_name} {team1['draw_rate']:.0f}%, "
            f"{team2_name} {team2['draw_rate']:.0f}%"
        ),
        "",
    ])

    # --------------------------------------------------------
    # GOAL ENVIRONMENT
    # --------------------------------------------------------

    combined_avg = mean([
        team1["avg_total"],
        team2["avg_total"]
    ])

    # OVER 0.5
    over05_base = mean([
        team1["over05"],
        team2["over05"]
    ])

    over05 = confidence_from_base(
        over05_base,
        support=8 if combined_avg >= 2 else 0,
        counter=0,
        sample=min(
            team1["sample"],
            team2["sample"]
        ),
    )

    # OVER 1.5
    over15_base = mean([
        team1["over15"],
        team2["over15"]
    ])

    over15 = confidence_from_base(
        over15_base,
        support=10 if combined_avg >= 2.5 else 0,
        counter=0,
        sample=min(
            team1["sample"],
            team2["sample"]
        ),
    )

    # OVER 2.5
    over25_base = mean([
        team1["over25"],
        team2["over25"]
    ])

    over25 = confidence_from_base(
        over25_base,
        support=10 if combined_avg >= 3 else 0,
        counter=12
        if away and away["over25"] <= 40
        else 0,
        sample=min(
            team1["sample"],
            team2["sample"]
        ),
    )

    # UNDER 3.5
    under35_base = mean([
        team1["under35"],
        team2["under35"]
    ])

    under35 = confidence_from_base(
        under35_base,
        support=10 if combined_avg <= 2.5 else 0,
        counter=15 if combined_avg >= 3.5 else 0,
        sample=min(
            team1["sample"],
            team2["sample"]
        ),
    )

    lines.extend([
        "⚽ GOAL MARKETS",
        "",
        f"Over 0.5 Goals — Confidence {over05}%",
        f"Grade: {grade(over05)}",
        f"Advice: {advice(over05)}",
        (
            f"Reason: {team1_name} recent Over 0.5: "
            f"{team1['over05']:.0f}%; "
            f"{team2_name}: {team2['over05']:.0f}%; "
            f"sample-size adjustment applied"
        ),
        "",
        f"Over 1.5 Goals — Confidence {over15}%",
        f"Grade: {grade(over15)}",
        f"Advice: {advice(over15)}",
        (
            f"Reason: Combined recent goal "
            f"environment: {combined_avg:.2f}"
        ),
        "",
        f"Over 2.5 Goals — Confidence {over25}%",
        f"Grade: {grade(over25)}",
        f"Advice: {advice(over25)}",
        (
            f"Reason: {team1_name}: "
            f"{team1['over25']:.0f}%; "
            f"{team2_name}: "
            f"{team2['over25']:.0f}%; "
            f"combined average: {combined_avg:.2f}"
        ),
        "",
        f"Under 3.5 Goals — Confidence {under35}%",
        f"Grade: {grade(under35)}",
        f"Advice: {advice(under35)}",
        (
            f"Reason: Combined recent goal "
            f"environment: {combined_avg:.2f}"
        ),
        "",
    ])

    # --------------------------------------------------------
    # BTTS
    # --------------------------------------------------------

    btts_base = mean([
        team1["btts"],
        team2["btts"]
    ])

    btts = confidence_from_base(
        btts_base,
        support=10
        if home and home["btts"] >= 67
        else 0,
        counter=15
        if away and away["btts"] <= 33
        else 0,
        sample=min(
            team1["sample"],
            team2["sample"]
        ),
    )

    lines.extend([
        "🤝 BTTS",
        "",
        f"BTTS — Yes — Confidence {btts}%",
        f"Grade: {grade(btts)}",
        f"Advice: {advice(btts)}",
        (
            f"Reason: {team1_name} BTTS: "
            f"{team1['btts']:.0f}%; "
            f"{team2_name} BTTS: "
            f"{team2['btts']:.0f}%"
        ),
        "",
    ])

    # --------------------------------------------------------
    # TEAM TO SCORE
    # --------------------------------------------------------

    team1_score_base = mean([
        team1["scoring"],
        home["scoring"] if home else team1["scoring"],
        100 - team2["clean"],
    ])

    team1_score = confidence_from_base(
        team1_score_base,
        support=8
        if home and home["scoring"] >= 67
        else 0,
        counter=10
        if away and away["clean"] >= 67
        else 0,
        sample=(
            min(
                team1["sample"],
                home["sample"]
            )
            if home
            else team1["sample"]
        ),
    )

    team2_score_base = mean([
        team2["scoring"],
        away["scoring"] if away else team2["scoring"],
        100 - team1["clean"],
    ])

    team2_score = confidence_from_base(
        team2_score_base,
        support=8
        if away and away["scoring"] >= 67
        else 0,
        counter=10
        if home and home["clean"] >= 67
        else 0,
        sample=(
            min(
                team2["sample"],
                away["sample"]
            )
            if away
            else team2["sample"]
        ),
    )

    lines.extend([
        "🎯 TEAM TO SCORE",
        "",
        (
            f"{team1_name} to Score — "
            f"Confidence {team1_score}%"
        ),
        f"Grade: {grade(team1_score)}",
        f"Advice: {advice(team1_score)}",
        (
            f"Reason: Scoring consistency: "
            f"{team1['scoring']:.0f}%; "
            f"opponent clean-sheet rate: "
            f"{team2['clean']:.0f}%"
        ),
        "",
        (
            f"{team2_name} to Score — "
            f"Confidence {team2_score}%"
        ),
        f"Grade: {grade(team2_score)}",
        f"Advice: {advice(team2_score)}",
        (
            f"Reason: Scoring consistency: "
            f"{team2['scoring']:.0f}%; "
            f"opponent clean-sheet rate: "
            f"{team1['clean']:.0f}%"
        ),
        "",
    ])

    # --------------------------------------------------------
    # PRIMARY SIGNAL
    # --------------------------------------------------------

    candidates = [
        ("1X", one_x),
        ("X2", x2),
        ("12", no_draw),
        ("Over 1.5 Goals", over15),
        ("Over 2.5 Goals", over25),
        ("Under 3.5 Goals", under35),
        ("BTTS — Yes", btts),
        (
            f"{team1_name} to Score",
            team1_score
        ),
        (
            f"{team2_name} to Score",
            team2_score
        ),
    ]

    candidates.sort(
        key=lambda item: item[1],
        reverse=True
    )

    primary_name, primary_confidence = candidates[0]

    lines.extend([
        "⭐ PRIMARY STATISTICAL SIGNAL",
        "",
        (
            f"{primary_name} — "
            f"Confidence {primary_confidence}%"
        ),
        f"Grade: {grade(primary_confidence)}",
        f"Advice: {advice(primary_confidence)}",
        "",
        (
            "🧠 GoalLogic AI uses a calibrated confidence "
            "model based on recent form, home/away context, "
            "scoring, defending and sample size."
        ),
        "",
        (
            "⚠️ Statistical analysis is not a guarantee "
            "of the match outcome. Confidence figures are "
            "indicators, not certainty."
        ),
    ])

    return "\n".join(lines)


# ============================================================
# TELEGRAM
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "⚽ GoalLogic AI is online.\n\n"
        "Use:\n"
        "/analyze Chelsea vs Arsenal\n\n"
        "Or simply send:\n"
        "Chelsea vs Arsenal"
    )


async def apitest(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not OPENFOOT_API_KEY:
        await update.message.reply_text(
            "❌ OPENFOOT_API_KEY is missing."
        )
        return

    try:

        response = requests.get(
            OPENFOOT_BASE + "/v1/health",
            headers={
                "Accept": "application/json",
                "Authorization": (
                    f"Bearer {OPENFOOT_API_KEY}"
                ),
            },
            timeout=15,
        )

        if response.status_code == 200:

            await update.message.reply_text(
                "✅ OPENFOOT TEST PASSED\n\n"
                "OpenFoot API is connected successfully."
            )

        else:

            await update.message.reply_text(
                "❌ OpenFoot test failed.\n"
                f"HTTP {response.status_code}"
            )

    except Exception as e:

        await update.message.reply_text(
            f"❌ OpenFoot test failed.\n{e}"
        )


def parse_match(text):

    cleaned = re.sub(
        r"^/analyze\s*",
        "",
        text,
        flags=re.I
    ).strip()

    cleaned = re.sub(
        r"\s+",
        " ",
        cleaned
    )

    parts = re.split(
        r"\s+(?:vs?|versus)\s+",
        cleaned,
        flags=re.I
    )

    if len(parts) != 2:
        return None, None

    return (
        parts[0].strip(),
        parts[1].strip()
    )


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text or ""

    team1, team2 = parse_match(text)

    if not team1 or not team2:

        await update.message.reply_text(
            "Use this format:\n"
            "/analyze Chelsea vs Arsenal"
        )

        return

    await update.message.reply_text(
        "🔎 Analyzing recent OpenFoot data..."
    )

    result = analyze_match(
        team1,
        team2
    )

    await update.message.reply_text(result)


async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text or ""

    if re.search(
        r"\s+(?:vs?|versus)\s+",
        text,
        flags=re.I
    ):

        team1, team2 = parse_match(text)

        if team1 and team2:

            await update.message.reply_text(
                "🔎 Analyzing recent OpenFoot data..."
            )

            result = analyze_match(
                team1,
                team2
            )

            await update.message.reply_text(result)

            return

    await update.message.reply_text(
        "⚽ GoalLogic AI\n\n"
        "Send a match like:\n"
        "Chelsea vs Arsenal\n\n"
        "or use:\n"
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

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    app = (
        Application
        .builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("apitest", apitest)
    )

    app.add_handler(
        CommandHandler(
            "analyze",
            analyze_command
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    print("GoalLogic AI is running.")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
