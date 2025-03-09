from contextlib import suppress
from io import BytesIO

from discord.ext import commands
from discord import utils
import discord
import aiohttp
import pyfsig


class Starboard(commands.Cog):
    """A system that adds messages voted with stars into a channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def check_permissions(
        self, channel: discord.TextChannel, *, starboard: bool
    ):
        """Return whether the bot has enough permissions for this channel."""
        perms = channel.permissions_for(channel.guild.me)

        if starboard:
            return all((
                perms.manage_messages, perms.attach_files,
                perms.read_messages, perms.send_messages,
                perms.manage_webhooks))

        return all((
            perms.manage_messages, perms.read_messages, perms.send_messages))

    async def fetch_starboard_webhook(self, starboard: discord.TextChannel):
        """Fetch existing starboard webhook or make one."""
        for webhook in await starboard.webhooks():
            if webhook.name == "toast_starboard_webhook":
                return webhook

        return await starboard.create_webhook(name="toast_starboard_webhook")

    async def get_reply_content(self, message: discord.Message):
        if message.type != discord.MessageType.reply:
            return None

        resolved = message.reference.resolved or await self.bot.fetch_message(
            message.reference.channel_id, message.reference.message_id)

        if not isinstance(resolved, discord.Message):
            return (
                f"{self.bot.toast_emoji('reply')} "
                f" *Original message was deleted*")

        reply_content = self.bot.cut(
            f"{self.bot.toast_emoji('reply')} "
            f"{resolved.author.mention} {resolved.clean_content}", 180)

        if resolved.attachments or resolved.embeds:
            attachment_emoji = self.bot.toast_emoji('attachment')
            if not resolved.content:
                reply_content += f"*Attachment* {attachment_emoji}"
            else:
                reply_content += f" {attachment_emoji}"

        return reply_content

    async def prepare_embed(
        self, embed: discord.Embed, files: list, i: int, filesize_limit: int
    ):
        """Preserve every image as is possible and format embed better."""
        if embed.image.url:
            embed.set_image(url=await self.fetch_file(
                embed.image.url, files, filesize_limit, file_type=f"image{i}"))

        if embed.thumbnail.url:
            embed.set_thumbnail(url=await self.fetch_file(
                embed.thumbnail.url, files, filesize_limit,
                file_type=f"thumbnail{i}"))

        if embed.author.icon_url:
            author_icon_url = await self.fetch_file(
                embed.author.icon_url, files, filesize_limit,
                file_type=f"author{i}")
            embed.set_author(
                name=embed.author.name,
                icon_url=author_icon_url,
                url=embed.author.url)

        if embed.footer.icon_url:
            footer_icon_url = await self.fetch_file(
                embed.footer.icon_url, files, filesize_limit,
                file_type=f"footer{i}")
            embed.set_footer(text=embed.footer.text, icon_url=footer_icon_url)

        # Some sites work around hidden descriptions by putting it in author
        if embed.author.name == embed.description:
            embed.description = ""

    async def fetch_file(
        self, url: str, files: list, filesize_limit: int, file_type: str = ""
    ):
        """Add a file to the list of uploaded files, return URL."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return url

                    data = BytesIO(await resp.read())
        except aiohttp.ClientConnectorError:
            return url

        if data.getbuffer().nbytes >= filesize_limit:
            return url

        name = resp.url.path.split("/")[-1]
        extension = "unknown"
        expected_formats = (
            "png", "jpg", "jpeg", "gif", "webm", "mp3", "mp4", "mov")

        if "." in name:
            name, extension = name.rsplit(".", 1)

        if extension.lower() not in expected_formats:
            signatures = pyfsig.find_matches_for_file_header(data.read(32))
            data.seek(0)

            for sig in signatures:
                if sig.file_extension in expected_formats:
                    extension = sig.file_extension
                    break

        if extension.lower() == "getblob":  # dumb bluesky stuff
            extension = "mp4"

        if file_type:
            filename = f"toast_{file_type}.{extension}"
        else:
            filename = f"{name}.{extension}"

        files.append(discord.File(data, filename=filename))

        if file_type:
            return f"attachment://{filename}"

    @commands.Cog.listener("on_raw_reaction_add")
    @commands.Cog.listener("on_raw_reaction_remove")
    async def update_starboard(self, src: discord.RawReactionActionEvent):
        """Update starboard."""
        if src.emoji.name != "⭐" or not src.guild_id:
            return

        settings = self.bot.db["settings"][src.guild_id]
        starboard = self.bot.get_channel(settings["starboard_channel"])

        if not starboard:
            return
        if not self.check_permissions(starboard, starboard=True):
            return
        if not await self.bot.cooldown_check(f"starboard{src.message_id}", 6):
            return

        message = await self.bot.fetch_message(src.channel_id, src.message_id)
        messages = await self.fetch_both_messages(message, starboard)
        original_msg, starboard_msg = messages.values()

        if not original_msg:
            return
        if not self.check_permissions(original_msg.channel, starboard=False):
            return

        stars = await self.fetch_stars(messages)
        starmin = settings["starboard_starmin"]

        if not starboard_msg:
            if original_msg.is_system() or stars < starmin:
                return

            webhook = await self.fetch_starboard_webhook(starboard)
            await self.create_message(original_msg, stars, webhook)
        else:
            if starboard_msg.author == self.bot.user:  # old starboard
                return

            message_stars = int(starboard_msg.content.split()[1])

            if stars == message_stars:
                return
            # Embed stars being under minimum might mean minimum was changed
            if stars < starmin and (message_stars >= starmin or stars == 0):
                await starboard_msg.delete()
                return

            webhook = await self.fetch_starboard_webhook(starboard)
            await self.edit_message(starboard_msg, stars, starmin, webhook)

    async def create_message(
        self, message: discord.Message, stars: int, webhook: discord.Webhook
    ):
        """Create a message in the starboard."""
        content = []
        files = []
        embeds = []
        potential_embeds = []
        filesize_limit = message.guild.filesize_limit
        starboard_info = (
            f"{stars} {self.bot.toast_emoji('star')}", message.author.name,
            message.jump_url)

        content.append(f"-# {' • '.join(starboard_info)}")
        content.append(await self.get_reply_content(message))

        for s_message in [message] + message.message_snapshots:
            if isinstance(s_message, discord.MessageSnapshot):
                content.append(
                    f"{self.bot.toast_emoji('forward')} *Forwarded*")

            if s_message.content:
                content.append(self.bot.cut(s_message.content, 1700))

            for attachment in s_message.attachments:
                if attachment.size < filesize_limit:
                    files.append(await attachment.to_file(
                        spoiler=attachment.is_spoiler()))
                else:
                    content.append(attachment.url)

            for i, embed in enumerate(list(s_message.embeds)):
                await self.prepare_embed(embed, files, i, filesize_limit)

                if embed.type == "video" and embed.provider.name == "YouTube":
                    potential_embeds.append(embed)
                elif embed.video.url:
                    fetched = await self.fetch_file(
                        embed.video.url, files, filesize_limit)

                    if fetched != embed.video.url:
                        # Ensure embed isn't essentially empty
                        if embed.title or embed.author.name:
                            embeds.append(embed)
                    else:
                        potential_embeds.append(embed)
                else:
                    embeds.append(embed)

        if embeds:
            embeds.extend(potential_embeds)
        else:
            # Remove all files related to potential_embeds
            for file in list(files):
                if file.filename.startswith("toast_"):
                    files.remove(file)

        content = list(filter(None, content))

        if len(content) > 1:
            content.insert(1, "-# _ _")  # small separator

        sent_webhook = await webhook.send(
            content=self.bot.cut("\n".join(content), 1998),
            username=message.author.display_name,
            avatar_url=message.author.display_avatar.url,
            files=files,
            embeds=embeds or utils.MISSING,
            wait=True)

        self.bot.db["starboard"][message.id] = sent_webhook.id

    async def edit_message(
        self, message: discord.Message, stars: int, webhook: discord.Webhook
    ):
        """Edit star color and number."""
        message = await webhook.fetch_message(message.id)
        split_content = message.content.split(" • ")
        split_content[0] = f"-# {stars} {self.bot.toast_emoji('star')}"

        await message.edit(content=" • ".join(split_content))

    async def fetch_stars(self, msgs: list):
        """Return star count from both messages with author removed."""
        reactions = set()

        for message in filter(None, msgs.values()):
            for reaction in message.reactions:
                if reaction.emoji == "⭐":
                    reactions.update([u async for u in reaction.users()])

                    if msgs["original"].author in reactions:
                        await reaction.remove(msgs["original"].author)
                        reactions.discard(msgs["original"].author)

        return len(reactions)

    async def fetch_both_messages(
        self, reference_msg: discord.Message, starboard: discord.TextChannel
    ):
        """Get original/starboard based off contents from the opposite msg."""
        msgs = {"original": None, "starboard": None}
        reference_likely_old_starboard = (
            reference_msg.author == self.bot.user
            and reference_msg.channel.id == starboard.id)
        reference_likely_starboard = (
            reference_msg.webhook_id
            and reference_msg.channel.id == starboard.id)

        if reference_likely_old_starboard:
            with suppress(ValueError, IndexError):
                og_link = reference_msg.embeds[0].author.url

                msgs["starboard"] = reference_msg
                msgs["original"] = await self.bot.fetch_message_link(og_link)

        if reference_likely_starboard:
            with suppress(ValueError, IndexError):
                og_link = reference_msg.content.split()[5]

                msgs["starboard"] = reference_msg
                msgs["original"] = await self.bot.fetch_message_link(og_link)

        if not msgs["starboard"]:
            msg_id = (
                self.bot.db["starboard"].get(reference_msg.id)
                or self.bot.db["old_starboard"].get(reference_msg.id))

            msgs["original"] = reference_msg
            msgs["starboard"] = await self.bot.fetch_message(
                starboard.id, msg_id)

        return msgs


async def setup(bot):
    await bot.add_cog(Starboard(bot))
