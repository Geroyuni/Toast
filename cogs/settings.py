from discord import Interaction, app_commands
from discord.ext import commands
import discord

class SettingsView(discord.ui.View):
    def __init__(self, bot, guild_id):
        self.guild = bot.get_guild(guild_id)
        self.settings = bot.db["settings"][guild_id]
        super().__init__(timeout=None)

        self.add_item(TypeSelect())

class TypeSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Choose what setting you wanna change...")

        self.add_option(
            label="Enable /color command", value="color_command",
            description="Lets people change their name color to anything.")
        self.add_option(
            label="Roles used in the /roles command", value="editable_roles",
            description=(
                "Roles people can assign themselves. "
                "De-select all to disable."))
        self.add_option(
            label="Starboard channel", value="starboard_channel",
            description=(
                "The channel the bot posts messages to. "
                "De-select to disable."))
        self.add_option(
            label="Starboard minimum stars", value="starboard_starmin",
            description=(
                "Minimum star reactions to get into the starboard."))
        self.add_option(
            label="Dynamic voice channel", value="dynamic_voicechannel",
            description=(
                "Ensure an empty voice chat always exists. "
                "De-select to disable."))
        self.add_option(
            label="Dynamic voice channel name",
            value="dynamic_voicechannel_text",
            description=(
                "Name of the dynamic voice channels that are made."))

    async def callback(self, itx: Interaction):
        setting = self.values[0]

        if len(self.view.children) > 1:
            self.view.remove_item(self.view.children[-1])

        for option in self.options:
            if option.value == setting:
                option.default = True
            else:
                option.default = False

        if setting == "color_command":
            item = ColorCommandSelect(self.view)
        elif setting == "editable_roles":
            item = EditableRolesSelect(self.view)
        elif setting == "starboard_channel":
            item = StarboardChannelSelect(self.view)
        elif setting == "starboard_starmin":
            item = StarboardStarminSelect(self.view)
        elif setting == "dynamic_voicechannel":
            item = DynamicVoicechannelSelect(self.view)
        elif setting == "dynamic_voicechannel_text":
            modal = DynamicVoicechannelTextModal(self.view)
            await itx.response.send_modal(modal)
            return

        self.view.add_item(item)

        await itx.response.edit_message(view=self.view)

class ColorCommandSelect(discord.ui.Select):
    def __init__(self, view: discord.ui.View):
        super().__init__(custom_id="color_command")

        setting = view.settings[self.custom_id]

        self.add_option(
            label="True", value="True",
            default=setting)
        self.add_option(
            label="False", value="False",
            default=not setting)

    async def callback(self, itx: Interaction):
        value = True if self.values[0] == "True" else False
        self.view.settings[self.custom_id] = value
        await itx.response.defer()


class EditableRolesSelect(discord.ui.Select):
    def __init__(self, view: discord.ui.View):
        if view.guild.roles == 1:
            super().__init__(
                placeholder="Your guild has no roles",
                custom_id="editable_roles",
                disabled=True)
            return

        super().__init__(
            placeholder="No roles selected (/roles disabled)",
            custom_id="editable_roles",
            min_values=0,
            max_values=len(view.guild.roles) - 1)

        setting = view.settings[self.custom_id]

        for role in reversed(view.guild.roles):
            if role.name == "@everyone":
                continue

            self.add_option(
                label=f"@{role.name}",
                value=str(role.id),
                default=role.id in setting)

    async def callback(self, itx: Interaction):
        self.view.settings[self.custom_id] = [int(i) for i in self.values]
        await itx.response.defer()

class StarboardChannelSelect(discord.ui.Select):
    def __init__(self, view: discord.ui.View):
        super().__init__(
            placeholder="No channel selected (starboard disabled)",
            custom_id="starboard_channel",
            min_values=0)

        setting = view.settings[self.custom_id]

        for channel in view.guild.text_channels:
            self.add_option(
                label=f"#{channel.name}", value=str(channel.id),
                default=channel.id == setting)

    async def callback(self, itx: Interaction):
        value = int(self.values[0]) if self.values else None
        self.view.settings[self.custom_id] = value
        await itx.response.defer()

