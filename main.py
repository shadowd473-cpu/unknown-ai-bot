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
