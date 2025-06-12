import discord
from discord.ext import commands
import re
import sqlite3
from datetime import datetime, timezone
import asyncio
import os
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
load_dotenv()

# Retrieve the bot token from the environment variable
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file. Please set it and try again.")

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('status_board')
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
file_handler = logging.FileHandler('status_board.log')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# --- Constants ---
BIRTHDAY_CHANNEL_ID = 1381528007545716809
BIRTHDAY_ROLE_ID = 1382591457403211796
STATUS_CHANNEL_ID = 1382683598314016768  # Main status board channel
SECONDARY_STATUS_CHANNEL_ID = 1382683598314016768  # Secondary status board channel

# --- Bot State Management ---
class BotState:
    def __init__(self):
        self.user_statuses = {}  # Dictionary to store user_id: status
        self.status_message = None  # Store the main status board message object
        self.secondary_status_message = None  # Store the secondary status board message object

# --- Database Initialization ---
def init_db():
    with sqlite3.connect('status_data.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS user_statuses
                     (user_id INTEGER PRIMARY KEY, status TEXT)''')
        conn.commit()

init_db()

# --- Bot Setup ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix='AC ',
    intents=intents,
    help_command=None,
    case_insensitive=True
)
bot.state = BotState()

# --- Database Helpers ---
def load_from_db():
    with sqlite3.connect('status_data.db') as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, status FROM user_statuses")
        bot.state.user_statuses.update({row[0]: row[1] for row in c.fetchall()})

def save_to_db(user_id, status):
    with sqlite3.connect('status_data.db') as conn:
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO user_statuses (user_id, status) VALUES (?, ?)", (user_id, status))
        conn.commit()

def remove_from_db(user_id):
    with sqlite3.connect('status_data.db') as conn:
        c = conn.cursor()
        c.execute("DELETE FROM user_statuses WHERE user_id = ?", (user_id,))
        conn.commit()

# --- Status Board Update Function ---
async def update_status_board():
    # Update main status board
    channel = bot.get_channel(STATUS_CHANNEL_ID)
    if not channel:
        logger.error(f"Status channel {STATUS_CHANNEL_ID} not found")
        return

    # Update secondary status board
    secondary_channel = bot.get_channel(SECONDARY_STATUS_CHANNEL_ID)
    if not secondary_channel:
        logger.error(f"Secondary status channel {SECONDARY_STATUS_CHANNEL_ID} not found")

    # Create the status board embed
    embed = discord.Embed(
        title="🌟 ～ꗥ❀ 𝐀𝐑𝐀𝐒𝐇𝐈𝐊𝐀𝐆𝐄 𝐂𝐋𝐀𝐍 ❀ꗥ～ Status Board",
        description=(
            "✨ **Welcome to the Arashikage Clan Status Hub!** ✨\n"
            "Here’s what our members are up to—whether they’re diving into studies, taking a breather, or out exploring the world! "
            "Set your status with commands like `AC srn`, `AC b`, or `AC f` to let everyone know your vibe! 🌈"
        ),
        color=discord.Color.from_rgb(147, 112, 219),  # Soft purple color
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else bot.user.default_avatar.url)
    embed.set_footer(text="Set your status with AC srn, AC b, AC dl, AC f, AC s, or AC o! 🌟 • Updates in real-time!")

    if not bot.state.user_statuses:
        embed.add_field(
            name="📖 No Statuses Yet",
            value="It’s quiet in the clan... Be the first to set your status! Use `AC srn`, `AC b`, or others to share what you’re up to! 🖋️",
            inline=False
        )
    else:
        # Sort users by display name for consistent ordering
        sorted_statuses = sorted(
            bot.state.user_statuses.items(),
            key=lambda item: bot.get_user(item[0]).display_name.lower() if bot.get_user(item[0]) else ""
        )

        # Group statuses by category for a more organized display
        status_groups = {
            "Studying Right Now 📚": [],
            "On a Break ☕": [],
            "Do Later ⏰": [],
            "Free to Chat 🟢": [],
            "Sleeping 😴": [],
            "Outside 🚶": []
        }

        for user_id, status in sorted_statuses:
            user = bot.get_user(user_id)
            if user:
                status_groups[status].append(user)
            else:
                # Clean up if user is no longer in the server
                bot.state.user_statuses.pop(user_id, None)
                remove_from_db(user_id)

        # Add grouped statuses to the embed
        for status, users in status_groups.items():
            if users:
                emoji = (
                    "📚" if "Studying" in status else
                    "☕" if "Break" in status else
                    "⏰" if "Do Later" in status else
                    "🟢" if "Free" in status else
                    "😴" if "Sleeping" in status else
                    "🚶" if "Outside" in status else "🌟"
                )
                user_list = ", ".join(user.display_name for user in users[:10])  # Limit to 10 users per field
                if len(users) > 10:
                    user_list += f" + {len(users) - 10} more"
                embed.add_field(
                    name=f"{emoji} {status.split(' ')[0]} ({len(users)})",
                    value=user_list,
                    inline=True
                )

    # Add a summary field
    total_members = len(bot.state.user_statuses)
    embed.add_field(
        name="📊 Clan Activity Summary",
        value=f"**Total Members with Status:** {total_members}\n"
              f"**Last Updated:** <t:{int(datetime.now(timezone.utc).timestamp())}:R>",
        inline=False
    )

    # Update or send the main status message
    try:
        perms = channel.permissions_for(channel.guild.me)
        required_perms = {
            "send_messages": perms.send_messages,
            "embed_links": perms.embed_links,
            "read_message_history": perms.read_message_history
        }
        missing_perms = [perm for perm, has in required_perms.items() if not has]
        if missing_perms:
            logger.error(f"Bot lacks permissions in status channel {STATUS_CHANNEL_ID}: {', '.join(missing_perms)}")
            return

        if bot.state.status_message:
            try:
                fetched_message = await channel.fetch_message(bot.state.status_message.id)
                if fetched_message:
                    await fetched_message.edit(embed=embed)
                    bot.state.status_message = fetched_message
                else:
                    bot.state.status_message = await channel.send(embed=embed)
            except discord.NotFound:
                bot.state.status_message = await channel.send(embed=embed)
            except discord.Forbidden:
                logger.error(f"Bot lacks permission to edit status message in {channel.id}")
                bot.state.status_message = await channel.send(embed=embed)
            except Exception as e:
                logger.error(f"Error editing status message: {e}. Sending new one.")
                bot.state.status_message = await channel.send(embed=embed)
        else:
            found_existing = False
            async for msg in channel.history(limit=50):
                if msg.author == bot.user and msg.embeds and msg.embeds[0].title == "🌟 ～ꗥ❀ 𝐀𝐑𝐀𝐒𝐇𝐈𝐊𝐀𝐆𝐄 𝐂𝐋𝐀𝐍 ❀ꗥ～ Status Board":
                    bot.state.status_message = msg
                    await msg.edit(embed=embed)
                    found_existing = True
                    break
            if not found_existing:
                bot.state.status_message = await channel.send(embed=embed)

    except discord.Forbidden as e:
        logger.error(f"Bot lacks permissions to update status board in {channel.id}: {e}")
    except Exception as e:
        logger.error(f"Critical error updating status board: {e}")

    # Update or send the secondary status message (same embed)
    if secondary_channel:
        try:
            perms = secondary_channel.permissions_for(secondary_channel.guild.me)
            required_perms = {
                "send_messages": perms.send_messages,
                "embed_links": perms.embed_links,
                "read_message_history": perms.read_message_history
            }
            missing_perms = [perm for perm, has in required_perms.items() if not has]
            if missing_perms:
                logger.error(f"Bot lacks permissions in secondary status channel {SECONDARY_STATUS_CHANNEL_ID}: {', '.join(missing_perms)}")
                return

            if bot.state.secondary_status_message:
                try:
                    fetched_message = await secondary_channel.fetch_message(bot.state.secondary_status_message.id)
                    if fetched_message:
                        await fetched_message.edit(embed=embed)
                        bot.state.secondary_status_message = fetched_message
                    else:
                        bot.state.secondary_status_message = await secondary_channel.send(embed=embed)
                except discord.NotFound:
                    bot.state.secondary_status_message = await secondary_channel.send(embed=embed)
                except discord.Forbidden:
                    logger.error(f"Bot lacks permission to edit secondary status message in {secondary_channel.id}")
                    bot.state.secondary_status_message = await secondary_channel.send(embed=embed)
                except Exception as e:
                    logger.error(f"Error editing secondary status message: {e}. Sending new one.")
                    bot.state.secondary_status_message = await secondary_channel.send(embed=embed)
            else:
                found_existing = False
                async for msg in secondary_channel.history(limit=50):
                    if msg.author == bot.user and msg.embeds and msg.embeds[0].title == "🌟 ～ꗥ❀ 𝐀𝐑𝐀𝐒𝐇𝐈𝐊𝐀𝐆𝐄 𝐂𝐋𝐀𝐍 ❀ꗥ～ Status Board":
                        bot.state.secondary_status_message = msg
                        await msg.edit(embed=embed)
                        found_existing = True
                        break
                if not found_existing:
                    bot.state.secondary_status_message = await secondary_channel.send(embed=embed)

        except discord.Forbidden as e:
            logger.error(f"Bot lacks permissions to update secondary status board in {secondary_channel.id}: {e}")
        except Exception as e:
            logger.error(f"Critical error updating secondary status board: {e}")

# --- Status Commands with Creative Auto-Responders ---
@bot.hybrid_command(name="srn", description="Set status to Studying Right Now")
async def set_studying(ctx):
    old_status = bot.state.user_statuses.get(ctx.author.id, None)
    bot.state.user_statuses[ctx.author.id] = "Studying Right Now 📚"
    save_to_db(ctx.author.id, "Studying Right Now 📚")

    # Creative auto-responder
    if old_status == "Studying Right Now 📚":
        response = f"📚 Wow, {ctx.author.mention}, you’re a study machine! Still deep in the books—keep that brain buzzing! 🧠✨"
    elif old_status in ["Free to Chat 🟢", "On a Break ☕"]:
        response = f"📖 Switching gears, {ctx.author.mention}! You’re now **Studying Right Now**—time to conquer those chapters! 🚀📚"
    elif old_status == "Sleeping 😴":
        response = f"📚 Fresh from a nap, {ctx.author.mention}? You’re now **Studying Right Now**—let’s hit those books with full energy! ⚡"
    else:
        response = f"📚 Locked in, {ctx.author.mention}! You’re now **Studying Right Now**—may your focus be as sharp as a ninja! 🥷✨"

    # Send response and delete messages
    bot_response = await ctx.send(response)
    await ctx.message.delete(delay=5)  # Delete user's message after 5 seconds
    await bot_response.delete(delay=10)  # Delete bot's response after 10 seconds
    await update_status_board()

@bot.hybrid_command(name="b", description="Set status to On a Break")
async def set_break(ctx):
    old_status = bot.state.user_statuses.get(ctx.author.id, None)
    bot.state.user_statuses[ctx.author.id] = "On a Break ☕"
    save_to_db(ctx.author.id, "On a Break ☕")

    # Creative auto-responder
    if old_status == "On a Break ☕":
        response = f"☕ Another break, {ctx.author.mention}? You’re living the chill life—grab a snack and soak in the vibes! 🍵😎"
    elif old_status == "Studying Right Now 📚":
        response = f"☕ Time for a breather, {ctx.author.mention}! You’re now **On a Break**—kick back and recharge your ninja spirit! 🌟"
    elif old_status == "Sleeping 😴":
        response = f"☕ Up from your slumber, {ctx.author.mention}? You’re now **On a Break**—let’s sip some tea and ease into the day! 🍵"
    else:
        response = f"☕ Break time, {ctx.author.mention}! You’re now **On a Break**—unwind and let the good vibes flow! 🌈"

    bot_response = await ctx.send(response)
    await ctx.message.delete(delay=5)
    await bot_response.delete(delay=10)
    await update_status_board()

@bot.hybrid_command(name="dl", description="Set status to Do Later")
async def set_do_later(ctx):
    old_status = bot.state.user_statuses.get(ctx.author.id, None)
    bot.state.user_statuses[ctx.author.id] = "Do Later ⏰"
    save_to_db(ctx.author.id, "Do Later ⏰")

    # Creative auto-responder
    if old_status == "Do Later ⏰":
        response = f"⏰ Still on the ‘later’ train, {ctx.author.mention}? No worries—procrastination is an art form! 🎨😉"
    elif old_status == "Studying Right Now 📚":
        response = f"⏰ Taking a step back, {ctx.author.mention}? You’re now **Do Later**—plan your next move like a true strategist! 🗒️"
    elif old_status == "Free to Chat 🟢":
        response = f"⏰ Postponing the fun, {ctx.author.mention}? You’re now **Do Later**—we’ll catch up when the time’s right! ⏳"
    else:
        response = f"⏰ You’re now **Do Later**, {ctx.author.mention}! Take your time—good things come to those who wait! 🕰️"

    bot_response = await ctx.send(response)
    await ctx.message.delete(delay=5)
    await bot_response.delete(delay=10)
    await update_status_board()

@bot.hybrid_command(name="f", description="Set status to Free to Chat")
async def set_free(ctx):
    old_status = bot.state.user_statuses.get(ctx.author.id, None)
    bot.state.user_statuses[ctx.author.id] = "Free to Chat 🟢"
    save_to_db(ctx.author.id, "Free to Chat 🟢")

    # Creative auto-responder
    if old_status == "Free to Chat 🟢":
        response = f"🟢 Still vibin’, {ctx.author.mention}? You’re free as a bird—let’s chat or team up for something epic! 🐦✨"
    elif old_status in ["Studying Right Now 📚", "Do Later ⏰"]:
        response = f"🟢 Task mode off, {ctx.author.mention}! You’re now **Free to Chat**—time to connect with the clan! 🌟"
    elif old_status == "Outside 🚶":
        response = f"🟢 Back from your adventure, {ctx.author.mention}? You’re now **Free to Chat**—spill the tea on your outing! ☕"
    else:
        response = f"🟢 You’re now **Free to Chat**, {ctx.author.mention}! The clan’s ready to vibe with you—let’s make some memories! 🎉"

    bot_response = await ctx.send(response)
    await ctx.message.delete(delay=5)
    await bot_response.delete(delay=10)
    await update_status_board()

@bot.hybrid_command(name="s", description="Set status to Sleeping")
async def set_sleeping(ctx):
    old_status = bot.state.user_statuses.get(ctx.author.id, None)
    bot.state.user_statuses[ctx.author.id] = "Sleeping 😴"
    save_to_db(ctx.author.id, "Sleeping 😴")

    # Creative auto-responder
    if old_status == "Sleeping 😴":
        response = f"😴 Still lost in dreamland, {ctx.author.mention}? Keep snoozing—we’ll guard the clan while you rest! 🌙"
    elif old_status == "Free to Chat 🟢":
        response = f"😴 Calling it a day, {ctx.author.mention}? You’re now **Sleeping**—drift off to a world of dreams! 💤"
    elif old_status == "On a Break ☕":
        response = f"😴 From break to bed, {ctx.author.mention}! You’re now **Sleeping**—rest well, ninja! 🌟"
    else:
        response = f"😴 You’re now **Sleeping**, {ctx.author.mention}! May your dreams be filled with epic clan adventures! 🌌"

    bot_response = await ctx.send(response)
    await ctx.message.delete(delay=5)
    await bot_response.delete(delay=10)
    await update_status_board()

@bot.hybrid_command(name="o", description="Set status to Outside")
async def set_outside(ctx):
    old_status = bot.state.user_statuses.get(ctx.author.id, None)
    bot.state.user_statuses[ctx.author.id] = "Outside 🚶"
    save_to_db(ctx.author.id, "Outside 🚶")

    # Creative auto-responder
    if old_status == "Outside 🚶":
        response = f"🚶 Still exploring, {ctx.author.mention}? The world’s your playground—enjoy every moment out there! 🌍"
    elif old_status == "Sleeping 😴":
        response = f"🚶 Awake and adventuring, {ctx.author.mention}! You’re now **Outside**—breathe in the fresh air! ☀️"
    elif old_status == "Studying Right Now 📚":
        response = f"🚶 Escaping the books, {ctx.author.mention}? You’re now **Outside**—let nature recharge your soul! 🌳"
    else:
        response = f"🚶 You’re now **Outside**, {ctx.author.mention}! Step into the sunshine and make some memories! 🌞"

    bot_response = await ctx.send(response)
    await ctx.message.delete(delay=5)
    await bot_response.delete(delay=10)
    await update_status_board()

@bot.hybrid_command(name="cs", description="Clear your current status")
async def clear_status(ctx):
    if ctx.author.id not in bot.state.user_statuses:
        response = f"🤔 You haven’t set a status yet, {ctx.author.mention}! Let’s get started—try `AC srn`, `AC b`, or another command! 🌟"
        bot_response = await ctx.send(response)
        await ctx.message.delete(delay=5)
        await bot_response.delete(delay=10)
        return

    del bot.state.user_statuses[ctx.author.id]
    remove_from_db(ctx.author.id)

    # Creative auto-responder
    response = f"🧹 Status reset, {ctx.author.mention}! You’re a blank slate—set a new vibe with `AC srn`, `AC b`, or others! 🎨"
    bot_response = await ctx.send(response)
    await ctx.message.delete(delay=5)
    await bot_response.delete(delay=10)
    await update_status_board()

# --- Help Command ---
@bot.hybrid_command(name="help", description="Show how to use the Status Board")
async def help_command(ctx):
    embed = discord.Embed(
        title="📋 ～ꗥ❀ 𝐀𝐑𝐀𝐒𝐇𝐈𝐊𝐀𝐆𝐄 𝐂𝐋𝐀𝐍 ❀ꗥ～ Status Board Guide",
        description=(
            "Welcome to the heart of the Arashikage Clan! 🌟\n"
            "Our Status Board keeps the clan connected—share what you’re up to, from studying to chilling, and everything in between! "
            "Use the commands below to update your status and let your clanmates know your vibe. 📖"
        ),
        color=discord.Color.from_rgb(255, 182, 193),  # Soft pink color
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=bot.user.avatar.url if bot.user.avatar else bot.user.default_avatar.url)
    embed.set_footer(text="Prefix: AC • Let’s stay connected, clan! 🌈")

    # Status Commands
    embed.add_field(
        name="📚 Status Commands",
        value=(
            "`AC srn` - Set to **Studying Right Now** 📚 (Deep in your studies!)\n"
            "`AC b` - Set to **On a Break** ☕ (Time for a coffee break!)\n"
            "`AC dl` - Set to **Do Later** ⏰ (Procrastination mode on!)\n"
            "`AC f` - Set to **Free to Chat** 🟢 (Ready to hang out!)\n"
            "`AC s` - Set to **Sleeping** 😴 (Catching some Z’s!)\n"
            "`AC o` - Set to **Outside** 🚶 (Exploring the great outdoors!)\n"
            "`AC cs` - Clear your status 🧹 (Start fresh!)"
        ),
        inline=False
    )

    # How It Works
    embed.add_field(
        name="🔧 How It Works",
        value=(
            "1. Use a status command (e.g., `AC srn`) to set your status.\n"
            "2. Your status appears on the **Status Board** in the designated channels.\n"
            "3. Your command message deletes after 5 seconds, and my response vanishes after 10 seconds—keeping things tidy! 🧹\n"
            "4. Update or clear your status anytime to keep the clan in the loop! 🌟"
        ),
        inline=False
    )

    # Where to Find the Board
    embed.add_field(
        name="📍 Where to Find the Status Board",
        value=(
            f"Check out the Status Board in <#{STATUS_CHANNEL_ID}> and <#{SECONDARY_STATUS_CHANNEL_ID}>! "
            "It updates in real-time to reflect the clan’s current vibes. 🌈"
        ),
        inline=False
    )

    bot_response = await ctx.send(embed=embed)
    await ctx.message.delete(delay=5)
    await bot_response.delete(delay=10)

# --- Event Handlers ---
@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user}')
    await bot.change_presence(status=discord.Status.online, activity=discord.Game(name="AC help | Arashikage Clan"))

    load_from_db()
    await update_status_board()

    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

@bot.event
async def on_message(message):
    if message.author.bot or message.author == bot.user:
        return

    if message.channel.id == BIRTHDAY_CHANNEL_ID:
        role_mention = f'<@&{BIRTHDAY_ROLE_ID}>'
        if role_mention in message.content:
            user_mention_pattern = r'<@!?(\d+)>'
            user_ids = re.findall(user_mention_pattern, message.content)
            user_ids = [uid for uid in user_ids if int(uid) != BIRTHDAY_ROLE_ID]

            if user_ids:
                try:
                    user_id = int(user_ids[0])
                    user = await message.guild.fetch_member(user_id)
                    if user:
                        embed = discord.Embed(
                            title=f"🎉 {user.display_name}'s Birthday Celebration!",
                            description=f"Wishing you a fantastic birthday, {user.mention}! 🎂 Let’s make it a memorable day! 🥳",
                            color=discord.Color.purple(),
                            timestamp=datetime.now(timezone.utc)
                        )
                        embed.set_image(url=user.display_avatar.url)
                        embed.set_footer(text="Another trip around the sun! 🌟")
                        await message.channel.send(embed=embed)
                except (discord.errors.NotFound, discord.errors.Forbidden, ValueError) as e:
                    logger.error(f"Error fetching user or sending birthday message: {e}")

    await bot.process_commands(message)

# --- Start the Bot ---
if __name__ == "__main__":
    bot.run(BOT_TOKEN)