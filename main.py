import discord
import os
import aiohttp

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

OWNER_ID = 1203529902498607174
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

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

client.run(BOT_TOKEN)
