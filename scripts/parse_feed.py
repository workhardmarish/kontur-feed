#!/usr/bin/env python3
"""
Парсер YML-фида kontur.ru → products.json
Запускается GitHub Actions каждый день в 9:00 МСК
"""

import json
import xml.etree.ElementTree as ET
import requests
import os
import re

FEED_URL = 'https://kontur.ru/products/yml.xml'
OUTPUT_PATH = 'public/products.json'

# Маппинг id товара → данные для конфигуратора KStore
# Заполните когда получите ID тарифов от разработчика
KASSA_TARIFFS = {
    # Имя категории или vendorCode → тариф KStore
    'km_modulecashbox_mspos_f20_f': ['mspos', 'f20'],   # MSPOS-F20
    'km_pos':     ['mspos-t', 'optima', 'payor', 'edpos', 'pos'],
    'km_printer': ['27ф', '30ф', 'атол 2', 'атол 3'],
}

KASSA_HAS_FN = {
    'km_modulecashbox_mspos_f20_f': True,
    'km_pos':     False,
    'km_printer': True,
}

# Категории которые считаются кассами (нужен конфигуратор)
KASSA_CAT_SLUGS = ['kasses', 'kits']

def guess_tariff(name, vendor_code=''):
    """Определяем тариф KStore по названию товара"""
    name_lower = (name + ' ' + vendor_code).lower()
    if 'f20' in name_lower or 'mspos-f20' in name_lower:
        return 'km_modulecashbox_mspos_f20_f', True
    if 'принтер' in name_lower or '27ф' in name_lower or '30ф' in name_lower or 'atol' in name_lower:
        return 'km_printer', True
    if 'pos' in name_lower or 'терминал' in name_lower or 'optima' in name_lower:
        return 'km_pos', False
    if 'mspos' in name_lower:
        return 'km_pos', False
    return '', False

def guess_cat_slug(category_name):
    """Определяем slug категории"""
    cat = category_name.lower()
    if any(w in cat for w in ['касс', 'pos', 'терминал', 'регистратор']):
        return 'kasses'
    if any(w in cat for w in ['комплект', 'набор']):
        return 'kits'
    if any(w in cat for w in ['фискальн', 'накопитель', 'фн']):
        return 'fn'
    if any(w in cat for w in ['офд', 'оператор']):
        return 'ofd'
    if any(w in cat for w in ['диадок', 'эдо', 'документ']):
        return 'edo'
    if any(w in cat for w in ['сканер', 'принтер', 'ящик', 'перифер']):
        return 'periphery'
    return 'other'

def parse_feed():
    print(f"Fetching feed from {FEED_URL}...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; GitHubActions/1.0)',
        'Accept': 'application/xml,text/xml,*/*',
    }
    
    resp = requests.get(FEED_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    print(f"Feed fetched: {len(resp.content)} bytes")
    
    root = ET.fromstring(resp.content)
    shop = root.find('shop')
    
    # Парсим категории
    categories = {}
    for cat in shop.find('categories').findall('category'):
        categories[cat.get('id')] = cat.text or ''
    print(f"Categories: {len(categories)}")
    
    # Парсим товары
    products = []
    for offer in shop.find('offers').findall('offer'):
        pid = offer.get('id', '')
        name = offer.findtext('name', '')
        price = offer.findtext('price', '0')
        cat_id = offer.findtext('categoryId', '')
        cat_name = categories.get(cat_id, '')
        url = offer.findtext('url', '')
        vendor_code = offer.findtext('vendorCode', offer.get('vendorCode', ''))
        description = offer.findtext('description', '')
        
        # Картинки
        pictures = [p.text for p in offer.findall('picture') if p.text]
        
        # Параметры
        params = []
        for param in offer.findall('param'):
            params.append({
                'name': param.get('name', ''),
                'value': param.text or ''
            })
        
        # Старая цена
        old_price = offer.findtext('oldprice', '')
        
        # Определяем slug и тип
        cat_slug = guess_cat_slug(cat_name)
        is_kassa = cat_slug in KASSA_CAT_SLUGS
        is_kit = cat_slug == 'kits'
        
        kassa_tariff, has_fn = guess_tariff(name, vendor_code)
        if not is_kassa:
            kassa_tariff = ''
            has_fn = False
        
        # URL страницы в Tilda (генерируем из vendorCode или id)
        slug = vendor_code.lower().replace(' ', '-').replace('/', '-') if vendor_code else f'product-{pid}'
        slug = re.sub(r'[^a-z0-9\-]', '', slug)
        tilda_url = '/' + slug if slug else f'/product-{pid}'
        
        products.append({
            'id': pid,
            'name': name,
            'price': float(price) if price else 0,
            'oldPrice': float(old_price) if old_price else 0,
            'cat': cat_name,
            'catSlug': cat_slug,
            'img': pictures[0] if pictures else '',
            'imgs': pictures,
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
    
    # Сортируем: кассы первыми
    order = ['kasses', 'kits', 'fn', 'ofd', 'edo', 'periphery', 'other']
    products.sort(key=lambda p: (order.index(p['catSlug']) if p['catSlug'] in order else 99, p['name']))
    
    os.makedirs('public', exist_ok=True)
    
    output = {
        'updated': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
        'count': len(products),
        'products': products
    }
    
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"Saved to {OUTPUT_PATH}: {len(products)} products")
    
    # Покажем первые 3 товара для проверки
    for p in products[:3]:
        print(f"  [{p['catSlug']}] {p['name']} — {p['price']} ₽")

if __name__ == '__main__':
    main()
