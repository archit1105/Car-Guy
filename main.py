import asyncio
from collections import defaultdict
import csv
import discord
from discord.ext import commands
import aiohttp
import urllib
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

car_brands = {}
car_models = defaultdict(list)

# Creating a database for the bot
with open('carapi-opendatafeed-sample.csv', 'r') as file:
    reader = csv.DictReader(file)
    for row in reader:
        make = row['Make Name']
        model = row['Model Name']
        make_id = row['Make Id']
        year = row['Trim Year']
        trim_id = row['Trim Id']

        if make not in car_brands:
            car_brands[make] = make_id

        car_models[make].append((model, year, trim_id))

# Sort car brands by make_id
car_brands = dict(sorted(car_brands.items(), key=lambda x: int(x[1])))

WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"

async def get_image_url(make, model, year):
    logging.info(f"Attempting to get image URL for {make} {model} {year}")
    try:
        async with aiohttp.ClientSession() as session:
            params = {
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": f"{make} {model} {year}",
                "srnamespace": "6",  # File namespace
                "srlimit": "1",
                "srprop": "size|url"
            }
            logging.debug(f"API request params: {params}")
            async with session.get(WIKIMEDIA_API_URL, params=params) as response:
                logging.debug(f"API response status: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    logging.debug(f"API Response: {data}")
                    if data['query']['search']:
                        file_name = data['query']['search'][0]['title']
                        file_name = file_name.replace("File:", "")
                        file_name = urllib.parse.quote(file_name)
                        image_url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{file_name}"
                        logging.info(f"Image URL found: {image_url}")
                        return image_url
                    else:
                        logging.warning("No search results found in API response")
                else:
                    logging.error(f"API returned non-200 status code: {response.status}")
    except Exception as e:
        logging.exception(f"Error in get_image_url: {str(e)}")
    logging.warning("No image URL found")
    return None

def create_embed(title, description=None, fields=None, color=0x00ff00, image_url=None):
    embed = discord.Embed(title=title, description=description, color=color)
    if fields:
        for name, value in fields:
            if len(value) > 1024:
                chunks = [value[i:i + 1024] for i in range(0, len(value), 1024)]
                for i, chunk in enumerate(chunks):
                    embed.add_field(name=f"{name} (part {i + 1})", value=chunk, inline=False)
            else:
                embed.add_field(name=name, value=value, inline=False)
    if image_url:
        logging.info(f"Setting image URL in embed: {image_url}")
        embed.set_image(url=image_url)
    return embed

@bot.command(name='hello')
async def on_hello(ctx):
    logging.info("Hello command received")
    await ctx.reply('Hello fellow car guy!', mention_author=True)

def paginate(options, page_size=10):
    for i in range(0, len(options), page_size):
        yield options[i:i + page_size]

@bot.command(name='car')
async def find_car(ctx):
    logging.info("Car command received")
    brands = '\n'.join([f'{make_id}. {make}' for make, make_id in car_brands.items()])
    embed = create_embed("Car Brands", "Please choose a car brand by entering the number", [("Options", brands)])
    await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel and m.content.isdigit()

    try:
        logging.info("Waiting for brand selection")
        msg = await bot.wait_for('message', check=check, timeout=30)
        selected_make_id = msg.content.strip()
        selected_brand = next((make for make, make_id in car_brands.items() if make_id == selected_make_id), None)
        if not selected_brand:
            logging.warning("Invalid brand number entered")
            await ctx.send(embed=create_embed("Error", "Invalid brand number"))
            return
        logging.info(f"Selected brand: {selected_brand}")
    except asyncio.TimeoutError:
        logging.warning("Brand selection timed out")
        await ctx.send(embed=create_embed("Error", "You took too long to respond"))
        return

    models = car_models[selected_brand]
    pages = list(paginate(models))

    current_page = 0
    embed = create_embed("Models", f"Please choose a car model from {selected_brand} by entering the number", [
        ("Options", '\n'.join([f'{trim_id}. {model} ({year})' for model, year, trim_id in pages[current_page]]))])
    message = await ctx.send(embed=embed)

    await message.add_reaction('⬅️')
    await message.add_reaction('➡️')

    def reaction_check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ['⬅️', '➡️'] and reaction.message.id == message.id

    while True:
        try:
            tasks = [
                asyncio.create_task(bot.wait_for('message', check=check, timeout=30)),
                asyncio.create_task(bot.wait_for('reaction_add', check=reaction_check, timeout=30))
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            for task in pending:
                task.cancel()

            if not done:
                raise asyncio.TimeoutError()

            result = done.pop().result()

            if isinstance(result, discord.Message):
                # User selected a model
                msg = result
                selected_trim_id = msg.content.strip()
                try:
                    selected_model, selected_year = next(
                        (model, year) for model, year, trim_id in models if trim_id == selected_trim_id)
                    logging.info(f"Selected model: {selected_model}, year: {selected_year}")
                    break
                except StopIteration:
                    logging.warning("Invalid model number entered")
                    await ctx.send(embed=create_embed("Error", "Invalid model number"))
                    continue
            else:
                # User navigated pages
                reaction, user = result
                if str(reaction.emoji) == '➡️':
                    current_page = min(current_page + 1, len(pages) - 1)
                elif str(reaction.emoji) == '⬅️':
                    current_page = max(current_page - 1, 0)

                embed = create_embed("Models",
                                     f"Please choose a car model from {selected_brand} by entering the number",
                                     [("Options", '\n'.join(
                                         [f'{trim_id}. {model} ({year})' for model, year, trim_id in
                                          pages[current_page]]))])
                await message.edit(embed=embed)
                await message.remove_reaction(reaction, user)

        except asyncio.TimeoutError:
            logging.info("Model selection/navigation timed out")
            await ctx.send(embed=create_embed("Error", "You took too long to respond"))
            return

    logging.info(f"Attempting to get image URL for {selected_brand} {selected_model} {selected_year}")
    image_url = await get_image_url(selected_brand, selected_model, selected_year)
    if not image_url:
        logging.warning("No image URL found, sending error embed")
        await ctx.send(embed=create_embed("Error", "No image found for the selected car"))
        return

    logging.info(f"Creating embed with image URL: {image_url}")
    embed = create_embed("Selected Car", description=f"{selected_brand} {selected_model} {selected_year}",
                         image_url=image_url)
    logging.debug(f"Embed image URL: {embed.image.url if embed.image else 'No image set'}")
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    logging.error(f"An error occurred: {str(error)}")
    await ctx.send(f"An error occurred: {str(error)}")

@bot.event
async def on_ready():
    logging.info(f"Bot is ready. Logged in as {bot.user.name}")

bot.run(MY_TOKEN)
