from datetime import datetime
from urllib.parse import urlparse
from contextlib import suppress
from io import BytesIO

from discord.ext import commands
from discord import Embed, utils
import discord
import aiohttp
import pyfsig


class Starboard(commands.Cog):
    """A system that adds messages voted with stars into a channel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener("on_raw_reaction_add")
    @commands.Cog.listener("on_raw_reaction_remove")
    async def update_starboard(self, src):
        """Update starboard."""

        if src.emoji.name != "⭐" or not src.guild_id:
            return

        settings = self.bot.db["settings"][src.guild_id]
        starboard = self.bot.get_channel(settings["starboard_channel"])

        if not starboard:
            return
        if src.message_id == settings.get("starboard_stat_message_id"):
            return
        if not await self.bot.cooldown_check(f"starboard{src.message_id}", 6):
            return

        message = await self.bot.fetch_message(src.channel_id, src.message_id)

        if not self.check_permissions(message, is_starboard=True):
            return

        msgs = await self.fetch_both_messages(message, starboard)

        if not msgs["original"]:
            await self.archive_message(msgs["starboard"])
            return
        if not self.check_permissions(msgs["original"], is_starboard=False):
            return

        # Update stats message for this starboard if needed
        self.bot.loop.create_task(
            self.update_starboard_stats(starboard, settings))

        stars = await self.fetch_stars(msgs)
        starmin = settings["starboard_starmin"]

        if not msgs["starboard"]:
            if stars >= starmin:
                await self.create_message(message, stars, starmin, starboard)
            return

        embed = msgs["starboard"].embeds[0]
        embed_stars = int(embed.footer.text.split()[0])

        if stars == embed_stars:
            return

        # Beware of stars under minimum on deletion, means minimum was changed
        if stars < starmin and (embed_stars >= starmin or stars == 0):
            await msgs["starboard"].delete()
            return

        embed = self.edit_embed_stars(embed, stars, starmin)
        embed = self.edit_embed_attachments(embed)
        await msgs["starboard"].edit(embed=embed)

    def check_permissions(self, message, *, is_starboard):
        """Return whether the bot has enough permissions for this channel."""
        perms = message.channel.permissions_for(message.guild.me)

        if is_starboard:
            return all((
                perms.manage_messages, perms.attach_files,
                perms.read_messages, perms.send_messages))

        return all((
            perms.manage_messages, perms.read_messages, perms.send_messages))

    async def create_message(self, message, stars, starmin, dest):
        """Create a message in the starboard."""
        desc = []
        files = []
        embed = Embed()
        filesize_limit = message.guild.filesize_limit
        expected_formats = (
            "png", "jpg", "jpeg", "gif", "webm", "mp3", "mp4", "mov")

        async def fetch_file(url, file_type=None):
            """Add a file to the list of uploaded files, return a valid URL."""
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            return url

                        data = BytesIO(await resp.read())

                        if data.getbuffer().nbytes >= filesize_limit:
                            return url

                        name = resp.url.path.split("/")[-1]
                        extension = "unknown"

                        if "." in name:
                            name, extension = name.rsplit(".", 1)

                        if extension.lower() not in expected_formats:
                            signatures = (
                                pyfsig.find_matches_for_file_header(
                                    data.read(32)))
                            data.seek(0)

                            for sig in signatures:
                                if sig.file_extension in expected_formats:
                                    extension = sig.file_extension
                                    break

                        if file_type:
                            filename = f"toast_{file_type}.{extension}"
                        else:
                            filename = f"{name}.{extension}"

                        file = discord.File(data, filename=filename)
            except aiohttp.ClientConnectorError:
                return url

            files.append(file)

            if file_type:
                return f"attachment://{filename}"

        if message.is_system():
            embed.set_author(
                name=f"{message.system_content} 🔗",
                icon_url="https://files.catbox.moe/8t9j1y.png",
                url=f"{message.jump_url}#{message.author.id}")
        else:
            author = message.author

            if author.display_name.lower() == author.name.lower():
                author_name = author.display_name
            else:
                author_name = f"{author.display_name} ({author.name})"

            embed.set_author(
                name=f"{author_name} 🔗",
                icon_url=await fetch_file(author.display_avatar.url, "avatar"),
                url=f"{message.jump_url}#{message.author.id}")

        if message.type == discord.MessageType.reply:
            reference = message.reference
            resolved = reference.resolved or await self.bot.fetch_message(
                reference.channel_id, reference.message_id)

            if isinstance(resolved, discord.Message):
                attachment_emoji = self.bot.toast_emoji("attachment")
                author = utils.escape_markdown(resolved.author.name)
                content = utils.remove_markdown(resolved.content)
                content = content.replace("\n", " ")
                reply = self.bot.cut(f"**{author}** {content}", 160)

                if resolved.attachments or resolved.embeds:
                    if not content:
                        reply += f"*Attachment* {attachment_emoji}"
                    else:
                        reply += f" {attachment_emoji}"
            else:
                reply = "*Original message was deleted*"

            replied_emojis = (
                str(self.bot.toast_emoji("replied_to1"))
                + str(self.bot.toast_emoji("replied_to2")))

            desc.append(f"{replied_emojis}{reply}\n")

        for m in [message] + message.message_snapshots:
            if m.content:
                cut_content = self.bot.cut(m.content, 3000)
                if isinstance(m, discord.MessageSnapshot):
                    cut_content = cut_content.replace('\n', '\n> ')
                    desc.append(f"> (Forwarded) {cut_content}")
                else:
                    desc.append(cut_content)

            for attachment in m.attachments:
                desc.append(
                    f"-# [{attachment.filename}]({attachment.url})")

                if attachment.size < filesize_limit:
                    files.append(await attachment.to_file(
                        spoiler=attachment.is_spoiler()))

            for e in m.embeds:
                values = []

                if e.title and e.url:
                    values.append(f"**[{e.title}]({e.url})**")
                elif e.title:
                    values.append(f"**{e.title}**")

                if e.description:
                    # Video embeds like YouTube's have a hidden description
                    # fx/vxtwitter put content in author.name because of that
                    if e.type != "video" or e.author.name == e.description:
                        values.append(e.description)

                if values:
                    if e.author.name == e.description:
                        author = "Embed"  # Refer to previous comment
                    else:
                        author = e.author.name or "Embed"

                    embed.add_field(
                        name=f"\n{author}",
                        value="\n".join(values),
                        inline=False)

                if e.video and "youtube.com" not in e.video.url:
                    await fetch_file(e.video.url)
                elif e.image:
                    await fetch_file(e.image.url)
                elif e.thumbnail:
                    await fetch_file(e.thumbnail.url)

        if desc:
            embed.description = "\n".join(desc)

        embed.set_footer(text=f"? ⭐ (#{message.channel})")

        embed = self.edit_embed_stars(embed, stars, starmin)
        starboard_message = await dest.send(embed=embed, files=files)
        self.bot.db["starboard"][message.id] = starboard_message.id

    def edit_embed_stars(self, embed, stars, starmin):
        """Edit star color and number."""
        colors = None, 0x786938, 0xc8aa4b, 0xffd255, 0xffd255, 0x28d7fa
        calc = int((stars - starmin) / (starmin - 1))
        embed.color = colors[max(0, min(calc, 5))]
        embed.set_footer(text=f"{stars} {embed.footer.text.split(' ', 1)[1]}")

        return embed

    def edit_embed_attachments(self, embed):
        """Ensure the attachments added for the embed stay hidden."""
        def get_extension(url):
            og_name = urlparse(url).path.split("/")[-1]
            return og_name.split(".")[-1].lower()

        if embed.image.url and "toast_image" in embed.image.url:
            ext = get_extension(embed.image.url)
            embed.set_image(url=f"attachment://toast_image.{ext}")

        if embed.thumbnail.url and "toast_thumbnail" in embed.thumbnail.url:
            ext = get_extension(embed.thumbnail.url)
            embed.set_thumbnail(url=f"attachment://toast_thumbnail.{ext}")

        if embed.author.icon_url and "toast_avatar" in embed.author.icon_url:
            ext = get_extension(embed.author.icon_url)
            embed.set_author(
                name=embed.author.name,
                icon_url=f"attachment://toast_avatar.{ext}",
                url=embed.author.url)

        return embed

    async def archive_message(self, message):
        """Edit starboard message to show it's archived."""
        embed = message.embeds[0]

        if not embed.author.name.endswith("🔒"):
            embed.set_author(
                name=embed.author.name[:-1] + "🔒",
                icon_url=embed.author.icon_url,
                url=embed.author.url)

            embed = self.edit_embed_attachments(embed)
            await message.edit(embed=embed)

    async def fetch_stars(self, msgs):
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

    async def fetch_both_messages(self, reference_msg, starboard):
        """Get original/starboard based off contents from the opposite msg."""
        msgs = {"original": None, "starboard": None}
        reference_likely_starboard = (
            reference_msg.author == self.bot.user
            and reference_msg.channel.id == starboard.id)

        if reference_likely_starboard:
            with suppress(ValueError, IndexError):
                og_link = reference_msg.embeds[0].author.url

                msgs["starboard"] = reference_msg
                msgs["original"] = await self.bot.fetch_message_link(og_link)

        if not msgs["starboard"]:
            msg_id = self.bot.db["starboard"].get(reference_msg.id)

            msgs["original"] = reference_msg
            msgs["starboard"] = await self.bot.fetch_message(
                starboard.id, msg_id)

        return msgs

    async def fetch_starboard_stats(self, starboard: discord.TextChannel):
        """Return an embed based on the messages in this starboard."""
        messages = {}
        authors = {}
        message_total = 0
        star_total = 0

        async for m in starboard.history(limit=None, oldest_first=True):
            if m.author != self.bot.user or not m.embeds:
                continue

            with suppress(IndexError, ValueError, AttributeError):
                embed = m.embeds[0]

                author_id = int(embed.author.url.split("#")[1])
                stars = int(embed.footer.text.split(" ")[0])

                if not authors.get(author_id):
                    authors[author_id] = 0

                authors[author_id] += stars
                messages[m] = stars
                star_total += stars
                message_total += 1

        sort = lambda items: items[1]
        messages_sorted = sorted(messages.items(), key=sort, reverse=True)[:20]
        authors_sorted = sorted(authors.items(), key=sort, reverse=True)[:10]
        best_messages = []
        best_authors = []

        if messages_sorted:
            author_ljust = len(str(authors_sorted[0][1]))
            msg_ljust = len(str(messages_sorted[0][1]))

            for author_id, stars in authors_sorted:
                best_authors.append(
                    f"`{str(stars).ljust(author_ljust)} ⭐` <@{author_id}>")

            for m, stars in messages_sorted:
                author_id = int(m.embeds[0].author.url.split("#")[1])

                best_messages.append(
                    f"`{str(stars).ljust(msg_ljust)} ⭐` "
                    f"[Link]({m.jump_url}) - By <@{author_id}>")

        nl = "\n"

        description = (
            f"There are {message_total} starred messages, "
            f"and a total of {star_total} stars added."
            f"\n\n**Best messages**\n"
            f"{nl.join(best_messages) or 'Check next month.'}"
            f"\n\n**Best authors**\n"
            f"{nl.join(best_authors) or 'Check next month.'}")
        footer = (
            "This is updated shortly after the first time "
            "someone stars a post every month.")

        stats_embed = discord.Embed(
            title=f"{starboard.guild.name}'s starboard",
            description=description)
        stats_embed.set_footer(text=footer)

        return stats_embed

    async def update_starboard_stats(self, starboard, settings):
        """Update the stats message for this starboard if needed."""
        stat_last_edited = settings.get("starboard_stat_last_edited")
        current_month_year = datetime.now().strftime("%m/%y")

        if stat_last_edited == current_month_year:
            return

        settings["starboard_stat_last_edited"] = current_month_year

        msg_id = settings.get("starboard_stat_message_id")
        stat_embed = await self.fetch_starboard_stats(starboard)
        stat_message = await self.bot.fetch_message(starboard.id, msg_id)

        if not stat_message:
            stat_message = await starboard.send(embed=stat_embed)
            settings["starboard_stat_message_id"] = stat_message.id

            try:
                await stat_message.pin()
            except discord.HTTPException:
                await starboard.send("can't pin above msg (pin limit?)")
        else:
            await stat_message.edit(embed=stat_embed)


async def setup(bot):
    await bot.add_cog(Starboard(bot))
