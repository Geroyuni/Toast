from contextlib import suppress
import datetime
import asyncio
from typing import Literal
from types import MethodType

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


class Player(wavelink.Player):
    """Custom wavelink Player class."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.bot = self.client

        self.votes = {"skip": set(), "pause": set(), "leave": set()}
        self.queue_message = None
        self.info = ""
        self.pending_searches = []
        self.total_played = 0
        self.updated_queue_message_at = datetime.datetime.now()
        self.started_session = datetime.datetime.now()
        self.queue_task = self.bot.loop.create_task(self.auto_queue_update())
        self.do_next_lock = asyncio.Lock()

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

    async def get_queue_embed(self):
        """Return queue embed."""
        position = self.position / 1000
        tracks = ""

        for track in self.queue.history[-3:-1]:
            tracks += f"`{track.queue_sign}.` {track.formatted_name(27)}\n"

        most_current = self.current or self.queue.history[-1]

        if self.paused:
            npsymbol = "||"
        elif self.playing:
            npsymbol = ">>"
        else:
            npsymbol = f"{most_current.queue_sign}."

            if most_current.queue_sign == ".":
                position = most_current.length / 1000

        tracks += f"`{npsymbol}` {most_current.formatted_name(27)}\n"

        for i, track in enumerate(self.queue):
            fmt = f"`{i + 1}.` {track.formatted_name(27)}\n"

            if i + 1 >= 6 or len(tracks + fmt) >= 2970:
                amount = len(self.queue) - i
                tracks += f"`++` and {amount} more songs"
                break

            tracks += fmt

        if most_current.is_stream:
            footer = "Live"
            icon_url = "https://files.catbox.moe/j7p5dg.png"
        else:
            circle_index = int(7 * (position / (most_current.length / 1000)))
            circles = (
                "z5f2nv", "0xixvt", "vrme8x", "zzg5i2",
                "aguy64", "ry5vrh", "5kjsb1", "7si0i6")

            footer = f"{fmt_time(position)} / {most_current.length_fmt}"
            icon_url = f"https://files.catbox.moe/{circles[circle_index]}.png"

        if self.info:
            footer += f" - {self.info}"

        embed = discord.Embed(description=tracks, color=0x2b2d31)
        embed.set_thumbnail(url=most_current.thumbnail)
        embed.set_footer(text=footer, icon_url=icon_url)
        return embed

    async def update_queue(self, *, new_message=False, reset_votes=False):
        """Handle creating and updating queue."""
        if not self.queue and not self.queue.history:
            return

        if not await self.bot.cooldown_check(self.channel.id, 2):
            return

        if new_message:
            for vote in self.votes.values():
                vote.clear()

            with suppress(discord.NotFound, AttributeError):
                message = [m async for m in self.channel.history(limit=1)][0]

                if self.queue_message.id == message.id:
                    await self.queue_message.edit(
                        embed=await self.get_queue_embed(),
                        view=QueueButtons(self))

                    self.updated_queue_message_at = datetime.datetime.now()
                    return

                await self.queue_message.delete()

            self.queue_message = await self.channel.send(
                embed=await self.get_queue_embed(), view=QueueButtons(self))

            self.updated_queue_message_at = datetime.datetime.now()
            return

        with suppress(discord.NotFound, AttributeError):
            if reset_votes:
                for vote in self.votes.values():
                    vote.clear()

            await self.queue_message.edit(
                embed=await self.get_queue_embed(), view=QueueButtons(self))

            self.updated_queue_message_at = datetime.datetime.now()

    async def do_next(self):
        """Get playing into motion, or disconnect if inactive."""
        async with self.do_next_lock:
            if self.playing:
                return

            if not self.queue and self.queue.mode == wavelink.QueueMode.normal:
                await self.update_queue(reset_votes=True)
                time = datetime.datetime.now()
                delta = datetime.timedelta(seconds=15)

                while not self.queue:
                    await asyncio.sleep(0.1)

                    if self.pending_searches:
                        time = datetime.datetime.now()
                        continue

                    if datetime.datetime.now() - time > delta:
                        await self.send_disconnect_log("due to inactivity.")
                        await self.disconnect()
                        return

            self.total_played += 1
            await self.play(self.queue.get())
            await self.update_queue(new_message=True)

    async def auto_queue_update(self):
        """Update queue every so often to update time."""
        while True:
            await asyncio.sleep(10)
            delta = datetime.timedelta(seconds=29)

            if datetime.datetime.now() - self.updated_queue_message_at < delta:
                continue

            if self.playing and not (self.paused or self.current.is_stream):
                await self.update_queue()

    async def send_disconnect_log(self, reason):
        """Log that Toast left, and leave cool stats."""
        if hasattr(self, "already_sent_log"):
            return

        self.already_sent_log = True

        time = datetime.datetime.now() - self.started_session

        if time.seconds < 60:
            lasted = f"{time.seconds} seconds"
        elif time.seconds < 3600:
            minutes = int(time.seconds / 60)
            lasted = f"{minutes} minute{'s'[:minutes^1]}"
        else:
            hours = int(time.seconds / 3600)
            lasted = f"{hours} hour{'s'[:hours^1]}"

        embed = discord.Embed(
            description=f"Closing the music session {reason}",
            color=0x2b2d31)
        embed.set_footer(text=
            f"The music session lasted {lasted}, with "
            f"{self.total_played} song{'s'[:self.total_played^1]} played.")

        await self.channel.send(embed=embed)

    def cleanup(self):
        """Clear internal states, remove player controller and disconnect."""
        super().cleanup()

        self.queue_task.cancel()

        for search_view in self.pending_searches:
            self.bot.loop.create_task(
                search_view.itx.delete_original_response())

        with suppress(AttributeError):
            self.bot.loop.create_task(self.queue_message.delete())

class SearchButtons(discord.ui.View):
    def __init__(self, search_results, itx):
        super().__init__(timeout=30)

        self.itx = itx
        self.voice_client = itx.guild.voice_client
        self.voice_client.pending_searches.append(self)
        self.user = search_results[0].requester

        for i, result in enumerate(search_results[:4]):
            self.add_item(NumberButton(i + 1, result))

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
    def __init__(self, number, result):
        super().__init__(label=str(number))
        self.result = result

    async def callback(self, itx: Interaction):
        await itx.guild.voice_client.queue.put_wait(self.result)

        description = f"Enqueued {self.result.formatted_name(31)}"
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

    @staticmethod
    def formatted_name(self, length: int):
        """(For use in a Playable) Return cut name with link and tooltip."""

        tooltip = (
            f"{self.requester.display_name}: "
            f"[{self.length_fmt}] {self.author}: {self.title}")

        # Checking hyphen assuming that it could be the 'Author - Name' format
        if self.author.lower() in self.title.lower() or " - " in self.title:
            name = self.title
        else:
            name = f"{self.author} - {self.title}"

        name = name.replace(" - Topic - ", " - ")  # dumb YouTube thing
        return f"[{cut(name, length)}]({self.uri} '{tooltip}')"

    def prepare_playable(self, playable: wavelink.Playable, requester):
        """Add extra information I need to a playable track."""
        playable.queue_sign = "."
        playable.requester = requester
        playable.length_fmt = fmt_time(playable.length / 1000)
        playable.thumbnail = (
            playable.artwork or "https://files.catbox.moe/s6w50k.png")

        playable.formatted_name = MethodType(self.formatted_name, playable)

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

        sources = {
            None: wavelink.TrackSource.YouTube,
            "YouTube": wavelink.TrackSource.YouTube,
            "YouTube Music": wavelink.TrackSource.YouTubeMusic,
            "SoundCloud": wavelink.TrackSource.SoundCloud}

        source = sources[search_type]

        try:
            playable = await wavelink.Playable.search(query, source=source)
        except wavelink.LavalinkLoadException:
            playable = None

        if not playable:
            error = "No search results or your link is invalid or blocked."
            embed = discord.Embed(description=error, color=0xed2121)
            await itx.followup.send(embed=embed)
            await itx.guild.voice_client.do_next()
            return

        if isinstance(playable, list) and len(playable) > 1:
            search_results = playable[:4]
            description = []

            for i, result in enumerate(search_results):
                self.prepare_playable(result, itx.user)
                description.append(f"`{i + 1}.` {result.formatted_name(31)}")

            view = SearchButtons(search_results, itx)
            embed = discord.Embed(
                title="Choose a result",
                description="\n".join(description))

            await itx.followup.send(embed=embed, view=view)
            return

        if isinstance(playable, wavelink.Playlist):
            if playable.selected != -1:
                playable = playable.tracks[playable.selected]
                self.prepare_playable(playable, itx.user)
                description = f"Enqueued {playable.formatted_name(31)}"
            else:
                for track in playable.tracks:
                    self.prepare_playable(track, itx.user)

                description = (
                    f"Enqueued {len(playable.tracks)} songs from: "
                    f"[{cut(playable.name, 23)}]({query})")
        else:
            playable = playable[0]
            self.prepare_playable(playable, itx.user)
            description = f"Enqueued {playable.formatted_name(31)}"

        embed = discord.Embed(description=description)
        await itx.followup.send(embed=embed)

        await itx.guild.voice_client.queue.put_wait(playable)
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
    async def on_wavelink_track_end(
        self, payload: wavelink.TrackEndEventPayload):
        if not payload.player:
            return

        payload.player.info = ""

        if payload.reason == "LOAD_FAILED":
            payload.player.info = "Previous track had trouble playing"

        await payload.player.do_next()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Leave if people left chat or bot got manually disconnected."""
        voice_client = member.guild.voice_client

        if voice_client and len(voice_client.channel.members) == 1:
            await voice_client.send_disconnect_log("because everyone left.")
            await voice_client.disconnect()


