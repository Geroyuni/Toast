import pickle
import asyncio
import datetime

from discord.ext import commands
import discord

from token_ import token


class ToastBot(commands.Bot):
    def __init__(self):
        allowed_mentions = discord.AllowedMentions.none()
        intents = discord.Intents(
            members=True, emojis=True, guilds=True, voice_states=True,
            messages=True, reactions=True, message_content=True)
        emoji_ids = {
            "cooldown": (822620939506286623, "⏰"),
            "skip": (1016241951814717481, "⏩"),
            "pause": (1016241949570773112, "⏸️"),
            "resume": (1016530529744597033, "▶️"),
            "more": (1236918340849504359, "*️⃣"),
            "leave": (1016241948304085083, "🚪"),
            "bot_account": (844063672258134046, "🤖"),
            "replied_to1": (848652492963446804, "📩"),
            "replied_to2": (848654634800381962, "➡️"),
            "attachment": (1010999258280886373, "🖼️")}

        super().__init__(
            command_prefix="!", case_insensitive=True,
            allowed_mentions=allowed_mentions, intents=intents)
        self.remove_command("help")

        self.times = {}
        self.emoji_ids = emoji_ids
        self.db = self.load_db()
        self.invoke_dict = {}

    async def setup_hook(self):
        self.owner = (await self.application_info()).owner
        self.cog_file_names = (
            "embed", "general", "hidden", "logging", "misc",
            "music", "owner", "servers", "settings", "starboard")

        for cog in self.cog_file_names:
            await self.load_extension(f"cogs.{cog}")

    def load_db(self):
        try:
            with open("db.p", "rb") as file:
                db = pickle.load(file)
        except FileNotFoundError:
            db = {"settings": {}, "starboard": {}, "logs": {}, "whitelist": []}

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
            user == self.owner or
            (member and member.guild_permissions.manage_guild))

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
                self.get_channel(channel_id) or
                await self.fetch_channel(channel_id))
        except discord.NotFound:
            return None

        try:
            return await channel.fetch_message(message_id)
        except (discord.NotFound, AttributeError):
            return None

    async def on_message(self, message):
        pass


bot = ToastBot()

try:
    bot.run(token)
finally:
    bot.save_db()
