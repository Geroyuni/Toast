from contextlib import suppress

from discord import app_commands, Interaction
from discord.ext import commands
import discord

class CommandsServers(commands.Cog):
    """Commands that need to be used in a guild."""

    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    async def summon_log(itx: Interaction, guild_id: int):
        if not itx.client.db["logs"].get(guild_id):
            await itx.response.send_message("nothing here yet", ephemeral=True)
            return

        events = (
            "Edited messages are formatted as: ~~`removed content`~~ and "
            "**`added content`**. Keep in mind deleted messages can be "
            "deleted by anyone with permission. Cross check with the "
            "Discord audit log where needed.\n\n")

        for event in reversed(itx.client.db["logs"][guild_id]):
            event = "> " + event.replace("\n", "\n> ")

            if len(events + event) < 4096:
                events += f"{event}\n\n"

        embed = discord.Embed(title="Log", description=events)
        await itx.response.send_message(embed=embed, ephemeral=True)

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
                f"removed your color (wanted black? try `/color 1`)",
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

    @app_commands.default_permissions(create_instant_invite=True)
    @app_commands.checks.bot_has_permissions(create_instant_invite=True)
    @app_commands.guild_only()
    @app_commands.command()
    async def invite(
        self, itx: Interaction, max_uses: int, max_age_days: float
    ):
        """Create an invite link with specific settings more quickly.

        :param max_uses: Number of uses it can have (0 means unlimited)
        :param max_age_days: How many days before it expires (0 means never)
        """
        invite = await itx.channel.create_invite(
            max_uses=max_uses,
            max_age=int(max_age_days * 86400),
            reason=self.bot.fmt_command(itx))

        await itx.response.send_message(ephemeral=True, content=
            f"Created {invite.url} (max uses: {max_uses or 'unlimited'}, "
            f"expires in days: {max_age_days or 'never'})")

    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.command()
    async def log(self, itx: Interaction):
        """Show moderation logs not available on Discord's audit log, like
        message edit/deletes or joins."""
        await self.summon_log(itx, itx.guild_id)

async def setup(bot):
    await bot.add_cog(CommandsServers(bot))
