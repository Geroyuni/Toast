from contextlib import suppress

from discord import app_commands, Interaction
from discord.ext import commands
import discord

class CommandsServers(commands.Cog):
    """Commands that need to be used in a guild."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.guild_only()
    @app_commands.command()
    @app_commands.rename(input_value="hex_value")
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def color(self, itx: Interaction, input_value: str):
        """Change your username color to a specific hexadecimal value.

        :param input_value: The hex value, e.g. #ff9030. #000000 removes colors
        """
        if not self.bot.db["settings"][itx.guild.id]["color_command"]:
            await itx.response.send_message(
                "this command isn't enabled in this server. "
                "Someone with manage server permissions can enable "
                "it in /settings",
                ephemeral=True)

            return

        try:
            stripped_value = input_value.strip("#").removeprefix("0x")[:6]
            int_value = max(0, min(0xffffff, int(stripped_value, 16)))
        except ValueError:
            await itx.response.send_message(ephemeral=True, content=
                "invalid hex value. If you need a color picker, "
                "see <https://rgbacolorpicker.com/hex-color-picker>")
            return

        author_colors = []
        for role in itx.user.roles:
            if role.name.startswith("#") and len(role.name) == 7:
                with suppress(ValueError):
                    int(role.name[1:], 16)
                    author_colors.append(role)

        await itx.user.remove_roles(
            *author_colors, reason=self.bot.fmt_command(itx))

        if int_value != 0:
            hex_value = f"#{hex(int_value)[2:].zfill(6)}"

            chosen_role = (
                discord.utils.get(itx.guild.roles, name=hex_value)
                or await itx.guild.create_role(name=hex_value, color=int_value)
            )

            await itx.user.add_roles(
                chosen_role, reason=self.bot.fmt_command(itx))

            await itx.response.send_message(
                f"you've been given the {chosen_role.mention} color",
                ephemeral=True)
        else:
            await itx.response.send_message(
                "removed your color (wanted black? try `/color 1`)",
                ephemeral=True)


        guild_color_roles = []
        for role in itx.guild.roles:
            if role.name.startswith("#") and len(role.name) == 7:
                with suppress(ValueError):
                    int(role.name[1:], 16)
                    guild_color_roles.append(role)

        for role in guild_color_roles:
            if not role.members:
                await role.delete(reason="cleaning up unused color role")

    @app_commands.checks.bot_has_permissions(manage_roles=True)
    @app_commands.guild_only()
    @app_commands.command()
    @app_commands.rename(role_id="name")
    async def roles(self, itx: Interaction, role_id: str):
        """Give or remove a role from yourself. The role list is
        configured by this server.

        :param role_id: The role to give you or take away from you
        """
        role_ids = self.bot.db["settings"][itx.guild_id]["editable_roles"]
        if not role_ids:
            await itx.response.send_message(ephemeral=True, content=
                "this command isn't enabled in this server. "
                "Someone with manage server permissions can enable "
                "it with the settings command")

            return

        role_id = int(role_id)

        if role_id not in role_ids:
            await itx.response.send_message("invalid role", ephemeral=True)
            return

        role = itx.guild.get_role(role_id)

        if role in itx.user.roles:
            await itx.user.remove_roles(role, reason=self.bot.fmt_command(itx))
            await itx.response.send_message(
                f"removed {role.mention} from your roles", ephemeral=True)
        else:
            await itx.user.add_roles(role, reason=self.bot.fmt_command(itx))
            await itx.response.send_message(
                f"added {role.mention} to your roles", ephemeral=True)

    @roles.autocomplete("role_id")
    async def role_autocomplete(self, itx: Interaction, current: str):
        role_ids = self.bot.db["settings"][itx.guild_id]["editable_roles"]

        if not role_ids:
            return []

        roles = [itx.guild.get_role(r) for r in role_ids]
        roles = list(filter(None, roles))[:24]

        choices = []

        for r in roles:
            if current.lower() in r.name.lower():
                if r in itx.user.roles:
                    have = " - ✅ You have this role"
                else:
                    have = ""

                choices.append(app_commands.Choice(
                    name=f"{r.name}{have}", value=str(r.id)))

        return choices

async def setup(bot):
    await bot.add_cog(CommandsServers(bot))
