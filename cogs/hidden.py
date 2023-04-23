import html

from discord import app_commands, Interaction
from discord.utils import escape_markdown
from discord.ext import commands
import wavelink
import discord


class CommandsHidden(commands.Cog):
    """These commands are for specific guilds."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command()
    @app_commands.guilds(898109234091294750)
    async def template(
        self, itx: Interaction, playlist_link: str, public: bool = False
    ):
        """Output a template for rating songs, based on a playlist.

        :param playlist_link: The link to the playlist
        :param public: Show the result publicly (false by default)
        """
        node = wavelink.NodePool.get_node()

        try:
            playlist = await node.get_playlist(
                wavelink.YouTubePlaylist, playlist_link)
        except wavelink.WavelinkException:
            await itx.response.send_message(ephemeral=True, content=
                "this isn't a playlist link or I can't access it")
            return

        if not playlist:
            await itx.response.send_message(ephemeral=True, content=
                "this isn't a playlist link or I can't access it")
            return

        playlist_name = f"⚪ {playlist.name.removeprefix('Album - ')}"
        track_names = "\n".join([f"⬜ {t.title}" for t in playlist.tracks])
        full_output = f"{playlist_name}\n\n{track_names}"

        if len(full_output) >= 1992:
            full_output = full_output[:1990] + ".."

        await itx.response.send_message(
            f"```{html.unescape(full_output)}```", ephemeral=not public)

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

        content = ["\😔\🔵\🟢\🟣\⚫"]
        sort = lambda x: x[0].casefold()

        async def iterate_thread(thread):
            threads[thread.name] = total.copy()

            async for message in thread.history(limit=None):
                for line in message.content.split("\n"):
                    # Remove header formatting
                    if line.startswith(("# ", "## ", "### ")):
                        line = line.split(" ", 1)[1]

                    should_add_rating = (
                        line
                        and line[0] in "🔴🟠🟡⚪🔵🟢🟣⚫"
                        and "**" not in line)

                    if should_add_rating:
                        threads[thread.name][line[0]] += 1

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
