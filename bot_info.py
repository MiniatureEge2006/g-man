import discord
from discord.ext import commands
import json

# Load bot info (contains bot login, owners/admins, and such)
data = None
with open('bot_info.json') as f:
    data = json.load(f)

# Returns true if you can use dev commands (like reload)
def is_owner():
    def predicate(ctx):
        return str(ctx.message.author.id) in data['owners']
    return commands.check(predicate)
