import discord
from discord.ext import commands
import aiohttp
import asyncio
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────────
BOT_TOKEN = "MTQ4MTM5NzkyNDUyMDAwNTczNA.GEX1D6.l3CU33IOWi1Rs7erRiE4FeKhue4nL5UYKVIEw0"

SUPABASE_URL    = "https://uohmshxaypofbdnuaiwj.supabase.co"
SUPABASE_KEY    = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVvaG1zaHhheXBvZmJkbnVhaXdqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzMxNjY2NDQsImV4cCI6MjA4ODc0MjY0NH0.32yA_vM19i_0K-e95qdXrY4dR6m_fTDsJaNXqfi7T4I"
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1475155012266098688/gN9IvDw1VACuP9wrUJ6jjpxsfbyTC0_laPXcSI4OE1s9wIlbhFN58XoEpnju-TNm-uZb"

ALLOWED_ROLES = {"owner", "developer", "admin", "admins"}

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}
# ──────────────────────────────────────────────────────────────────────────────

_processed_messages = set()
_processed_lock = asyncio.Lock()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="?", intents=intents)

# ── Role check ─────────────────────────────────────────────────────────────────

def has_allowed_role():
    async def predicate(ctx):
        user_roles = {role.name.lower() for role in ctx.author.roles}
        if user_roles & ALLOWED_ROLES or ctx.author.guild_permissions.administrator:
            return True
        raise commands.CheckFailure("missing_role")
    return commands.check(predicate)

# ── Deduplication ──────────────────────────────────────────────────────────────

async def already_processed(message_id: int) -> bool:
    async with _processed_lock:
        if message_id in _processed_messages:
            return True
        _processed_messages.add(message_id)
        if len(_processed_messages) > 500:
            _processed_messages.discard(next(iter(_processed_messages)))
        return False

# ── Mention parser ─────────────────────────────────────────────────────────────

def parse_mention(identifier: str) -> str:
    if identifier.startswith("<@") and identifier.endswith(">"):
        uid = identifier[2:-1].lstrip("!")
        return uid
    return identifier

def resolve_display_name(identifier, player_data, player_key, guild):
    raw_id = identifier if identifier.isdigit() else (
        player_key.replace("discord_", "") if player_key.startswith("discord_") else None
    )
    if raw_id and raw_id.isdigit() and guild:
        member = guild.get_member(int(raw_id))
        if member:
            return member.display_name
    for field in ("displayName", "username", "discordName"):
        name = player_data.get(field)
        if name and name not in ("null", "", None):
            return str(name)
    return player_key.replace("discord_", "") if player_key.startswith("discord_") else player_key

# ── Supabase helpers ───────────────────────────────────────────────────────────

async def db_get(user_id: str):
    """Fetch user data from Supabase. user_id should be like 'discord_123456789'"""
    url = f"{SUPABASE_URL}/rest/v1/users?id=eq.{user_id}&select=*"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=SUPABASE_HEADERS) as resp:
                rows = await resp.json()
                print(f"[dbGet] id={user_id} status={resp.status} rows={rows}")
                if isinstance(rows, list) and len(rows) > 0:
                    return rows[0].get("data")
    except Exception as e:
        print(f"❌ db_get error: {e}")
    return None