class StarboardStarminSelect(discord.ui.Select):
    def __init__(self, view: discord.ui.View):
        super().__init__(custom_id="starboard_starmin")

        setting = view.settings[self.custom_id]

        for i in range(2, 9):
            self.add_option(
                label=str(i), value=str(i),
                default=i == setting)

    async def callback(self, itx: Interaction):
        self.view.settings[self.custom_id] = int(self.values[0])
        await itx.response.defer()

class DynamicVoicechannelSelect(discord.ui.Select):
    def __init__(self, view: discord.ui.View):
        super().__init__(
            placeholder="No category selected (dynamic voice chat disabled)",
            custom_id="dynamic_voicechannel",
            min_values=0)

        setting = view.settings[self.custom_id]

        self.add_option(
            label=f"Use non-category part of the server", value="no_category",
            default="no_category" == setting)

        for channel in view.guild.categories:
            self.add_option(
                label=f"{channel.name}", value=str(channel.id),
                default=channel.id == setting)

    async def callback(self, itx: Interaction):
        value = self.values[0] if self.values else None
        value = value if value in ("no_category", None) else int(value)
        self.view.settings[self.custom_id] = value
        await itx.response.defer()

class DynamicVoicechannelTextModal(discord.ui.Modal, title="Settings"):
    def __init__(self, view: discord.ui.View):
        super().__init__(custom_id="dynamic_voicechannel_text")
        self.view = view
        setting = view.settings[self.custom_id]

        self.add_item(discord.ui.TextInput(
            label="Name of the dynamic voice channels",
            custom_id="dynamic_voicechannel_text",
            placeholder="Voice",
            required=True,
            default=setting))

    async def on_submit(self, itx: Interaction):
        self.view.settings[self.custom_id] = self.children[0].value
        await itx.response.defer()

class CommandsSettings(commands.Cog):
    """Allow servers to reconfigure parts of Toast."""

    def __init__(self, bot):
        self.bot = bot
        self.default_settings = {
            "color_command": False,
            "editable_roles": [],
            "starboard_channel": None,
            "starboard_starmin": 2,
            "dynamic_voicechannel": None,
            "dynamic_voicechannel_text": "Voice"}

    @staticmethod
    async def summon_settings(itx: Interaction, guild_id: int):
        await itx.response.send_message(
            "**Bot permissions to take note of**\n"
            "• Roles and Color commands: Manage roles\n"
            "• Starboard: Manage messages (all channels; prevents "
            "self-starring), read/send/attach files (starboard channel)\n"
            "• Dynamic voice channel: Manage channels and Manage "
            "permissions (on chosen category)\n"
            "• Alter command visibility or users that can use commands in "
            "Server settings > Integrations > Toast\n\n"
            "**Modify settings**\n"
            "Select any settings you want to change below. "
            "You can dismiss this message when you're done.\n\n",
            view=SettingsView(itx.client, guild_id),
            ephemeral=True)

    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.command()
    async def settings(self, itx: Interaction):
        """Edit the bot settings for this server."""
        await self.summon_settings(itx, itx.guild_id)

    @commands.Cog.listener()
    async def on_ready(self):
        """Prepare default settings for guilds not in data on start."""
        for guild in self.bot.guilds:
            if guild.id not in self.bot.db["logs"]:
                self.bot.db["logs"][guild.id] = []

            if guild.id not in self.bot.db["settings"]:
                setting = self.default_settings.copy()
                self.bot.db["settings"][guild.id] = setting
                continue

            for k in self.default_settings.copy():
                if k not in self.bot.db["settings"][guild.id]:
                    setting = self.default_settings[k]
                    self.bot.db["settings"][guild.id][k] = setting

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        """Prepare default settings for new guilds."""
        self.bot.db["settings"][guild.id] = self.default_settings.copy()
        self.bot.db["logs"][guild.id] = []

    @commands.Cog.listener()
    async def on_guild_leave(self, guild):
        """Remove guild data if the bot is removed from it."""
        self.bot.db["settings"].pop(guild.id)
        self.bot.db["logs"].pop(guild.id)


async def setup(bot):
    await bot.add_cog(CommandsSettings(bot))
