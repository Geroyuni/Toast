from contextlib import suppress
import traceback
import time

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

    async def send_error_message(self, itx: Interaction, content):
        """Send error message in the right way (using followup if needed)."""
        if itx.response.is_done():
            await itx.followup.send(content)
        else:
            await itx.response.send_message(ephemeral=True, content=content)

    @commands.Cog.listener()
    async def on_ready(self):
        self.print(f"Logged in as {self.bot.user}!", color="BLUE")

    @commands.Cog.listener()
    async def on_interaction(self, itx: Interaction):
        if itx.type != discord.InteractionType.application_command:
            return

        location = f"{itx.guild.name}/#{itx.channel}" if itx.guild else "DM"
        self.print(f"{itx.user.name} ({location}):", itx.command.name)

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

            await self.send_error_message(itx,
                f"I need `{perms}` permissions to run this command properly")

            return

        if isinstance(e, app_commands.MissingPermissions):
            perms = "`, `".join(e.missing_permissions)

            await self.send_error_message(itx,
                f"you need `{perms}` permissions to run this command")

            return

        if isinstance(e, app_commands.CheckFailure):
            with suppress(discord.InteractionResponded):
                await self.send_error_message(itx,
                    "you're not allowed to use this")
            return

        if isinstance(e, discord.Forbidden):
            await self.send_error_message(itx, e)
            return

        await self.send_error_message(itx,
            f"some unexpected error happened: `{e}`")

        await self.bot.owner.send(
            f"{itx.user}: {itx.command.name} [{logged}]\n"
            f"```py\n{''.join(traceback.format_exception(e))}```")

        raise e


async def setup(bot):
    await bot.add_cog(Logging(bot))
