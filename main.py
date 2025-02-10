import aiohttp
import aiosqlite
import asyncio
import random
from bs4 import BeautifulSoup
from tqdm import tqdm
import re

result_body = ""

letters = [chr(i) for i in range(ord('A'), ord('z') + 1)]


async def load_titles_categories(db_connection):
    titles = []
    categories = []
    async with db_connection.execute("SELECT title, Category FROM items") as cursor:
        async for row in cursor:
            titles.append(row[0].strip())
            categories.append(row[1].strip())
    return [titles, categories]


async def n_string(n):
    return ''.join(random.choices(letters, k=n)).replace("/", "").replace("\\", "")


async def update_item_category(db_connection, title, new_category):
    async with db_connection.execute("SELECT Category FROM items WHERE title = ?", (title,)) as cursor:
        row = await cursor.fetchone()
        if row:
            current_categories = row[0]
            if new_category not in current_categories.split(';'):
                updated_categories = current_categories + ';' + new_category
                await db_connection.execute("UPDATE items SET Category = ? WHERE title = ?", (updated_categories, title))
                await db_connection.commit()


async def fetch_page(session, url):
    async with session.get(url) as response:
        return await response.text()


async def download_img(session, url, sku):
    new_name = f"pictures/{await n_string(32)}.jpeg"
    async with session.get(url) as response:
        img_data = await response.read()
        with open(new_name, 'wb') as handler:
            handler.write(img_data)
    return new_name


async def process_element(session, element, sku):
    global result_body
    try:
        if element.name == 'img':
            if 'src' in element.attrs:
                new_url = await download_img(session, element['src'], sku)
                result_body += " " + new_url
            else:
                result_body += " "
        elif element.name is None:
            result_body += " " + element
        else:
            for child in element.children:
                await process_element(session, child, sku)
    except Exception as e:
        result_body = " "


