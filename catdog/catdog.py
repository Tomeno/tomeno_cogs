
import discord
import aiohttp
from redbot.core import commands
from PIL import Image
from io import BytesIO
import asyncio
import aiohttp
import urllib
from typing import Union
import base64
import re

MAX_SIZE = 8 * 1024 * 1024 # 8 MiB
API_URL = 'https://hf.space/embed/gsgbills/dogcat/+/api/predict/'
LINK_URL = 'https://huggingface.co/spaces/gsgbills/dogcat'

class ImageFindError(Exception):
    """Generic error for the _get_image function."""
    pass

class CaptionApiError(Exception):
    """Generic error for errors returned by the API."""
    pass

class Catdog(commands.Cog):
    """Classify images as cats or dogs using AI."""
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot
        self.imagetypes = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
        self.mimetypes = ['image/png', 'image/jpg', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp']
        self.translate_table = {'Cat': '🐱 Kitty', 'Dog': '🐶 Doggie'}
        self.color_table = {'Cat': 0xFFC83D, 'Dog': 0x8E562E}

    @staticmethod
    async def _classify(img, mimetype):
        img.seek(0)
        imgstr = base64.b64encode(img.getvalue()).decode()
        input_json = {
            'data': [f'{mimetype};base64,{imgstr}']
        }
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            async with session.post(API_URL, json=input_json) as response:
                json = await response.json()
                data_arr = json.get('data')
                if (not data_arr) or (len(data_arr) == 0):
                    raise CaptionApiError('API didn\'t return any data')
                duration = json.get('duration')
                return data_arr[0]['label'], data_arr[0]['confidences'], duration

    def _translate(self, input):
        return self.translate_table.get(input, input)

    def _get_color(self, input):
        return self.color_table.get(input, 0xFF0000)
    
    def _extract_link(self, msg: discord.Message):
        link = None
        for a in msg.attachments:
            if (a.size > MAX_SIZE):
                continue
            path = urllib.parse.urlparse(a.url).path
            if (any(path.lower().endswith(x) for x in self.imagetypes)):
                link = a.url
                break
        for m in msg.embeds:
            if m.type == 'image':
                link = m.url
                break
            if m.type == 'gifv':
                link = m.thumbnail.url
                break
            if m.type == 'link':
                if m.image:
                    link = m.image.url
                    break
                elif m.thumbnail:
                    link = m.thumbnail.url
                    break
        return link
    
    async def _get_image(self, ctx: commands.Context, link: Union[discord.Member, str]):
        """Helper function to find an image."""
        if not ctx.message.attachments and not link:
            if hasattr(ctx.channel, 'history'): # discord.py moment for text in voice channels
                async for msg in ctx.channel.history(limit=10):
                    msg: discord.Message
                    if msg.author.id == self.bot.user.id:
                        continue
                    link_try = self._extract_link(msg)
                    if link_try:
                        link = link_try
                        break
            if not link:
                raise ImageFindError('Please provide an attachment.')
        if isinstance(link, discord.Member): #member avatar
            if discord.version_info.major == 1:
                avatar = link.avatar_url_as(static_format="png")
            else:
                avatar = link.display_avatar.with_static_format("png").url
            source = str(avatar)
            data = await avatar.read()
            img = BytesIO(data)
            mimetype = 'image/gif' if link.is_avatar_animated() else 'image/png'
        elif link: #linked image or emoji
            custom_emojis = re.findall(r'<a?:\w+:(\d+)>', link)
            if len(custom_emojis) > 0: #emoji
                emoji = self.bot.get_emoji(int(custom_emojis[0]))
                if emoji:
                    asset = emoji.url_as(static_format="png")
                    source = str(asset)
                    data = await asset.read()
                    img = BytesIO(data)
                    mimetype = 'image/gif' if emoji.animated else 'image/png'
                else:
                    raise ImageFindError(
                        f'Failed to retrieve emoji.'
                    )
            else: #link
                source = link
                try_link = self._extract_link(ctx.message)
                if try_link:
                    source = try_link
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.head(source) as response:
                            if response.status == 200:
                                res_type = response.headers.get('Content-Type')
                                if not res_type in self.mimetypes:
                                    raise ImageFindError(
                                        f'That does not look like an image of a supported filetype. Make sure you provide a direct link.'
                                    )
                        async with session.get(source) as response:
                            mimetype = response.headers.get('Content-Type')
                            if not mimetype or not mimetype in self.mimetypes:
                                raise ImageFindError(
                                    f'That does not look like an image of a supported filetype. Make sure you provide a direct link.'
                                )
                            r = await response.read()
                            img = BytesIO(r)
                    except (OSError, aiohttp.ClientError):
                        raise ImageFindError(
                            'An image could not be found. Make sure you provide a direct link.'
                        )
        # elif ctx.message.stickers: # stickers apparently don't work with redbot
        #     source = ctx.message.stickers[0].url
        #     data = await ctx.message.stickers[0].read()
        #     img = BytesIO(data)
        #     mimetype = Image.open(img).get_format_mimetype()
        elif ctx.message.attachments: #attached image
            attachment: discord.Attachment = ctx.message.attachments[0]
            mimetype = attachment.content_type
            if not mimetype in self.mimetypes:
                raise ImageFindError(
                    f'That does not look like an image of a supported filetype.'
                )
            source = str(attachment.url)
            img = BytesIO()
            await attachment.save(img)
            img.seek(0)
        if img.getbuffer().nbytes > MAX_SIZE:
            raise ImageFindError('That image is too large.')
        img.seek(0)
        return img, mimetype, source
    
    @commands.command(aliases=['kitty', 'doggie'])
    @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.cooldown(1, 1, commands.BucketType.guild)
    @commands.bot_has_permissions(attach_files=True)
    async def catdog(self, ctx: commands.Context, link: Union[discord.Member, str]=None):
        """
        Classify images as cats or dogs using AI.
        
        The optional parameter "link" can be either a member or a **direct link** to an image.
        """
        async with ctx.typing():
            try:
                img, mimetype, source = await self._get_image(ctx, link)
            except ImageFindError as e:	
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(e)
            try:
                task = self._classify(img, mimetype)
            except aiohttp.ClientResponseError as e:
                return await ctx.send(f'The classifier API returned the following error: {e.status} {e.message}')
            except CaptionApiError as e:
                return await ctx.send(f'The classifier API failed with the following error: {str(e)}')
            except Exception as e:
                return await ctx.send('An error occurred while processing your image.')
            try:
                label, confidences, time = await asyncio.wait_for(task, timeout=30)
            except asyncio.TimeoutError:
                return await ctx.send('The image took too long to process.')
            try:
                msg_text = '\n'.join(f'{self._translate(c["label"])}: {c["confidence"] * 100:.2f}%' for c in confidences)
                embed = discord.Embed(
                    type='rich',
                    title=f'{self._translate(label)} detected',
                    description=msg_text,
                    colour=self.color_table.get(label, 0xFF0000),
                    url=LINK_URL
                )
                if source:
                    embed.set_thumbnail(url=source)
                if time:
                    embed.set_footer(text=f'Generated in {round(time, 2)} seconds')
                await ctx.send(embed=embed)
            except discord.errors.HTTPException:
                return await ctx.send('That image is too large.')
