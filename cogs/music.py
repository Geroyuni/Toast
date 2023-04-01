from contextlib import suppress
import datetime
import asyncio
from typing import Literal

from discord import app_commands, Interaction
from discord.ext import commands
import wavelink
import discord


def fmt_time(seconds):
    """Format raw seconds into string of hours/minutes/seconds (e.g. 12:34)."""
    time = divmod(int(seconds), 60)

    if time[0] >= 60:
        time = divmod(time[0], 60) + time[1:]

    return ":".join([str(t).zfill(2) for t in time])


def cut(string, length):
    """Cut a string based on the horizontal size of its characters.

    Made to prevent song names from breaking into a new line on desktop.
    For Discord's Whitney Book font. Imperfect solution.
    """
    newstr = ""
    curlen = 0
    length *= 5  # input length is the amount of 'size 5' characters
    size = {1: "Iijl!,.':| ", 2: 'Jfrt1¨*([])-"', 5: "MW%",
            3: "BCEFKLPRSTZabcdeghknopqsuvxyz234567890$_+=?/",
            4: "ADGHNOQUVXYmw@#&"}  # horizontal size of characters (aprox.)

    for letter in str(string):
        for number in size:
            if letter not in size[number]:
                continue

            if curlen + number + 5 > length:
                return newstr + ".."

            newstr += letter
            curlen += number
            break
        else:
            if curlen + 12 > length:
                return newstr + ".."

            newstr += letter
            curlen += 7

    return newstr


class Track(wavelink.GenericTrack):
    """Wavelink Track object with additional attributes."""

    def __init__(self, track, requester=None):
        super().__init__(track.data)

        self.queue_sign = "."
        self.message = ""
        self.requester = requester

        if "youtube" in self.uri or "youtu.be" in self.uri:
            self.thumb = (
                f"https://i.ytimg.com/vi/{self.identifier}/hqdefault.jpg")
        else:
            self.thumb = "https://files.catbox.moe/bqyvm5.png"

        if self.is_stream:
            self.length_fmt = "Live"
        else:
            self.length_fmt = fmt_time(self.length / 60)

    def formatted_name(self, length: int):
        """Return cut name with link and tooltip."""
        message = f", {self.message}" if self.message else ""

        tooltip = (
            f"{self.requester}: "
            f"[{self.length_fmt}{message}] {self.author}: {self.title}")

        # Checking hyphen assuming that it could be the 'Author - Name' format
        if self.author.lower() in self.title.lower() or " - " in self.title:
            name = self.title
        else:
            name = f"{self.author} - {self.title}"

        # Avoid markdown issues and remove stupid youtube 'topic' in names
        name = name.replace(" - Topic - ", " - ")
        name = name.replace("[", "(").replace("]", ")")
        name = discord.utils.escape_markdown(name)
        tooltip = tooltip.replace("'", "ʹ")

        return f"[{cut(name, length)}]({self.uri} '{tooltip}')"


