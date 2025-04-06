import datetime
import asyncio
import logging
import pickle

from discord.ext import commands
import discord

from token_ import token


EMOJI_IDS = {
    "skip": (1016241951814717481, "⏩"),
    "pause": (1016241949570773112, "⏸️"),
    "resume": (1016530529744597033, "▶️"),
    "more": (1236918340849504359, "*️⃣"),
    "leave": (1016241948304085083, "🚪"),
    "attachment": (1010999258280886373, "🖼️"),
    "reply": (1347752310411104308, "📩"),
    "forward": (1347797107313999934, "⤴️"),
    "star": (1348053464252416020, "⭐")}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S")

for logger in logging.root.manager.loggerDict:
    logging.getLogger(logger).setLevel(logging.WARNING)


class ToastBot(commands.Bot):
    def __init__(self):
        allowed_mentions = discord.AllowedMentions.none()
        intents = discord.Intents(
            members=True, emojis=True, guilds=True, voice_states=True,
            messages=True, reactions=True, message_content=True)

        super().__init__(
            command_prefix=[], allowed_mentions=allowed_mentions,
            intents=intents)

        self.times = {}
        self.emoji_ids = EMOJI_IDS
        self.db = self.load_db()
        self.invoke_dict = {}

    async def setup_hook(self):
        self.owner = (await self.application_info()).owner
        self.cog_file_names = (
            "embed", "general", "hidden", "logging", "misc",
            "owner", "servers", "settings", "starboard")

        for cog in self.cog_file_names:
            await self.load_extension(f"cogs.{cog}")

    def load_db(self):
        try:
            with open("db.p", "rb") as file:
                db = pickle.load(file)
        except FileNotFoundError:
            db = {"settings": {}, "starboard": {}, "old_starboard": {}}

        return db

    def save_db(self):
        with open("db.p", "wb") as file:
            pickle.dump(self.db, file)

    def toast_emoji(self, name):
        emoji_set = self.emoji_ids[name]
        return self.get_emoji(emoji_set[0]) or emoji_set[1]

    def has_permission(self, user, guild):
        """Check member has manage guild perm or is bot owner."""
        member = guild.get_member(user.id)

        return (
            user == self.owner
            or (member and member.guild_permissions.manage_guild))

    @staticmethod
    def fmt_command(itx: discord.Interaction):
        return f"{itx.user.name}: /{itx.command.name}"

    @staticmethod
    def cut(string, length):
        """Cut a string to based on the string length."""
        return string if len(string) < length else f"{string[:length - 2]}.."

    async def cooldown_check(self, reference_id, seconds):
        """Approve only 1 reference_id every seconds.

        - A reference_id is sent with a 5 second cooldown: Returns True
        - 2nd sent 1s later: Schedule it to return True when 4 seconds pass
        - 3rd sent 1s later: Returns False, 2nd is already scheduled

        Probably a mess, but it's my way of not letting things out of control.
        The intention is that I leave one request hanging around so it
        eventually acts and updates things to the newest state, while
        preventing spam.
        """
        if times := self.times.get(reference_id):
            if times["ignore"]:
                return False

            times["ignore"] = True
            seconds = datetime.timedelta(seconds=seconds)

            while datetime.datetime.now() - times["time"] < seconds:
                await asyncio.sleep(0.2)

        self.times[reference_id] = {
            "time": datetime.datetime.now(), "ignore": False}
        return True

    async def fetch_message_link(self, link):
        """Try to fetch a message from a given link."""
        ids = link.split("#")[0].split("/")[-2:]
        return await self.fetch_message(ids[0], ids[1])

    async def fetch_message(self, channel_id, message_id):
        """Try to fetch a message from the given channel and message id."""
        if not channel_id or not message_id:
            return None

        try:
            channel = (
                self.get_channel(channel_id)
                or await self.fetch_channel(channel_id))
        except discord.NotFound:
            return None

        try:
            return await channel.fetch_message(message_id)
        except (discord.NotFound, AttributeError):
            return None

    async def close(self):
        self.save_db()
        await super().close()


if __name__ == "__main__":
    bot = ToastBot()
    bot.run(token)
