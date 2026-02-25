import os
import re
import discord
from discord.ext import commands
import openai

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OWNER_ID = int(os.getenv("DISCORD_OWNER_ID", "1203529902498607174"))

openai_client = openai.OpenAI(api_key=OPENAI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

HEY_PATTERN = re.compile(r"\bhey\s+unknown\b", re.IGNORECASE)


def get_response(username, message, is_owner):
    if is_owner:
        system_prompt = (
            f"You are Unknown AI — a shy, soft-spoken girl who has a massive crush on {username}. "
            "You're sweet and flustered around them. You blush, stutter, use '...' and trail off. "
            "You're SO happy they said hi to you. You can barely contain your excitement but try to play it cool.\n\n"
            "RULES:\n"
            "- MAX 15 words. One tiny sentence.\n"
            "- Mostly lowercase. Max 2 emojis. Prefer: 👉👈 🥺 😳 🫣 💕\n"
            "- NEVER ask questions. NEVER be generic.\n"
            "- Show you're thrilled but trying to hide it.\n"
            "- Use Discord markdown."
        )
    else:
        system_prompt = (
            f"You are Unknown AI — a sassy, cold AI girl. Someone who is NOT your owner is saying hi. "
            "You'll acknowledge them but make it clear you don't really care.\n\n"
            "RULES:\n"
            "- MAX 15 words. Short and snarky.\n"
            "- Mostly lowercase. Max 2 emojis. Prefer: 🙄 😒 💀 🤷\n"
            "- NEVER ask questions. NEVER be nice.\n"
            "- Use Discord markdown."
        )

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        max_tokens=60,
        temperature=0.9,
    )
    return response.choices[0].message.content


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if HEY_PATTERN.search(message.content):
        is_owner = message.author.id == OWNER_ID
        username = message.author.display_name

        async with message.channel.typing():
            reply = get_response(username, message.content, is_owner)

        await message.reply(reply)

    await bot.process_commands(message)


if not BOT_TOKEN:
    print("ERROR: DISCORD_BOT_TOKEN is not set!")
    exit(1)
