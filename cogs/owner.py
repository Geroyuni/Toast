from contextlib import redirect_stdout, suppress
from io import StringIO
import traceback
import textwrap
import sys
import os

from discord import app_commands, Interaction
from discord.ext import commands
import discord

from cogs.settings import CommandsSettings
from cogs.servers import CommandsServers
from cogs.embed import EmbedEditorView

class Context(commands.Context):
    """Modified Context allowing for non-slash command edit/deletion."""
    async def isend(self, content=None, *, dest=None, embed=None, file=None):
        """Do what ctx.send does, while keeping track of the invoker/invoked.

        The *invoker* message is the one that used the command,
        then *invoking* a message by the bot.
        By keeping track, the bot can edit or delete its own messages
        in case someone edits a command.
        """

        invoker = self.channel.id, self.message.id
        invoked = self.bot.invoke_dict.get(invoker)

        # Edit message instead of sending a new one if an invoked exists
        if invoked:
            message = await self.bot.fetch_message(invoked[0], invoked[1])

            if message:
                cant_edit = (
                    file or message.attachments or
                    (dest or self.channel) != message.channel)

                if cant_edit:
                    await message.delete()
                else:
                    edited = await message.edit(content=content, embed=embed)
                    return edited

        sent = await (dest or self).send(content, embed=embed, file=file)
        self.bot.invoke_dict[invoker] = sent.channel.id, sent.id
        return sent

class AskView(discord.ui.View):
    """Provide a button to shutdown the bot anyway."""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Shutdown anyway")
    async def shutdown(self, itx: Interaction, button: discord.ui.Button):
        await itx.response.defer()
        self.stop()