class Skip(discord.ui.Button):
    def __init__(self, player):
        super().__init__(
            label="Skip" + player.format_vote("skip"),
            emoji=player.bot.toast_emoji("skip"),
            disabled=not player.playing)

        self.player = player

    async def callback(self, itx: Interaction):
        await itx.response.defer()

        self.player.update_vote(itx.user, "skip")

        if self.player.has_won_vote("skip"):
            msg = "Previous track was skipped by vote"
        elif itx.user == self.player.current.requester:
            msg = "Previous track was skipped by requester"
        elif self.player.bot.has_permission(itx.user, self.player.guild):
            msg = f"Previous track was force-skipped by {itx.user}"
        else:
            await self.player.update_queue()
            return

        self.player.current.queue_sign = "S"
        self.player.info = msg
        await self.player.skip()

class Pause(discord.ui.Button):
    def __init__(self, player):
        if not player.paused:
            label = "Pause"
            emoji = player.bot.toast_emoji("pause")
        else:
            label = "Resume"
            emoji = player.bot.toast_emoji("resume")

        super().__init__(
            label=label + player.format_vote("pause"),
            emoji=emoji,
            disabled=not player.playing)

        self.player = player

    async def callback(self, itx: Interaction):
        await itx.response.defer()

        self.player.update_vote(itx.user, "pause")

        if self.player.has_won_vote("pause"):
            msg = "Recently %s by vote"
        elif itx.user == self.player.current.requester:
            msg = "Recently %s by requester"
        elif self.player.bot.has_permission(itx.user, self.player.guild):
            msg = f"Recently force-%s by {itx.user}"
        else:
            await self.player.update_queue()
            return

        if self.player.paused:
            self.player.info = msg % "resumed"
        else:
            self.player.info = msg % "paused"

        await self.player.pause(not self.player.paused)
        await self.player.update_queue(reset_votes=True)

