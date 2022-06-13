from .caption import Caption


def setup(bot):
    bot.add_cog(Caption(bot))