async def db_set(user_id: str, data: dict) -> bool:
    """Upsert user data in Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/users"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=SUPABASE_HEADERS, json={"id": user_id, "data": data}) as resp:
                print(f"[dbSet] id={user_id} status={resp.status}")
                return resp.status in (200, 201, 204)
    except Exception as e:
        print(f"❌ db_set error: {e}")
    return False

async def get_player(identifier: str):
    """
    Look up a player by Discord ID (digits) or username.
    Returns (player_key, player_data) or (None, None).
    """
    # Discord ID path
    if identifier.isdigit() and len(identifier) >= 17:
        key = f"discord_{identifier}"
        data = await db_get(key)
        if data:
            return key, data
        print(f"[get_player] Not found with key {key}")
        return None, None

    # Username path — search all users
    url = f"{SUPABASE_URL}/rest/v1/users?select=*"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=SUPABASE_HEADERS) as resp:
                rows = await resp.json()
                if not isinstance(rows, list):
                    return None, None
                for row in rows:
                    d = row.get("data", {})
                    stored = (d.get("displayName") or d.get("username") or d.get("discordName") or "").strip().lower()
                    if stored == identifier.strip().lower():
                        return row["id"], d
    except Exception as e:
        print(f"❌ get_player search error: {e}")
    return None, None

# ── Webhook log ────────────────────────────────────────────────────────────────

async def send_discord_log(embed_dict: dict):
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(DISCORD_WEBHOOK, json={"embeds": [embed_dict]})
    except Exception as e:
        print(f"❌ Webhook error: {e}")

# ── Embed builders ─────────────────────────────────────────────────────────────

def deposit_embed(recipient, admin, amount, old_bal, new_bal):
    return {
        "title": "💰 DEPOSIT — Coins Added",
        "color": 0x2ECC71,
        "description": f"**{recipient}** received coins from **{admin}**",
        "fields": [
            {"name": "📥 Recipient",       "value": f"**{recipient}**", "inline": True},
            {"name": "👨‍💼 Admin",           "value": f"**{admin}**",     "inline": True},
            {"name": "⭐ Amount",           "value": f"+{amount} coins", "inline": False},
            {"name": "💰 Previous Balance", "value": f"{old_bal} coins", "inline": True},
            {"name": "💎 New Balance",      "value": f"{new_bal} coins", "inline": True},
        ],
        "footer": {"text": "BSS Gambling — Deposit"},
        "timestamp": datetime.utcnow().isoformat(),
    }

def withdraw_embed(target, admin, amount, old_bal, new_bal):
    return {
        "title": "🔻 WITHDRAWAL — Coins Removed",
        "color": 0xE74C3C,
        "description": f"**{target}** had coins withdrawn by **{admin}**",
        "fields": [
            {"name": "📤 Withdrawn From",  "value": f"**{target}**",    "inline": True},
            {"name": "👨‍💼 Admin",           "value": f"**{admin}**",     "inline": True},
            {"name": "⭐ Amount",           "value": f"-{amount} coins", "inline": False},
            {"name": "💰 Previous Balance", "value": f"{old_bal} coins", "inline": True},
            {"name": "💎 New Balance",      "value": f"{new_bal} coins", "inline": True},
        ],
        "footer": {"text": "BSS Gambling — Withdrawal"},
        "timestamp": datetime.utcnow().isoformat(),
    }

# ── Events ─────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot is ready! Logged in as {bot.user}")
    print(f"📝 Commands: ?deposit | ?withdraw | ?balance")
    print(f"🔐 Allowed roles: {', '.join(ALLOWED_ROLES)}")
    print(f"🗄️  Supabase: {SUPABASE_URL}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ **Permission Denied!**\nOnly users with the **owner**, **developer**, or **admin** role can use this command!")
    elif isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument: `{error.param.name}`")
    else:
        print(f"❌ Command error: {error}")

# ── Commands ───────────────────────────────────────────────────────────────────

@bot.command()
@has_allowed_role()
async def deposit(ctx, user: str, amount: int):
    """?deposit @mention 500  OR  ?deposit discordId 500"""
    if await already_processed(ctx.message.id):
        return
    if amount <= 0:
        await ctx.send("❌ Amount must be positive!")
        return

    identifier = parse_mention(user)
    player_key, player_data = await get_player(identifier)

    if not player_data:
        await ctx.send(f"❌ Player `{identifier}` not found. They need to log into the website first.")
        return

    player_name = resolve_display_name(identifier, player_data, player_key, ctx.guild)
    old_balance = player_data.get("chips", 0)
    new_balance = old_balance + amount

    player_data["chips"] = new_balance
    if not await db_set(player_key, player_data):
        await ctx.send("❌ Failed to update Supabase — try again!")
        return

    await send_discord_log(deposit_embed(player_name, ctx.author.display_name, amount, old_balance, new_balance))

    embed = discord.Embed(title="✅ Deposit Successful", color=discord.Color.green(),
                          description=f"Deposited **{amount}** coins to **{player_name}**")
    embed.add_field(name="💰 Previous Balance", value=f"{old_balance} coins", inline=True)
    embed.add_field(name="💎 New Balance",       value=f"{new_balance} coins", inline=True)
    embed.add_field(name="🌐 Status",            value="✅ Website Updated!",  inline=False)
    await ctx.send(embed=embed)


@bot.command()
@has_allowed_role()
async def withdraw(ctx, user: str, amount: int):
    """?withdraw @mention 500  OR  ?withdraw discordId 500"""
    if await already_processed(ctx.message.id):
        return
    if amount <= 0:
        await ctx.send("❌ Amount must be positive!")
        return

    identifier = parse_mention(user)
    player_key, player_data = await get_player(identifier)

    if not player_data:
        await ctx.send(f"❌ Player `{identifier}` not found. They need to log into the website first.")
        return

    player_name = resolve_display_name(identifier, player_data, player_key, ctx.guild)
    old_balance = player_data.get("chips", 0)

    if old_balance < amount:
        await ctx.send(f"❌ **{player_name}** only has **{old_balance}** coins!\nCannot withdraw **{amount}** coins.")
        return

    new_balance = old_balance - amount
    player_data["chips"] = new_balance
    if not await db_set(player_key, player_data):
        await ctx.send("❌ Failed to update Supabase — try again!")
        return

    await send_discord_log(withdraw_embed(player_name, ctx.author.display_name, amount, old_balance, new_balance))

    embed = discord.Embed(title="✅ Withdrawal Successful", color=discord.Color.red(),
                          description=f"Withdrew **{amount}** coins from **{player_name}**")
    embed.add_field(name="💰 Previous Balance", value=f"{old_balance} coins", inline=True)
    embed.add_field(name="💎 New Balance",       value=f"{new_balance} coins", inline=True)
    embed.add_field(name="🌐 Status",            value="✅ Website Updated!",  inline=False)
    await ctx.send(embed=embed)


@bot.command()
@has_allowed_role()
async def balance(ctx, user: str):
    """?balance @mention  OR  ?balance discordId"""
    identifier = parse_mention(user)
    player_key, player_data = await get_player(identifier)

    if not player_data:
        await ctx.send(f"❌ Player `{identifier}` not found.")
        return

    player_name = resolve_display_name(identifier, player_data, player_key, ctx.guild)
    coins = player_data.get("chips", 0)

    embed = discord.Embed(title="💰 Player Balance", color=discord.Color.blue(),
                          description=f"**{player_name}**")
    embed.add_field(name="⭐ Current Balance", value=f"**{coins}** coins", inline=False)
    await ctx.send(embed=embed)


bot.run(BOT_TOKEN)
