import discord
import os
import aiohttp
import json
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

OWNER_ID = 1203529902498607174
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
WARNINGS_FILE = "/tmp/warnings.json"

# --- Warnings Storage ---
def load_warnings():
    try:
        with open(WARNINGS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_warnings(data):
    with open(WARNINGS_FILE, "w") as f:
        json.dump(data, f)

def add_warning(guild_id, user_id, username, reason, issued_by):
    data = load_warnings()
    key = f"{guild_id}:{user_id}"
    if key not in data:
        data[key] = []
    data[key].append({
        "username": username,
        "reason": reason,
        "issued_by": issued_by,
        "date": datetime.utcnow().isoformat()
    })
    save_warnings(data)
    return len(data[key])

def get_warnings(guild_id, user_id):
    data = load_warnings()
    key = f"{guild_id}:{user_id}"
    return data.get(key, [])

# --- AI Response ---
async def get_ai_response(prompt):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300
            }
        ) as resp:
            data = await resp.json()
            return data["choices"][0]["message"]["content"]

# --- Discord API Helper ---
async def discord_api(method, endpoint, json_body=None):
    headers = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    async with aiohttp.ClientSession() as session:
        req_method = getattr(session, method.lower())
        async with req_method(f"https://discord.com/api/v10{endpoint}", headers=headers, json=json_body) as resp:
            if resp.status == 204:
                return None
            return await resp.json()

# --- Events ---
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    bot_mentioned = client.user in message.mentions
    hey_unknown = "hey unknown" in message.content.lower()

    if not bot_mentioned and not hey_unknown:
        return

    is_owner = message.author.id == OWNER_ID
    username = message.author.name

    if is_owner:
        prompt = f"You are Unknown AI — a shy, sweet girl with a crush on {username}. Be flustered and cute. MAX 20 words, lowercase, max 2 emojis. No questions. {username} says: {message.content}"
    else:
        prompt = f"You are Unknown AI — snarky and cold. Be dismissive but still answer. MAX 20 words, lowercase, max 2 emojis. No questions. {username} says: {message.content}"

    response = await get_ai_response(prompt)
    await message.reply(response)

@client.event
async def on_interaction(interaction):
    if interaction.type != discord.InteractionType.application_command:
        return

    command = interaction.data["name"]
    options = {opt["name"]: opt["value"] for opt in interaction.data.get("options", [])}
    guild_id = str(interaction.guild_id)

    # /warn user reason
    if command == "warn":
        target_id = options["user"]
        reason = options.get("reason", "No reason provided")
        # Resolve username
        resolved = interaction.data.get("resolved", {}).get("users", {})
        target_username = resolved.get(target_id, {}).get("username", target_id)
        issued_by = str(interaction.user.id)

        count = add_warning(guild_id, target_id, target_username, reason, issued_by)
        await interaction.response.send_message(
            f"⚠️ **Warning issued to <@{target_id}>**\n**Reason:** {reason}\n**Total warnings:** {count}"
        )

# /mute user duration reason
    elif command == "mute":
        target_id = options["user"]
        duration = options.get("duration", 5)
        reason = options.get("reason", "No reason provided")
        timeout_until = (datetime.utcnow() + timedelta(minutes=duration)).isoformat()

        try:
            await discord_api("PATCH", f"/guilds/{guild_id}/members/{target_id}", {
                "communication_disabled_until": timeout_until
            })
            await interaction.response.send_message(
                f"🔇 **<@{target_id}> has been muted for {duration} minute(s).**\n**Reason:** {reason}"
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to mute: {e}")

    # /purge amount
    elif command == "purge":
        amount = min(max(options.get("amount", 5), 1), 100)
        channel_id = str(interaction.channel_id)

        try:
            messages = await discord_api("GET", f"/channels/{channel_id}/messages?limit={amount}")
            if not messages:
                await interaction.response.send_message("❌ No messages found.")
                return

            # Filter messages older than 14 days
            two_weeks_ago = datetime.utcnow() - timedelta(days=14)
            deletable = [m for m in messages if datetime.fromisoformat(m["timestamp"].replace("+00:00", "")) > two_weeks_ago]

            if not deletable:
                await interaction.response.send_message("❌ No deletable messages (older than 14 days).")
                return

            if len(deletable) == 1:
                await discord_api("DELETE", f"/channels/{channel_id}/messages/{deletable[0]['id']}")
            else:
                await discord_api("POST", f"/channels/{channel_id}/messages/bulk-delete", {
                    "messages": [m["id"] for m in deletable]
                })

            await interaction.response.send_message(f"🗑️ **Deleted {len(deletable)} message(s).**")
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to purge: {e}")

    # /warnings user
    elif command == "warnings":
        target_id = options["user"]
        warns = get_warnings(guild_id, target_id)

        if not warns:
            await interaction.response.send_message(f"✅ <@{target_id}> has no warnings.")
        else:
            lines = [f"**{i+1}.** {w['reason']} ({w['date'][:10]})" for i, w in enumerate(warns)]
            await interaction.response.send_message(
                f"📋 **Warnings for <@{target_id}> ({len(warns)} total):**\n" + "\n".join(lines)
            )

    # /unknown message (chat command)
    elif command == "unknown":
        user_message = options.get("message", "")
        username = interaction.user.name
        is_owner = interaction.user.id == OWNER_ID

        await interaction.response.defer()

        if is_owner:
            prompt = f"You are Unknown AI — a shy, sweet girl with a crush on {username}. Be flustered and cute. MAX 20 words, lowercase, max 2 emojis. No questions. {username} says: {user_message}"
        else:
            prompt = f"You are Unknown AI — snarky and cold. Be dismissive but still answer. MAX 20 words, lowercase, max 2 emojis. No questions. {username} says: {user_message}"

        response = await get_ai_response(prompt)
        await interaction.followup.send(response[:2000])

client.run(BOT_TOKEN)
