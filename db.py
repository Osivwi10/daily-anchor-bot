"""
SQLite layer for Daily Anchor Bot - multi-user.
Everything is scoped by chat_id so independent users share one bot.
"""
import sqlite3
import os
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo

DB_PATH = os.environ.get("DB_PATH", "anchor.db")

DEFAULT_TRACKS = ["Task", "Content", "Learning"]
DEFAULT_TIMES = {
    "morning_time": "08:00",
    "midday_time": "14:00",
    "checkin_time": "20:30",
    "night_time": "21:00",
    "recap_time": "20:00",
}
DEFAULT_TZ = "Africa/Lagos"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            chat_id INTEGER PRIMARY KEY,
            timezone TEXT NOT NULL DEFAULT 'Africa/Lagos',
            morning_time TEXT NOT NULL DEFAULT '08:00',
            midday_time TEXT NOT NULL DEFAULT '14:00',
            checkin_time TEXT NOT NULL DEFAULT '20:30',
            night_time TEXT NOT NULL DEFAULT '21:00',
            recap_time TEXT NOT NULL DEFAULT '20:00',
            planning_mode TEXT NOT NULL DEFAULT 'today',
            created_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(chat_id, name)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            track TEXT NOT NULL,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# ---------------- users ----------------

def user_exists(chat_id: int) -> bool:
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM users WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    return row is not None


