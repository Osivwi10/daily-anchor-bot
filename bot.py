"""
Daily Anchor Bot - multi-user edition.

Anyone who messages /start gets their own independent setup: tracks,
ping times, timezone, streaks. One bot, many people, fully isolated data.

Default flow per user (all configurable via /settings):
  08:00  morning ping   - shows what was planned for today, asks for more
  14:00  midday nudge    - only fires for tracks with nothing logged yet
  20:30  evening check-in - Done/Missed buttons on today's pending items
  21:00  night-before ping - plan tomorrow (sets planning_mode='tomorrow')
  Sun 20:00  weekly recap

Commands:
  /start                          register + sync your schedule
  /help                           show usage
  /status                         today's items + streaks
  /add <track> <text>             manually log an item
  /tracks                         list your tracks
  /tracks add <name>
  /tracks remove <name>
  /tracks rename <old> <new>
  /settings                       show your current times + timezone
  /settings morning HH:MM
  /settings midday HH:MM
  /settings checkin HH:MM
  /settings night HH:MM
  /settings timezone <IANA tz>    e.g. Africa/Lagos, America/New_York, Europe/London

Free-text logging works anytime, no command needed:
  Task: reply to that client email
  Content: thread about XO market mechanics
  Learning: finish chapter 3
(Lines are matched against YOUR current track names, case-insensitive.)
"""
import logging
import os
import re
from datetime import time as dtime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
TRACK_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,20}$")


def parse_hhmm(s: str):
    m = TIME_RE.match(s.strip())
    if not m:
        return None
    return dtime(hour=int(m.group(1)), minute=int(m.group(2)))


def build_track_pattern(tracks):
    if not tracks:
        return None
    escaped = sorted((re.escape(t) for t in tracks), key=len, reverse=True)
    return re.compile(
        r"^\s*(" + "|".join(escaped) + r")\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
    )


# ---------------- scheduling ----------------

def schedule_all_for_user(application: Application, chat_id: int):
    user = db.get_user(chat_id)
    if not user:
        return
    try:
        tz = ZoneInfo(user["timezone"])
    except Exception:
        tz = ZoneInfo(db.DEFAULT_TZ)

    jq = application.job_queue

    def resched(name, func, time_str, days=None):
        for j in jq.get_jobs_by_name(name):
            j.schedule_removal()
        t = parse_hhmm(time_str)
        if t is None:
            return
        kwargs = {"name": name, "data": chat_id}
        if days is not None:
            kwargs["days"] = days
        jq.run_daily(func, dtime(hour=t.hour, minute=t.minute, tzinfo=tz), **kwargs)

    resched(f"morning_{chat_id}", job_morning, user["morning_time"])
    resched(f"midday_{chat_id}", job_midday_nudge, user["midday_time"])
    resched(f"checkin_{chat_id}", job_checkin, user["checkin_time"])
    resched(f"night_{chat_id}", job_night, user["night_time"])
    resched(f"recap_{chat_id}", job_recap, user["recap_time"], days=(6,))  # Sunday