class More(discord.ui.Button):
    def __init__(self, player):
        super().__init__(
            label="More",
            emoji=player.bot.toast_emoji("more"),
            disabled=not player.playing)

        self.player = player

    async def callback(self, itx: Interaction):
        can_use = (
            itx.user == self.player.current.requester
            or self.player.bot.has_permission(itx.user, self.player.guild))

        if not can_use:
            await itx.response.send_message(ephemeral=True, content=
                "you must be the requester of the song or a server manager")
            return

        await itx.response.send_modal(MoreModal(self.player))

class Leave(discord.ui.Button):
    def __init__(self, player):
        super().__init__(
            label="Leave" + player.format_vote("leave"),
            emoji=player.bot.toast_emoji("leave"))

        self.player = player

    async def callback(self, itx: Interaction):
        await itx.response.defer()

        self.player.update_vote(itx.user, "leave")
        most_current = self.player.current or self.player.queue.history[-1]

        user_requested_all_queue_tracks = (
            itx.user == most_current.requester
            and all([itx.user == t.requester for t in self.player.queue]))

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

class MoreModal(discord.ui.Modal, title="More settings"):
    def __init__(self, player):
        super().__init__()
        self.player = player

        self.default_position = fmt_time(self.player.position / 1000)
        self.default_volume = f"{self.player.volume}%"
        self.default_loop_mode = str(self.player.queue.mode.value)

        self.add_item(discord.ui.TextInput(
            label="Timestamp",
            default=self.default_position,
            placeholder=self.default_position,
            max_length=10,
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Volume (0 to 500%) [server managers only]",
            default=self.default_volume,
            placeholder=self.default_volume,
            max_length=4,
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Loop mode [server managers only]",
            default=self.default_loop_mode,
            placeholder="Examples: 0 (off), 1 (this song), 2 (whole queue)",
            max_length=10,
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Shuffle [server managers only]",
            placeholder="Type anything here to shuffle the queue",
            required=False))

    async def on_submit(self, itx: discord.Interaction):
        await itx.response.defer()

        position, volume, loop_mode, shuffle = [i.value for i in self.children]
        queue_info = None

        if position and position != self.default_position:
            queue_info = f"Recently jumped to {position}"

            split_times = zip([1, 60, 3600], position.split(":")[::-1])
            seek_to = sum(unit * int(times) for unit, times in split_times)

            await self.player.seek(seek_to * 1000)  # seek uses ms

        if volume and volume != self.default_volume:
            await self.player.set_volume(int(volume.strip("%")))

        if self.player.bot.has_permission(itx.user, self.player.guild):
            if volume and volume != self.default_volume:
                queue_info = f"Volume recently set to {volume}"
                await self.player.set_volume(int(volume.strip("%")))

            if loop_mode and loop_mode != self.default_loop_mode:
                queue_mode = wavelink.QueueMode(int(loop_mode))
                queue_info = f"Loop mode recently set to {queue_mode.name}"
                self.player.queue.mode = queue_mode

            if shuffle:
                queue_info = "Queue recently shuffled"
                self.player.queue.shuffle()

        values_changed = (
            position != self.default_position,
            volume != self.default_volume,
            loop_mode != self.default_loop_mode,
            shuffle)

        if values_changed.count(True) > 1:
            queue_info = "Multiple changes recently made"

        if not queue_info:
            return

        if itx.user == self.player.current.requester:
            queue_info = queue_info + " by requester"
        elif self.player.bot.has_permission(itx.user, self.player.guild):
            queue_info = queue_info + f" by {itx.user}"

        self.player.info = queue_info

        await asyncio.sleep(0.5)
        await self.player.update_queue()

class QueueButtons(discord.ui.View):
    def __init__(self, player):
        super().__init__(timeout=None)

        self.add_item(Pause(player))
        self.add_item(Skip(player))
        self.add_item(More(player))
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

    try:
        wavelink.Pool.get_node()
    except wavelink.InvalidNodeException:
        node = wavelink.Node(
            uri="http://localhost:2333", password="youshallnotpass")
        await wavelink.Pool.connect(client=bot, nodes=[node])
