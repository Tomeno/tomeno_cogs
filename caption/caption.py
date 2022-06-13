
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
API_URL = 'https://hf.space/embed/OFA-Sys/OFA-Image_Caption/+/api/predict/'
LINK_URL = 'https://huggingface.co/spaces/OFA-Sys/OFA-Image_Caption'

class ImageFindError(Exception):
    """Generic error for the _get_image function."""
    pass

class CaptionApiError(Exception):
    """Generic error for errors returned by the API."""
    pass

class Caption(commands.Cog):
    """Captions images using AI."""
    def __init__(self, bot):
        self.bot = bot
        self.imagetypes = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']
    
    @staticmethod
    async def _caption(img, mimetype):
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
                duration_arr = json.get('durations')
                duration = duration_arr[0] if (duration_arr and len(duration_arr) > 0) else None
                return data_arr[0], duration
    
    async def _get_image(self, ctx, link: Union[discord.Member, str]):
        """Helper function to find an image."""
        if not ctx.message.attachments and not link:
            async for msg in ctx.channel.history(limit=10):
                for a in msg.attachments:
                    path = urllib.parse.urlparse(a.url).path
                    if (
                        any(path.lower().endswith(x) for x in self.imagetypes)
                    ):
                        link = a.url
                        break
                if link:
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
            mimetype = Image.open(img).get_format_mimetype()
        elif link: #linked image or emoji
            custom_emojis = re.findall(r'<a?:\w+:(\d+)>', link)
            if len(custom_emojis) > 0: #emoji
                emoji = self.bot.get_emoji(custom_emojis[0])
                if not emoji and ctx.guild: # try to get it from current guild
                    for i_emoji in ctx.guild.emojis:
                        if i_emoji.id == int(custom_emojis[0]):
                            emoji = i_emoji
                if emoji:
                    asset = emoji.url_as(static_format="png")
                    source = str(asset)
                    data = await asset.read()
                    img = BytesIO(data)
                    mimetype = Image.open(img).get_format_mimetype()
                else:
                    raise ImageFindError(
                        f'Failed to retrieve emoji.'
                    )
            else: #link
                path = urllib.parse.urlparse(link).path
                if not any(path.lower().endswith(x) for x in self.imagetypes):
                    raise ImageFindError(
                        f'That does not look like an image of a supported filetype. Make sure you provide a direct link.'
                    )
                source = link
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.get(link) as response:
                            r = await response.read()
                            img = BytesIO(r)
                            mimetype = Image.open(img).get_format_mimetype()
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
            path = urllib.parse.urlparse(ctx.message.attachments[0].url).path
            if not any(path.lower().endswith(x) for x in self.imagetypes):
                raise ImageFindError(f'That does not look like an image of a supported filetype.')
            if ctx.message.attachments[0].size > MAX_SIZE:
                raise ImageFindError('That image is too large.')
            source = str(ctx.message.attachments[0].url)
            img = BytesIO()
            await ctx.message.attachments[0].save(img)
            img.seek(0)
            mimetype = Image.open(img).get_format_mimetype()
        if img.getbuffer().nbytes > MAX_SIZE:
            raise ImageFindError('That image is too large.')
        img.seek(0)
        return img, mimetype, source
    
    @commands.command(aliases=['cap'])
    @commands.cooldown(1, 10, commands.BucketType.user)
    @commands.cooldown(1, 5, commands.BucketType.guild)
    @commands.bot_has_permissions(attach_files=True)
    async def caption(self, ctx: commands.Context, link: Union[discord.Member, str]=None):
        """
        Captions images using AI.
        
        The optional parameter "link" can be either a member or a **direct link** to an image.
        """
        async with ctx.typing():
            try:
                img, mimetype, source = await self._get_image(ctx, link)
            except ImageFindError as e:	
                ctx.command.reset_cooldown(ctx)
                return await ctx.send(e)
            try:
                #task = functools.partial(self._caption, img, mimetype)
                #task = self.bot.loop.run_in_executor(None, task)
                task = self._caption(img, mimetype)
            except aiohttp.ClientResponseError as e:
                return await ctx.send(f'The caption API returned the following error: {e.status} {e.message}')
            except CaptionApiError as e:
                return await ctx.send(f'The caption API failed with the following error: {str(e)}')
            except Exception as e:
                return await ctx.send('An error occurred while processing your image.')
            try:
                caption, time = await asyncio.wait_for(task, timeout=30)
            except asyncio.TimeoutError:
                return await ctx.send('The image took too long to process.')
            try:
                embed = discord.Embed(
                    type='rich',
                    title='AI Caption',
                    description=f'"{caption}"',
                    colour=discord.Color.green(),
                    url=LINK_URL
                )
                if source:
                    embed.set_thumbnail(url=source)
                    # embed.set_image(url=source)
                if time:
                    embed.set_footer(text=f'Generated in {round(time, 2)} seconds')
                await ctx.send(embed=embed)
            except discord.errors.HTTPException:
                return await ctx.send('That image is too large.')
