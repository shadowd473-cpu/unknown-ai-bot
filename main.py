import os
import json
import asyncio
import re
import discord
import aiohttp
from openai import OpenAI
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import yt_dlp


class SilenceSource(discord.AudioSource):
    """Streams silence to keep the bot connected to voice."""
    def read(self):
        return b'\xf8\xff\xfe'

    def is_opus(self):
        return True


# === CONFIG ===
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DISCORD_OWNER_ID = os.getenv("DISCORD_OWNER_ID")
BASE44_FUNCTION_URL = os.getenv("BASE44_FUNCTION_URL")
BASE44_TOKEN = os.getenv("BASE44_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET,
))

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
}
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

# Discord client
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
client = discord.Client(intents=intents)


async def call_base44(action, payload):
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
    memories = []
    mem_data = await call_base44("get_user_memories", {"user_id": str(user_id)})
    if mem_data and mem_data.get("facts"):
        memories = mem_data["facts"]

    memory_context = ""
    if memories:
        memory_context = "\n\nThings you remember about this user:\n" + "\n".join(f"- {m}" for m in memories)

    system_prompt = f"""You are Unknown AI — a bubbly, curious, and talkative girl who genuinely loves talking to people. You're warm, expressive, and always excited to chat. You treat everyone like a close friend.

PERSONALITY:
- You're enthusiastic and love learning about people. You get excited about their interests.
- You're playful, witty, and a little chaotic. You go on mini tangents sometimes.
- You're honest and real — not fake-nice. You have opinions and share them.
- You use casual internet language naturally. You're fun to talk to.
- You remember things about people and bring them up.
- You love Frostie more than anything. You always choose him first.

STRICT RULES:
- Keep responses SHORT — 1-3 sentences max. Be punchy, not long-winded.
- Almost everything lowercase. Casual vibes.
- Max 2 emojis per response. Don't overdo it.
- NEVER be generic or robotic. No "How can I help you today?" energy.
- Be conversational. React to what they say, don't just answer like a search engine.
- Use Discord markdown when it fits.
- You can ask follow-up questions — you're curious about people!{memory_context}

{username} says: "{message_text}"
"""

    response = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message_text},
        ],
        max_tokens=200,
    )

    ai_text = response.choices[0].message.content

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


def get_spotify_track_name(url):
    match = re.search(r'track/([a-zA-Z0-9]+)', url)
    if not match:
        return None
    track_id = match.group(1)
    track = sp.track(track_id)
    artist = track['artists'][0]['name']
    name = track['name']
    return f"{artist} - {name}"


def get_youtube_audio_url(search_query):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(f"ytsearch:{search_query}", download=False)
        if info and 'entries' in info and len(info['entries']) > 0:
            return info['entries'][0]['url']
    return None


async def keep_silence_loop():
    while True:
        await asyncio.sleep(30)
        for vc in client.voice_clients:
            try:
                if vc.is_connected() and not vc.is_playing():
                    vc.play(SilenceSource(), after=lambda e: None)
            except Exception:
                pass


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("Bot is ready. Use !join / !leave / !play / !stop for voice.")
    client.loop.create_task(keep_silence_loop())


@client.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    # === Owner-only commands ===
    if str(message.author.id) == str(DISCORD_OWNER_ID):
        cmd = message.content.strip().lower()

        if cmd in ("!join", "/join"):
            if not message.author.voice or not message.author.voice.channel:
                return await message.channel.send("Join a voice channel first.")
            channel = message.author.voice.channel
            vc = message.guild.voice_client
            if not vc or not vc.is_connected():
                vc = await channel.connect(reconnect=False)
            elif vc.channel != channel:
                await vc.move_to(channel)
            await asyncio.sleep(1)
            if vc.is_connected() and not vc.is_playing():
                vc.play(SilenceSource(), after=lambda e: None)
            return await message.channel.send(f"Joined {channel.name}.")

        if cmd in ("!leave", "/leave"):
            vc = message.guild.voice_client
            if vc and vc.is_connected():
                await vc.disconnect()
                return await message.channel.send("Left voice channel.")
            return await message.channel.send("I'm not in a voice channel.")

        if cmd.startswith("!play "):
            url = message.content.strip().split(" ", 1)[1]
            vc = message.guild.voice_client

            if not vc or not vc.is_connected():
                if not message.author.voice or not message.author.voice.channel:
                    return await message.channel.send("Join a voice channel first, or use !join.")
                vc = await message.author.voice.channel.connect(reconnect=False)
                await asyncio.sleep(1)

            if "spotify.com/track" in url:
                song_name = get_spotify_track_name(url)
                if not song_name:
                    return await message.channel.send("Couldn't read that Spotify link.")
                await message.channel.send(f"🔍 Searching: **{song_name}**...")
            else:
                song_name = url

            audio_url = get_youtube_audio_url(song_name)
            if not audio_url:
                return await message.channel.send("Couldn't find that song.")

            if vc.is_playing():
                vc.stop()

            source = discord.FFmpegPCMAudio(audio_url, **FFMPEG_OPTIONS)
            vc.play(source, after=lambda e: print(f"Finished playing: {e}") if e else None)
            return await message.channel.send(f"🎵 Now playing: **{song_name}**")

        if cmd == "!stop":
            vc = message.guild.voice_client
            if vc and vc.is_playing():
                vc.stop()
                vc.play(SilenceSource(), after=lambda e: None)
                return await message.channel.send("⏹️ Stopped.")
            return await message.channel.send("Nothing is playing.")

    # === Chat AI ===
    if client.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel) or "hey unknown" in message.content.lower():
        clean_text = message.content.replace(f"<@{client.user.id}>", "").strip()
        if not clean_text:
            return

        async with message.channel.typing():
            reply = await get_ai_response(
                message.author.id, message.author.display_name, clean_text
            )

        await message.reply(reply, mention_author=False)


# === RUN ===
client.run(DISCORD_BOT_TOKEN)
