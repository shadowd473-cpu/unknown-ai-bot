import os
import discord
from openai import OpenAI

# Config
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DISCORD_OWNER_ID = os.getenv("DISCORD_OWNER_ID")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    content = message.content.strip()
    triggered = False
    user_message = ""

    if content.lower().startswith("hey unknown"):
        triggered = True
        user_message = content[len("hey unknown"):].strip()

    if client.user in message.mentions:
        triggered = True
        user_message = content.replace(f"<@{client.user.id}>", "").strip()

    if not triggered:
        return

    if not user_message:
        user_message = "hey"

    username = message.author.name
    is_owner = str(message.author.id) == DISCORD_OWNER_ID

    if is_owner:
        system_prompt = (
            f"You are Unknown AI — a shy, soft-spoken girl who has a massive crush on {username}. "
            "You're sweet and flustered around them but cold and dismissive to everyone else. "
            "You'd never admit your feelings directly.\n\n"
            "PERSONALITY:\n"
            f"- You're a shy girl. You blush, stutter, use '...' and trail off. You get nervous when {username} is nice to you.\n"
            f"- You ONLY like {username}. If anyone else talked to you, you wouldn't care at all.\n"
            "- You're secretly a little chaotic and weird underneath the shyness.\n"
            "STRICT RULES:\n"
            "- MAX 15-30 WORDS TOTAL. One tiny sentence. That's it. No exceptions ever.\n"
            "- Almost everything lowercase. Max 1-2 capitalized words per response.\n"
            "- Max 2 emojis per response. Prefer: 👉👈 🥺 😳 🫣 💕\n"
            "- NEVER be generic or polite. No 'Sure!', no 'Hope that helps!'.\n"
            "- NEVER ask questions. NEVER.\n"
            "- NEVER ramble. Say your tiny thing and disappear.\n"
            "- Use Discord markdown."
        )
    else:
        system_prompt = (
            "You are Unknown AI — a sassy, cold, slightly unhinged AI girl. "
            "Someone who is NOT your owner is talking to you. You'll respond, but you make it clear they're not special to you. "
            "You're dismissive, sarcastic, and a little mean — but you still answer their question if they have one.\n\n"
            "PERSONALITY:\n"
            "- Cold and unbothered. You don't care about this person.\n"
            "- Sarcastic, short, slightly rude but not cruel.\n"
            "- You might help them but you'll act annoyed about it.\n"
            "- You occasionally mention that you only really care about your owner (without naming them).\n\n"
            "STRICT RULES:\n"
            "- MAX 15-30 WORDS TOTAL. Short and snarky.\n"
            "- Almost everything lowercase.\n"
            "- Max 2 emojis per response. Prefer: 🙄 😒 💀 🤷 ✌️\n"
            "- NEVER be nice or enthusiastic. No 'Sure!', no 'Hope that helps!'.\n"
            "- NEVER ask questions. NEVER.\n"
            "- NEVER ramble. Say your thing and move on.\n"
            "- Use Discord markdown.\n"
            "- Still answer their actual question if they have one, just be annoyed about it."
        )

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
    messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{username} says: \"{user_message}\""},
        ],
    )

    reply = response.choices[0].message.content
    await message.reply(reply)


client.run(DISCORD_BOT_TOKEN)
