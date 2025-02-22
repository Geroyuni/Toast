from contextlib import suppress
import traceback
import logging

from discord.app_commands import AppCommandError
from discord import app_commands, Interaction
from discord.ext import commands
import discord


class Logging(commands.Cog):
    """Log bot events, announce errors."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.tree.on_error = self.on_app_command_error

    async def send_error_message(self, itx: Interaction, content):
        """Send error message in the right way (using followup if needed)."""
        if itx.response.is_done():
            await itx.followup.send(content)
        else:
            await itx.response.send_message(content, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        logging.info(f"Logged in as {self.bot.user}!")

    @commands.Cog.listener()
    async def on_interaction(self, itx: Interaction):
        if itx.type != discord.InteractionType.application_command:
            return

        location = f"{itx.guild.name}/#{itx.channel}" if itx.guild else "DM"
        logging.info(f"{itx.user} ({location}): {itx.command.name}")

    async def on_app_command_error(self, itx: Interaction, e: AppCommandError):
        """Error handling for slash commands."""
        if hasattr(e, "original"):
            logged = f"{type(e).__name__}: {type(e.original).__name__}"
            e = e.original
        else:
            logged = type(e).__name__

        location = f"{itx.guild.name}/#{itx.channel}" if itx.guild else "DM"

        logging.error(
            f"{itx.user} ({location}): {itx.command.name} [{logged}]")

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
                await itx.response.send_message(
                    "you're not allowed to use this", ephemeral=True)
            return

        if isinstance(e, discord.Forbidden):
            await self.send_error_message(itx, e)
            return

        await self.send_error_message(itx,
            f"some unexpected error happened: `{e}`")

        await self.bot.owner.send(
            f"{itx.user} ({location}): {itx.command.name} [{logged}]\n"
            f"```py\n{''.join(traceback.format_exception(e))}```")

        raise e


async def setup(bot):
    await bot.add_cog(Logging(bot))
