from contextlib import suppress
from io import BytesIO
import datetime
import pickle

from discord import app_commands, Interaction
from discord.ext import commands, tasks
import discord


class PurgeModal(discord.ui.Modal, title="Purge all messages after here"):
    timestamp = discord.ui.TextInput(
        label="Delete only messages by this author?",
        default="No",
        placeholder="Yes or No (I'd make this a selection if I could)")

    def __init__(self, message):
        super().__init__()
        self.message = message

    async def purge(self, itx: Interaction, message, only_from_author=False):
        if only_from_author:
            check = lambda m: m.author == message.author
        else:
            check = lambda m: True

        after = message.created_at - datetime.timedelta(milliseconds=1)
        reason = (
            f"{itx.user} right-clicked a message "
            f"from {message.author}")

        return await itx.channel.purge(
            limit=500, after=after, reason=reason, check=check)

    async def on_submit(self, itx: Interaction):
        await itx.response.defer(thinking=True, ephemeral=True)

        answer = self.children[0].value
        only_from_author = True if answer.lower() == "yes" else False
        deleted = await self.purge(itx, self.message, only_from_author)

        if only_from_author:
            msg = f"deleted {len(deleted)} messages by {self.message.author}"
        else:
            msg = f"deleted {len(deleted)} messages"

        log = []

        for m in deleted:
            attachments = "\n[attachment]" if m.attachments else ""
            embeds = "\n[embed]" if m.embeds else ""
            log.append(
                f"[{m.created_at:%H:%M)}] "
                f"{m.author.display_name} ({m.author.id})\n"
                f"{m.clean_content}{attachments}{embeds}\n")

        data = BytesIO("\n".join(log).encode())
        file = discord.File(data, filename="deleted_messages.txt")
        await itx.followup.send(msg, file=file)


class Miscellaneous(commands.Cog):
    """For all the stuff that doesn't fit in other cogs."""

    def __init__(self, bot: commands.Bot):
        self.counter = 0
        self.bot = bot
        self.auto_db_save.start()
        self.purge_menu = app_commands.ContextMenu(
            name="Purge after here", callback=self.purge)
        self.bot.tree.add_command(self.purge_menu)

    @tasks.loop(minutes=1)
    async def auto_db_save(self):
        """Save db every minute."""
        with open("db.p", "wb") as file:
            pickle.dump(self.bot.db, file)

    @app_commands.guild_only()
    @app_commands.checks.bot_has_permissions(manage_messages=True)
    @app_commands.default_permissions(manage_messages=True)
    async def purge(self, itx: Interaction, message: discord.Message):
        """Delete all messages after this one."""
        await itx.response.send_modal(PurgeModal(message))

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if after.name != before.name:
            await self.dynamic_voicechannel_update(after.guild)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        await self.dynamic_voicechannel_update(member.guild)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if self.counter % 20 == 0:
            await message.add_reaction("🖕")

        self.counter += 1

    async def dynamic_voicechannel_update(self, guild):
        """Update voice channels based on demand."""
        settings = self.bot.db["settings"][guild.id]
        category_id = settings["dynamic_voicechannel"]
        voice_name = settings["dynamic_voicechannel_text"]

        if not category_id:
            return

        if not await self.bot.cooldown_check(f"{guild.id}{category_id}", 6):
            return

        if category_id == "no_category":
            category = guild
            channels = [c for c in guild.voice_channels if not c.category]
        else:
            category = guild.get_channel(settings["dynamic_voicechannel"])

            if not category:
                return

            channels = category.voice_channels

        # creating own empty list because category.voice_channels is unreliable
        empty = [c for c in channels if not c.members]

        # Delete empty channels, leave one remaining
        for channel in empty[1:]:
            channels.remove(channel)
            with suppress(discord.NotFound, discord.Forbidden):
                await channel.delete(reason="dynamic_voicechannel: removing")

        # Ensure at least one empty channel exists
        if not empty:
            try:
                channel = await category.create_voice_channel(
                    name=f"{voice_name} {len(channels) + 1}",
                    reason="dynamic_voicechannel: adding new")
            except discord.Forbidden:
                return

            channels.append(channel)

        # Ensure default names are ordered correctly, reset empty channels
        for i, channel in enumerate(channels):
            name = voice_name + ("" if i == 0 else f" {i + 1}")

            if channel.name == name:
                continue

            split = channel.name.split()
            is_default_name = (
                (split[0] == voice_name and split[::-1][0].isdigit())
                or channel.name == voice_name)

            if is_default_name or not channel.members:
                with suppress(discord.NotFound, discord.Forbidden):
                    await channel.edit(
                        name=name,
                        user_limit=None if channel.members else 0,
                        reason="dynamic_voicechannel: resetting")


async def setup(bot):
    await bot.add_cog(Miscellaneous(bot))
