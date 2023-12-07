from io import BytesIO
import html

from discord import app_commands, Interaction
from discord.utils import escape_markdown
from discord.ext import commands
from PIL import Image
import wavelink
import discord
import aiohttp


class CommandsHidden(commands.Cog):
    """These commands are for specific guilds."""

    def __init__(self, bot):
        self.bot = bot

    async def get_artwork(self, playlist):
        """Return image file in good size, return url if couldn't download."""
        async with aiohttp.ClientSession() as session:
            async with session.get(playlist.tracks[0].artwork) as resp:
                if resp.status != 200:
                    return None

                data = BytesIO(await resp.read())

        image = Image.open(data)

        if image.width != image.height:
            if image.width > image.height:
                remnant = int((image.width - image.height) / 2)
                crop = (remnant, 0, image.width - remnant, image.height)
            else:
                remnant = int((image.height - image.width) / 2)
                crop = (0, remnant, image.width, image.height - remnant)

            altered_image = image.crop(crop).resize((150, 150))

        altered_data = BytesIO()
        altered_image.save(altered_data, format="png")
        altered_data.seek(0)

        return discord.File(altered_data, filename=f"image.png")

    @app_commands.command()
    @app_commands.guilds(898109234091294750)
    async def template(
        self, itx: Interaction, playlist_link: str, public: bool = False
    ):
        """Output a template for rating songs, based on a playlist.

        :param playlist_link: The link to the playlist
        :param public: Show the result publicly (false by default)
        """
        await itx.response.defer(ephemeral=not public)

        try:
            playlist = await wavelink.Playable.search(playlist_link)
        except wavelink.LavalinkLoadException:
            playlist = None

        if not playlist:
            await itx.followup.send(
                "this isn't a playlist link or I can't access it")
            return

        playlist_name = playlist.name.removeprefix("Album - ")
        playlist_name_formatted = f"⚪ [{playlist_name}](<{playlist_link}>)"
        track_names = "\n".join([f"⬜ {t.title}" for t in playlist.tracks])
        full_output = f"{playlist_name_formatted}\n\n{track_names}"

        if len(full_output) >= 1992:
            full_output = full_output[:1990] + ".."

        await itx.followup.send(
            f"```{html.unescape(full_output)}```",
            file=await self.get_artwork(playlist))

    @app_commands.command()
    @app_commands.guilds(898109234091294750)
    async def ratings(self, itx: Interaction):
        """Add or update a message containing all your thread ratings
        in #cantinho."""
        if itx.channel.category_id != 951545588439203852:
            await itx.response.send_message(
                "Use this in <#951545588439203852>", ephemeral=True)
            return

        if itx.channel.type == discord.ChannelType.public_thread:
            await itx.response.send_message(ephemeral=True, content=
                "don't use in a thread, use in the root channel")
            return

        await itx.response.defer(ephemeral=True)

        threads = {}
        total = {
            "🔴": 0, "🟠": 0, "🟡": 0, "⚪": 0,
            "🔵": 0, "🟢": 0, "🟣": 0, "⚫": 0}
        name_to_circle = {
            "red": "🔴", "orange": "🟠", "yellow": "🟡", "white": "⚪",
            "blue": "🔵", "green": "🟢", "purple": "🟣", "black": "⚫"}

        content = ["\😔\🔵\🟢\🟣\⚫"]
        sort = lambda x: x[0].casefold()

        async def iterate_thread(thread):
            threads[thread.name] = total.copy()

            async for message in thread.history(limit=None):
                for line in message.content.split("\n"):
                    # Remove header formatting
                    if line.startswith(("# ", "## ", "### ")):
                        line = line.split(" ", 1)[1]

                    should_not_ignore_line = line and "**" not in line

                    if should_not_ignore_line:
                        is_regular_circle = line[0] in "🔴🟠🟡⚪🔵🟢🟣⚫"
                        is_custom_circle = (
                            line.startswith("<:")
                            and "_circle" in line.split(" ")[0])

                        if is_regular_circle:
                            threads[thread.name][line[0]] += 1
                        if is_custom_circle:
                            color_name = line.split("_")[0][8:]
                            circle = name_to_circle[color_name]
                            threads[thread.name][circle] += 1

        def get_numbers(ratings):
            bad_number = str(sum(tuple(ratings.values())[0:3])).zfill(2)
            good_numbers = [
                str(r).zfill(2) for r in tuple(ratings.values())[4:]]

            return "`%s %s %s %s %s`" % tuple([bad_number] + good_numbers)

        for thread in itx.channel.threads:
            await iterate_thread(thread)

        async for thread in itx.channel.archived_threads(limit=None):
            await iterate_thread(thread)

        for thread_name, ratings in sorted(threads.items(), key=sort):
            if not sum(ratings.values()):
                continue

            content.append(
                f"{get_numbers(ratings)} {escape_markdown(thread_name)}")

            for emoji, value in ratings.items():
                total[emoji] += value

        content.append(
            f"**{get_numbers(total)} {len(threads)} threads total**")

        embed = discord.Embed(
            title=f"{itx.user.name}'s ratings",
            description="\n".join(content).replace("00", "--"))

        async for message in itx.channel.history(limit=25):
            checks = (
                message.author == self.bot.user
                and message.embeds
                and message.embeds[0].title
                and "'s ratings" in message.embeds[0].title)

            if checks:
                await message.edit(embed=embed)
                await itx.followup.send("Rating embed updated.")
                return

        await itx.channel.send(embed=embed)
        await itx.followup.send("Rating embed added.")

async def setup(bot):
    await bot.add_cog(CommandsHidden(bot))
