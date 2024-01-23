import discord
from discord.ext import commands
from datetime import timedelta
from typing import Optional
from discord import app_commands
from discord.app_commands import Choice
from typing import List
from sql import Store
import helpers
import aiohttp
import asyncio
from constants import TIMEFRAMES
import logging

log = logging.getLogger(__name__)

class Logs_Display(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.myguild = self.bot.get_guild(617136488840429598)

    @app_commands.command(name='logs', description=f'View your logs')
    @app_commands.describe(name='''You can use vndb IDs and titles for VN and Anilist codes for Anime and Manga''')
    @app_commands.choices(media_type = [Choice(name="Visual Novel", value="VN"), Choice(name="Manga", value="Manga"), Choice(name="Anime", value="Anime"), Choice(name="Book", value="Book"), Choice(name="Readtime", value="Readtime"), Choice(name="Listening", value="Listening"), Choice(name="Reading", value="Reading")])
    @app_commands.describe(timeframe='''DEFAULT=MONTH; Week, Month, Year, All, [year-month-day] or [year-month-day-year-month-day]''')
    @app_commands.checks.has_role("QA Tester")
    async def logs(self, interaction: discord.Interaction, user: Optional[discord.User], timeframe: Optional[str], media_type: Optional[str], name: Optional[str]):
        
        channel = interaction.channel
        if channel.id != 1010323632750350437 and channel.id != 814947177608118273 and channel.type != discord.ChannelType.private:
            return await interaction.response.send_message(content='You can only log in #immersion-log or DMs.',ephemeral=True)
        
        if not user:
            user = interaction.user

        if not media_type:
            media_type = None

        if not name:
            name = None

        if name and media_type:
            calc_amount, format, msg, title = helpers.point_message_converter(media_type.upper(), 0, name)

        if not timeframe or timeframe.upper() == "MONTH":
            #Month
            beginn = interaction.created_at.replace(day=1, hour=0, minute=0)
            end = (beginn.replace(day=28) + timedelta(days=4)) - timedelta(days=(beginn.replace(day=28) + timedelta(days=4)).day)

        elif timeframe.upper() == "WEEK":
            beginn = (interaction.created_at - timedelta(days=interaction.created_at.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            end = (beginn + timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)

        elif timeframe.upper() == "YEAR":
            beginn = interaction.created_at.date().replace(month=1, day=1)
            end = interaction.created_at.date().replace(month=12, day=31)

        elif timeframe.upper() == "ALL":
            beginn = interaction.created_at.replace(year=2020)
            end = interaction.created_at

        elif timeframe.upper() not in TIMEFRAMES:
            try:
                dates = timeframe.split('-')
                if len(timeframe.split('-')) == 6:
                    beginn = interaction.created_at.replace(year=int(dates[0]), month=int(dates[1]), day=int(dates[2]))
                    end = interaction.created_at.replace(year=int(dates[3]), month=int(dates[4]), day=int(dates[5]))
                    if beginn > end:
                        return await interaction.response.send_message(content='You switched up the dates.', ephemeral=True)
                elif len(timeframe.split('-')) == 3:
                    beginn = interaction.created_at.replace(year=int(dates[0]), month=int(dates[1]), day=int(dates[2]), hour=0, minute=0, second=0)
                    end = beginn + timedelta(days=1)
                    if beginn > interaction.created_at:
                        return await interaction.response.send_message(content='''You can't look into the future.''', ephemeral=True)
                else:
                    return Exception
            except Exception:
                return await interaction.response.send_message(content='Enter a valid date. [Year-Month-day] e.g 2023-12-24', ephemeral=True)

        await interaction.response.defer()

        store_prod = Store("prod.db")
        print(user.id, media_type, [beginn, end], title if name else name)
        logs = store_prod.get_logs_by_user(user.id, media_type, [beginn, end], title if name else name)
        message_logs = []
        for log in logs:
            try:
                note = eval(log.note)[1]
            except Exception:
                note = ""
            if note == None:
                note = ""
            message_logs.append((f'{log.created_at.strftime("%Y-%m-%d")}: {log.media_type.value.upper()} {log.amount} {helpers.media_type_format(log.media_type.value)} → {round(helpers._to_amount(log.media_type.value, log.amount), 5)}pts: {note}'))

        if message_logs:
            max_logs = 20
            def gen_desc(logs, max_logs):
                desc = '\n'.join((log) for log in logs[:max_logs])
                if len(logs) > max_logs:
                    too_many_logs = (
                        f'...({len(logs) - max_logs} more logs)...\n'
                        f'Specify a smaller timeframe or use `.export` to see them all\n'
                    )
                else:
                    too_many_logs = ''
                return f'```\n{desc}\n{too_many_logs}```'
            
            max_logs = 20
            log_desc = gen_desc(message_logs, max_logs)
            while len(log_desc) > 2000:
                max_logs -= 1
                log_desc = gen_desc(message_logs, max_logs)
        else:
            log_desc = 'No logs were found.'

        await interaction.edit_original_response(content=log_desc)

    @logs.autocomplete('name')
    async def log_autocomplete(self, interaction: discord.Interaction, current: str,) -> List[app_commands.Choice[str]]:

        await interaction.response.defer()
        media_type = interaction.namespace['media_type']
        suggestions = []
        url = ''

        if media_type == 'VN':
            url = 'https://api.vndb.org/kana/vn'
            data = {'filters': ['search', '=', f'{current}'], 'fields': 'title, alttitle'} # default no. of results is 10
        
        elif media_type == 'Anime' or media_type == 'Manga':
            url = 'https://graphql.anilist.co'
            query = f'''
            query ($page: Int, $perPage: Int, $title: String) {{
                Page(page: $page, perPage: $perPage) {{
                    pageInfo {{
                        total
                        perPage
                    }}
                    media (search: $title, type: {media_type.upper()}) {{
                        id
                        title {{
                            romaji
                            native
                        }}
                    }}
                }}
            }}
            '''

            variables = {
                'title': current,
                'page': 1,
                'perPage': 10
            }

            data = {'query': query, 'variables': variables}

        if not url:
            return []

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data) as resp:
                log.info(resp.status)
                json_data = await resp.json()

                if media_type == 'VN':
                    suggestions = [(result['title'], result['id']) for result in json_data['results']]

                elif media_type == 'Anime' or media_type == 'Manga':
                    suggestions = [(f"{result['title']['romaji']} ({result['title']['native']})", result['id']) for result in json_data['data']['Page']['media']]

                await asyncio.sleep(0)

                return [
                    app_commands.Choice(name=title, value=str(id))
                    for title, id in suggestions if current.lower() in title.lower()
                ]

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Logs_Display(bot))
