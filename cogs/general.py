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

    async def search(self, search_type, query):
        """Return user or guild with ID or close enough name."""
        names = {}

        if search_type == "user":
            with suppress(discord.NotFound, ValueError):
                return await self.bot.fetch_user(int(query))

            for m in self.bot.get_all_members():
                names[str(m)] = names[m.display_name] = names[m.name] = m

        elif search_type == "guild":
            if query.isdecimal() and (guild := self.bot.get_guild(int(query))):
                return guild

            for g in self.bot.guilds:
                names[str(g)] = g

        match = get_close_matches(query, names.keys(), n=1)
        return names.get(match[0]) if match else None

    @app_commands.command()
    @app_commands.allowed_installs(guilds=True, users=True)
    async def info(
        self,
        itx: Interaction,
        user: Union[discord.Member, discord.User, None],
        guild: str = None,
        private: bool = False
    ):
        """Shows information about a user or server I'm in. If nothing is
        entered, it shows about yourself.

        :param user: Get information from a specific user
        :param guild: Get information from a specific guild
        :param private: Show result only to you (false by default)
        """
        if guild:
            guild = await self.search("guild", guild)

            if not guild:
                await itx.response.send_message(
                    "the guild you typed wasn't found", ephemeral=True)
                return

            created = format_dt(guild.created_at, style="R")

            embed = discord.Embed(title=f"**{escape_markdown(guild.name)}**")
            embed.add_field(name="Created", value=created)
            embed.add_field(name="Members", value=guild.member_count)
            embed.add_field(name="Owner", value=guild.owner.mention)
            embed.set_thumbnail(url=guild.icon.url)

            await itx.response.send_message(embed=embed, ephemeral=private)
            return

        if not user:
            user = itx.user

        is_bot = self.bot.toast_emoji("bot_account") if user.bot else ''
        created = format_dt(user.created_at, style="R")

        embed = discord.Embed(title=f"{escape_markdown(str(user))}  {is_bot}")
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Created Account", value=created)
        embed.set_footer(text="Server dates change if user left")

        if itx.channel.type == discord.ChannelType.private:
            if itx.user in (self.bot.owner, user):
                members = [g.get_member(user.id) for g in self.bot.guilds]
                joined = []
                for member in filter(None, members):
                    joined.append(
                        f"{format_dt(member.joined_at, style='R')} "
                        f"{escape_markdown(member.guild.name)}")

                embed.add_field(
                    name="Joined Server",
                    value="\n".join(joined) or "Not in any")

        elif isinstance(user, discord.Member):
            embed.color = user.color.value or None
            embed.add_field(
                name="Joined Server",
                value=format_dt(user.joined_at, style="R"))
        else:
            embed.add_field(name="Joined Server", value="Isn't a member")

        await itx.response.send_message(embed=embed, ephemeral=private)

    @info.autocomplete("guild")
    async def info_guild_autocomplete(self, itx: Interaction, current: str):
        guilds = []

        for guild in self.bot.guilds:
            can_see_guild = (
                itx.user == self.bot.owner or guild.get_member(itx.user.id))

            if can_see_guild and current.lower() in guild.name.lower():
                guilds.append(app_commands.Choice(
                    name=guild.name, value=guild.name))

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

    @app_commands.command()
    @app_commands.allowed_installs(guilds=True, users=True)
    async def hex(self, itx: Interaction, value: str, private: bool = False):
        """Shows a hex color visually.

        :param value: A hex value like #ff9030. Type 'random' for a random one
        :param private: Show result only to you (false by default)
        """
        if value == "random":
            value = hex(random.randint(0, 0xffffff))

        try:
            stripped_value = value.strip("#").removeprefix("0x")[:6]
            int_value = max(0, min(0xffffff, int(stripped_value, 16)))
        except ValueError:
            await itx.response.send_message(ephemeral=True, content=
                "this isn't a valid hex value")
            return

        hex_color = f"#{hex(int_value)[2:].zfill(6)}"
        rgb_color = ImageColor.getcolor(hex_color, "RGB")

        embed = discord.Embed(title=hex_color)
        embed.description = f"RGB {', '.join([str(c) for c in rgb_color])}"

        data = BytesIO()
        image = Image.new("RGB", (50,50), rgb_color)
        image.save(data, format="png")
        data.seek(0)

        file = discord.File(data, filename=f"{hex_color[1:]}.png")
        embed.set_thumbnail(url=f"attachment://{hex_color[1:]}.png")

        await itx.response.send_message(
            embed=embed, file=file, ephemeral=private)


async def setup(bot):
    await bot.add_cog(CommandsGeneral(bot))
