# 🎰 BSS Gambling — Discord Admin Bot

A Discord bot that lets admins **deposit** and **withdraw** coins directly in
your website's Supabase database using simple prefix commands.

---

## Commands

| Command | Description | Example |
|---|---|---|
| `?deposit <user_id> <amount>` | Add coins to a player | `?deposit 123456789012345678 500` |
| `?withdraw <user_id> <amount>` | Remove coins from a player | `?withdraw 123456789012345678 200` |
| `?help` | Show command list | `?help` |

> **Note:** `<user_id>` is the player's **Discord User ID** (17–19 digit number).  
> To find it: enable Developer Mode in Discord → right-click a user → **Copy User ID**.

---

## Setup Guide

### Step 1 — Create a Discord Bot

1. Go to https://discord.com/developers/applications
2. Click **New Application** → give it a name (e.g. `BSS Admin Bot`)
3. Go to the **Bot** tab → click **Add Bot**
4. Under **Privileged Gateway Intents**, enable **Message Content Intent**
5. Click **Reset Token** and copy your bot token (keep it secret!)
6. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Read Message History`
7. Copy the generated URL and open it in your browser to invite the bot to your server

### Step 2 — Configure the Bot

1. Copy `.env.example` to `.env`:
   ```
   cp .env.example .env
   ```
2. Open `.env` and fill in:
   - `BOT_TOKEN` — your Discord bot token from Step 1
   - `SUPABASE_KEY` — your Supabase anon key (already in your website's HTML)
   - `DISCORD_WEBHOOK` — your webhook URL for logging (already in your website's HTML)

### Step 3 — Set Up Admin Roles

By default, the bot allows commands from users with any of these role names:
**Admin**, **Owner**, **Moderator**, **Staff**

To change this, open `bot.py` and edit the `ADMIN_ROLES` set near the top:
```python
ADMIN_ROLES = {"admin", "owner", "moderator", "staff"}
```
Role names are case-insensitive. Make sure these roles exist in your Discord server.

### Step 4 — Install & Run

**Requirements:** Python 3.10+

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python bot.py
```

You should see:
```
✅ Logged in as BSS Admin Bot#1234 (ID: ...)
   Prefix  : ?
   Commands: ?deposit, ?withdraw, ?help
```

---

## How It Works

1. An admin runs `?deposit 123456789012345678 500`
2. The bot looks up the player in your **Supabase `users` table** using the key `discord_<user_id>`
3. It adds 500 to their `chips` field and saves the updated record
4. A rich embed confirmation is sent back to Discord
5. A matching log embed is posted to your webhook channel (same format as the website's admin panel)

If the player has never logged into the website before, the bot will **create a new record** for them so they can log in and find their coins waiting.

---

## Keeping the Bot Online 24/7

| Option | Details |
|---|---|
| **Railway** (recommended free tier) | https://railway.app — connect your repo, set env vars in dashboard |
| **Render** | https://render.com — free background workers |
| **VPS / home server** | Use `screen`, `tmux`, or a `systemd` service |
| **Replit** | Works but may sleep after inactivity on free tier |

---

## File Structure

```
bss_bot/
├── bot.py            ← Main bot (all logic lives here)
├── requirements.txt  ← Python dependencies
├── .env.example      ← Template — copy to .env and fill in
└── README.md         ← This file
```
