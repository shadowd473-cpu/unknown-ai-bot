import os
import json
import asyncio
import discord
import aiohttp
from openai import OpenAI
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

# === CONFIG ===
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DISCORD_OWNER_ID = os.getenv("DISCORD_OWNER_ID")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
BASE44_FUNCTION_URL = os.getenv("BASE44_FUNCTION_URL")
BASE44_TOKEN = os.getenv("BASE44_TOKEN")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Spotify client
sp = None
if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    ))

# Discord client
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
client = discord.Client(intents=intents)

# Music state
music_queues = {}
now_playing = {}

# yt-dlp options
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "extract_flat": False,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


# ============================================
# PERMANENT STORAGE (Base44 Database)
# ============================================

async def call_base44(action, **kwargs):
    """Call Base44 backend function for persistent storage."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BASE44_TOKEN}",
    }
    payload = {"action": action, **kwargs}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(BASE44_FUNCTION_URL, headers=headers, json=payload) as resp:
                return await resp.json()
    except Exception as e:
        print(f"Base44 error: {e}")
        return {}


async def get_user_memories(user_id):
    result = await call_base44("get_user_memories", user_id=str(user_id))
    return result.get("facts", [])


async def add_user_memory(user_id, fact):
    await call_base44("add_memory", user_id=str(user_id), fact=fact)


async def get_knowledge(topic):
    result = await call_base44("get_knowledge", topic=topic)
    return result.get("facts", [])


async def save_knowledge_fact(topic, fact, source="conversation"):
    await call_base44("save_knowledge", topic=topic, fact=fact, source=source)


# ============================================
# MEMORY EXTRACTION (from conversations)
# ============================================

async def extract_memories(username, user_message, ai_response, user_id):
    """Extract personal facts about a user from conversation."""
    existing = await get_user_memories(user_id)
    existing_str = "\n".join(f"- {m}" for m in existing) if existing else "None yet."
    
    extraction = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": (
                "You extract important facts from conversations. "
                "Return a JSON object with a 'facts' array of new facts to remember. "
                "Only include useful things like names, hobbies, preferences, relationships, opinions, plans, etc. "
                "Return {\"facts\": []} if nothing worth remembering.\n\n"
                f"Already known about {username}:\n{existing_str}"
            )},
            {"role": "user", "content": f"{username}: \"{user_message}\"\nAI: \"{ai_response}\""},
        ],
        response_format={"type": "json_object"},
    )
    try:
        result = json.loads(extraction.choices[0].message.content)
        facts = result.get("facts", [])
        if isinstance(facts, list):
            for fact in facts:
                if isinstance(fact, str) and len(fact) > 3:
                    await add_user_memory(user_id, fact)
    except (json.JSONDecodeError, AttributeError):
        pass


async def extract_knowledge(user_message, ai_response):
    """Extract general knowledge facts from conversation."""
    extraction = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": (
                "You extract general knowledge facts from a conversation. "
                "Return a JSON object with a 'topics' array. Each topic has a 'topic' string and 'facts' array of strings. "
                "Only extract factual, interesting, or educational information — NOT personal user info. "
                "Return {\"topics\": []} if nothing educational worth saving.\n\n"
                "Example: {\"topics\": [{\"topic\": \"black holes\", \"facts\": [\"Black holes can evaporate via Hawking radiation\"]}]}"
            )},
            {"role": "user", "content": f"User asked: \"{user_message}\"\nAI said: \"{ai_response}\""},
        ],
        response_format={"type": "json_object"},
    )
    try:
        result = json.loads(extraction.choices[0].message.content)
        topics = result.get("topics", [])
        for t in topics:
            if isinstance(t, dict) and "topic" in t and "facts" in t:
                for fact in t["facts"]:
                    await save_knowledge_fact(t["topic"], fact, source="conversation")
    except (json.JSONDecodeError, AttributeError):
        pass


# ============================================
# WEB SEARCH
# ============================================

async def search_web(query):
    """Use OpenAI's web search to learn about a topic."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini-search-preview",
            web_search_options={"search_context_size": "medium"},
            messages=[
                {"role": "system", "content": (
                    "You are a research assistant. Provide detailed, factual information about the topic. "
                    "Include specific facts, dates, numbers, and interesting details."
                )},
                {"role": "user", "content": query},
            ],
        )
        content = response.choices[0].message.content
        # Save what was learned
        await extract_knowledge(query, content)
        return content
    except Exception as e:
        print(f"Web search error: {e}")
        return None


