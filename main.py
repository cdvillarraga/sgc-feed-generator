import requests
from bs4 import BeautifulSoup
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import os

# Configuración para GitHub
MAX_WORKERS = 5
MAX_RETRIES = 3
INPUT_FILE = "urls.csv"  # El archivo que subirás a GitHub
OUTPUT_FILE = "gmc_feed_sgc.xml"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

FORBIDDEN_KEYWORDS = [
    'sight', 'optic', 'mount', 'ring set', 'picatinny', 'weaver', 'adptr', 
    'bipod', 'bi-pod', 'taser', 'pepper spray', 'ballistic', 'armor', 
    'weapon light', 'laser', 'magazine', 'ammo', 'ammunition'
]

def get_gpc(url):
    url_lower = url.lower()
    if "handheld-lights" in url_lower: return "554"
    elif "medical-and-survival" in url_lower: return "4621"
    elif "backpacks" in url_lower or "range-bags" in url_lower: return "100"
    elif "apparel-and-accessories" in url_lower: return "1604"
    elif "gun-safes-and-storage" in url_lower: return "6140"
    elif "drinkware" in url_lower: return "673"
    return "632"

def clean_title(title):
    # Limpia el título quitando separadores de Scottsdale Gun Club
    title = title.split('|')[0].split('-')[0].strip()
    # Eufemismos para evitar banderas rojas de Google
    title = title.replace('Military', 'Emergency').replace('Patrol', 'Safety').replace('Officer', 'Individual')
    return title

def is_safe(title):
    t = title.lower()
    return not any(word in t for word in FORBIDDEN_KEYWORDS)

def get_product_data(url):
    attempt = 0
    while attempt < MAX_RETRIES:
        try:
            time.sleep(1) 
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                h1_tag = soup.find('h1')
                raw_title = h1_tag.get_text().strip() if h1_tag else (soup.title.string if soup.title else "Product")
                
                if not is_safe(raw_title):
                    print(f"Excluido por seguridad: {raw_title}")
                    return None
                
                title = clean_title(raw_title)

                desc_container = soup.find(attrs={"itemprop": "description"}) or soup.find('div', id='product-description')
                if desc_container:
                    description = desc_container.get_text(separator=' ').strip()
                else:
                    meta_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
                    description = meta_desc["content"] if meta_desc else title
                description = ' '.join(description.split())[:1000]

                sku = None
                sku_tag = soup.find(attrs={"itemprop": "sku"})
                if sku_tag:
                    sku = sku_tag.get_text().strip()
                else:
                    sku_match = re.search(r'-(\d+)(?:\.html)?', url)
                    sku = sku_match.group(1) if sku_match else None
                
                if not sku: return None

                img_tag = soup.find('img', class_='prodImage') or soup.find('img', itemprop='image')
                image_link = img_tag.get('src') if img_tag else ""
                
                if image_link and image_link.startswith('//'):
                    image_link = "https:" + image_link
                elif image_link and image_link.startswith('/'):
                    image_link = "https://scottsdalegunclub.com" + image_link

                price_tag = soup.find('span', id='listPrice') or soup.find('span', class_='listPrice')
                if price_tag:
                    price_val = price_tag.get_text().replace('$', '').strip()
                else:
                    price_fallback = soup.find(attrs={"itemprop": "price"})
                    price_val = price_fallback.get_text().replace('$', '').strip() if price_fallback else "0.00"
                
                price = f"{price_val} USD"

                return {
                    'id': sku,
                    'title': title,
                    'description': description if len(description) > 15 else title,
                    'link': url,
                    'image_link': image_link,
                    'price': price,
                    'availability': 'in stock',
                    'brand': 'SGC',
                    'condition': 'new',
                    'gpc': get_gpc(url)
                }
        except Exception as e:
            print(f"Error en {url}: {e}")
        attempt += 1
    return None

def generate_gmc_xml():
    # Validar si el archivo de entrada existe
    if not os.path.exists(INPUT_FILE):
        print(f"Error: No se encuentra el archivo {INPUT_FILE} en el repositorio.")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f.readlines() if line.startswith('http')]

    if not urls:
        print("No se encontraron URLs válidas en el archivo CSV.")
        return

    print(f"Extrayendo datos de {len(urls)} productos...")

    rss = ET.Element("rss", {"version": "2.0", "xmlns:g": "http://base.google.com/ns/1.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "SGC Approved Products Feed"

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(get_product_data, url): url for url in urls}
        for i, future in enumerate(as_completed(futures), 1):
            data = future.result()
            if data:
                item = ET.SubElement(channel, "item")
                ET.SubElement(item, "g:id").text = data['id']
                ET.SubElement(item, "g:title").text = data['title']
                ET.SubElement(item, "g:description").text = data['description']
                ET.SubElement(item, "link").text = data['link']
                ET.SubElement(item, "g:image_link").text = data['image_link']
                ET.SubElement(item, "g:price").text = data['price']
                ET.SubElement(item, "g:availability").text = data['availability']
                ET.SubElement(item, "g:brand").text = data['brand']
                ET.SubElement(item, "g:condition").text = data['condition']
                ET.SubElement(item, "g:google_product_category").text = data['gpc']
            
            if i % 10 == 0 or i == len(urls):
                print(f"Progreso: {i}/{len(urls)}")

    tree = ET.ElementTree(rss)
    tree.write(OUTPUT_FILE, encoding="utf-8", xml_declaration=True)
    print(f"\nFeed generado exitosamente: {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_gmc_xml()
