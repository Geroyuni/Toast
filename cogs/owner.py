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


class AskView(discord.ui.View):
    """Provide a button to shutdown the bot anyway."""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="Shutdown anyway")
    async def shutdown(self, itx: Interaction, button: discord.ui.Button):
        await itx.response.defer()
        self.stop()


class EditCodeView(discord.ui.View):
    """View for editing code in Python command."""
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.code = None
        self.bot = bot

    @discord.ui.button(label="Edit code", style=discord.ButtonStyle.blurple)
    async def edit_code(self, itx: Interaction, button: discord.ui.Button):
        await itx.response.send_modal(CodeModal(self))

    async def execute_code(self, itx: Interaction, code):
        redirected_out = StringIO()
        env = {"bot": self.bot, "itx": itx, "discord": discord}
        env.update(globals())

        try:
            with redirect_stdout(redirected_out):
                exec(f"async def func():\n{textwrap.indent(code, '  ')}", env)
                await env["func"]()
        except Exception:
            outputs = redirected_out.getvalue(), traceback.format_exc()
        else:
            outputs = redirected_out.getvalue(), ""

        result = "\n".join([f"```\n{i}```" for i in outputs if i.strip()])

        if len(result) > 4000:
            content = "too long; printing to console"
            embed = None
            self.bot.print("\n".join(outputs), color="BLUE")
        elif len(result) > 2000:
            content = None
            embed = discord.Embed(description=result, color=0x2b2d31)
        else:
            content = result or "`empty result`"
            embed = None

        return content, embed

    async def update(self, itx: Interaction, code):
        self.code = code
        content, embed = await self.execute_code(itx, code)
        await itx.response.edit_message(content=content, embed=embed)

    async def new_message(self, itx: Interaction, code):
        await itx.response.defer(ephemeral=True)

        if "\n" not in code and not code.startswith("print("):
            code = f"print({code})"

        self.code = code
        content, embed = await self.execute_code(itx, code)

        await itx.followup.send(
            content=content, embed=embed, view=self, ephemeral=True)


class CodeModal(discord.ui.Modal, title="Edit code"):
    def __init__(self, view):
        super().__init__()
        self.view = view

        self.add_item(discord.ui.TextInput(
            label="Code",
            default=self.view.code,
            placeholder='print("hello world")',
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=True))

    async def on_submit(self, itx: Interaction):
        code = self.children[0].value
        await self.view.update(itx, code)


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
    @app_commands.allowed_installs(guilds=False, users=True)
    async def owner(
        self,
        itx: Interaction,
        say: str = None,
        restart: str = None,
        sync: str = None,
        shutdown: bool = False,
        settings: str = None,
        embed: str = None,
        avatar: discord.Attachment = None,
        invite: bool = False,
        python: str = None,
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
        if embed:
            return await self.embed(itx, embed)
        if avatar:
            return await self.avatar(itx, avatar)
        if invite:
            return await self.invite(itx)
        if python:
            return await self.python(itx, python)
        if recover_starboard_db:
            return await self.recover_starboard_db(itx)

    async def say(self, itx: Interaction, words: str):
        """Make toast speak."""
        try:
            await itx.channel.send(words)
            await itx.response.send_message("sent", ephemeral=True)
        except discord.Forbidden:
            await itx.response.send_message(words)

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

    async def embed(self, itx: Interaction, message_url: str):
        message = await self.bot.fetch_message_link(message_url)
        view = EmbedEditorView(
            message.embeds[0], message_to_edit=message, show_sender=False)

        await itx.response.send_message(
            embed=message.embeds[0], view=view, ephemeral=True)

    async def avatar(self, itx: Interaction, image: discord.Attachment):
        """Change the bot's avatar."""
        await self.bot.user.edit(avatar=await image.read())
        await itx.response.send_message("changed", ephemeral=True)

    async def invite(self, itx: Interaction):
        """Send a link to invite the bot to a server."""
        await itx.response.send_message(ephemeral=True, content=
            f"<{discord.utils.oauth_url(self.bot.user.id)}>")

    async def python(self, itx: Interaction, code: str):
        """Open up a place to type Python commands."""
        view = EditCodeView(self.bot)
        await view.new_message(itx, code)

    async def recover_starboard_db(self, itx: Interaction):
        """If all goes to shit, recover the ids from starboard posts."""
        await itx.response.defer(ephemeral=True)

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

                    self.bot.db["starboard"][int(ids[1])] = m.id
                    ids_added += 1

        await itx.followup.send(f"{ids_added} message IDs added into db")

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


async def setup(bot):
    await bot.add_cog(CommandsOwner(bot))