class CommandsOwner(commands.Cog):
    """All of the owner commands."""

    def __init__(self, bot):
        self.bot = bot
        self.say_recent_id = None

    @staticmethod
    def is_owner(itx: Interaction):
        """Check if it's the owner."""
        return itx.user == itx.client.owner

    @staticmethod
    def trim_codeblock(text):
        """Remove the formatting for codeblocks from the text."""
        if text.startswith("`") and text.endswith("`"):
            text = text[3:-3] if text.startswith("```") else text[1:-1]

            if text.startswith("py\n"):
                text = text[3:]

        return text

    async def proceed_after_closing_players(self, itx: Interaction):
        """Return true if allowed to proceed after closing any players."""
        if not self.bot.voice_clients:
            await itx.response.defer(ephemeral=True)
            return True

        guilds = ", ".join(
            p.channel.guild.name for p in self.bot.voice_clients)

        view = AskView()
        await itx.response.send_message(
            f"Players in {guilds} will be shutdown. Are you sure?",
            ephemeral=True,
            view=view)

        timed_out = await view.wait()

        if not timed_out:
            for voice_client in self.bot.voice_clients:
                await voice_client.send_disconnect_log(
                    "because a manual bot restart was triggered. "
                    "Try playing music again in a bit.")
                await voice_client.disconnect()

        return not timed_out

    @app_commands.check(is_owner)
    @app_commands.command()
    async def owner(
        self,
        itx: Interaction,
        say: str = None,
        restart: str = None,
        sync: str = None,
        shutdown: bool = False,
        settings: str = None,
        log: str = None,
        embed: str = None,
        avatar: discord.Attachment = None,
        invite: bool = False,
        recover_starboard_db: bool = False
    ):
        """Bot owner command 🤔. I can't hide this, blame Discord"""
        if say:
            return await self.say(itx, say)
        if restart:
            return await self.restart(itx, restart)
        if sync:
            return await self.sync(itx, sync)
        if shutdown:
            return await self.shutdown(itx)
        if settings:
            return await self.settings(itx, settings)
        if log:
            return await self.log(itx, log)
        if embed:
            return await self.embed(itx, embed)
        if avatar:
            return await self.avatar(itx, avatar)
        if invite:
            return await self.invite(itx)
        if recover_starboard_db:
            return await self.recover_starboard_db(itx)

    async def say(self, itx: Interaction, words: str):
        """Make toast speak."""
        await itx.channel.send(words)
        await itx.response.send_message("sent", ephemeral=True)

    async def restart(self, itx: Interaction, cog: str):
        """Restart specific cog of the bot or all of it."""
        if cog in ("music", "full"):
            if not await self.proceed_after_closing_players(itx):
                return
        else:
            await itx.response.defer(ephemeral=True)

        if cog == "full":
            await itx.followup.send("(restarting)")
            self.bot.save_db()
            os.execl(sys.executable, sys.executable, *sys.argv)

        try:
            await self.bot.reload_extension(f"cogs.{cog}")
            await itx.followup.send(f"Reloaded 'cogs.{cog}'", ephemeral=True)
        except Exception as e:
            await itx.followup.send(e)

    async def sync(self, itx: Interaction, guild_id: str):
        """Sync changes that should be reflected on the Discord UI."""
        if guild_id == "global":
            await self.bot.tree.sync()
        else:
            await self.bot.tree.sync(guild=discord.Object(id=int(guild_id)))

        await itx.response.send_message("synced.", ephemeral=True)

    async def shutdown(self, itx: Interaction):
        """Shutdown the bot properly."""
        if not await self.proceed_after_closing_players(itx):
            return

        await itx.followup.send("(shutting down)", ephemeral=True)
        await self.bot.close()

    async def settings(self, itx: Interaction, guild_id: str):
        """Summon settings for a server the bot is in."""
        await CommandsSettings.summon_settings(itx, int(guild_id))

    async def log(self, itx: Interaction, guild_id: str):
        """Summon logs for a server the bot is in."""
        await CommandsServers.summon_log(itx, int(guild_id))

    async def embed(self, itx: Interaction, message_url: str):
        message = await self.bot.fetch_message_link(message_url)
        view = EmbedEditorView(
            message.embeds[0], message_to_edit=message, show_sender=False)

        await itx.response.send_message(
            embed=message.embeds[0], view=view, ephemeral=True)

    async def avatar(self, itx: Interaction, image: discord.Attachment):
        """Change the bot's avatar."""
        await self.bot.user.edit(image.read())
        await itx.response.send_message("changed", ephemeral=True)

    async def invite(self, itx: Interaction):
        """Send a link to invite the bot to a server."""
        await itx.response.send_message(ephemeral=True, content=
            f"<{discord.utils.oauth_url(self.bot.user.id)}>")

    async def recover_starboard_db(self, itx: Interaction):
        """If all goes to shit, recover the ids from starboard posts."""
        ids_added = 0

        for guild_settings in self.bot.db["settings"].values():
            starboard = self.bot.get_channel(
                guild_settings.get("starboard_channel"))

            if not starboard:
                continue

            async for m in starboard.history(limit=None):
                if m.author != self.bot.user or not m.embeds:
                    continue

                with suppress(ValueError, IndexError, AttributeError):
                    embed = m.embeds[0]
                    og_link = embed.author.url
                    ids = og_link.split("#")[0].split("/")[-2:]

                    self.bot.db["starboard"][ids[1]] = m.id
                    ids_added += 1

        await itx.response.send_message(ephemeral=True, content=
            f"{ids_added} message IDs added into db")

    @owner.autocomplete("restart")
    async def restart_autocomplete(self, itx: Interaction, current: str):
        names = ["full"]
        names.extend(self.bot.cog_file_names)

        return [
            app_commands.Choice(name=n, value=n)
            for n in names if current.lower() in n.lower()]

    @owner.autocomplete("sync")
    async def sync_autocomplete(self, itx: Interaction, current: str):
        if itx.user != self.bot.owner:
            return []  # don't leak the bot guild names for no reason

        guilds = await self.guild_autocomplete(itx, current)

        if current.lower() in "global":
            guilds.insert(
                0, app_commands.Choice(name="global", value="global"))

        return guilds

    @owner.autocomplete("settings")
    @owner.autocomplete("log")
    async def guild_autocomplete(self, itx: Interaction, current: str):
        if itx.user != self.bot.owner:
            return []  # don't leak the bot guild names for no reason

        guilds = [
            app_commands.Choice(name=g.name, value=str(g.id))
            for g in self.bot.guilds if current.lower() in g.name.lower()]

        guilds.sort(key=lambda i: i.name.lower())
        return guilds

    @commands.is_owner()
    @commands.command()
    async def python(self, ctx, *, body):
        """Run the given python code inside the bot. Non-slash command."""
        redirected_out = StringIO()
        env = {"bot": self.bot, "ctx": ctx, "discord": discord}
        env.update(globals())
        body = self.trim_codeblock(body)

        if "\n" not in body and not body.startswith("print("):
            body = f"print({body})"

        try:
            with redirect_stdout(redirected_out):
                exec(f"async def func():\n{textwrap.indent(body, '  ')}", env)
                await env["func"]()
        except Exception:
            outputs = redirected_out.getvalue(), traceback.format_exc()
        else:
            outputs = redirected_out.getvalue(), ""

            if "ctx.isend(" in body:
                return

        msg = "\n".join([f"```{i}```" for i in outputs if i.strip()])

        if len(msg) > 4000:
            await ctx.isend("too long; printing to console")
            ctx.bot.print("\n".join(outputs), color="BLUE")
        elif len(msg) > 2000:
            embed = discord.Embed(description=msg, color=0x2f3136)
            await ctx.isend(embed=embed)
        else:
            await ctx.isend(msg or "`empty result`")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Like the default on_message, but using my custom Context."""
        if message.author.bot:
            return

        ctx = await self.bot.get_context(message, cls=Context)
        await self.bot.invoke(ctx)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        """Allow for editing non-slash commands via editing messages."""
        if before.clean_content == after.clean_content or after.author.bot:
            return

        # Remove bot reactions
        for reaction in after.reactions:
            async for u in reaction.users():
                if u == self.bot.user:
                    await reaction.remove(u)

        invoker = (after.channel.id, after.id)
        invoked = self.bot.invoke_dict.get(invoker)
        timestamp = None

        if invoked:
            invoked_msg = await self.bot.fetch_message(invoked[0], invoked[1])

            if invoked_msg:
                timestamp = invoked_msg.edited_at or "unedited"

        ctx = await self.bot.get_context(after, cls=Context)
        await self.bot.invoke(ctx)

        if timestamp:
            invoked_msg = await self.bot.fetch_message(invoked[0], invoked[1])

            if invoked_msg:
                if (invoked_msg.edited_at or "unedited") == timestamp:
                    await invoked_msg.edit(content="(empty)", embed=None)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        """Allow for deleting non-slash commands when deleting messages."""
        invoker = message.channel.id, message.id
        invoked = self.bot.invoke_dict.pop(invoker, None)

        if invoked:
            message = await self.bot.fetch_message(invoked[0], invoked[1])

            if message:
                await message.delete()


async def setup(bot):
    await bot.add_cog(CommandsOwner(bot))
