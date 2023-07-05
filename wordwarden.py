import discord
from discord.ext import commands
from discord.ext.commands import has_permissions
import sqlite3
import asyncio
import random

# Define the main variables
intents = discord.Intents.default()
intents.message_content = True  # Enable message content intent
bot = commands.Bot(command_prefix='&', intents=intents)

# Initialize the database
conn = sqlite3.connect('wordwarden.db')
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS bot_settings (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER
            )''')

c.execute('''CREATE TABLE IF NOT EXISTS claimed_words (
                word TEXT PRIMARY KEY,
                owner TEXT,
                for_sale INTEGER,
                price INTEGER
            )''')

c.execute('''CREATE TABLE IF NOT EXISTS user_funds (
                user_id INTEGER PRIMARY KEY,
                tokens INTEGER
            )''')

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} ({bot.user.id})')

def get_assigned_channel(guild_id):
    c.execute('SELECT channel_id FROM bot_settings WHERE guild_id = ?', (str(guild_id),))
    result = c.fetchone()
    return result[0] if result else None

def set_assigned_channel(guild_id, channel_id):
    c.execute('REPLACE INTO bot_settings (guild_id, channel_id) VALUES (?, ?)', (str(guild_id), channel_id))
    conn.commit()

def get_user_funds(user_id):
    c.execute('SELECT tokens FROM user_funds WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    return result[0] if result else None

def set_user_funds(user_id, tokens):
    c.execute('REPLACE INTO user_funds (user_id, tokens) VALUES (?, ?)', (user_id, tokens))
    conn.commit()

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.content.startswith('&info') or message.content.startswith('&channel'):
        await bot.process_commands(message)
        return

    assigned_channel = get_assigned_channel(message.guild.id)
    if assigned_channel and message.channel.id != assigned_channel:
        return

    if not message.content.startswith(bot.command_prefix):
        # Check if the message contains any unclaimed words
        words = message.content.lower().split()
        claimed_words = set()
        for word in words:
            c.execute('SELECT * FROM claimed_words WHERE word=?', (word,))
            existing_word = c.fetchone()
            if not existing_word:
                claimed_words.add(word)
            else:
                owner = existing_word[1]
                for_sale = existing_word[2]
                if owner != message.author.name:
                    # Delete the message
                    await message.delete()

                    # Send notification embed
                    channel = message.channel
                    embed = discord.Embed(
                        title=':x: Word Already Taken',
                        description=f'The word "{word}" is already claimed by {owner}.',
                        color=discord.Color.red()
                    )
                    if for_sale:
                        embed.add_field(name='For Sale', value='This word is up for sale though, just buy it so you can use it ig.', inline=False)
                    else:
                        embed.add_field(name='Not for Sale', value='This word is not up for sale either.. Find an alternative instead', inline=False)
                    notification_message = await channel.send(f'{message.author.mention}', embed=embed)

                    # Add a lock emoji reaction to the notification message
                    try:
                        await notification_message.add_reaction('🔒')
                    except discord.NotFound:
                        pass

        if claimed_words:
            for word in claimed_words:
                c.execute('INSERT INTO claimed_words (word, owner, for_sale, price) VALUES (?, ?, ?, ?)',
                          (word, message.author.name, False, 0))
                conn.commit()

                # Add a lock emoji reaction to the original message
                try:
                    await message.add_reaction('🔒')
                except discord.NotFound:
                    pass

        # Check if the user exists in the user_funds table
        c.execute('SELECT * FROM user_funds WHERE user_id=?', (message.author.id,))
        user_funds = c.fetchone()
        if not user_funds:
            # User doesn't exist, give them 1000 tokens
            c.execute('INSERT INTO user_funds (user_id, tokens) VALUES (?, ?)', (message.author.id, 1000))
            conn.commit()

    await bot.process_commands(message)

@bot.event
async def on_message_edit(before, after):
    if before.content != after.content:
        c.execute('SELECT word, owner, for_sale FROM claimed_words WHERE owner = ?', (before.author.name,))
        claimed_words = c.fetchall()

        for word, owner, for_sale in claimed_words:
            if word.lower() in after.content.lower():
                # Delete the user's message containing the word they don't own
                await after.delete()

                embed = discord.Embed(
                    title=':x: Word Already Taken',
                    description=f'The word "{word}" is already claimed by {owner}.',
                    color=discord.Color.red()
                )
                if for_sale:
                    embed.add_field(name='For Sale', value='This word is up for sale though, just buy it so you can use it ig.', inline=False)
                else:
                    embed.add_field(name='Not for Sale', value='This word is not up for sale either.. Find an alternative instead', inline=False)

                notification_msg = await after.channel.send(f'{after.author.mention}', embed=embed)
                await asyncio.sleep(5)  # Wait for 5 seconds
                await notification_msg.delete()
                break  # Break out of the loop after deleting the message

    await bot.process_commands(after)

@bot.command()
async def sell(ctx, word, price: int):
    c.execute('SELECT * FROM claimed_words WHERE word=?', (word,))
    existing_word = c.fetchone()
    if existing_word and existing_word[1] == ctx.author.name:
        c.execute('UPDATE claimed_words SET for_sale=?, price=? WHERE word=?', (True, price, word))
        conn.commit()

        embed = discord.Embed(
            title=':white_check_mark: Word For Sale!',
            description=f'The word "{word}" is now up for sale.',
            color=discord.Color.green()
        )
        embed.add_field(name='Price', value=f'{price} tokens', inline=False)
    else:
        embed = discord.Embed(
            title=':x: Word Not Owned',
            description=f'The word "{word}" is not owned by you.',
            color=discord.Color.red()
        )
    await ctx.send(embed=embed)

@sell.error
async def sell_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title=':x: Missing Argument',
            description='Please provide the word you want to sell. Example: `&sell [word] [price]`.',
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command()
async def buy(ctx, word):
    c.execute('SELECT * FROM claimed_words WHERE word=?', (word,))
    existing_word = c.fetchone()
    if existing_word:
        owner = existing_word[1]
        for_sale = existing_word[2]
        price = existing_word[3]
        user_id = ctx.author.id

        if owner == ctx.author.name:
            if for_sale:
                # Reclaim the word
                c.execute('UPDATE claimed_words SET for_sale=?, price=? WHERE word=?',
                          (False, 0, word))
                conn.commit()

                embed = discord.Embed(
                    title=':white_check_mark: Word Reclaimed',
                    description=f'"{word}" has been reclaimed by {ctx.author.name}. It is no longer for sale. 🔒',
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title=':x: Word Not for Sale',
                    description=f'{word} is not currently for sale.',
                    color=discord.Color.red()
                )
        else:
            if for_sale and price > 0:
                c.execute('SELECT * FROM user_funds WHERE user_id=?', (user_id,))
                user_funds = c.fetchone()
                if user_funds and user_funds[1] >= price:
                    # Update the word's owner
                    c.execute('UPDATE claimed_words SET owner=?, for_sale=?, price=? WHERE word=?',
                              (ctx.author.name, False, 0, word))
                    # Update the buyer's funds
                    new_funds = user_funds[1] - price
                    c.execute('UPDATE user_funds SET tokens=? WHERE user_id=?', (new_funds, user_id))
                    # Update the seller's funds
                    c.execute('SELECT * FROM user_funds WHERE user_id=?', (owner,))
                    seller_funds = c.fetchone()
                    new_funds = seller_funds[1] + price
                    c.execute('UPDATE user_funds SET tokens=? WHERE user_id=?', (new_funds, owner))
                    conn.commit()
                    mock_messages = [
                        f'{ctx.author.name} be like: {word} is mine now! Muahahaha!',
                        f'Can you believe this user actually paid for the word `{word}`? Imagine buying pixels smh',
                        f'Congratulations on your purchase of permission to speak, who thought that would be possible in the future?!',
                        f'Did you really just buy a word to just use in this one channel? Have fun ig',
                    ]
                    mock_message = random.choice(mock_messages)
                    embed = discord.Embed(
                        title=':white_check_mark: Word Purchased',
                        description=f'{word} has been purchased by {ctx.author.name} from {owner}! 🔒\n{mock_message}',
                        color=discord.Color.green()
                    )
                    await ctx.send(embed=embed)
                    return
                else:
                    embed = discord.Embed(
                        title=':x: Insufficient Funds',
                        description='You have insufficient funds to buy the word.',
                        color=discord.Color.red()
                    )
            else:
                embed = discord.Embed(
                    title=':x: Invalid Word',
                    description=f'{word} is either not a claimed word or you already own it.',
                    color=discord.Color.red()
                )
    else:
        embed = discord.Embed(
            title=':x: Invalid Word',
            description=f'{word} is not a claimed word.',
            color=discord.Color.red()
        )
    await ctx.send(embed=embed)

@buy.error
async def buy_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title=':x: Missing Argument',
            description='Please provide the word you want to buy. Example: `&buy [word]`.',
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command()
async def marketplace(ctx, page: int = 1):
    per_page = 10  # Number of words per page
    c.execute('SELECT COUNT(*) FROM claimed_words WHERE for_sale=1')
    total_words = c.fetchone()[0]
    total_pages = (total_words + per_page - 1) // per_page

    if total_pages < 1:
        embed = discord.Embed(title=':shopping_cart: Word Marketplace', description='Nothing here but crickets...',
                              color=discord.Color.red())
        await ctx.send(embed=embed)
        return

    if page > total_pages:
        await ctx.send(f'Invalid page number. Please enter a value between 1 and {total_pages}.')
        return

    c.execute('SELECT word, owner, price FROM claimed_words WHERE for_sale=1 ORDER BY word LIMIT ?, ?',
              ((page - 1) * per_page, per_page))
    words = c.fetchall() 

    embed = discord.Embed(title=':shopping_cart: Word Marketplace', color=discord.Color.red())

    embed.add_field(name='Word', value='\n'.join(word[0] for word in words), inline=True)
    embed.add_field(name='Owner', value='\n'.join(f'@{word[1]}' for word in words), inline=True)
    embed.add_field(name='Price', value='\n'.join(f'{word[2]} tokens' for word in words), inline=True)


    await ctx.send(embed=embed)

@bot.command()
async def inventory(ctx, page: int = 1):
    per_page = 10  # Number of words per page
    c.execute('SELECT COUNT(*) FROM claimed_words WHERE owner=?', (ctx.author.name,))
    total_words = c.fetchone()[0]
    total_pages = (total_words + per_page - 1) // per_page

    if page > total_pages:
        await ctx.send(f'Invalid page number. Please enter a value between 1 and {total_pages}.')
        return
    
    if total_words == 0:
        embed = discord.Embed(
            title=':closed_book: Word Inventory',
            description='You do not own any words.',
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    c.execute('SELECT word, price, for_sale FROM claimed_words WHERE owner=? LIMIT ?, ?', (ctx.author.name, (page - 1) * per_page, per_page))
    inventory = c.fetchall()

    embed = discord.Embed(title=':closed_book: Word Inventory', color=discord.Color.red())

    words = []
    prices = []
    for word, price, for_sale in inventory:
        words.append(f'`{word}`')
        prices.append(f'{price} tokens' if for_sale else 'Not for sale')

    embed.add_field(name='Word', value='\n'.join(words), inline=True)
    embed.add_field(name='Price', value='\n'.join(prices), inline=True)

    embed.set_footer(text=f'Showing inventory for {ctx.author.name} ({len(words)}/{total_words}) | Page {page}/{total_pages}')
    await ctx.send(embed=embed)

@bot.command()
async def balance(ctx):
    c.execute('SELECT tokens FROM user_funds WHERE user_id=?', (ctx.author.id,))
    result = c.fetchone()
    if result:
        tokens = result[0]
    else:
        tokens = 0
    embed = discord.Embed(
        title=':moneybag: Token Balance',
        description=f'You have {tokens} tokens.',
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.command()
@has_permissions(manage_guild=True)
async def channel(ctx, channel: discord.TextChannel):
    set_assigned_channel(ctx.guild.id, channel.id)
    if channel:
        embed = discord.Embed(
            title=':white_check_mark: Channel Assigned',
            description=f'Channel {channel.mention} has been successfully assigned for Word Warden.',
            color=discord.Color.green()
        )
    await ctx.send(embed=embed)

@channel.error
async def channel_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title=':x: Missing Argument',
            description='Please provide the channel to assign. Example: `&channel [channel]`',
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

@bot.command()
async def info(ctx):
    prefix = bot.command_prefix
    bot_user = bot.user
    # Trading Commands
    trading_commands = [
        '`&buy [word]`: Purchase a word that is for sale',
        '`&sell [word] [price]`: Put a word you own up for sale',
        '`&marketplace (page)`: See what words are up for sale'
    ]
    # User Commands
    user_commands = [
        '`&balance`: Check your token balance',
        '`&inventory (page)`: See the words in your inventory'
    ]
    # Misc Commands
    misc_commands = [
        '`&channel`: Set the channel you want the bot to operate in',
        '`&info`: Show this message'
    ]
    embed = discord.Embed(description=f"Hi! I am a simple Discord bot made by <@603158153638707242>.\nI am the warden of words! Simply say a word and you can own it!\n\nMy current prefix is `{prefix}`", color=discord.Color.red())
    embed.set_author(name=f'Word Warden', icon_url=bot_user.avatar.url)
    embed.add_field(name='Trading Commands', value='\n'.join(trading_commands), inline=False)
    embed.add_field(name='User Commands', value='\n'.join(user_commands), inline=False)
    embed.add_field(name='Misc Commands', value='\n'.join(misc_commands), inline=False)
    embed.set_footer(text=f'Required: [], Optional: ()')
    await ctx.send(embed=embed)

# Run the bot
bot.run('MTExODkyMDY4NDQ5Njc2OTA4NQ.GeJLr0.1EXmgJV4BKxMOELoUGHHsboJvvew2fJQ13XvS4')