def register_user(chat_id: int):
    """Idempotent: creates the user + default tracks if they don't exist yet."""
    if user_exists(chat_id):
        return
    conn = get_conn()
    conn.execute(
        "INSERT INTO users (chat_id, timezone, morning_time, midday_time, "
        "checkin_time, night_time, recap_time, planning_mode, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'today', ?)",
        (
            chat_id,
            DEFAULT_TZ,
            DEFAULT_TIMES["morning_time"],
            DEFAULT_TIMES["midday_time"],
            DEFAULT_TIMES["checkin_time"],
            DEFAULT_TIMES["night_time"],
            DEFAULT_TIMES["recap_time"],
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()
    for t in DEFAULT_TRACKS:
        add_track(chat_id, t)


def get_user(chat_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE chat_id=?", (chat_id,)).fetchone()
    conn.close()
    return row


def get_all_users():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    return rows


_SETTABLE_FIELDS = {
    "timezone", "morning_time", "midday_time", "checkin_time",
    "night_time", "recap_time", "planning_mode",
}


def set_user_field(chat_id: int, field: str, value: str):
    if field not in _SETTABLE_FIELDS:
        raise ValueError(f"Not a settable field: {field}")
    conn = get_conn()
    conn.execute(f"UPDATE users SET {field}=? WHERE chat_id=?", (value, chat_id))
    conn.commit()
    conn.close()


def set_planning_mode(chat_id: int, mode: str):
    assert mode in ("today", "tomorrow")
    set_user_field(chat_id, "planning_mode", mode)


def _user_tz(chat_id: int) -> ZoneInfo:
    user = get_user(chat_id)
    tz_name = user["timezone"] if user else DEFAULT_TZ
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def local_today(chat_id: int) -> str:
    return datetime.now(_user_tz(chat_id)).date().isoformat()


def local_tomorrow(chat_id: int) -> str:
    return (datetime.now(_user_tz(chat_id)).date() + timedelta(days=1)).isoformat()


def target_day(chat_id: int) -> str:
    """Which date new free-text/manual entries should land on, based on planning_mode."""
    user = get_user(chat_id)
    mode = user["planning_mode"] if user else "today"
    return local_tomorrow(chat_id) if mode == "tomorrow" else local_today(chat_id)


# ---------------- tracks ----------------

def get_tracks(chat_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT name FROM tracks WHERE chat_id=? ORDER BY id", (chat_id,)
    ).fetchall()
    conn.close()
    return [r["name"] for r in rows]


def find_track_case_insensitive(chat_id: int, name: str):
    for t in get_tracks(chat_id):
        if t.lower() == name.lower():
            return t
    return None


def add_track(chat_id: int, name: str) -> bool:
    if find_track_case_insensitive(chat_id, name):
        return False
    conn = get_conn()
    conn.execute("INSERT INTO tracks (chat_id, name) VALUES (?, ?)", (chat_id, name))
    conn.commit()
    conn.close()
    return True


def remove_track(chat_id: int, name: str) -> bool:
    exact = find_track_case_insensitive(chat_id, name)
    if not exact:
        return False
    conn = get_conn()
    conn.execute("DELETE FROM tracks WHERE chat_id=? AND name=?", (chat_id, exact))
    conn.commit()
    conn.close()
    return True


def rename_track(chat_id: int, old_name: str, new_name: str) -> bool:
    exact = find_track_case_insensitive(chat_id, old_name)
    if not exact:
        return False
    if find_track_case_insensitive(chat_id, new_name):
        return False  # new name already taken
    conn = get_conn()
    conn.execute(
        "UPDATE tracks SET name=? WHERE chat_id=? AND name=?", (new_name, chat_id, exact)
    )
    conn.execute(
        "UPDATE items SET track=? WHERE chat_id=? AND track=?", (new_name, chat_id, exact)
    )
    conn.commit()
    conn.close()
    return True


# ---------------- items ----------------

def add_item(chat_id: int, track: str, text: str, day: str):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO items (chat_id, day, track, text, status, created_at) "
        "VALUES (?, ?, ?, ?, 'pending', ?)",
        (chat_id, day, track, text.strip(), datetime.utcnow().isoformat()),
    )
    conn.commit()
    item_id = cur.lastrowid
    conn.close()
    return item_id


def get_items_for_day(chat_id: int, day: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM items WHERE chat_id=? AND day=? ORDER BY id", (chat_id, day)
    ).fetchall()
    conn.close()
    return rows


def get_pending_items_for_day(chat_id: int, day: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM items WHERE chat_id=? AND day=? AND status='pending' ORDER BY id",
        (chat_id, day),
    ).fetchall()
    conn.close()
    return rows


def get_item(item_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    return row


def update_item_status(item_id: int, status: str):
    conn = get_conn()
    conn.execute("UPDATE items SET status=? WHERE id=?", (status, item_id))
    conn.commit()
    conn.close()


def tracks_touched_on(chat_id: int, day: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT track FROM items WHERE chat_id=? AND day=?", (chat_id, day)
    ).fetchall()
    conn.close()
    return {r["track"] for r in rows}


def done_dates_for_track(chat_id: int, track: str, limit_days: int = 60):
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT day FROM items WHERE chat_id=? AND track=? AND status='done' "
        "ORDER BY day DESC LIMIT ?",
        (chat_id, track, limit_days),
    ).fetchall()
    conn.close()
    return [r["day"] for r in rows]


def current_streak(chat_id: int, track: str) -> int:
    done_days = set(done_dates_for_track(chat_id, track))
    if not done_days:
        return 0

    today = date.fromisoformat(local_today(chat_id))
    streak = 0
    cursor = today

    if cursor.isoformat() in done_days:
        streak += 1
    cursor -= timedelta(days=1)

    while cursor.isoformat() in done_days:
        streak += 1
        cursor -= timedelta(days=1)

    return streak


def weekly_summary(chat_id: int):
    today = date.fromisoformat(local_today(chat_id))
    start = today - timedelta(days=6)
    conn = get_conn()
    summary = {}
    for track in get_tracks(chat_id):
        row = conn.execute(
            "SELECT COUNT(*) as c FROM items WHERE chat_id=? AND track=? AND status='done' "
            "AND day BETWEEN ? AND ?",
            (chat_id, track, start.isoformat(), today.isoformat()),
        ).fetchone()
        summary[track] = row["c"]
    conn.close()
    return summary
