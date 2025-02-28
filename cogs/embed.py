from contextlib import suppress
from ast import literal_eval
import asyncio

from discord import app_commands, Interaction
from discord.ext import commands
import discord


class EmbedEditorView(discord.ui.View):
    def __init__(self, embed, *, message_to_edit=None, show_sender=True):
        super().__init__(timeout=None)

        self.add_item(EmbedSelect(embed))
        self.add_item(PostButton(message_to_edit, show_sender))
        self.add_item(CancelButton())

        self.select = self.children[0]


class EmbedSelect(discord.ui.Select):
    def __init__(self, embed):
        super().__init__(placeholder="Select a section to edit...")

        self.add_option(label="Title, description and color", value="main")
        self.add_option(label="Image and thumbnail", value="images")
        self.add_option(label="Author", value="author")
        self.add_option(label="Footer", value="footer")
        self.add_option(label="Raw dictionary data", value="raw")
        self.add_option(label="New field", value="field_new")

        self.embed = embed
        self.update_fields()

    def update_fields(self):
        self.options = self.options[:6]

        for i, field in enumerate(self.embed.fields):
            self.append_option(discord.SelectOption(
                label=f"Field {i+1}",
                value=f"field_{i}",
                description=field.name))

    async def update(self, itx: discord.Interaction):
        self.update_fields()

        await itx.response.edit_message(
            content=None, embed=self.embed, view=self.view)

    async def callback(self, interaction):
        selected = self.values[0]

        if selected == "main":
            modal = MainEmbedModal(self)
        elif selected == "images":
            modal = ImagesEmbedModal(self)
        elif selected == "author":
            modal = AuthorEmbedModal(self)
        elif selected == "footer":
            modal = FooterEmbedModal(self)
        elif selected == "raw":
            modal = RawEmbedModal(self)
        elif selected == "field_new":
            modal = FieldEmbedModal(self)
        elif selected.startswith("field_"):
            modal = FieldEmbedModal(self, int(selected[6:]))

        await interaction.response.send_modal(modal)


class PostButton(discord.ui.Button):
    def __init__(self, message_to_edit=None, show_sender=True):
        super().__init__(
            label="Post embed" if not message_to_edit else "Edit embed",
            style=discord.ButtonStyle.blurple)

        self.message_to_edit = message_to_edit
        self.show_sender = show_sender

    async def callback(self, itx: discord.Interaction):
        if self.message_to_edit:
            await self.message_to_edit.edit(embed=self.view.select.embed)
            await itx.response.edit_message(
                embed=None, view=None, content="Edited the embed.")

            self.view.stop()
            return

        if self.show_sender:
            await itx.channel.send(
                f"{itx.user.mention} used </embed:1023847929670283264>:",
                embed=self.view.select.embed)
        else:
            await itx.channel.send(embed=self.view.select.embed)

        await itx.response.edit_message(embed=None, view=None, content=(
            "Sent the embed. You can clone (or edit, if you have 'Manage "
            "Messages' permission) the sent embed later by **right-clicking "
            "it > Apps > Edit embed**."))

        self.view.stop()


class CancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel")

    async def callback(self, itx: discord.Interaction):
        await itx.response.edit_message(
            content="Canceled. You can dismiss the message below",
            embed=None,
            view=None)

        self.view.stop()


class MainEmbedModal(discord.ui.Modal, title="Title, description and color"):
    def __init__(self, select):
        super().__init__()
        self.select = select

        if select.embed.color:
            embed_color = f"#{hex(select.embed.color.value)[2:].zfill(6)}"
        else:
            embed_color = None

        self.add_item(discord.ui.TextInput(
            label="Title",
            default=select.embed.title,
            placeholder="Example title",
            max_length=256,
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Title URL",
            default=select.embed.url,
            placeholder="https://discord.com",
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Embed color",
            default=embed_color,
            placeholder="#ff9030",
            min_length=6,
            max_length=7,
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Description",
            default=select.embed.description,
            placeholder="This is an example description.",
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=False))

    async def on_submit(self, itx: Interaction):
        title, url, color, description = [i.value for i in self.children]

        self.select.embed.title = title
        self.select.embed.url = url
        self.select.embed.description = description

        if color:
            with suppress(ValueError):
                stripped_value = self.children[2].value.strip("#")
                int_value = max(0, min(0xffffff, int(stripped_value, 16)))
                self.select.embed.color = int_value
        else:
            self.select.embed.color = None

        await self.select.update(itx)


class ImagesEmbedModal(discord.ui.Modal, title="Image and thumbnail"):
    def __init__(self, select):
        super().__init__()
        self.select = select

        self.add_item(discord.ui.TextInput(
            label="Image URL",
            default=select.embed.image.url,
            placeholder="https://example.com/example.png",
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Thumbnail URL",
            default=select.embed.thumbnail.url,
            placeholder="https://example.com/smaller_example.png",
            required=False))

    async def on_submit(self, itx: Interaction):
        image_url, thumbnail_url = [i.value for i in self.children]

        self.select.embed.set_image(url=image_url)
        self.select.embed.set_thumbnail(url=thumbnail_url)

        await self.select.update(itx)


class AuthorEmbedModal(discord.ui.Modal, title="Author"):
    def __init__(self, select):
        super().__init__()
        self.select = select

        self.add_item(discord.ui.TextInput(
            label="Author name",
            default=select.embed.author.name,
            placeholder="John",
            max_length=256,
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Author URL",
            default=select.embed.author.url,
            placeholder="https://discord.com",
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Author icon URL",
            default=select.embed.author.icon_url,
            placeholder="https://example.com/example.png",
            required=False))

    async def on_submit(self, itx: Interaction):
        name, url, icon_url = [i.value for i in self.children]

        self.select.embed.set_author(name=name, url=url, icon_url=icon_url)
        await self.select.update(itx)