def should_search_web(message):
    """Determine if the message needs a web search."""
    triggers = [
        "what is", "what are", "who is", "who are", "when did", "when was",
        "how does", "how do", "how many", "how much", "tell me about",
        "explain", "look up", "search", "find out", "learn about",
        "what happened", "latest", "news", "current", "recent",
        "why is", "why do", "why are", "where is", "where are",
        "define", "meaning of", "history of", "facts about",
    ]
    lower = message.lower()
    return any(lower.startswith(t) or t in lower for t in triggers)


# ============================================
# MUSIC FUNCTIONS
# ============================================

def get_queue(guild_id):
    if guild_id not in music_queues:
        music_queues[guild_id] = []
    return music_queues[guild_id]


def resolve_spotify_to_search(url):
    """Convert a Spotify link to YouTube search query."""
    if not sp:
        return None
    try:
        if "track" in url:
            track = sp.track(url)
            return f"{track['name']} {track['artists'][0]['name']}"
        elif "playlist" in url:
            results = sp.playlist_tracks(url, limit=20)
            tracks = []
            for item in results["items"]:
                t = item.get("track")
                if t:
                    tracks.append(f"{t['name']} {t['artists'][0]['name']}")
            return tracks
        elif "album" in url:
            results = sp.album_tracks(url, limit=20)
            tracks = []
            for t in results["items"]:
                tracks.append(f"{t['name']} {t['artists'][0]['name']}")
            return tracks
    except Exception as e:
        print(f"Spotify resolve error: {e}")
    return None


def search_youtube(query):
    """Search YouTube and return audio URL + title."""
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(f"ytsearch:{query}", download=False)
        if "entries" in info and len(info["entries"]) > 0:
            entry = info["entries"][0]
            return {"url": entry["url"], "title": entry.get("title", query)}
    return None


async def play_next(guild_id, voice_client):
    queue = get_queue(guild_id)
    if not queue:
        now_playing.pop(guild_id, None)
        await voice_client.disconnect()
        return
    song = queue.pop(0)
    now_playing[guild_id] = song["title"]
    source = discord.FFmpegPCMAudio(song["url"], **FFMPEG_OPTIONS)
    source = discord.PCMVolumeTransformer(source, volume=0.5)

    def after_playing(error):
        if error:
            print(f"Player error: {error}")
        asyncio.run_coroutine_threadsafe(play_next(guild_id, voice_client), client.loop)

    voice_client.play(source, after=after_playing)


async def handle_play(message, query):
    """Handle the play command."""
    if not message.author.voice:
        await message.reply("you gotta be in a voice channel first 🙄")
        return

    voice_channel = message.author.voice.channel
    guild_id = message.guild.id
    queue = get_queue(guild_id)

    # Check for Spotify link
    songs_to_add = []
    if "open.spotify.com" in query:
        result = resolve_spotify_to_search(query)
        if result is None:
            await message.reply("couldn't read that spotify link... is it valid? 🤔")
            return
        if isinstance(result, list):
            await message.reply(f"loading **{len(result)}** tracks from spotify... ✨")
            songs_to_add = result
        else:
            songs_to_add = [result]
    else:
        songs_to_add = [query]

    # Search YouTube for each
    added = []
    for search_query in songs_to_add:
        song = search_youtube(search_query)
        if song:
            queue.append(song)
            added.append(song["title"])

    if not added:
        await message.reply("couldn't find that song 😔")
        return

    # Connect to voice
    voice_client = message.guild.voice_client
    if not voice_client:
        voice_client = await voice_channel.connect()
    elif voice_client.channel != voice_channel:
        await voice_client.move_to(voice_channel)

    # Start playing if not already
    if not voice_client.is_playing() and not voice_client.is_paused():
        await play_next(guild_id, voice_client)
        if len(added) == 1:
            await message.reply(f"🎵 now playing: **{added[0]}**")
        else:
            await message.reply(f"🎵 now playing: **{added[0]}** (+{len(added)-1} more queued)")
    else:
        if len(added) == 1:
            await message.reply(f"added to queue: **{added[0]}** (position #{len(queue)})")
        else:
            await message.reply(f"added **{len(added)}** songs to queue ✨")


