from .catdog import Catdog


def setup(bot):
    bot.add_cog(Catdog(bot))