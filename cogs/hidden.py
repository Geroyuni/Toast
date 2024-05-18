from io import BytesIO
import html
import math

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

    async def get_artwork(self, image_link):
        """Return image file in good size, return None if failed."""
        if not image_link:
            return None

        async with aiohttp.ClientSession() as session:
            async with session.get(image_link) as resp:
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

            image = image.crop(crop)

        image = image.resize((150, 150))

        altered_data = BytesIO()
        image.save(altered_data, format="png")
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
        average_track_length = (
            sum([t.length for t in playlist.tracks]) / len(playlist.tracks))

        track_names = []

        for track in playlist.tracks:
            title = f"⬜ {track.title}"

            if track.length <= (average_track_length / 2):
                title += " 🔹"

            track_names.append(title)

        track_names = "\n".join(track_names)
        full_output = f"{playlist_name_formatted}\n\n{track_names}"

        if len(full_output) >= 1992:
            full_output = full_output[:1990] + ".."

        await itx.followup.send(
            f"```{html.unescape(full_output)}```",
            file=await self.get_artwork(playlist.tracks[0].artwork))

    @app_commands.command()
    @app_commands.guilds(898109234091294750)
    async def resize_cover(
        self, itx: Interaction, image_link: str, public: bool = False
    ):
        """Resize an album cover to be 150x150.

        :param image_link: The link to the image
        :param public: Show the result publicly (false by default)
        """
        await itx.response.defer(ephemeral=not public)

        file = await self.get_artwork(image_link)

        if not file:
            await itx.followup.send("is this a valid image? Couldn't resize")
            return

        await itx.followup.send(file=file)

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
        name_to_circle = {
            "red": "🔴", "orange": "🟠", "yellow": "🟡", "blue": "🔵",
            "green": "🟢", "purple": "🟣", "black": "⚫"}
        circles = "🔴", "🟠", "🟡", "🔵", "🟢", "🟣", "⚫"
        content = []
        sort = lambda x: x[0].casefold()

        async def iterate_thread(thread):
            threads[thread.name] = {"albums": 0, "rating": 0}

            async for message in thread.history(limit=None):
                for line in message.content.split("\n"):
                    # Remove header formatting
                    if line.startswith(("# ", "## ", "### ")):
                        line = line.split(" ", 1)[1]

                    if not line or "**" in line:
                        continue

                    is_regular_circle = line[0] in circles
                    is_custom_circle = (
                        line.startswith("<:")
                        and "_circle" in line.split(" ")[0])

                    if is_regular_circle:
                        rating = circles.index(line[0])
                    elif is_custom_circle:
                        color_name = line.split("_")[0][8:]
                        rating = circles.index(name_to_circle[color_name])
                    else:
                        continue

                    threads[thread.name]["rating"] += rating
                    threads[thread.name]["albums"] += 1

        for thread in itx.channel.threads:
            await iterate_thread(thread)

        async for thread in itx.channel.archived_threads(limit=None):
            await iterate_thread(thread)

        for thread_name, totals in sorted(threads.items(), key=sort):
            if not totals["albums"]:
                rating_color = "⚪"
            else:
                rating_sum = totals["rating"] / totals["albums"]
                rating_color = circles[math.ceil(rating_sum)]

            content.append(
                f"{rating_color} `{str(totals['albums']).zfill(2)}` "
                f"{escape_markdown(thread_name)}")

        albums = sum([t["albums"] for t in threads.values()])

        embed = discord.Embed(
            title=f"{itx.user.display_name}'s ratings",
            description="\n".join(content))

        embed.set_footer(
            text=f"\n{albums} albums seen in {len(threads)} threads.")

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
