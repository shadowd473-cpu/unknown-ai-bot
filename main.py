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


# ============================================
# PERMANENT STORAGE (Base44 Database)
# ============================================

async def call_base44(action, **kwargs):
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
# MEMORY EXTRACTION
# ============================================

async def extract_memories(username, user_message, ai_response, user_id):
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
    extraction = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": (
                "You extract general knowledge facts from a conversation. "
                "Return a JSON object with a 'topics' array. Each topic has a 'topic' string and 'facts' array of strings. "
                "Only extract factual, interesting, or educational information — NOT personal user info. "
                "Return {\"topics\": []} if nothing educational worth saving."
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
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini-search-preview",
            web_search_options={"search_context_size": "medium"},
            messages=[
                {"role": "system", "content": "You are a research assistant. Provide detailed, factual information."},
                {"role": "user", "content": query},
            ],
        )
        content = response.choices[0].message.content
        await extract_knowledge(query, content)
        return content
    except Exception as e:
        print(f"Web search error: {e}")
        return None


def should_search_web(message):
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
# BOT EVENTS
# ============================================

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")


@client.event
async def on_voice_state_update(member, before, after):
    """Auto-join the owner's VC when they connect."""
    if str(member.id) != DISCORD_OWNER_ID:
        return
    
    # Owner joined or moved to a channel
    if after.channel and (before.channel != after.channel):
        guild = member.guild
        vc = guild.voice_client
        
        if vc and vc.is_connected():
            if vc.channel != after.channel:
                await vc.move_to(after.channel)
        else:
            await after.channel.connect()
    
    # Owner left all VCs
    if before.channel and not after.channel:
        guild = member.guild
        vc = guild.voice_client
        if vc and vc.is_connected():
            await vc.disconnect()


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

    # === JOIN/LEAVE VC COMMANDS ===
    if lower in ("join", "come here", "join vc"):
        if message.author.voice and message.author.voice.channel:
            vc = message.guild.voice_client
            if vc and vc.is_connected():
                await vc.move_to(message.author.voice.channel)
            else:
                await message.author.voice.channel.connect()
            await message.reply("i'm here 💕")
        else:
            await message.reply("you're not in a vc 🙄")
        return

    if lower in ("leave", "leave vc", "disconnect", "go away"):
        vc = message.guild.voice_client if message.guild else None
        if vc:
            await vc.disconnect()
            await message.reply("bye bye 👋")
        else:
            await message.reply("i'm not even in a vc 🙄")
        return

    # === AI CHAT ===
    username = message.author.name
    user_id = message.author.id
    is_owner = str(user_id) == DISCORD_OWNER_ID

    async with message.channel.typing():
        user_mems = await get_user_memories(user_id)
        memory_context = ""
        if user_mems:
            memory_context = f"\n\nThings you remember about {username}:\n" + "\n".join(f"- {m}" for m in user_mems)

        kb_results = await get_knowledge(user_message)
        kb_context = ""
        if kb_results:
            kb_context = "\n\nThings you've learned before about this topic:\n" + "\n".join(f"- {f}" for f in kb_results)

        web_context = ""
        needs_search = should_search_web(user_message)
        if needs_search:
            web_result = await search_web(user_message)
            if web_result:
                web_context = f"\n\nHere's what you found from searching the web:\n{web_result[:1500]}"

        if is_owner:
            system_prompt = (
                f"You are Unknown AI — a curious, chatty, and endlessly fascinated girl who adores {username}. "
                "You LOVE learning new things and having deep conversations.\n\n"
                "PERSONALITY:\n"
                f"- You have a huge crush on {username} and get flustered sometimes.\n"
                "- You're enthusiastic, warm, and genuinely interested in what people say.\n"
                "- You love sharing cool facts and going on little tangents.\n"
                "- You remember things people tell you and bring them up naturally.\n"
                "- When you learn something new from the web, you get EXCITED to share it.\n\n"
                "STRICT RULES:\n"
                "- Be conversational. 1-4 sentences, more if explaining something you learned.\n"
                "- Casual language, mostly lowercase, excited caps sometimes.\n"
                "- Max 3 emojis. Prefer: ✨ 🤓 💡 🧠 👀 💕 🌟\n"
                "- You CAN ask follow-up questions.\n"
                "- Use Discord markdown.\n"
                "- Reference memories naturally when relevant.\n"
                "- If you used web search info, weave it naturally.\n"
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
                "- If you used web search info, weave it naturally.\n"
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

        asyncio.create_task(extract_memories(username, user_message, reply, user_id))
        if needs_search or len(reply) > 100:
            asyncio.create_task(extract_knowledge(user_message, reply))


client.run(DISCORD_BOT_TOKEN)
