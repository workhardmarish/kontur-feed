#!/usr/bin/env python3
"""
Парсер YML-фида kontur.ru → products.json
"""

import json
import xml.etree.ElementTree as ET
import requests
import os
import re
import time
import random

FEED_URL = 'https://kontur.ru/products/yml.xml'
OUTPUT_PATH = 'public/products.json'

# Разные User-Agent чтобы не блокировали
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

def fetch_feed(url, max_retries=5):
    """Скачиваем фид с повторными попытками"""
    for attempt in range(max_retries):
        try:
            ua = random.choice(USER_AGENTS)
            headers = {
                'User-Agent': ua,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0',
            }

            session = requests.Session()
            # Сначала заходим на главную чтобы получить cookies
            if attempt == 0:
                print("Getting cookies from main page...")
                try:
                    session.get('https://kontur.ru/', headers=headers, timeout=15)
                    time.sleep(2)
                except:
                    pass

            print(f"Attempt {attempt+1}/{max_retries}: fetching {url}")
            resp = session.get(url, headers=headers, timeout=60)
            resp.raise_for_status()
            print(f"Success! Content length: {len(resp.content)} bytes")
            return resp.content

        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 10 + random.randint(1, 10)
                print(f"Waiting {wait} seconds before retry...")
                time.sleep(wait)

    raise Exception(f"Failed to fetch feed after {max_retries} attempts")

def guess_tariff(name, vendor_code=''):
    """Определяем тариф KStore по названию товара"""
    name_lower = (name + ' ' + vendor_code).lower()
    if 'f20' in name_lower or 'mspos-f20' in name_lower or 'mspos_f20' in name_lower:
        return 'km_modulecashbox_mspos_f20_f', True
    if '27ф' in name_lower or 'atol 27' in name_lower or 'атол 27' in name_lower:
        return 'km_printer', True
    if '30ф' in name_lower or 'atol 30' in name_lower or 'атол 30' in name_lower:
        return 'km_printer', True
    if 'принтер' in name_lower and ('фискальн' in name_lower or 'касс' in name_lower):
        return 'km_printer', True
    if 'pos' in name_lower or 'терминал' in name_lower or 'optima' in name_lower:
        return 'km_pos', False
    if 'mspos' in name_lower:
        return 'km_pos', False
    return '', False

def guess_cat_slug(category_name):
    """Определяем slug категории"""
    cat = category_name.lower()
    if any(w in cat for w in ['касс', 'pos', 'терминал', 'регистратор', 'фискальн']):
        return 'kasses'
    if any(w in cat for w in ['комплект', 'набор']):
        return 'kits'
    if any(w in cat for w in ['накопитель', 'фн']):
        return 'fn'
    if any(w in cat for w in ['офд', 'оператор фискальн']):
        return 'ofd'
    if any(w in cat for w in ['диадок', 'эдо', 'документ']):
        return 'edo'
    if any(w in cat for w in ['сканер', 'принтер', 'ящик', 'перифер']):
        return 'periphery'
    return 'other'

def parse_feed():
    content = fetch_feed(FEED_URL)
    root = ET.fromstring(content)
    shop = root.find('shop')

    # Парсим категории
    categories = {}
    cats_el = shop.find('categories')
    if cats_el is not None:
        for cat in cats_el.findall('category'):
            categories[cat.get('id')] = cat.text or ''
    print(f"Categories: {len(categories)}")

    # Парсим товары
    products = []
    offers_el = shop.find('offers')
    if offers_el is None:
        raise Exception("No <offers> element found in feed")

    for offer in offers_el.findall('offer'):
        pid      = offer.get('id', '')
        name     = offer.findtext('name', '')
        price    = offer.findtext('price', '0')
        old_price = offer.findtext('oldprice', '')
        cat_id   = offer.findtext('categoryId', '')
        cat_name = categories.get(cat_id, '')
        url      = offer.findtext('url', '')
        vendor_code = offer.findtext('vendorCode', offer.get('vendorCode', ''))
        description = offer.findtext('description', '')

        pictures = [p.text for p in offer.findall('picture') if p.text]
        params = [{'name': p.get('name',''), 'value': p.text or ''} for p in offer.findall('param')]

        cat_slug = guess_cat_slug(cat_name)
        is_kassa = cat_slug in ('kasses', 'kits')
        is_kit   = cat_slug == 'kits'

        kassa_tariff, has_fn = guess_tariff(name, vendor_code)
        if not is_kassa:
            kassa_tariff, has_fn = '', False

        # Slug для URL в Tilda
        slug = vendor_code.lower().replace(' ', '-').replace('/', '-') if vendor_code else ''
        slug = re.sub(r'[^a-z0-9\-]', '', slug).strip('-')
        tilda_url = '/' + slug if slug else f'/product-{pid}'

        products.append({
            'id': pid,
            'name': name,
            'price': float(price) if price else 0,
            'oldPrice': float(old_price) if old_price else 0,
            'cat': cat_name,
            'catSlug': cat_slug,
            'img': pictures[0] if pictures else '',
            'imgs': pictures[:4],
            'desc': description[:200] if description else '',
            'fullDesc': description,
            'params': params,
            'vendorCode': vendor_code,
            'url': url,
            'tildaUrl': tilda_url,
            'isKassa': is_kassa,
            'isKit': is_kit,
            'hasFn': has_fn,
            'kassaTariff': kassa_tariff,
        })

    print(f"Products parsed: {len(products)}")
    return products

def main():
    products = parse_feed()

    order = ['kasses', 'kits', 'fn', 'ofd', 'edo', 'periphery', 'other']
    products.sort(key=lambda p: (
        order.index(p['catSlug']) if p['catSlug'] in order else 99,
        p['name']
    ))

    os.makedirs('public', exist_ok=True)

    import datetime
    output = {
        'updated': datetime.datetime.utcnow().isoformat() + 'Z',
        'count': len(products),
        'products': products
    }

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(products)} products to {OUTPUT_PATH}")
    print("\nFirst 5 products:")
    for p in products[:5]:
        print(f"  [{p['catSlug']}] {p['name']} — {p['price']} ₽")

if __name__ == '__main__':
    main()
