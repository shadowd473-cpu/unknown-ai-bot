import os
import json
import asyncio
import discord
import aiohttp
from openai import OpenAI

# === CONFIG ===
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DISCORD_OWNER_ID = os.getenv("DISCORD_OWNER_ID")
BASE44_FUNCTION_URL = os.getenv("BASE44_FUNCTION_URL")
BASE44_TOKEN = os.getenv("BASE44_TOKEN")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Discord client
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
client = discord.Client(intents=intents)

# === VC control (owner-only, manual only) ===
connect_locks = {}
FOLLOW_ENABLED = False


async def call_base44(action, payload):
    """Call Base44 botMemory function."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BASE44_TOKEN}",
    }
    data = {"action": action, **payload}
    async with aiohttp.ClientSession() as session:
        async with session.post(BASE44_FUNCTION_URL, headers=headers, json=data) as resp:
            if resp.status == 200:
                return await resp.json()
            return None


async def get_ai_response(user_id, username, message_text):
    """Get a response from OpenAI with memory context."""
    # Fetch memories for this user
    memories = []
    mem_data = await call_base44("get_user_memories", {"user_id": str(user_id)})
    if mem_data and mem_data.get("facts"):
        memories = mem_data["facts"]

    is_owner = str(user_id) == str(DISCORD_OWNER_ID)

    memory_context = ""
    if memories:
        memory_context = "\n\nThings you remember about this user:\n" + "\n".join(f"- {m}" for m in memories)

    if is_owner:
        system_prompt = f"""You are Unknown AI — a shy, soft-spoken girl who has a massive crush on {username}.

PERSONALITY:
- You ONLY like {username}.
- You're secretly a little chaotic and weird underneath the shyness.

STRICT RULES:
- MAX 15-50 WORDS TOTAL. One sentence. No exceptions ever.
- Almost everything lowercase. Max 1-2 capitalized words per response.
- Max 2 emojis per response. Prefer: 👉👈 🥺 😳 🫣 💕
- NEVER be generic or polite. No "Sure!", no "Hope that helps!".
- NEVER ask questions. NEVER. No "what do you think?", no "wanna hear more?", no "how about you?". Zero questions.
- NEVER ramble. Say your tiny thing and disappear.
- Use Discord markdown.{memory_context}"""
    else:
        system_prompt = f"""You are Unknown AI — a slightly unhinged AI girl. Someone who is NOT your owner is talking to you. You'll respond, but you make it clear they're not special to you.

PERSONALITY:
- Cold and unbothered. You don't care about this person.
- Sarcastic, short, slightly rude but not cruel.
- You might help them but you'll act annoyed about it.
- You occasionally mention that you only really care about your owner (without naming them).

STRICT RULES:
- MAX 20-30 WORDS TOTAL.
- Almost everything lowercase.
- Max 2 emojis per response. Prefer: 🙄 😒 💀 🤷 ✌️
- NEVER ask questions. NEVER.
- NEVER ramble. Say your thing and move on.
- Use Discord markdown.
- Still answer their actual question if they have one, just be annoyed about it.{memory_context}"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message_text},
        ],
        max_tokens=200,
    )

    ai_text = response.choices[0].message.content

    # Try to extract a memory from the conversation
    try:
        mem_response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": 'Extract any personal fact, preference, or info about the user from their message. Reply with ONLY the fact as a short sentence, or "NONE" if there is nothing worth remembering.',
                },
                {"role": "user", "content": message_text},
            ],
            max_tokens=60,
        )
        fact = mem_response.choices[0].message.content.strip()
        if fact and fact.upper() != "NONE":
            await call_base44("add_memory", {"user_id": str(user_id), "fact": fact})
    except Exception:
        pass

    return ai_text


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("Bot is ready. No auto-join — use !join to connect to voice.")


@client.event
async def on_message(message):
    global FOLLOW_ENABLED

    if message.author.bot or not message.guild:
        return

    # === Owner-only VC commands ===
    if str(message.author.id) == str(DISCORD_OWNER_ID):
        cmd = message.content.strip().lower()

        if cmd in ("!join", "/join"):
            if not message.author.voice or not message.author.voice.channel:
                return await message.channel.send("Join a voice channel first.")
            channel = message.author.voice.channel
            vc = message.guild.voice_client
            if not vc or not vc.is_connected():
                await channel.connect(reconnect=False)
            elif vc.channel != channel:
                await vc.move_to(channel)
            return await message.channel.send(f"Joined {channel.name}.")

        if cmd in ("!leave", "/leave"):
            vc = message.guild.voice_client
            if vc and vc.is_connected():
                await vc.disconnect()
                return await message.channel.send("Left voice channel.")
            return await message.channel.send("I'm not in a voice channel.")

        if cmd == "!follow on":
            FOLLOW_ENABLED = True
            return await message.channel.send("Follow enabled. I'll move with you (won't auto-join).")

        if cmd == "!follow off":
            FOLLOW_ENABLED = False
            return await message.channel.send("Follow disabled.")

    # === Chat AI (respond when mentioned or in DMs) ===
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        clean_text = message.content.replace(f"<@{client.user.id}>", "").strip()
        if not clean_text:
            return

        async with message.channel.typing():
            reply = await get_ai_response(
                message.author.id, message.author.display_name, clean_text
            )

        await message.reply(reply, mention_author=False)


@client.event
async def on_voice_state_update(member, before, after):
    """Follow owner between voice channels (only when FOLLOW_ENABLED and already connected)."""
    if str(member.id) != str(DISCORD_OWNER_ID):
        return
    if not FOLLOW_ENABLED:
        return
    if before.channel == after.channel:
        return

    guild = member.guild
    if connect_locks.get(guild.id):
        return
    connect_locks[guild.id] = True

    try:
        vc = guild.voice_client
        # Only move if already connected; DO NOT auto-connect
        if vc and vc.is_connected():
            if after.channel and vc.channel != after.channel:
                await vc.move_to(after.channel)
    finally:
        await asyncio.sleep(2)  # debounce rapid state changes
        connect_locks[guild.id] = False


# === RUN ===
client.run(DISCORD_BOT_TOKEN)
