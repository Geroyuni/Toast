from difflib import get_close_matches
from contextlib import suppress
from typing import Union
from io import BytesIO
import random

from PIL import Image, ImageColor

from discord.utils import escape_markdown, format_dt
from discord import app_commands, Interaction
from discord.ext import commands
import discord


class CommandsGeneral(commands.Cog):
    """General commands that can be used by any guild or user."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command()
    @app_commands.allowed_installs(guilds=True, users=True)
    async def images(
        self,
        itx: Interaction,
        user: Union[discord.Member, discord.User, None],
        guild: str = None,
        private: bool = False
    ):
        """Get images from a user or server.

        :param user: Get images from a specific user
        :param guild: Get images from a specific guild
        :param private: Show result only to you (false by default)
        """
        await itx.response.defer(ephemeral=private)
        files = []

        if not user and not guild:
            user = itx.user

        if user:
            user_object_with_banner = await self.bot.fetch_user(user.id)

            if user.avatar:
                files.append(await user.avatar.to_file())
            if isinstance(user, discord.Member) and user.guild_avatar:
                files.append(await user.guild_avatar.to_file())
            if user_object_with_banner.banner:
                files.append(await user_object_with_banner.banner.to_file())
            # TODO: add guild_banner on discord.py 2.5
        elif guild:
            guild = self.bot.get_guild(int(guild))

            if not guild:
                await itx.followup.send("the guild you typed wasn't found")
                return

            if guild.icon:
                files.append(await guild.icon.to_file())
            if guild.banner:
                files.append(await guild.banner.to_file())
            if guild.splash:
                files.append(await guild.splash.to_file())

        if not files:
            await itx.followup.send("no images found")
            return

        await itx.followup.send(files=files, ephemeral=private)

    @images.autocomplete("guild")
    async def info_guild_autocomplete(self, itx: Interaction, current: str):
        guilds = []

        for guild in self.bot.guilds:
            can_see_guild = (
                itx.user == self.bot.owner or guild.get_member(itx.user.id))

            if can_see_guild and current.lower() in guild.name.lower():
                guilds.append(
                    app_commands.Choice(name=guild.name, value=str(guild.id)))

        guilds.sort(key=lambda i: i.name.lower())
        return guilds

    @app_commands.command(name="random")
    @app_commands.allowed_installs(guilds=True, users=True)
    async def random_(self, itx: Interaction, things: str):
        """Picks a random option or number.

        :param things: Numbers or words, split by space or comma
        """
        things = [
            i.strip() for i in things.split("," if "," in things else " ")]

        if len(things) <= 2:
            with suppress(ValueError):
                nums = [int(i) for i in things]

                if len(nums) == 1:
                    nums.append(0)

                if nums[0] > nums[1]:  # avoids some ValueError on randint
                    nums.reverse()

                fmt = nums[0], nums[1], random.randint(nums[0], nums[1])
                await itx.response.send_message("%s to %s: `%s`" % fmt)
                return

        if len(things) == 1:
            things = things[0]

        fmt = len(things), random.choice(things)
        await itx.response.send_message("from %s choices: `%s`" % fmt)

    @random_.autocomplete("things")
    async def random_autocomplete(self, itx: Interaction, current: str):
        names = ["10", "1 100", "yes no", "Big tower, small house", "abcde"]

        return [
            app_commands.Choice(name=name, value=name)
            for name in names if current.lower() in name.lower()]


async def setup(bot):
    await bot.add_cog(CommandsGeneral(bot))
