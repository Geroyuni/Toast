from contextlib import suppress
from datetime import datetime
import traceback
import difflib
import time
import re

from discord.utils import format_dt, escape_markdown
from discord.app_commands import AppCommandError
from discord import app_commands, Interaction
from colorama import Style, Fore
from discord.ext import commands
import colorama
import discord

colorama.init()



class Logging(commands.Cog):
    """Log guild actions for /log, print bot events, announce errors."""

    def __init__(self, bot):
        self.bot = bot
        self.bot.print = self.print
        self.bot.tree.on_error = self.on_app_command_error

    def log(self, guild_id: int, event: str):
        """Add the given action to a list for guilds to see with /log."""
        if not self.bot.db["logs"].get(guild_id):
            self.bot.db["logs"][guild_id] = []

        self.bot.db["logs"][guild_id].append(event)
        del self.bot.db["logs"][guild_id][:-30]

    @staticmethod
    def print(primary, secondary="", *, color="GRAY"):
        """Format things to print into console, with color and time."""
        colors = {
            "DEFAULT":  Style.RESET_ALL,
            "WHITE":    Style.BRIGHT + Fore.WHITE,
            "GRAY":     Style.BRIGHT + Fore.BLACK,
            "RED":      Style.BRIGHT + Fore.RED,
            "YELLOW":   Style.BRIGHT + Fore.YELLOW,
            "BLUE":     Style.BRIGHT + Fore.BLUE}

        primary = str(primary)
        secondary = str(secondary)
        current_time = colors[color] + time.strftime("[%H:%M] ")

        if secondary:
            too_long = len(primary + secondary) + 8 > 130
            nl = "\n" if (too_long or "\n" in secondary) else " "

            text = (
                colors["WHITE"] + primary + nl +
                colors["DEFAULT"] + secondary)
        else:
            text = colors["DEFAULT"] + primary

        print(current_time + text)

    @property
    def current_time(self):
        """Give time formatted for use in Discord."""
        return format_dt(datetime.now(), style="R")

    @commands.Cog.listener()
    async def on_ready(self):
        self.print(f"Logged in as {self.bot.user}!", color="BLUE")

    @commands.Cog.listener()
    async def on_interaction(self, itx: Interaction):
        if itx.type != discord.InteractionType.application_command:
            return

        location = f"{itx.guild.name}/#{itx.channel}" if itx.guild else "DM"
        self.print(f"{itx.user.name} ({location}):", itx.command.name)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        self.log(member.guild.id,
            f"{member.mention} joined this server {self.current_time}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        self.log(member.guild.id,
            f"{member.mention} left this server {self.current_time}")

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.clean_content == after.clean_content or \
           after.author.bot or not after.guild:
            return

        cbefore = self.bot.cut(escape_markdown(before.clean_content), 2000)
        cafter = self.bot.cut(escape_markdown(after.clean_content), 2000)

        # Separate into words and special characters to compare that
        # e.g. "test123" "," " " "lol" "!"
        separate_before = re.findall(r"[^\w\d]|[\w\d]*", cbefore)
        separate_after = re.findall(r"[^\w\d]|[\w\d]*", cafter)

        previous_sign = " "
        comparison = []
        formatting = {"+": "**`", "-": "~~`", " ": ""}

        # Differ starts with symbols representing add/remove
        # Make text bold for adds, strikethrough for removes, else normal
        for item in difflib.Differ().compare(separate_before, separate_after):
            sign, content = item[0], item[2:]

            if sign == "?":
                continue
            if sign != previous_sign:
                comparison.append(formatting[previous_sign][::-1])
                comparison.append(formatting[sign])

            comparison.append(content)
            previous_sign = sign

        comparison.append(formatting[previous_sign])

        self.log(after.guild.id,
            f"{after.author.mention} edited in {after.channel.mention} "
            f"{self.current_time}:\n{''.join(comparison)}")

    @commands.Cog.listener("on_message_delete")
    @commands.Cog.listener("on_bulk_message_delete")
    async def handle_delete(self, messages):
        if isinstance(messages, list):
            self.log(messages[0].guild.id,
                f"Bulk message deletion {self.current_time}; "
                f"{len(messages)} deleted")
        else:
            messages = [messages]

        for message in messages:
            if message.author.bot or not message.guild:
                continue

            content = []

            if message.content:
                content.append(message.clean_content)

            if message.attachments:
                content.append(
                    f"[Attachment]({message.attachments[0].proxy_url})")

            if message.embeds and not (message.content or message.attachments):
                content.append("[embed]")

            content = "\n".join(content)

            self.log(message.guild.id,
                f"{message.author.mention} deleted in "
                f"{message.channel.mention} {self.current_time}:\n{content}")

    @commands.Cog.listener()
    async def on_command_error(self, ctx, e):
        """Error handling for non-slash commands."""
        if hasattr(e, "original"):
            e = e.original

        if isinstance(e, (commands.CommandNotFound, commands.CheckFailure)):
            return

        if isinstance(e, (commands.UserInputError, discord.Forbidden)):
            await ctx.isend(e)
            return

        await ctx.bot.owner.send(
            f"{ctx.message.content}\n"
            f"```py\n{''.join(traceback.format_exception(e))}```")

        raise e

    async def on_app_command_error(self, itx: Interaction, e: AppCommandError):
        """Error handling for slash commands."""
        if hasattr(e, "original"):
            logged = f"{type(e).__name__}: {type(e.original).__name__}"
            e = e.original
        else:
            logged = type(e).__name__

        self.print(f"{itx.user}: {itx.command.name} [{logged}]", color="RED")

        if isinstance(e, app_commands.BotMissingPermissions):
            perms = "`, `".join(e.missing_permissions)

            await itx.response.send_message(ephemeral=True, content=
                f"I need `{perms}` permissions to run this command properly")

            return

        if isinstance(e, app_commands.MissingPermissions):
            perms = "`, `".join(e.missing_permissions)

            await itx.response.send_message(ephemeral=True, content=
                f"you need `{perms}` permissions to run this command")

            return

        if isinstance(e, app_commands.CheckFailure):
            with suppress(discord.InteractionResponded):
                await itx.response.send_message(ephemeral=True, content=
                    "you're not allowed to use this")
            return

        if isinstance(e, discord.Forbidden):
            await itx.response.send_message(e, ephemeral=True)
            return

        await itx.response.send_message(ephemeral=True, content=
            f"some unexpected error happened: `{e}`")

        await self.bot.owner.send(
            f"{itx.user}: {itx.command.name} [{logged}]\n"
            f"```py\n{''.join(traceback.format_exception(e))}```")

        raise e


async def setup(bot):
    await bot.add_cog(Logging(bot))
