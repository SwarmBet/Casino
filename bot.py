"""
BSS Gambling - Discord Admin Bot
Commands: ?deposit, ?withdraw
Database: Supabase (same backend as the website)
"""

import os
import discord
from discord.ext import commands
import aiohttp
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN      = os.getenv("BOT_TOKEN")
SUPABASE_URL   = os.getenv("SUPABASE_URL", "https://uohmshxaypofbdnuaiwj.supabase.co")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY")
DISCORD_WEBHOOK= os.getenv("DISCORD_WEBHOOK")

# Only users with these role names (case-insensitive) can run admin commands.
# Add or remove role names to match your server setup.
ADMIN_ROLES    = {"admin", "owner", "moderator", "staff"}

# ── Bot setup ─────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="?", intents=intents, help_command=None)

# ── Supabase helpers ──────────────────────────────────────────────────────────
HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates",
}

async def db_get(session: aiohttp.ClientSession, user_id: str) -> dict | None:
    """
    Fetches a user row from Supabase.
    The website stores rows as: { id: "discord_<user_id>", data: { chips: N, ... } }
    Returns the inner `data` dict, or None if the user doesn't exist.
    """
    db_id = f"discord_{user_id}"
    url   = f"{SUPABASE_URL}/rest/v1/users?id=eq.{db_id}&select=*"
    async with session.get(url, headers=HEADERS) as resp:
        rows = await resp.json()
        if not isinstance(rows, list) or len(rows) == 0:
            return None
        return rows[0].get("data")


async def db_set(session: aiohttp.ClientSession, user_id: str, data: dict):
    """
    Upserts a user row into Supabase.
    """
    db_id = f"discord_{user_id}"
    url   = f"{SUPABASE_URL}/rest/v1/users"
    payload = {"id": db_id, "data": data}
    async with session.post(url, headers=HEADERS, json=payload) as resp:
        return resp.status in (200, 201)