class FooterEmbedModal(discord.ui.Modal, title="Footer"):
    def __init__(self, select):
        super().__init__()
        self.select = select

        self.add_item(discord.ui.TextInput(
            label="Footer text",
            default=select.embed.footer.text,
            placeholder="More beans required.",
            max_length=2048,
            style=discord.TextStyle.paragraph,
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Footer icon URL",
            default=select.embed.footer.icon_url,
            placeholder="https://example.com/example.png",
            required=False))

    async def on_submit(self, itx: Interaction):
        text, icon_url = [i.value for i in self.children]

        self.select.embed.set_footer(text=text, icon_url=icon_url)
        await self.select.update(itx)


class FieldEmbedModal(discord.ui.Modal, title="Field"):
    def __init__(self, select, index=None):
        super().__init__()
        self.select = select
        self.index = index

        field = select.embed.fields[index] if index is not None else None

        self.add_item(discord.ui.TextInput(
            label="Field name",
            default=field.name if field else None,
            placeholder="Cool field name",
            max_length=256,
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Field value",
            default=field.value if field else None,
            placeholder="This is a cool field description.",
            style=discord.TextStyle.paragraph,
            max_length=1024,
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Display in-line",
            default=str(field.inline) if field else "False",
            placeholder="True or False (false if empty)",
            max_length=5,
            required=False))

        self.add_item(discord.ui.TextInput(
            label="Position (leave unmodified if unsure)",
            default=index + 1 if field else None,
            placeholder="1-25, or empty to add to bottom",
            max_length=2,
            required=False))

    async def on_submit(self, itx: Interaction):
        name, value, inline, position = [i.value for i in self.children]

        if not name and not value:
            if self.index is None:
                await itx.response.defer()
                return

            self.select.embed.remove_field(self.index)
        elif self.index is None:
            if not position:
                self.select.embed.add_field(
                    name=name,
                    value=value,
                    inline=True if inline.lower() == "true" else False)
            else:
                self.select.embed.insert_field_at(
                    max(int(position), 1) - 1,
                    name=name,
                    value=value,
                    inline=True if inline.lower() == "true" else False)
        else:
            if position == self.index - 1:
                self.select.embed.set_field_at(
                    self.index,
                    name=name,
                    value=value,
                    inline=True if inline.lower() == "true" else False)
            else:
                self.select.embed.remove_field(self.index)
                self.select.embed.insert_field_at(
                    max(int(position), 1) - 1,
                    name=name,
                    value=value,
                    inline=True if inline.lower() == "true" else False)

        await self.select.update(itx)


class RawEmbedModal(discord.ui.Modal, title="Raw dictionary data"):
    def __init__(self, select):
        super().__init__()
        self.select = select

        embed_dict = str(self.select.embed.to_dict())

        self.add_item(discord.ui.TextInput(
            label="Data",
            default=embed_dict if len(embed_dict) <= 4000 else "(too long)",
            placeholder="{'title': 'Example title'}",
            style=discord.TextStyle.paragraph,
            max_length=4000))

    async def on_submit(self, itx: Interaction):
        embed_dict = self.children[0].value

        if embed_dict == "(too long)":
            await itx.response.defer()
            return

        embed_dict = literal_eval(embed_dict)

        self.select.embed = discord.Embed.from_dict(embed_dict)
        await self.select.update(itx)


class EmbedEditor(commands.Cog):
    """Allows people to create and edit embeds easily."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.menu = app_commands.ContextMenu(
            name="Edit embed", callback=self.edit_embed)
        self.bot.tree.add_command(self.menu)

    def check_permission(self, itx: Interaction):
        return itx.user == self.bot.owner or (
            itx.guild
            and itx.channel.permissions_for(itx.user).manage_messages)

    @app_commands.command()
    @app_commands.allowed_installs(guilds=True, users=True)
    async def embed(self, itx: Interaction, raw_data: str = None):
        """Summon a Discord embed editor. If you have 'Manage messages' perm,
        posting will hide you sent it.

        :param raw_data: Start the embed with dictionary data (optional)"""
        if raw_data:
            try:
                embed = discord.Embed.from_dict(literal_eval(raw_data))

            except (ValueError, SyntaxError, AttributeError) as e:
                await itx.response.send_message(
                    f"The given raw_data caused an exception ({e})",
                    ephemeral=True)
                return
        else:
            embed = discord.Embed(title="Example title")

        can_be_hidden = self.check_permission(itx)
        view = EmbedEditorView(embed, show_sender=not can_be_hidden)
        await itx.response.send_message(embed=embed, view=view, ephemeral=True)

    async def edit_embed(self, itx: Interaction, message: discord.Message):
        """Edit the embed in this message."""
        if itx.guild:
            guild_settings = self.bot.db["settings"][itx.guild_id]
            star_id = guild_settings["starboard_channel"]

            if itx.channel_id == star_id:
                await itx.response.send_message(
                    "Editing embeds is blocked on starboard", ephemeral=True)
                return

        if not message.embeds:
            await itx.response.send_message(
                "this message has no embed", ephemeral=True)
            return

        # This gives you the opportunity to jump to the most present messages
        # on Discord. If you're far too up in the channel, the ephemeral
        # message generated by the bot gets instantly removed.
        await asyncio.sleep(1)

        embed = message.embeds[0]
        can_edit_toast_message = self.check_permission(itx)
        view = EmbedEditorView(
            embed,
            message_to_edit=message if can_edit_toast_message else None,
            show_sender=not can_edit_toast_message)

        await itx.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(EmbedEditor(bot))