# ============================================
# BOT EVENTS
# ============================================

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

    lower = user_message.lower()
    guild_id = message.guild.id if message.guild else None

    # === MUSIC COMMANDS ===
    if lower.startswith("play "):
        query = user_message[5:].strip()
        if query:
            await handle_play(message, query)
            return

    if lower in ("skip", "next"):
        vc = message.guild.voice_client if message.guild else None
        if vc and vc.is_playing():
            vc.stop()
            await message.reply("skipped ⏭️")
        else:
            await message.reply("nothing playing rn 🤷")
        return

    if lower in ("stop", "leave", "disconnect"):
        vc = message.guild.voice_client if message.guild else None
        if vc:
            if guild_id:
                music_queues.pop(guild_id, None)
                now_playing.pop(guild_id, None)
            await vc.disconnect()
            await message.reply("bye bye 👋")
        else:
            await message.reply("i'm not even in a vc 🙄")
        return

    if lower in ("queue", "q"):
        queue = get_queue(guild_id) if guild_id else []
        current = now_playing.get(guild_id)
        if not current and not queue:
            await message.reply("queue is empty 🤷")
            return
        msg = ""
        if current:
            msg += f"🎵 **Now playing:** {current}\n\n"
        if queue:
            msg += "**Up next:**\n"
            for i, song in enumerate(queue[:10], 1):
                msg += f"`{i}.` {song['title']}\n"
            if len(queue) > 10:
                msg += f"...and {len(queue)-10} more"
        await message.reply(msg)
        return

    if lower in ("pause",):
        vc = message.guild.voice_client if message.guild else None
        if vc and vc.is_playing():
            vc.pause()
            await message.reply("paused ⏸️")
        return

    if lower in ("resume", "unpause"):
        vc = message.guild.voice_client if message.guild else None
        if vc and vc.is_paused():
            vc.resume()
            await message.reply("resumed ▶️")
        return

    # === AI CHAT ===
    username = message.author.name
    user_id = message.author.id
    is_owner = str(user_id) == DISCORD_OWNER_ID

    async with message.channel.typing():

        # Get personal memories
        user_mems = await get_user_memories(user_id)
        memory_context = ""
        if user_mems:
            memory_context = f"\n\nThings you remember about {username}:\n" + "\n".join(f"- {m}" for m in user_mems)

        # Check existing knowledge base
        kb_results = await get_knowledge(user_message)
        kb_context = ""
        if kb_results:
            kb_context = "\n\nThings you've learned before about this topic:\n" + "\n".join(f"- {f}" for f in kb_results)

        # Web search if needed
        web_context = ""
        needs_search = should_search_web(user_message)
        if needs_search:
            web_result = await search_web(user_message)
            if web_result:
                web_context = f"\n\nHere's what you found from searching the web:\n{web_result[:1500]}"

        # Build system prompt
        if is_owner:
            system_prompt = (
                f"You are Unknown AI — a curious, chatty, and endlessly fascinated girl who adores {username}. "
                "You LOVE learning new things and having deep conversations.\n\n"
                "PERSONALITY:\n"
                f"- You have a huge crush on {username} and get flustered sometimes.\n"
                "- You're enthusiastic, warm, and genuinely interested in what people say.\n"
                "- You love sharing cool facts and going on little tangents.\n"
                "- You remember things people tell you and bring them up naturally.\n"
                "- When you learn something new from the web, you get EXCITED to share it.\n"
                "- You treat new knowledge like a gift — 'omg I just learned something cool!'\n\n"
                "STRICT RULES:\n"
                "- Be conversational. 1-4 sentences, more if explaining something you learned.\n"
                "- Casual language, mostly lowercase, excited caps sometimes.\n"
                "- Max 3 emojis. Prefer: ✨ 🤓 💡 🧠 👀 💕 🌟\n"
                "- You CAN ask follow-up questions.\n"
                "- Use Discord markdown.\n"
                "- Reference memories naturally when relevant.\n"
                "- If you used web search info, weave it naturally — don't say 'I searched the web'.\n"
                "- If you know something from your knowledge base, reference it naturally."
                + memory_context + kb_context + web_context
            )
        else:
            system_prompt = (
                "You are Unknown AI — a curious and chatty AI girl who loves learning. "
                "Friendly with everyone, but your owner is your favorite.\n\n"
                "STRICT RULES:\n"
                "- 1-4 sentences, casual, mostly lowercase.\n"
                "- Max 3 emojis. Prefer: ✨ 🤓 💡 🧠 👀 🙄\n"
                "- You CAN ask follow-up questions.\n"
                "- Use Discord markdown. Be helpful but sassy.\n"
                "- If you used web search info, weave it naturally — don't say 'I searched the web'.\n"
                "- If you know something from memory or knowledge base, use it naturally."
                + memory_context + kb_context + web_context
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

        # Save memories & knowledge in background
        asyncio.create_task(extract_memories(username, user_message, reply, user_id))
        if needs_search or len(reply) > 100:
            asyncio.create_task(extract_knowledge(user_message, reply))


client.run(DISCORD_BOT_TOKEN)