async def process_page(url, session, db_connection, titles, categories):
    text = await fetch_page(session, url)
    soup = BeautifulSoup(text, "html.parser")
    all_items = soup.findAll('li', class_='product')
    for item in tqdm(all_items):
        try:
            link = item.find('a', class_='woocommerce-LoopProduct-link')
            link_url = link.get('href')
            page_text = await fetch_page(session, link_url)
            page_soup = BeautifulSoup(page_text, "html.parser")
            title = page_soup.title.string if page_soup.title else ""
            title = title.replace("| FashionReps", "").strip()

            category_element = page_soup.find('nav', class_="woocommerce-breadcrumb")
            category = category_element.text.split("/")[1:-1]
            category = "/".join(category)
            if title in titles:
                if category in categories:
                    continue
                else:
                    await update_item_category(db_connection, title, category)
                    continue

            sku_element = page_soup.find('span', class_="sku")
            sku = sku_element.text if sku_element else ""
            images = page_soup.findAll('div', class_='woocommerce-product-gallery__image')
            images_list = [await download_img(session, img.find('a')['href'], sku) for img in images]
            price_elements = page_soup.findAll('span', class_="woocommerce-Price-amount")
            price = price_elements[1].text if len(price_elements) > 1 else price_elements[0].text
            price = float(price.replace("$", "").strip()) - 25  # Discount applied here

            try:
                pa_size = page_soup.find('select', id="pa_size")
                if pa_size is None:
                    raise ValueError("No select element with id 'pa_size' found")

                selections = pa_size.find_all('option')[1:]
                size_list = [option.text for option in selections]
                pa_size = ",".join(size_list)
            except:
                pa_size = ""
                try:
                    pa_size = page_soup.find('select', id="pa_sizeeu")
                    if pa_size is None:
                        raise ValueError("No select element with id 'pa_sizeeu' found")

                    selections = pa_size.find_all('option')[1:]
                    size_list = [option.text for option in selections]
                    pa_size = ",".join(size_list)
                except Exception as e:
                    pa_size = ""

            try:
                pa_color = page_soup.find('select', id="pa_color")
                if pa_color is None:
                    raise ValueError("No select element with id 'pa_color' found")

                selections = pa_color.find_all('option')[1:]
                color_list = [option.text for option in selections]
                pa_color = ",".join(color_list)
            except Exception as e:
                pa_color = ""

            description = page_soup.find('div', class_="woocommerce-Tabs-panel--description")
            global result_body
            result_body = ""

            if description is not None:
                await process_element(session, description, sku)
            else:
                description = page_soup.find('div', class_="woocommerce-product-details__short-description")
                if description is not None:
                    result_body = description.text

            image_paths = extract_image_paths(result_body)
            desc_detail_cleaned = re.sub(r'pictures\/\S+\.jpeg', '', result_body).strip()

            # Store data in SQLite
            await db_connection.execute('''
                INSERT INTO items(title, DescDetail, DescDetailImg, Img, Price, Category, SKU, URL, Color, Size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                title,
                ",".join(image_paths),
                desc_detail_cleaned,
                ",".join(images_list),
                f"${price}",
                category,
                sku,
                link_url,
                pa_color,
                pa_size
            ))

            await db_connection.commit()
        except Exception as e:
            print(e)


def extract_image_paths(text):
    pattern = r'pictures\/\S+\.jpeg'
    matches = re.findall(pattern, text)
    return matches


async def setup_database():
    db_connection = await aiosqlite.connect('database.db')
    await db_connection.execute('''
        CREATE TABLE IF NOT EXISTS items (
            title TEXT,
            DescDetail TEXT,
            DescDetailImg TEXT,
            Img TEXT,
            Price TEXT,
            Category TEXT,
            SKU TEXT,
            URL TEXT,
            Color TEXT,
            Size TEXT
        )
    ''')
    await db_connection.commit()
    return db_connection


async def main():
    db_connection = await setup_database()
    spisok = await load_titles_categories(db_connection)
    titles = spisok[0]
    categories = spisok[1]
    print("Идет загрузка таблицы SQL...")
    for iss in [
        ["https://www.fashionreps.is/replica-bags/", 10],
        ["https://www.fashionreps.is/replica-accessories/", 2],
        ["https://www.fashionreps.is/replica-jeans-pants/", 4],
        ["https://www.fashionreps.is/replica-nike-x-tiffan/", 2],
        ["https://www.fashionreps.is/brand/dior/", 6],
        ["https://www.fashionreps.is/brand/bape/", 2],
        ["https://www.fashionreps.is/brand/nike/", 19],
        ["https://www.fashionreps.is/brand/prada/", 2],
        ["https://www.fashionreps.is/brand/gucci/", 7],
        ["https://www.fashionreps.is/brand/adidas/", 9],
        ["https://www.fashionreps.is/brand/chanel/", 3],
        ["https://www.fashionreps.is/brand/moncler/", 2],
        ["https://www.fashionreps.is/brand/off-white/", 9],
        ["https://www.fashionreps.is/brand/air-jordan/", 16],
        ["https://www.fashionreps.is/brand/givenchy/", 2],
        ["https://www.fashionreps.is/brand/balenciaga/", 11],
        ["https://www.fashionreps.is/brand/louis-vuitton/", 18],
        ["https://www.fashionreps.is/brand/the/", 3],
        ["https://www.fashionreps.is/brand/moose-knuckles/", 2],
        ["https://www.fashionreps.is/brand/alexander-mcqueen/", 3],
        ["https://www.fashionreps.is/replica-clothing/", 31],
        ["https://www.fashionreps.is/replica-shoes/", 71]
    ]:
        async with aiohttp.ClientSession() as session:
            tasks = [
                process_page(f"{iss[0]}/page/{i}/", session, db_connection, titles, categories)
                for i in range(1, iss[1])
            ]
            await asyncio.gather(*tasks)
    await db_connection.close()


asyncio.run(main())
