import asyncio
import csv
from collections import defaultdict
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

# Data structures to hold car information
car_brands = set()
car_models = defaultdict(lambda: defaultdict(set))


# Load data from CSV
def load_car_data(filename):
    with open(filename, 'r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            make = row['make']
            model = row['model']
            year = row['year']

            car_brands.add(make)
            car_models[make][model].add(year)


# Load the data when the bot starts
load_car_data('vehicles (1).csv')

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


def create_embed(title, description=None, options=None, color=0x00ff00, image_url=None, page=None, total_pages=None):
    embed = discord.Embed(title=title, description=description, color=color)

    if options:
        # Use larger font for options
        options_text = "\n".join([f"**{option}**" for option in options])
        embed.add_field(name="Options", value=options_text, inline=False)

    if image_url:
        embed.set_image(url=image_url)

    if page is not None and total_pages is not None:
        embed.set_footer(text=f"Page {page + 1} of {total_pages}")

    return embed


async def paginate_options(ctx, title, description, all_options, options_per_page=10):
    pages = [all_options[i:i + options_per_page] for i in range(0, len(all_options), options_per_page)]
    total_pages = len(pages)
    current_page = 0

    embed = create_embed(title, description, pages[current_page], page=current_page, total_pages=total_pages)
    message = await ctx.send(embed=embed)

    await message.add_reaction('⬅️')
    await message.add_reaction('➡️')

    def reaction_check(reaction, user):
        return user == ctx.author and str(reaction.emoji) in ['⬅️', '➡️'] and reaction.message.id == message.id

    def message_check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    while True:
        tasks = [
            asyncio.create_task(bot.wait_for('reaction_add', check=reaction_check)),
            asyncio.create_task(bot.wait_for('message', check=message_check))
        ]

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED, timeout=60.0)

        for task in pending:
            task.cancel()

        if not done:
            await ctx.send("You took too long to respond. Please try again.")
            return None

        result = done.pop().result()

        if isinstance(result, tuple):  # Reaction result
            reaction, user = result
            if str(reaction.emoji) == '➡️' and current_page < total_pages - 1:
                current_page += 1
            elif str(reaction.emoji) == '⬅️' and current_page > 0:
                current_page -= 1

            embed = create_embed(title, description, pages[current_page], page=current_page, total_pages=total_pages)
            await message.edit(embed=embed)
            await message.remove_reaction(reaction, user)
        else:  # Message result
            return result.content

    return None


@bot.command(name='car')
async def find_car(ctx):
    logging.info("Car command received")

    # Show brands
    brands = sorted(list(car_brands))
    selected_brand = await paginate_options(ctx, "Car Brands", "Please choose a car brand by entering its name", brands)

    if not selected_brand:
        return

    selected_brand = selected_brand.strip().title()
    if selected_brand not in car_brands:
        await ctx.send("Invalid brand name. Please try again.")
        return
    logging.info(f"Selected brand: {selected_brand}")

    # Show models for the selected brand
    models = car_models[selected_brand]
    if not models:
        await ctx.send(f"No models found for {selected_brand}. Please try another brand.")
        return

    model_options = [f"{model} ({', '.join(sorted(years, reverse=True))})" for model, years in models.items()]
    selected_model = await paginate_options(ctx, f"{selected_brand} Models",
                                            "Please choose a car model by entering its name", model_options)

    if not selected_model:
        return

    selected_model = selected_model.strip().title()
    if selected_model not in models:
        await ctx.send("Invalid model name. Please try again.")
        return
    logging.info(f"Selected model: {selected_model}")

    # Show years for the selected model and ask user to choose
    years = sorted(models[selected_model], reverse=True)
    selected_year = await paginate_options(ctx, f"{selected_brand} {selected_model} Years",
                                           "Please choose a year by entering it", years)

    if not selected_year:
        return

    if selected_year not in years:
        await ctx.send("Invalid year. Please try again.")
        return
    logging.info(f"Selected year: {selected_year}")

    # Fetch and display the image
    image_url = await get_image_url(selected_brand, selected_model, selected_year)
    if image_url:
        embed = create_embed(f"{selected_brand} {selected_model} {selected_year}",
                             image_url=image_url)
        await ctx.send(embed=embed)
    else:
        await ctx.send("Sorry, I couldn't find an image for that car.")


@bot.event
async def on_ready():
    logging.info(f"Bot is ready. Logged in as {bot.user.name}")


bot.run(YOUR_TOKEN)