# ── Discord Webhook logger ────────────────────────────────────────────────────
async def send_webhook_log(session: aiohttp.ClientSession, action: str, ctx,
                           target_id: str, target_name: str,
                           amount: int, old_bal: int, new_bal: int):
    """Sends a rich embed to the webhook channel, matching the website's log format."""
    if not DISCORD_WEBHOOK:
        return

    admin_name = ctx.author.display_name

    if action == "deposit":
        embed = {
            "title": "$ DEPOSIT - Coins Added",
            "color": 0x2ecc71,
            "description": f"**{target_name}** received coins from **{admin_name}**",
            "fields": [
                {"name": "📥 Recipient Account",  "value": target_name,         "inline": True},
                {"name": "👨‍💼 Admin Account",     "value": admin_name,          "inline": True},
                {"name": "★ Amount Deposited",    "value": f"+{amount} coins",  "inline": False},
                {"name": "$ Previous Balance",    "value": f"{old_bal} coins",  "inline": True},
                {"name": "◆ New Balance",          "value": f"{new_bal} coins",  "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Bss Gambling Admin Panel - Deposit"},
        }
    else:  # withdraw
        embed = {
            "title": "🔻 WITHDRAWAL - Coins Removed",
            "color": 0xe74c3c,
            "description": f"**{target_name}** had coins withdrawn by **{admin_name}**",
            "fields": [
                {"name": "📤 Withdrawn From",      "value": target_name,         "inline": True},
                {"name": "👨‍💼 Admin Account",     "value": admin_name,          "inline": True},
                {"name": "★ Amount Withdrawn",     "value": f"-{amount} coins",  "inline": False},
                {"name": "$ Previous Balance",    "value": f"{old_bal} coins",  "inline": True},
                {"name": "◆ New Balance",          "value": f"{new_bal} coins",  "inline": True},
            ],
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Bss Gambling Admin Panel - Withdrawal"},
        }

    await session.post(DISCORD_WEBHOOK, json={"embeds": [embed]})


# ── Permission check ──────────────────────────────────────────────────────────
def is_admin(ctx: commands.Context) -> bool:
    """Returns True if the message author has at least one admin role."""
    if ctx.guild is None:
        return False
    user_roles = {r.name.lower() for r in ctx.author.roles}
    return bool(user_roles & ADMIN_ROLES)


# ── Commands ──────────────────────────────────────────────────────────────────
@bot.command(name="deposit")
async def deposit(ctx: commands.Context, member: discord.Member = None, amount: str = None):
    """
    Usage: ?deposit @user <amount>
    Adds `amount` coins to the target user's balance on the website.
    Requires an admin role.
    """
    # ── Permission gate ──
    if not is_admin(ctx):
        await ctx.send("❌ You don't have permission to use this command.")
        return

    # ── Argument validation ──
    if member is None or amount is None:
        await ctx.send(
            "⚠️ **Usage:** `?deposit @user <amount>`\n"
            "**Example:** `?deposit @sepiakfromsponge 500`"
        )
        return

    user_id = str(member.id)

    try:
        amount_int = int(amount)
    except ValueError:
        await ctx.send("❌ Amount must be a whole number.")
        return

    if amount_int <= 0:
        await ctx.send("❌ Amount must be greater than 0.")
        return

    # ── Database operation ──
    async with aiohttp.ClientSession() as session:
        user_data = await db_get(session, user_id)

        if user_data is None:
            # User doesn't exist on the website yet — create a fresh record
            user_data = {"chips": 0, "discord": True, "displayName": member.display_name}

        old_balance = int(user_data.get("chips", 0))
        new_balance = old_balance + amount_int
        user_data["chips"] = new_balance

        success = await db_set(session, user_id, user_data)
        if not success:
            await ctx.send("❌ Database error — could not update balance. Please try again.")
            return

        display_name = user_data.get("displayName") or user_data.get("username") or member.display_name

        # ── Webhook log ──
        await send_webhook_log(
            session, "deposit", ctx,
            user_id, display_name,
            amount_int, old_balance, new_balance
        )

    # ── Confirmation ──
    embed = discord.Embed(
        title="✅ Deposit Successful",
        color=0x2ecc71
    )
    embed.add_field(name="User",             value=member.mention,       inline=True)
    embed.add_field(name="Display Name",     value=display_name,         inline=True)
    embed.add_field(name="Amount Added",     value=f"+{amount_int} ★",   inline=False)
    embed.add_field(name="Previous Balance", value=f"{old_balance} ★",   inline=True)
    embed.add_field(name="New Balance",      value=f"{new_balance} ★",   inline=True)
    embed.set_footer(text=f"Admin: {ctx.author.display_name}")
    embed.timestamp = datetime.utcnow()

    await ctx.send(
        f"✅ Successfully deposited **{amount_int} coins** to {member.mention}.",
        embed=embed
    )


@bot.command(name="withdraw")
async def withdraw(ctx: commands.Context, member: discord.Member = None, amount: str = None):
    """
    Usage: ?withdraw @user <amount>
    Removes `amount` coins from the target user's balance on the website.
    Requires an admin role.
    """
    # ── Permission gate ──
    if not is_admin(ctx):
        await ctx.send("❌ You don't have permission to use this command.")
        return

    # ── Argument validation ──
    if member is None or amount is None:
        await ctx.send(
            "⚠️ **Usage:** `?withdraw @user <amount>`\n"
            "**Example:** `?withdraw @sepiakfromsponge 200`"
        )
        return

    user_id = str(member.id)

    try:
        amount_int = int(amount)
    except ValueError:
        await ctx.send("❌ Amount must be a whole number.")
        return

    if amount_int <= 0:
        await ctx.send("❌ Amount must be greater than 0.")
        return

    # ── Database operation ──
    async with aiohttp.ClientSession() as session:
        user_data = await db_get(session, user_id)

        if user_data is None:
            await ctx.send(f"❌ {member.mention} was not found in the database.")
            return

        old_balance = int(user_data.get("chips", 0))

        if amount_int > old_balance:
            await ctx.send(
                f"❌ Cannot withdraw **{amount_int} coins** — "
                f"{member.mention} only has **{old_balance} coins**."
            )
            return

        new_balance = old_balance - amount_int
        user_data["chips"] = new_balance

        success = await db_set(session, user_id, user_data)
        if not success:
            await ctx.send("❌ Database error — could not update balance. Please try again.")
            return

        display_name = user_data.get("displayName") or user_data.get("username") or member.display_name

        # ── Webhook log ──
        await send_webhook_log(
            session, "withdraw", ctx,
            user_id, display_name,
            amount_int, old_balance, new_balance
        )

    # ── Confirmation ──
    embed = discord.Embed(
        title="🔻 Withdrawal Successful",
        color=0xe74c3c
    )
    embed.add_field(name="User",             value=member.mention,       inline=True)
    embed.add_field(name="Display Name",     value=display_name,         inline=True)
    embed.add_field(name="Amount Removed",   value=f"-{amount_int} ★",   inline=False)
    embed.add_field(name="Previous Balance", value=f"{old_balance} ★",   inline=True)
    embed.add_field(name="New Balance",      value=f"{new_balance} ★",   inline=True)
    embed.set_footer(text=f"Admin: {ctx.author.display_name}")
    embed.timestamp = datetime.utcnow()

    await ctx.send(
        f"✅ Successfully withdrew **{amount_int} coins** from {member.mention}.",
        embed=embed
    )


# ── Misc ──────────────────────────────────────────────────────────────────────
@bot.command(name="help")
async def help_cmd(ctx: commands.Context):
    embed = discord.Embed(
        title="🎰 BSS Gambling — Admin Bot",
        description="Manage player coin balances on the website.",
        color=0x0fd68a
    )
    embed.add_field(
        name="`?deposit <user_id> <amount>`",
        value="Add coins to a player's balance.\n**Example:** `?deposit 123456789012345678 500`",
        inline=False
    )
    embed.add_field(
        name="`?withdraw <user_id> <amount>`",
        value="Remove coins from a player's balance.\n**Example:** `?withdraw 123456789012345678 200`",
        inline=False
    )
    embed.set_footer(text="Requires an Admin / Staff role.")
    await ctx.send(embed=embed)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"   Prefix  : ?")
    print(f"   Commands: ?deposit, ?withdraw, ?help")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="BSS Gambling 🎰"
        )
    )


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        return  # Silently ignore unknown commands
    raise error


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set in your .env file!")
    if not SUPABASE_KEY:
        raise RuntimeError("SUPABASE_KEY is not set in your .env file!")
    bot.run(BOT_TOKEN)