# ---------------- commands ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    is_new = not db.user_exists(chat_id)
    db.register_user(chat_id)
    schedule_all_for_user(context.application, chat_id)

    if is_new:
        tracks = ", ".join(db.get_tracks(chat_id))
        await update.message.reply_text(
            "You're set up.\n\n"
            f"Default tracks: {tracks}\n"
            "Default times (Africa/Lagos): morning 08:00, midday nudge 14:00, "
            "check-in 20:30, plan-tomorrow 21:00, weekly recap Sunday 20:00.\n\n"
            "Everything is adjustable:\n"
            "/tracks - manage your tracks\n"
            "/settings - change times or your timezone\n"
            "/add <track> <text> - log something manually\n"
            "/status - see today + streaks\n\n"
            "Or just message me anytime like:\nTask: reply to that email\n"
            "Content: thread about XO market mechanics\nLearning: finish chapter 3"
        )
    else:
        await update.message.reply_text(
            "Already set up - your schedule's been re-synced. "
            "/settings or /tracks to adjust, /status to check today."
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Log anytime:\nTask: ...\nContent: ...\nLearning: ...\n\n"
        "/add <track> <text> - manual log\n"
        "/status - today's items + streaks\n"
        "/tracks - list tracks\n"
        "/tracks add <name>\n"
        "/tracks remove <name>\n"
        "/tracks rename <old> <new>\n"
        "/settings - show your times + timezone\n"
        "/settings morning|midday|checkin|night HH:MM\n"
        "/settings timezone <IANA tz>  e.g. Africa/Lagos, America/New_York\n"
        "/start - register or re-sync your schedule"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not db.user_exists(chat_id):
        await update.message.reply_text("Run /start first.")
        return

    today = db.local_today(chat_id)
    items = db.get_items_for_day(chat_id, today)

    if not items:
        body = "Nothing logged yet today."
    else:
        marks = {"pending": "⏳", "done": "✅", "missed": "❌"}
        body = "\n".join(f"{marks[it['status']]} [{it['track']}] {it['text']}" for it in items)

    tracks = db.get_tracks(chat_id)
    streaks = "\n".join(f"{t}: {db.current_streak(chat_id, t)} day streak" for t in tracks)

    await update.message.reply_text(f"Today:\n{body}\n\nStreaks:\n{streaks}")


async def tracks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not db.user_exists(chat_id):
        await update.message.reply_text("Run /start first.")
        return

    args = context.args
    if not args or args[0].lower() == "list":
        tracks = db.get_tracks(chat_id)
        await update.message.reply_text("Your tracks:\n" + "\n".join(tracks))
        return

    sub = args[0].lower()

    if sub == "add":
        if len(args) < 2:
            await update.message.reply_text("Usage: /tracks add <name>  (letters/numbers/underscore only)")
            return
        name = args[1]
        if not TRACK_NAME_RE.match(name):
            await update.message.reply_text("Track names: letters, numbers, underscore only, no spaces.")
            return
        ok = db.add_track(chat_id, name)
        await update.message.reply_text(f"Added '{name}'." if ok else f"'{name}' already exists.")

    elif sub == "remove":
        if len(args) < 2:
            await update.message.reply_text("Usage: /tracks remove <name>")
            return
        name = args[1]
        ok = db.remove_track(chat_id, name)
        await update.message.reply_text(f"Removed '{name}'." if ok else f"No track called '{name}'.")

    elif sub == "rename":
        if len(args) < 3:
            await update.message.reply_text("Usage: /tracks rename <old> <new>")
            return
        old, new = args[1], args[2]
        if not TRACK_NAME_RE.match(new):
            await update.message.reply_text("New name: letters, numbers, underscore only, no spaces.")
            return
        ok = db.rename_track(chat_id, old, new)
        await update.message.reply_text(
            f"Renamed '{old}' to '{new}'." if ok else f"Couldn't rename — check '{old}' exists and '{new}' isn't taken."
        )
    else:
        await update.message.reply_text("Usage: /tracks [list|add|remove|rename] ...")


async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not db.user_exists(chat_id):
        await update.message.reply_text("Run /start first.")
        return

    args = context.args
    user = db.get_user(chat_id)

    if not args:
        await update.message.reply_text(
            "Your settings:\n"
            f"Timezone: {user['timezone']}\n"
            f"Morning: {user['morning_time']}\n"
            f"Midday nudge: {user['midday_time']}\n"
            f"Check-in: {user['checkin_time']}\n"
            f"Plan-tomorrow: {user['night_time']}\n"
            f"Weekly recap: Sunday {user['recap_time']}\n\n"
            "Change with:\n/settings morning|midday|checkin|night HH:MM\n"
            "/settings timezone <IANA tz>"
        )
        return

    field = args[0].lower()

    if field == "timezone":
        if len(args) < 2:
            await update.message.reply_text("Usage: /settings timezone <IANA tz>  e.g. Africa/Lagos")
            return
        tz_name = args[1]
        try:
            ZoneInfo(tz_name)
        except Exception:
            await update.message.reply_text(f"'{tz_name}' isn't a valid IANA timezone name.")
            return
        db.set_user_field(chat_id, "timezone", tz_name)
        schedule_all_for_user(context.application, chat_id)
        await update.message.reply_text(f"Timezone set to {tz_name}.")
        return

    field_map = {
        "morning": "morning_time",
        "midday": "midday_time",
        "checkin": "checkin_time",
        "night": "night_time",
    }
    if field not in field_map:
        await update.message.reply_text("Usage: /settings morning|midday|checkin|night HH:MM, or /settings timezone <tz>")
        return

    if len(args) < 2 or parse_hhmm(args[1]) is None:
        await update.message.reply_text("Give a time like 08:00 (24h format).")
        return

    db.set_user_field(chat_id, field_map[field], args[1])
    schedule_all_for_user(context.application, chat_id)
    await update.message.reply_text(f"{field.capitalize()} time set to {args[1]}.")


async def add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not db.user_exists(chat_id):
        await update.message.reply_text("Run /start first.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /add <track> <text>")
        return

    track_in, text = args[0], " ".join(args[1:])
    matched = db.find_track_case_insensitive(chat_id, track_in)
    if not matched:
        tracks = ", ".join(db.get_tracks(chat_id))
        await update.message.reply_text(f"No track called '{track_in}'. Your tracks: {tracks}")
        return

    day = db.target_day(chat_id)
    db.add_item(chat_id, matched, text, day)
    when = "tomorrow" if day == db.local_tomorrow(chat_id) else "today"
    await update.message.reply_text(f"Logged for {when}: [{matched}] {text}")


# ---------------- free-text logging ----------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not db.user_exists(chat_id):
        await update.message.reply_text("Send /start first to get set up.")
        return

    tracks = db.get_tracks(chat_id)
    pattern = build_track_pattern(tracks)
    text = update.message.text or ""
    matches = pattern.findall(text) if pattern else []

    if not matches:
        track_list = ", ".join(tracks) if tracks else "(no tracks set up yet)"
        await update.message.reply_text(
            f"Didn't catch a track. Your tracks: {track_list}\nFormat: TrackName: your item"
        )
        return

    day = db.target_day(chat_id)
    when = "tomorrow" if day == db.local_tomorrow(chat_id) else "today"

    added = []
    for label, item_text in matches:
        canonical = db.find_track_case_insensitive(chat_id, label) or label
        db.add_item(chat_id, canonical, item_text, day)
        added.append(f"[{canonical}] {item_text.strip()}")

    await update.message.reply_text(f"Logged for {when}:\n" + "\n".join(added))


# ---------------- check-in buttons ----------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    action, item_id_str = query.data.split(":")
    item_id = int(item_id_str)
    item = db.get_item(item_id)

    if item is None or item["chat_id"] != update.effective_chat.id:
        await query.answer("Not found.")
        return

    new_status = "done" if action == "done" else "missed"
    db.update_item_status(item_id, new_status)

    mark = "✅" if new_status == "done" else "❌"
    await query.edit_message_text(f"{mark} [{item['track']}] {item['text']}")
    await query.answer()


# ---------------- scheduled jobs (per-user via job.data = chat_id) ----------------

async def job_morning(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    if not db.get_user(chat_id):
        return
    db.set_planning_mode(chat_id, "today")
    today = db.local_today(chat_id)
    items = db.get_items_for_day(chat_id, today)

    if items:
        lines = "\n".join(f"[{it['track']}] {it['text']}" for it in items)
        text = f"Morning. Last night you planned:\n{lines}\n\nAnything to add?"
    else:
        tracks = db.get_tracks(chat_id)
        text = "Morning. What are your things today?\n\n" + "\n".join(f"{t}: ..." for t in tracks)

    await context.bot.send_message(chat_id=chat_id, text=text)


async def job_midday_nudge(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    if not db.get_user(chat_id):
        return
    today = db.local_today(chat_id)
    touched = db.tracks_touched_on(chat_id, today)
    tracks = db.get_tracks(chat_id)
    missing = [t for t in tracks if t not in touched]
    if not missing:
        return
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Nothing logged yet for: {', '.join(missing)}. Quick one-liner for any of them?",
    )


async def job_checkin(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    if not db.get_user(chat_id):
        return
    today = db.local_today(chat_id)
    pending = db.get_pending_items_for_day(chat_id, today)

    if not pending:
        await context.bot.send_message(chat_id=chat_id, text="Nothing pending tonight. Clean slate.")
        return

    await context.bot.send_message(chat_id=chat_id, text="Evening check-in:")
    for it in pending:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Done", callback_data=f"done:{it['id']}"),
            InlineKeyboardButton("❌ Missed", callback_data=f"miss:{it['id']}"),
        ]])
        await context.bot.send_message(
            chat_id=chat_id, text=f"[{it['track']}] {it['text']}", reply_markup=keyboard
        )


async def job_night(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    if not db.get_user(chat_id):
        return
    db.set_planning_mode(chat_id, "tomorrow")
    tracks = db.get_tracks(chat_id)
    text = "What are you planning for tomorrow?\n\n" + "\n".join(f"{t}: ..." for t in tracks)
    await context.bot.send_message(chat_id=chat_id, text=text)


async def job_recap(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.data
    if not db.get_user(chat_id):
        return
    summary = db.weekly_summary(chat_id)
    tracks = db.get_tracks(chat_id)
    lines = [f"{t}: {summary.get(t, 0)} day(s) hit this week" for t in tracks]
    streak_lines = [f"{t}: {db.current_streak(chat_id, t)} day streak" for t in tracks]
    await context.bot.send_message(
        chat_id=chat_id,
        text="Weekly recap:\n" + "\n".join(lines) + "\n\nCurrent streaks:\n" + "\n".join(streak_lines),
    )


# ---------------- main ----------------

def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    db.init_db()

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("tracks", tracks_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Re-sync every existing user's schedule on startup (job_queue is in-memory).
    for user in db.get_all_users():
        schedule_all_for_user(app, user["chat_id"])

    logger.info("Daily Anchor Bot (multi-user) starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