class Player(wavelink.Player):
    """Custom wavelink Player class."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.bot = self.client

        self.votes = {"skip": set(), "pause": set(), "leave": set()}
        self.current_track = None  # .track is cleaned when I don't want it to
        self.queue_msg = None
        self.tracks = []
        self.tracks_played = []
        self.awaiting_track = False
        self.vote_warning = False
        self.errored_this_session = False
        self.pending_searches = []
        self.total_played = 0
        self.updated_queue_at = datetime.datetime.now()
        self.started_session = datetime.datetime.now()
        self.queue_task = self.bot.loop.create_task(self.auto_queue_update())

    def update_vote(self, user, vote_type):
        if user not in self.votes[vote_type]:
            self.votes[vote_type].add(user)
        else:
            self.votes[vote_type].discard(user)

        for user in self.votes[vote_type]:
            if user not in self.channel.members:
                self.votes[vote_type].discard(user)

    def format_vote(self, vote_type):
        votes = len(self.votes[vote_type])
        required = round(len(self.channel.members) / 2)

        return f" ({votes}/{required})" if votes else ""

    def has_won_vote(self, vote_type):
        votes = len(self.votes[vote_type])
        required = round(len(self.channel.members) / 2)

        return votes >= required

    @property
    def queue_embed(self):
        """Return queue embed."""
        position = self.position

        if self.is_paused():
            npsymbol = "||"
        elif self.is_playing():
            npsymbol = ">>"
        else:
            npsymbol = f"{self.current_track.queue_sign}."

            if self.current_track.queue_sign == ".":
                position = self.current_track.length / 60

        tracks = ""

        for track in self.tracks_played:
            tracks += f"`{track.queue_sign}.` {track.formatted_name(27)}\n"

        tracks += f"`{npsymbol}` {self.current_track.formatted_name(27)}\n"

        for i, track in enumerate(self.tracks):
            fmt = f"`{i + 1}.` {track.formatted_name(27)}\n"

            if i + 1 >= 6 or len(tracks + fmt) >= 2970:
                amount = len(self.tracks) - i
                tracks += f"`++` and {amount} more songs"
                break

            tracks += fmt

        if self.current_track.is_stream:
            time = "Live 🔴"
        else:
            time = f"{fmt_time(position)} / {self.current_track.length_fmt}"

        avatar = self.current_track.requester.display_avatar.url

        embed = discord.Embed(description=tracks, color=0x2b2d31)
        embed.set_thumbnail(url=self.current_track.thumb)
        embed.set_footer(text=time, icon_url=avatar)
        return embed

    async def update_queue(self, *, new_message=False, reset_votes=False):
        """Handle creating and updating queue."""
        if not self.current_track:
            return

        if not await self.bot.cooldown_check(self.channel.id, 2):
            return

        if new_message:
            for vote in self.votes.values():
                vote.clear()

            with suppress(discord.NotFound, AttributeError):
                message = [m async for m in self.channel.history(limit=1)][0]

                if self.queue_msg.id == message.id:
                    await self.queue_msg.edit(
                        embed=self.queue_embed, view=QueueButtons(self))

                    self.updated_queue_at = datetime.datetime.now()
                    return

                await self.queue_msg.delete()

            self.queue_msg = await self.channel.send(
                embed=self.queue_embed, view=QueueButtons(self))

            self.updated_queue_at = datetime.datetime.now()
            return

        with suppress(discord.NotFound, AttributeError):
            if reset_votes:
                for vote in self.votes.values():
                    vote.clear()

            await self.queue_msg.edit(
                embed=self.queue_embed, view=QueueButtons(self))

            self.updated_queue_at = datetime.datetime.now()

    async def do_next(self):
        """Proceed into next song."""
        if self.is_playing():
            return

        self.awaiting_track = True

        if not self.tracks:
            await self.update_queue(reset_votes=True)
            time = datetime.datetime.now()
            delta = datetime.timedelta(seconds=15)

            while not self.tracks:
                await asyncio.sleep(0.2)

                if self.pending_searches:
                    time = datetime.datetime.now()
                    continue

                if datetime.datetime.now() - time > delta:
                    await self.send_disconnect_log("due to inactivity.")
                    await self.disconnect()
                    return

        if self.current_track:
            self.tracks_played.append(self.current_track)
            del self.tracks_played[:-2]

        self.current_track = self.tracks.pop(0)
        await self.play(self.current_track)

        self.awaiting_track = False  # must put as soon as play is ran
        self.total_played += 1
        await self.update_queue(new_message=True)

    async def auto_queue_update(self):
        """Update queue every so often to update time."""
        while True:
            await asyncio.sleep(10)
            delta = datetime.timedelta(seconds=29)

            if datetime.datetime.now() - self.updated_queue_at < delta:
                continue

            if self.is_playing() and not (
                self.is_paused() or self.current_track.is_stream):
                await self.update_queue()

    async def send_disconnect_log(self, reason):
        """Log that Toast left, and leave cool stats."""
        if hasattr(self, "already_sent_log"):
            return

        self.already_sent_log = True

        embed = discord.Embed(
            description=f"Closing the music session {reason}",
            color=0x2b2d31)

        time = datetime.datetime.now() - self.started_session

        if time.seconds < 60:
            lasted = f"{time.seconds} seconds"
        elif time.seconds < 3600:
            minutes = int(time.seconds / 60)
            lasted = f"{minutes} minute{'s' if minutes != 1 else ''}"
        else:
            hours = int(time.seconds / 3600)
            lasted = f"{hours} hour{'s' if hours != 1 else ''}"

        played = (
            f"{self.total_played} song"
            f"{'s' if self.total_played != 1 else ''}")

        embed.set_footer(text=
            f"The music session lasted {lasted}, with {played} played.")

        await self.channel.send(embed=embed)

    def cleanup(self):
        """Clear internal states, remove player controller and disconnect."""
        super().cleanup()

        self.queue_task.cancel()

        for search_view in self.pending_searches:
            self.bot.loop.create_task(
                search_view.itx.delete_original_response())

        with suppress(AttributeError):
            self.bot.loop.create_task(self.queue_msg.delete())

class SearchButtons(discord.ui.View):
    def __init__(self, tracks, itx):
        super().__init__(timeout=30)

        self.itx = itx
        self.voice_client = itx.guild.voice_client
        self.voice_client.pending_searches.append(self)
        self.user = tracks[0].requester

        for i, track in enumerate(tracks[:4]):
            self.add_item(NumberButton(i + 1, track))

        self.add_item(CancelButton())

    async def on_timeout(self):
        with suppress(discord.HTTPException, discord.NotFound):
            await self.itx.delete_original_response()

        self.voice_client.pending_searches.remove(self)
        await self.voice_client.do_next()

    async def interaction_check(self, itx: Interaction):
        check = self.user == itx.user

        if not check:
            await itx.response.send_message(
                "this isn't for you", ephemeral=True)

        return check

class NumberButton(discord.ui.Button):
    def __init__(self, number, track):
        super().__init__(label=str(number))
        self.track = track

    async def callback(self, itx: Interaction):
        itx.guild.voice_client.tracks.append(self.track)

        description = f"Enqueued {self.track.formatted_name(31)}"
        embed = discord.Embed(description=description)
        await itx.response.edit_message(embed=embed, view=None)

        self.view.voice_client.pending_searches.remove(self.view)
        self.view.stop()
        await itx.guild.voice_client.update_queue()
        await itx.guild.voice_client.do_next()

class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel")

    async def callback(self, itx: Interaction):
        await itx.response.defer()

        with suppress(discord.HTTPException, discord.NotFound):
            await itx.delete_original_response()

        self.view.voice_client.pending_searches.remove(self.view)
        self.view.stop()
        await itx.guild.voice_client.do_next()

class Music(commands.Cog):
    """Toast's music side and commands, using wavelink."""

    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.start_node())

    @staticmethod
    async def music_check(itx: Interaction):
        """Check if the command should be allowed."""
        if not isinstance(itx.channel, discord.VoiceChannel):
            await itx.response.send_message(ephemeral=True, content=
                "you must use commands in the chat of a voice channel")
            return False

        voice = itx.user.voice

        if itx.guild.voice_client:
            if not voice or itx.channel_id != itx.user.voice.channel.id:
                await itx.response.send_message(ephemeral=True, content=
                    "you must join my voice chat")
                return False
        else:
            if voice and itx.channel_id != itx.user.voice.channel.id:
                await itx.response.send_message(ephemeral=True, content=
                    "use the chat of the voice channel you're "
                    "in instead of another")
                return False

            if itx.command.name != "play":
                await itx.response.send_message(ephemeral=True, content=
                    "no active session. Use /play")
                return False

            if not voice:
                await itx.response.send_message(ephemeral=True, content=
                    "join a voice chat")
                return False

            perms = itx.user.voice.channel.permissions_for(itx.guild.me)

            if not (perms.connect and perms.speak):
                await itx.response.send_message(ephemeral=True, content=
                    "I can't connect or speak in this voice channel")
                return False

        return True

    async def start_node(self):
        await self.bot.wait_until_ready()

        try:
            wavelink.NodePool.get_node()
        except wavelink.InvalidNode:
            node = wavelink.Node(
                uri="http://localhost:2333", password="youshallnotpass")
            await wavelink.NodePool.connect(client=self.bot, nodes=[node])

    @app_commands.check(music_check)
    @app_commands.guild_only()
    @app_commands.command()
    async def play(
        self,
        itx: Interaction,
        query: str,
        search_type: Literal["YouTube", "YouTube Music", "SoundCloud"] = None
    ):
        """Play a song in the voice channel.

        :param query: Link (YouTube, SoundCloud, Bandcamp, .MP3) or search
        :param search_type: Where your searches are done (YouTube by default)
        """
        await itx.response.defer()

        if not itx.guild.voice_client:
            await itx.user.voice.channel.connect(cls=Player)

        # Format query into something usable for node.get_tracks
        if query.startswith(("http://", "https://")):
            fetch_query = query
        elif search_type == "YouTube Music":
            fetch_query = f"ytmsearch:{query}"
        elif search_type == "SoundCloud":
            fetch_query = f"scsearch:{query}"
        else:
            fetch_query = f"ytsearch:{query}"

        node = wavelink.NodePool.get_node()

        # TODO: wavelink will replace ValueError later
        try:
            tracks = await node.get_tracks(wavelink.GenericTrack, fetch_query)
        except (wavelink.WavelinkException, ValueError):
            try:
                tracks = await node.get_playlist(
                    wavelink.YouTubePlaylist, fetch_query)
            except (wavelink.WavelinkException, ValueError):
                tracks = None

        # Do something with the results of get_tracks
        if not tracks:
            if query.startswith(("http://", "https://")):
                error = "Invalid link, or download was blocked."
            else:
                error = "No search results."

            embed = discord.Embed(description=error, color=0xed2121)

            await itx.followup.send(embed=embed)
            await itx.guild.voice_client.do_next()
            return

        if isinstance(tracks, wavelink.YouTubePlaylist):
            if tracks.selected_track not in (None, -1):
                selected = tracks.tracks[tracks.selected_track]
                track = Track(selected, itx.user)

                itx.guild.voice_client.tracks.append(track)
                description = f"Enqueued {track.formatted_name(31)}"
                embed = discord.Embed(description=description)
                await itx.followup.send(embed=embed)
                await itx.guild.voice_client.update_queue()
                await itx.guild.voice_client.do_next()
                return

            for track in tracks.tracks:
                track = Track(track, itx.user)
                itx.guild.voice_client.tracks.append(track)

            fmt = "Enqueued %s songs from: [%s](%s)"
            desc = fmt % (len(tracks.tracks), cut(tracks.name, 23), query)
            embed = discord.Embed(description=desc)
            await itx.followup.send(embed=embed)

            await itx.guild.voice_client.update_queue()
            await itx.guild.voice_client.do_next()
            return

        if len(tracks) > 1:
            description = []
            tracks = [Track(t, itx.user) for t in tracks]

            for i, track in enumerate(tracks[:4]):
                description.append(f"`{i + 1}.` {track.formatted_name(31)}")

            view = SearchButtons(tracks, itx)
            embed = discord.Embed(
                title="Choose a result",
                description="\n".join(description))

            await itx.followup.send(embed=embed, view=view)

            return

        track = Track(tracks[0], itx.user)
        itx.guild.voice_client.tracks.append(track)

        description = f"Enqueued {track.formatted_name(31)}"
        embed = discord.Embed(description=description)
        await itx.followup.send(embed=embed)
        await itx.guild.voice_client.update_queue()
        await itx.guild.voice_client.do_next()

    @app_commands.check(music_check)
    @app_commands.guild_only()
    @app_commands.command()
    async def queue(self, itx: Interaction):
        """Push the list of songs requested with /play to the bottom."""
        await itx.response.send_message("pushed to bottom.", ephemeral=True)
        await itx.guild.voice_client.update_queue(new_message=True)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEventPayload):
        if payload.reason == "LOAD_FAILED":
            return  # Handled by wavelink_track_exception

        await payload.player.do_next()

    @commands.Cog.listener()
    async def on_wavelink_track_exception(
        self, payload: wavelink.TrackEventPayload):

        payload.player.current_track.queue_sign = "!"
        payload.player.current_track.message = payload.reason
        await payload.player.do_next()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Leave if people left chat or bot got manually disconnected."""
        voice_client = member.guild.voice_client

        if not voice_client:
            return

        members = voice_client.channel.members
        toast_in_chat = voice_client.guild.me in members

        if toast_in_chat and len(voice_client.channel.members) == 1:
            await voice_client.send_disconnect_log("because everyone left.")
            await voice_client.disconnect()
        elif not toast_in_chat:
            await voice_client.send_disconnect_log("I got kicked out lol")
            await voice_client.disconnect()


class Skip(discord.ui.Button):
    def __init__(self, player):
        super().__init__(
            label="Skip" + player.format_vote("skip"),
            emoji=player.bot.toast_emoji("skip"),
            disabled=not player.is_playing())

        self.player = player

    async def callback(self, itx: Interaction):
        await itx.response.defer()

        self.player.update_vote(itx.user, "skip")

        if self.player.has_won_vote("skip"):
            msg = "skipped by vote"
        elif itx.user == self.player.current_track.requester:
            msg = "skipped by requester"
        elif self.player.bot.has_permission(itx.user, self.player.guild):
            msg = f"force-skipped by {itx.user}"
        else:
            await self.player.update_queue()
            return

        self.player.current_track.queue_sign = "S"
        self.player.current_track.message = msg
        await self.player.stop()

class Pause(discord.ui.Button):
    def __init__(self, player):
        if not player.is_paused():
            label = "Pause"
            emoji = player.bot.toast_emoji("pause")
        else:
            label = "Resume"
            emoji = player.bot.toast_emoji("resume")

        super().__init__(
            label=label + player.format_vote("pause"),
            emoji=emoji,
            disabled=not player.is_playing())

        self.player = player

    async def callback(self, itx: Interaction):
        await itx.response.defer()

        self.player.update_vote(itx.user, "pause")

        if self.player.has_won_vote("pause"):
            msg = "%s by vote"
        elif itx.user == self.player.current_track.requester:
            msg = "%s by requester"
        elif self.player.bot.has_permission(itx.user, self.player.guild):
            msg = f"force-%s by {itx.user}"
        else:
            await self.player.update_queue()
            return

        if self.player.is_paused():
            self.player.current_track.message = msg % "resumed"
            await self.player.resume()
        else:
            self.player.current_track.message = msg % "paused"
            await self.player.pause()

        await self.player.update_queue(reset_votes=True)

class Seek(discord.ui.Button):
    def __init__(self, player):
        disabled = not player.is_playing() or player.current_track.is_stream

        super().__init__(
            label="Seek",
            emoji=player.bot.toast_emoji("seek"),
            disabled=disabled)

        self.player = player

    async def callback(self, itx: Interaction):
        can_use = (
            itx.user == self.player.current_track.requester
            or self.player.bot.has_permission(itx.user, self.player.guild))

        if not can_use:
            await itx.response.send_message(ephemeral=True, content=
                "you must be the requester of the song or an admin")
            return

        await itx.response.send_modal(SeekModal(self.player))

class Leave(discord.ui.Button):
    def __init__(self, player):
        super().__init__(
            label="Leave" + player.format_vote("leave"),
            emoji=player.bot.toast_emoji("leave"))

        self.player = player

    async def callback(self, itx: Interaction):
        await itx.response.defer()

        self.player.update_vote(itx.user, "leave")

        user_requested_all_queue_tracks = (
            itx.user == self.player.current_track.requester
            and all([itx.user == t.requester for t in self.player.tracks]))

        if self.player.has_won_vote("leave"):
            reason = "because enough people clicked the Leave button."
        elif user_requested_all_queue_tracks:
            reason = (
                f"at the request of {itx.user.mention}, who had requested all "
                "remaining songs and clicked the Leave button.")
        elif self.player.bot.has_permission(itx.user, self.player.guild):
            reason = (
                f"at the request of {itx.user.mention}, who has special "
                "permissions and clicked the Leave button.")
        else:
            await self.player.update_queue()
            return

        await self.player.send_disconnect_log(reason)
        await self.player.disconnect()

class SeekModal(discord.ui.Modal, title="Seek to a specific timestamp"):
    timestamp = discord.ui.TextInput(
        label="Timestamp",
        placeholder="Examples: 01:30, 30, +30, -30",
        max_length=10)

    def __init__(self, player):
        super().__init__()
        self.player = player

    async def on_submit(self, itx: discord.Interaction):
        await itx.response.defer()

        time = self.children[0].value

        if itx.user == self.player.current_track.requester:
            msg = f"seek {time} by requester"
        elif self.player.bot.has_permission(itx.user, self.player.guild):
            msg = f"seek {time} by {itx.user}"

        if time.startswith(("+", "-")):
            relative_sign, time = time[0], time[1:]
        else:
            relative_sign = None

        split_times = zip([1, 60, 3600], time.split(":")[::-1])
        seek_to = sum(unit * int(times) for unit, times in split_times)

        if relative_sign == "+":
            seek_to = self.player.position + seek_to
        elif relative_sign == "-":
            seek_to = max(0, self.player.position - seek_to)

        await self.player.seek(seek_to * 1000)  # seek uses ms
        self.player.current_track.message = msg
        await asyncio.sleep(0.5)
        await self.player.update_queue()

class QueueButtons(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=None)

        self.add_item(Pause(player))
        self.add_item(Skip(player))
        self.add_item(Seek(player))
        self.add_item(Leave(player))

        self.player = player

    async def interaction_check(self, itx: Interaction):
        check = (not itx.user.bot and itx.user in self.player.channel.members)

        if not check:
            await itx.response.send_message(
                "you must be in the voice channel", ephemeral=True)

        return check

async def setup(bot):
    await bot.add_cog(Music(bot))
