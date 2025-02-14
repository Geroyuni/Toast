from io import BytesIO
import html

from discord import app_commands, Interaction
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

        return discord.File(altered_data, filename="image.png")

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


async def setup(bot):
    await bot.add_cog(CommandsHidden(bot))
