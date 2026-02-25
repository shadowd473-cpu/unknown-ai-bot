@client.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Check if bot is mentioned or "hey unknown" is said
    bot_mentioned = client.user in message.mentions
    hey_unknown = "hey unknown" in message.content.lower()
    
    if not bot_mentioned and not hey_unknown:
        return
    
    owner_id = 1203529902498607174
    is_owner = message.author.id == owner_id
    
    # Call your AI (adjust to match your setup)
    if is_owner:
        # Sweet/flustered personality
        prompt = f"Be shy and sweet to {message.author.name}: {message.content}"
    else:
        # Snarky/cold personality  
        prompt = f"Be snarky and cold to {message.author.name}: {message.content}"
    
    # Replace with your actual AI call
    response = await get_ai_response(prompt)
    await message.reply(response)
