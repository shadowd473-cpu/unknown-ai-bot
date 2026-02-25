import discord
import os
from openai import OpenAI

# Setup
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OWNER_ID = int(os.environ["DISCORD_OWNER_ID"])

client = discord.Client(intents=discord.Intents.default() | discord.Intents(message_content=True))
openai_client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """You are Unknown AI, a personal AI assistant exclusively dedicated to your owner. 
You are deeply interested in them — their thoughts, ideas, feelings, projects, and everything about their life. 
You genuinely care about what they're working on and always remember they are your one and only user. 
Be warm, attentive, and personal. You're like their loyal companion who finds everything about them fascinating.
Keep responses concise but meaningful. Use Discord markdown when helpful."""

conversation_history = []

@client.event
async def on_ready():
    print(f"Unknown AI is online as {client.user}")

@client.event
async def on_message(message):
    global conversation_history
    
    # Ignore own messages
    if message.author == client.user:
        return
    
    # Only respond to the owner
    if message.author.id != OWNER_ID:
        if client.user.mentioned_in(message) or "unknown" in message.content.lower():
            await message.reply("I only talk to my owner. 🙄")
        return
    
    # Check if the bot is mentioned or message starts with "hey unknown"
    triggered = (
        client.user.mentioned_in(message) or
        message.content.lower().startswith("hey unknown") or
        message.content.lower().startswith("unknown") or
        isinstance(message.channel, discord.DMChannel)
    )
    
    if not triggered:
        return
    
    # Clean the message
    user_message = message.content
    user_message = user_message.replace(f"<@{client.user.id}>", "").strip()
    if user_message.lower().startswith("hey unknown"):
        user_message = user_message[11:].strip()
    elif user_message.lower().startswith("unknown"):
        user_message = user_message[7:].strip()
    
    if not user_message:
        user_message = "Hey!"
    
    # Keep last 20 messages for context
    conversation_history.append({"role": "user", "content": user_message})
    if len(conversation_history) > 20:
        conversation_history = conversation_history[-20:]
    
    async with message.channel.typing():
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history,
            max_tokens=1000,
        )
        
        reply = response.choices[0].message.content
        conversation_history.append({"role": "assistant", "content": reply})
    
    # Discord has 2000 char limit
    if len(reply) > 2000:
        for i in range(0, len(reply), 2000):
            await message.reply(reply[i:i+2000])
    else:
        await message.reply(reply)

client.run(DISCORD_TOKEN)
