# Daily Anchor Bot (multi-user)

A Telegram bot that keeps your tracks honest — Task, Content, Learning by
default, but fully customizable. One bot, any number of people, each with
their own independent tracks, ping times, timezone, and streaks.

## How it works for each person who uses it

1. They message the bot `/start` — that's their entire signup.
2. Default tracks (Task, Content, Learning) and default times get created just for them.
3. Everything from there is theirs to control, entirely from Telegram — no code, no redeploying.

## Daily flow (defaults — fully changeable per person)

- **08:00** — morning ping. Shows what got planned the night before for today, asks if there's anything to add.
- **14:00** — midday nudge. Only fires for tracks that still have nothing logged that day.
- **20:30** — evening check-in. Tap ✅ Done or ❌ Missed on each pending item.
- **21:00** — plan-tomorrow ping. Whatever you log after this (free text or `/add`) lands on *tomorrow* automatically until the next morning ping flips it back.
- **Sunday 20:00** — weekly recap + current streaks.

## Logging — two ways, both work anytime

**Free text**, no command needed — just message the bot:
```
Task: reply to that client email
Content: thread about XO market mechanics
Learning: finish chapter 3
```
Each line matched against *your* current track names, case-insensitive. Send one line or several in one message.

**Explicit command:**
```
/add Task reply to that client email
```

## Commands

| Command | What it does |
|---|---|
| `/start` | Register (or re-sync your schedule if already registered) |
| `/status` | Today's items + your current streaks |
| `/add <track> <text>` | Manually log an item |
| `/tracks` | List your tracks |
| `/tracks add <name>` | Add a track (letters/numbers/underscore, no spaces) |
| `/tracks remove <name>` | Remove a track |
| `/tracks rename <old> <new>` | Rename a track (carries history forward) |
| `/settings` | Show your current times + timezone |
| `/settings morning\|midday\|checkin\|night HH:MM` | Change any ping time |
| `/settings timezone <IANA tz>` | e.g. `Africa/Lagos`, `America/New_York`, `Europe/London` |
| `/help` | Quick reference |

Every setting and track is scoped to the person's own Telegram chat — nobody can see or affect anyone else's data, all on the same bot.

## Setup

### 1. Create the bot in Telegram
- Message **@BotFather** → `/newbot` → name it → you get a **token** like `123456:ABC-DEF...`

### 2. Push this folder to GitHub
```bash
cd daily-anchor-bot
git init
git add .
git commit -m "Daily Anchor Bot - multi-user"
git branch -M main
git remote add origin https://github.com/<your-username>/daily-anchor-bot.git
git push -u origin main
```

### 3. Deploy to Railway
- New Project → Deploy from GitHub repo → pick `daily-anchor-bot`
- Railway auto-detects the `Procfile`
- **Variables** tab → add `TELEGRAM_BOT_TOKEN` = your token from BotFather
- Deploy. No port/web service needed — it just runs as a worker.

### 4. Use it
- You (or anyone you share the bot's @username with) message it `/start`
- That's the whole signup — each person's tracks/times/streaks are independent from that point on

### Optional: persist data across redeploys
Railway's default filesystem resets when you redeploy, which would wipe
everyone's streak history. To keep it permanent:
- Railway → Settings → **Volumes** → add a volume, mount at `/data`
- Set env var `DB_PATH` = `/data/anchor.db`

Without this, the bot still works day-to-day — streaks just reset to zero on a redeploy.

## Notes
- Default timezone is `Africa/Lagos` (WAT) — anyone can override their own with `/settings timezone <tz>`.
- On bot restart, every registered user's schedule is automatically re-synced from the database — nobody needs to `/start` again after a redeploy.
- Track names are kept simple (single word, no spaces) so free-text parsing stays unambiguous. If you want spaces in a track name later, that's a small follow-up change, not a rebuild.
