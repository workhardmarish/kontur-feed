#!/usr/bin/env python3
"""
Генератор сайта из YML-фида kontur.ru
Запускается GitHub Actions каждый день
Результат публикуется в папку public/ → GitHub Pages
"""

import json, os, re, time, random, datetime
import xml.etree.ElementTree as ET
import requests

FEED_URL   = 'https://kontur.ru/products/yml.xml'
OUTPUT_DIR = 'docs'

# ──────────────────────────────────────────
# Маппинг id → тариф KStore и URL страницы
# ──────────────────────────────────────────
KASSA_CFG = {
    # id: (tariff, hasFn, isKit, slug, hwParam, onlineSale)
    # hwParam  — Hardware.Printer для km_printer, '' для остальных
    # onlineSale — False если только заявка на менеджера
    4:  ('km_modulecashbox_mspos_f20_f', True,  False, 'mspos-f20',     '',          True),
    5:  ('km_pos',                       False, False, 'mspos-t',        '',          True),
    6:  ('km_printer',                   True,  False, 'atol-27f',       'printer27f', True),
    7:  ('km_printer',                   True,  False, 'atol-30f',       'fr30f',     True),
    8:  ('km_pos',                       False, False, 'atol-optima',    '',          True),
    9:  ('km_pos',                       False, False, 'paytor-jay-pro', '',          False),  # только заявка
    10: ('km_pos',                       False, False, 'edpos',          '',          False),  # только заявка
    11: ('km_pos',                       False, True,  'kit-nadezhnyj',  '',          True),
    12: ('km_pos',                       False, True,  'kit-udobnyj',    '',          True),
    13: ('km_pos',                       False, True,  'kit-bystryj',    '',          True),
    14: ('km_modulecashbox_mspos_f20_f', True,  True,  'kit-mobilnyj',   '',          True),
    15: ('km_printer',                   True,  True,  'kit-vygodnyj',   'fr30f',     True),
}

PAGE_SLUGS = {
    **{pid: cfg[3] for pid, cfg in KASSA_CFG.items()},
    16: 'fn-15',     17: 'fn-36',
    18: 'fn-ofd-15', 19: 'fn-ofd-36',
    20: 'ofd-13',    21: 'ofd-15',    22: 'ofd-36',
    23: 'scanner-neo-max',
    24: 'scanner-mindeo-mp8610',
    25: 'atol-jett',
    3:  'scanner-mindeo-md6600',
    1:  'pereiferia',
    2:  'diadok',
    26: 'diadok-600',
    27: 'diadok-1200',
    28: 'diadok-3000',
}

# Категории → раздел сайта
CAT_SECTIONS = {
    'kasses': 'kasses', 'kits': 'kits',
    'fn': 'fn-ofd', 'ofd': 'fn-ofd',
    'edo': 'edo', 'periphery': 'periphery',
}

# ──────────────────────────────────────────
# Загрузка фида
# ──────────────────────────────────────────
def fetch_feed():
    UAS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0 Safari/537.36',
    ]
    for attempt in range(5):
        try:
            s = requests.Session()
            ua = random.choice(UAS)
            h  = {'User-Agent': ua, 'Accept-Language': 'ru-RU,ru;q=0.9',
                  'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}
            try:
                s.get('https://kontur.ru/', headers=h, timeout=10)
                time.sleep(2)
            except: pass
            print(f"Attempt {attempt+1}: fetching feed...")
            r = s.get(FEED_URL, headers=h, timeout=60)
            r.raise_for_status()
            print(f"OK: {len(r.content)} bytes")
            return r.content
        except Exception as e:
            print(f"Failed: {e}")
            if attempt < 4:
                time.sleep((attempt+1)*10 + random.randint(1,5))
    raise Exception("Cannot fetch feed")

def guess_cat_slug(cat_name):
    c = cat_name.lower()
    if any(w in c for w in ['касс','pos','терминал','регистратор']): return 'kasses'
    if any(w in c for w in ['комплект','набор']): return 'kits'
    if any(w in c for w in ['накопитель','фн']): return 'fn'
    if any(w in c for w in ['офд','оператор']): return 'ofd'
    if any(w in c for w in ['диадок','эдо','документ']): return 'edo'
    if any(w in c for w in ['сканер','принтер','ящик']): return 'periphery'
    return 'other'

def parse(content):
    root = ET.fromstring(content)
    shop = root.find('shop')
    cats = {c.get('id'): c.text or '' for c in shop.find('categories').findall('category')}
    products = []
    for o in shop.find('offers').findall('offer'):
        pid      = int(o.get('id', 0))
        name     = o.findtext('name', '')
        price    = float(o.findtext('price', '0') or 0)
        oldprice = float(o.findtext('oldprice', '0') or 0)
        cat_name = cats.get(o.findtext('categoryId',''), '')
        desc     = o.findtext('description', '')
        pics     = [p.text for p in o.findall('picture') if p.text]
        params   = [{'name': p.get('name',''), 'value': p.text or ''} for p in o.findall('param')]
        cat_slug = guess_cat_slug(cat_name)
        slug     = PAGE_SLUGS.get(pid, f'product-{pid}')
        kassa_cfg = KASSA_CFG.get(pid, ('', False, False, slug, '', True))
        products.append({
            'id': pid, 'name': name, 'price': price, 'oldPrice': oldprice,
            'cat': cat_name, 'catSlug': cat_slug,
            'img': pics[0] if pics else '', 'imgs': pics[:4],
            'desc': desc[:220] if desc else '', 'fullDesc': desc,
            'params': params, 'slug': slug,
            'kassaTariff': kassa_cfg[0],
            'hasFn': kassa_cfg[1],
            'isKit': kassa_cfg[2],
            'isKassa': pid in KASSA_CFG,
            'hwParam': kassa_cfg[4] if len(kassa_cfg) > 4 else '',
            'onlineSale': kassa_cfg[5] if len(kassa_cfg) > 5 else True,
        })
    return products

# ──────────────────────────────────────────
# HTML-утилиты
# ──────────────────────────────────────────
def fmt(price):
    return f"{int(price):,}".replace(',', '\u00a0') + '\u00a0₽'

CART_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M3 5H5L7 15H18L21 7H6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="9" cy="20" r="1.5" fill="currentColor"/><circle cx="18" cy="20" r="1.5" fill="currentColor"/></svg>'

def slug_to_url(slug): return f'/{slug}' if slug else '/'

# ──────────────────────────────────────────
# Общий CSS + шапка + футер
# ──────────────────────────────────────────
COMMON_CSS = '''
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preload" href="https://fonts.googleapis.com/css2?family=Onest:wght@400;500;700&display=swap" as="style" onload="this.onload=null;this.rel='stylesheet'">
<noscript><link href="https://fonts.googleapis.com/css2?family=Onest:wght@400;500;700&display=swap" rel="stylesheet"></noscript>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--black:#21212A;--white:#fff;--gray:#F4F4F4;--gray2:#EBEBEB;--muted:#7A7A8A;--orange:#FF6B35;--mint:#00C896;--blue:#3D7FFF;--border:rgba(33,33,42,.1)}
body{font-family:'Onest','Helvetica Neue',Arial,sans-serif;background:#fff;color:var(--black);-webkit-font-smoothing:antialiased}
a{text-decoration:none;color:inherit}
img{display:block;max-width:100%}
button{font-family:inherit;cursor:pointer}

/* HEADER */
.hdr{position:sticky;top:0;z-index:9999;background:var(--black);border-bottom:1px solid rgba(255,255,255,.08)}
.hdr-in{max-width:1280px;margin:0 auto;padding:0 32px;height:60px;display:flex;align-items:center;gap:24px}
.logo{font-size:18px;font-weight:700;color:#fff;letter-spacing:-.3px;flex-shrink:0}
.hdr-nav{flex:1;display:flex;gap:4px}
.hdr-nav a{font-size:14px;color:rgba(255,255,255,.55);padding:7px 14px;border-radius:8px;transition:.15s}
.hdr-nav a:hover{color:#fff;background:rgba(255,255,255,.08)}
.hdr-right{display:flex;align-items:center;gap:10px;flex-shrink:0}
.hdr-phone{font-size:14px;font-weight:700;color:#fff;border-left:1px solid rgba(255,255,255,.1);padding-left:20px}
.hdr-phone small{display:block;font-size:11px;font-weight:400;color:var(--orange)}
.cart-btn{position:relative;width:36px;height:36px;border-radius:10px;border:1px solid rgba(255,255,255,.18);background:transparent;color:#fff;display:flex;align-items:center;justify-content:center;transition:.15s}
.cart-btn:hover{background:rgba(255,255,255,.08)}
.cart-badge{position:absolute;top:-4px;right:-4px;min-width:16px;height:16px;padding:0 4px;background:var(--orange);border-radius:20px;color:#fff;font-size:10px;font-weight:700;line-height:16px;text-align:center;display:none}
.btn-ghost{height:36px;padding:0 16px;border-radius:10px;border:1px solid rgba(255,255,255,.18);background:transparent;color:#fff;font-size:14px;font-weight:500;transition:.15s}
.btn-ghost:hover{background:rgba(255,255,255,.08)}

/* FOOTER */
.footer{background:var(--black);border-top:1px solid rgba(255,255,255,.08);margin-top:80px}
.footer-in{max-width:1280px;margin:0 auto;padding:48px 32px 40px;display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:40px}
.footer-logo{font-size:17px;font-weight:700;color:#fff;margin-bottom:12px}
.footer-desc{font-size:12px;color:rgba(255,255,255,.4);line-height:1.65;max-width:240px;margin-bottom:18px}
.footer-addr{font-size:12px;color:rgba(255,255,255,.4);line-height:1.6;font-style:normal}
.footer-addr strong{color:#fff;display:block;font-size:14px;font-weight:700;margin-bottom:3px}
.fcol h5{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:rgba(255,255,255,.3);margin:0 0 16px}
.fcol a{display:block;font-size:12px;color:rgba(255,255,255,.4);margin-bottom:9px;transition:.15s}
.fcol a:hover{color:#fff}
.footer-bot{max-width:1280px;margin:0 auto;padding:18px 32px;border-top:1px solid rgba(255,255,255,.08);display:flex;align-items:center;justify-content:space-between;font-size:11px;color:rgba(255,255,255,.3)}
.footer-docs{display:flex;gap:20px}.footer-docs a{color:rgba(255,255,255,.3)}
.footer-docs a:hover{color:#fff}

/* TOAST */
.k-toast{position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:var(--black);color:#fff;padding:11px 22px;border-radius:12px;font-size:14px;font-weight:500;z-index:99999;display:flex;align-items:center;gap:8px;opacity:0;pointer-events:none;transition:opacity .3s;white-space:nowrap;border:1px solid rgba(255,255,255,.1)}
.k-toast-ok{color:var(--mint);font-size:17px}

@media(max-width:768px){
  .hdr-in{padding:0 16px}
  .hdr-nav,.hdr-phone,.btn-ghost{display:none}
  .footer-in{grid-template-columns:1fr;padding:32px 16px}
  .footer-bot{flex-direction:column;gap:8px;padding:16px;text-align:center}
}
</style>'''

CART_JS = '''
<script>
function getCart(){try{return JSON.parse(localStorage.getItem('kontur_cart')||'[]')}catch(e){return[]}}
function saveCart(c){localStorage.setItem('kontur_cart',JSON.stringify(c))}
function fmt(n){return Math.round(n).toLocaleString('ru-RU')+'\u00a0₽'}
function updateBadge(){
  var c=getCart(),t=c.reduce(function(s,i){return s+(i.qty||0)},0);
  var b=document.getElementById('cart-badge');
  if(b){b.textContent=t;b.style.display=t>0?'block':'none'}
}
function addToCart(id,name,price){
  var c=getCart(),i=c.findIndex(function(x){return String(x.id)===String(id)});
  if(i>=0){c[i].qty++}else{c.push({id:id,name:name,price:price,qty:1})}
  saveCart(c);updateBadge();
  showToast(name+' добавлен в корзину');
}
function showToast(msg){
  var t=document.getElementById('k-toast'),tx=document.getElementById('k-toast-txt');
  if(tx)tx.textContent=msg;
  if(t){t.style.opacity='1';clearTimeout(t._t);t._t=setTimeout(function(){t.style.opacity='0'},2500)}
}
updateBadge();
window.addEventListener('storage',function(e){if(e.key==='kontur_cart')updateBadge()});
</script>'''

def header(title='Контур — Кассы и торговля', desc=''):
    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
<title>{title}</title>
<meta name="description" content="{desc}">
{COMMON_CSS}
</head>
<body>
<header class="hdr">
  <div class="hdr-in">
    <a href="/kontur-feed/" class="logo">Контур</a>
    <nav class="hdr-nav">
      <a href="/kontur-feed/#kasses">Кассы</a>
      <a href="/kontur-feed/#kits">Комплекты</a>
      <a href="/kontur-feed/#fn-ofd">ФН и ОФД</a>
      <a href="/kontur-feed/#edo">КЭП и ЭДО</a>
      <a href="/kontur-feed/#periphery">Периферия</a>
    </nav>
    <div class="hdr-right">
      <div class="hdr-phone">8 800 500-22-44<small>Бесплатно по России</small></div>
      <a href="/kontur-feed/cart/" class="cart-btn">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M3 5H5L7 15H18L21 7H6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="9" cy="20" r="1.5" fill="currentColor"/><circle cx="18" cy="20" r="1.5" fill="currentColor"/></svg>
        <span class="cart-badge" id="cart-badge">0</span>
      </a>
      <button class="btn-ghost">Войти в сервис</button>
    </div>
  </div>
</header>
<div class="k-toast" id="k-toast"><span class="k-toast-ok">✓</span><span id="k-toast-txt"></span></div>'''

def footer():
    year = datetime.datetime.now().year
    return f'''
<footer class="footer">
  <div class="footer-in">
    <div>
      <div class="footer-logo">Контур</div>
      <div class="footer-desc">Кассы, ФН, ОФД, КЭП, ЭДО — всё в одном месте.</div>
      <address class="footer-addr"><strong>8 800 500-22-44</strong>Бесплатно по России, 24/7</address>
    </div>
    <div class="fcol"><h5>Продукты</h5><a href="#">Контур.Маркет</a><a href="#">Контур.ОФД</a><a href="#">Контур.Диадок</a></div>
    <div class="fcol"><h5>Покупателям</h5><a href="#">Доставка</a><a href="#">Гарантия</a><a href="#">Рассрочка 0%</a></div>
    <div class="fcol"><h5>Компания</h5><a href="#">О Контуре</a><a href="#">Контакты</a></div>
  </div>
  <div class="footer-bot">
    <span>© {year} СКБ Контур. Все права защищены.</span>
    <div class="footer-docs"><a href="#">Политика конфиденциальности</a><a href="#">Реквизиты</a></div>
  </div>
</footer>
{CART_JS}
</body></html>'''

# ──────────────────────────────────────────
# ГЛАВНАЯ СТРАНИЦА
# ──────────────────────────────────────────
def build_index(products, updated):
    by_slug = {}
    for p in products:
        by_slug.setdefault(p['catSlug'], []).append(p)

    def pcard(p):
        url = f"/kontur-feed/{p['slug']}/"
        price_html = f"<span class='old-price'>{fmt(p['oldPrice'])}</span> " if p['oldPrice'] > 0 else ''
        price_html += f"{fmt(p['price'])}"
        return f'''<div class="pcard">
  <a href="{url}" class="pcard-img"><img src="{p['img']}" alt="{p['name']}" loading="lazy"></a>
  <div class="pcard-body">
    <div class="pcard-cat">{p['cat']}</div>
    <a href="{url}" class="pcard-name">{p['name']}</a>
    <div class="pcard-desc">{p['desc'][:120]}</div>
    <div class="pcard-foot">
      <div class="pcard-price">{price_html}</div>
      <div class="pcard-btns">
        <a href="{url}" class="btn-detail">Подробнее</a>
        <button class="btn-cart-sm" onclick="addToCart('{p['id']}','{p['name'].replace(chr(39),chr(92)+chr(39))}',{p['price']})">{CART_SVG} В корзину</button>
      </div>
    </div>
  </div>
</div>'''

    def kcard(p):
        url = f"/kontur-feed/{p['slug']}/"
        return f'''<div class="kcard" onclick="location.href='{url}'">
  <div class="kcard-img"><img src="{p['img']}" alt="{p['name']}" loading="lazy"></div>
  <div class="kcard-body">
    {'<span class="sale-badge">Скидка</span>' if p['oldPrice'] > 0 else ''}
    <div class="kcard-name">{p['name']}</div>
    <div class="kcard-desc">{p['desc'][:120]}</div>
    <div class="kcard-pr">
      {f'<span class="old-price">{fmt(p["oldPrice"])}</span> ' if p['oldPrice']>0 else ''}
      <strong>{fmt(p['price'])}</strong>
    </div>
    <button class="btn-kit" onclick="event.stopPropagation();addToCart('{p['id']}','{p['name'].replace(chr(39),chr(92)+chr(39))}',{p['price']})">{CART_SVG} Купить комплект</button>
  </div>
</div>'''

    sections = {
        'kasses':    ('Кассы и POS-терминалы',    '#FF6B35', 'Кассы',     pcard, 6),
        'kits':      ('Готовые кассовые комплекты','#00C896', 'Комплекты', kcard, 4),
        'fn':        ('Фискальные накопители',     '#3D7FFF', 'ФН и ОФД',  pcard, 4),
        'ofd':       ('Контур.ОФД',               '#3D7FFF', 'ФН и ОФД',  pcard, 3),
        'edo':       ('Электронный документооборот','#7B61FF', 'ЭДО',       pcard, 3),
        'periphery': ('Периферия',                 '#FF6B35', 'Периферия', pcard, 3),
    }

    sections_html = ''
    anchor_map = {'kasses':'kasses','kits':'kits','fn':'fn-ofd','ofd':'fn-ofd','edo':'edo','periphery':'periphery'}
    rendered_anchors = set()

    for slug, (title, color, nav_name, card_fn, limit) in sections.items():
        items = by_slug.get(slug, [])[:limit]
        if not items: continue
        anchor = anchor_map[slug]
        anchor_attr = f' id="{anchor}"' if anchor not in rendered_anchors else ''
        rendered_anchors.add(anchor)
        grid_class = 'kgrid' if slug == 'kits' else 'pgrid'
        sections_html += f'''
<section class="sec"{anchor_attr}>
  <div class="sec-in">
    <div class="sec-hd">
      <div class="sec-eye" style="color:{color}">{nav_name}</div>
      <h2 class="sec-h">{title}</h2>
    </div>
    <div class="{grid_class}">{''.join(card_fn(p) for p in items)}</div>
  </div>
</section>'''

    updated_str = updated[:10]

    return header('Контур — Кассы, ФН, ОФД, ЭДО') + f'''
<style>
.hero{{background:var(--black);padding:56px 0 0}}
.hero-in{{max-width:1280px;margin:0 auto;padding:0 32px}}
.hero-title{{font-size:64px;font-weight:700;letter-spacing:-3px;line-height:1;color:#fff;margin-bottom:40px}}
.hero-cats{{display:flex;gap:0;border-top:1px solid rgba(255,255,255,.1)}}
.hero-cat{{flex:1;padding:24px;border-right:1px solid rgba(255,255,255,.1);color:rgba(255,255,255,.55);font-size:15px;font-weight:500;transition:.2s}}
.hero-cat:hover{{color:#fff;background:rgba(255,255,255,.04)}}
.hero-cat:last-child{{border-right:none}}
.hero-cat.active{{background:#3D7FFF;color:#fff}}
.trust{{border-bottom:1px solid var(--border)}}
.trust-in{{max-width:1280px;margin:0 auto;display:flex}}
.ti{{flex:1;padding:18px 16px;border-right:1px solid var(--border);display:flex;align-items:flex-start;gap:10px}}
.ti:last-child{{border-right:none}}
.ti-ic{{width:36px;height:36px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:15px;flex-shrink:0}}
.ti-ttl{{font-size:12px;font-weight:700;color:var(--black);margin-bottom:2px}}
.ti-sub{{font-size:11px;color:var(--muted);line-height:1.4}}
.sec{{padding:56px 0;border-top:1px solid var(--border)}}
.sec:nth-child(even){{background:var(--gray)}}
.sec-in{{max-width:1280px;margin:0 auto;padding:0 32px}}
.sec-eye{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:8px}}
.sec-h{{font-size:32px;font-weight:700;letter-spacing:-1px;margin-bottom:28px}}
.sec-hd{{margin-bottom:0}}
.pgrid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.kgrid{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}}
.pcard{{border:1.5px solid var(--border);border-radius:16px;overflow:hidden;background:#fff;transition:border-color .2s,box-shadow .2s;display:flex;flex-direction:column}}
.pcard:hover{{border-color:var(--orange);box-shadow:0 0 0 3px rgba(255,107,53,.06)}}
.pcard-img{{background:var(--gray);padding:24px;display:flex;align-items:center;justify-content:center;min-height:180px}}
.pcard-img img{{max-height:140px;width:auto;transition:transform .3s}}
.pcard:hover .pcard-img img{{transform:scale(1.04)}}
.pcard-body{{padding:16px;flex:1;display:flex;flex-direction:column}}
.pcard-cat{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:5px}}
.pcard-name{{font-size:14px;font-weight:700;line-height:1.3;color:var(--black);margin-bottom:6px}}
.pcard-name:hover{{color:var(--orange)}}
.pcard-desc{{font-size:12px;color:var(--muted);line-height:1.5;flex:1;margin-bottom:12px}}
.pcard-price{{font-size:20px;font-weight:700;margin-bottom:10px}}
.pcard-btns{{display:flex;gap:7px}}
.btn-detail{{flex:1;padding:9px;font-size:12px;font-weight:500;color:var(--black);background:transparent;border:1.5px solid var(--border);border-radius:9px;text-align:center;transition:.15s}}
.btn-detail:hover{{background:var(--gray2)}}
.btn-cart-sm{{flex:1;padding:9px;font-size:12px;font-weight:700;color:#fff;background:var(--black);border:none;border-radius:9px;display:flex;align-items:center;justify-content:center;gap:5px;transition:.15s}}
.btn-cart-sm:hover{{opacity:.82}}
.old-price{{font-size:13px;color:var(--muted);text-decoration:line-through;margin-right:4px}}
.kcard{{background:#fff;border:1.5px solid var(--border);border-radius:16px;display:grid;grid-template-columns:160px 1fr;overflow:hidden;cursor:pointer;transition:border-color .2s}}
.kcard:hover{{border-color:var(--mint)}}
.kcard-img{{background:var(--gray);display:flex;align-items:center;justify-content:center;padding:18px}}
.kcard-img img{{max-height:120px;width:auto}}
.kcard-body{{padding:18px;display:flex;flex-direction:column}}
.sale-badge{{font-size:10px;font-weight:700;padding:2px 9px;border-radius:20px;background:rgba(0,200,150,.1);color:var(--mint);display:inline-block;margin-bottom:8px;width:fit-content}}
.kcard-name{{font-size:15px;font-weight:700;margin-bottom:6px}}
.kcard-desc{{font-size:12px;color:var(--muted);line-height:1.5;flex:1;margin-bottom:10px}}
.kcard-pr{{font-size:18px;font-weight:700;margin-bottom:10px}}
.btn-kit{{display:inline-flex;align-items:center;gap:5px;padding:9px 16px;font-size:12px;font-weight:700;background:var(--mint);color:#fff;border:none;border-radius:9px;transition:.15s}}
.btn-kit:hover{{opacity:.88}}
.upd-note{{font-size:11px;color:var(--muted);margin-top:16px}}
.cta{{background:var(--black);padding:72px 0;margin-top:0;border-top:1px solid rgba(255,255,255,.08)}}
.cta-in{{max-width:1280px;margin:0 auto;padding:0 32px;display:grid;grid-template-columns:1fr 1fr;gap:56px;align-items:center}}
.cta h2{{font-size:42px;font-weight:700;letter-spacing:-1.5px;color:#fff;margin-bottom:12px}}
.cta p{{font-size:15px;color:rgba(255,255,255,.5);margin-bottom:28px}}
.cta-btns{{display:flex;gap:10px}}
.btn-cta{{padding:13px 26px;font-size:14px;font-weight:700;background:var(--orange);color:#fff;border:none;border-radius:12px;transition:.15s}}
.btn-cta:hover{{opacity:.88}}
.btn-cta-g{{padding:13px 26px;font-size:14px;color:#fff;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.12);border-radius:12px;transition:.15s}}
.btn-cta-g:hover{{background:rgba(255,255,255,.12)}}
.cta-visual{{display:flex;align-items:flex-end;gap:10px;height:200px}}
.cta-bar{{flex:1;border-radius:12px 12px 0 0}}
@media(max-width:1100px){{.pgrid{{grid-template-columns:repeat(2,1fr)}}.kgrid{{grid-template-columns:1fr}}.cta-in{{grid-template-columns:1fr}}.cta-visual{{display:none}}}}
@media(max-width:768px){{.hero-title{{font-size:36px;letter-spacing:-1.5px}}.hero-cats{{flex-wrap:wrap}}.hero-cat{{width:50%}}.trust-in{{flex-wrap:wrap}}.ti{{width:50%;border-bottom:1px solid var(--border)}}.sec-in{{padding:0 16px}}.pgrid,.kgrid{{grid-template-columns:1fr}}.kcard{{grid-template-columns:120px 1fr}}}}
</style>

<div class="hero">
  <div class="hero-in">
    <div class="hero-title">Торговля<br>и ритейл</div>
    <div class="hero-cats">
      <a href="#kasses" class="hero-cat active">Кассы и торговля</a>
      <a href="#kits" class="hero-cat">Комплекты</a>
      <a href="#fn-ofd" class="hero-cat">ФН и ОФД</a>
      <a href="#edo" class="hero-cat">ЭДО</a>
      <a href="#periphery" class="hero-cat">Периферия</a>
    </div>
  </div>
</div>

<div class="trust">
  <div class="trust-in">
    <div class="ti"><div class="ti-ic" style="background:rgba(255,107,53,.1)">🚚</div><div><div class="ti-ttl">Быстрая доставка</div><div class="ti-sub">Москва 48 ч, Россия от 3 дней</div></div></div>
    <div class="ti"><div class="ti-ic" style="background:rgba(0,200,150,.1)">🛡</div><div><div class="ti-ttl">Гарантия производителя</div><div class="ti-sub">На всё оборудование</div></div></div>
    <div class="ti"><div class="ti-ic" style="background:rgba(61,127,255,.1)">📋</div><div><div class="ti-ttl">Регистрация в ФНС</div><div class="ti-sub">Онлайн за 1 день</div></div></div>
    <div class="ti"><div class="ti-ic" style="background:rgba(123,97,255,.1)">🎧</div><div><div class="ti-ttl">Поддержка 24/7</div><div class="ti-sub">Звонок и выезд специалиста</div></div></div>
    <div class="ti"><div class="ti-ic" style="background:rgba(255,107,53,.1)">💳</div><div><div class="ti-ttl">Рассрочка 0%</div><div class="ti-sub">До 12 месяцев</div></div></div>
  </div>
</div>

{sections_html}

<div class="sec-in" style="padding-bottom:16px;max-width:1280px;margin:0 auto;padding-left:32px">
  <div class="upd-note">Цены обновлены: {updated_str}</div>
</div>

<div class="cta">
  <div class="cta-in">
    <div>
      <h2>Готовы начать?<br>Поможем выбрать.</h2>
      <p>Бесплатная консультация — подберём кассу за 10 минут.</p>
      <div class="cta-btns">
        <button class="btn-cta" onclick="location.href='#kasses'">Выбрать кассу</button>
        <a href="tel:88005002244" class="btn-cta-g">8 800 500-22-44</a>
      </div>
    </div>
    <div class="cta-visual">
      <div class="cta-bar" style="background:var(--orange);height:100%"></div>
      <div class="cta-bar" style="background:var(--mint);height:72%"></div>
      <div class="cta-bar" style="background:var(--blue);height:86%"></div>
      <div class="cta-bar" style="background:#7B61FF;height:57%"></div>
    </div>
  </div>
</div>
''' + footer()

# ──────────────────────────────────────────
# СТРАНИЦА ТОВАРА
# ──────────────────────────────────────────
def build_product(p, all_products, updated):
    pid   = p['id']
    is_kassa = p['isKassa']
    is_kit   = p['isKit']
    has_fn   = p['hasFn']
    tariff   = p['kassaTariff']

    price_html = ''
    if p['oldPrice'] > 0:
        price_html += f'<div class="kp-price-old">{fmt(p["oldPrice"])}</div>'
    price_html += f'<div class="kp-price">{fmt(p["price"])}</div>'

    specs_rows = ''.join(
        f'<tr><td>{par["name"]}</td><td>{par["value"]}</td></tr>'
        for par in p['params']
    ) or '<tr><td colspan="2" style="color:var(--muted)">Уточняйте у менеджера</td></tr>'

    related = [x for x in all_products if x['id'] != pid and x['catSlug'] == p['catSlug']][:3]
    related_html = ''
    if related:
        cards = ''.join(f'''<a href="/kontur-feed/{r['slug']}/" class="rel-card">
  <div class="rel-img"><img src="{r['img']}" alt="{r['name']}" loading="lazy"></div>
  <div class="rel-body">
    <div class="rel-cat">{r['cat']}</div>
    <div class="rel-name">{r['name']}</div>
    <div class="rel-price">{fmt(r['price'])}</div>
    <button class="btn-rel" onclick="event.stopPropagation();addToCart('{r['id']}','{r['name'].replace(chr(39),chr(92)+chr(39))}',{r['price']})">{CART_SVG} В корзину</button>
  </div>
</a>''' for r in related)
        related_html = f'<section class="rel"><div class="sec-in"><h2 class="rel-title">С этим покупают</h2><div class="rel-grid">{cards}</div></div></section>'

    fn_step = ''
    if is_kassa and not is_kit:
        fn_step = '''<div class="cfg-step">
    <div class="cfg-ttl">4. Фискальный накопитель</div>
    <div class="cfg-opts" id="cfg-fn">
      <button class="cfg-opt" data-val="15" data-price="15900" onclick="cfgSel(this,'fn')">15 мес. <span class="cfg-p">15 900 ₽</span></button>
      <button class="cfg-opt on" data-val="36" data-price="23100" onclick="cfgSel(this,'fn')">36 мес. <span class="cfg-p">23 100 ₽</span></button>
    </div>
    <div class="cfg-hint" id="cfg-fn-hint">💡 Для розницы и услуг рекомендуем 36 мес.</div>
  </div>'''

    ofd_num = '4' if is_kit else '5'
    cfg_html = ''
    if is_kassa:
        cfg_html = f'''<div class="cfg">
  <div class="cfg-lbl">{'Настройте комплект' if is_kit else 'Скомплектуйте кассу'}</div>
  <div class="cfg-step">
    <div class="cfg-ttl">1. Ваша отрасль</div>
    <div class="cfg-opts" id="cfg-industry">
      <button class="cfg-opt on" data-val="retail" onclick="cfgSel(this,'industry')">🛒 Розница</button>
      <button class="cfg-opt" data-val="food" onclick="cfgSel(this,'industry')">🍕 Общепит</button>
      <button class="cfg-opt" data-val="service" onclick="cfgSel(this,'industry')">✂️ Услуги</button>
    </div>
  </div>
  <div class="cfg-step">
    <div class="cfg-ttl">2. Контур.Маркет — тариф</div>
    <div class="cfg-opts" id="cfg-tier">
      <button class="cfg-opt" data-val="base" onclick="cfgSel(this,'tier')">Базовый</button>
      <button class="cfg-opt on" data-val="optimal" onclick="cfgSel(this,'tier')">Оптимальный</button>
      <button class="cfg-opt" data-val="premium" onclick="cfgSel(this,'tier')">Премиум</button>
    </div>
  </div>
  <div class="cfg-step">
    <div class="cfg-ttl">3. Срок ПО</div>
    <div class="cfg-opts" id="cfg-soft">
      <button class="cfg-opt on" data-val="3" data-price="3990" onclick="cfgSel(this,'soft')">3 мес. <span class="cfg-p">от 3 990 ₽</span></button>
      <button class="cfg-opt" data-val="12" data-price="12990" onclick="cfgSel(this,'soft')">12 мес. <span class="cfg-p">от 12 990 ₽</span></button>
    </div>
  </div>
  {fn_step}
  <div class="cfg-step">
    <div class="cfg-ttl">{ofd_num}. Контур.ОФД</div>
    <div class="cfg-opts" id="cfg-ofd">
      <button class="cfg-opt" data-val="13" data-price="5000" onclick="cfgSel(this,'ofd')">13 мес. <span class="cfg-p">5 000 ₽</span></button>
      <button class="cfg-opt on" data-val="15" data-price="5300" onclick="cfgSel(this,'ofd')">15 мес. <span class="cfg-p">5 300 ₽</span></button>
      <button class="cfg-opt" data-val="36" data-price="12000" onclick="cfgSel(this,'ofd')">36 мес. <span class="cfg-p">12 000 ₽</span></button>
    </div>
  </div>
  <div class="cfg-tot">
    <div id="cfg-rows"></div>
    <div class="cfg-sum"><span class="cfg-sum-lbl">Итого</span><span class="cfg-sum-val" id="cfg-total">—</span></div>
    <div class="cfg-note">💡 Цена ПО зависит от региона. Точная стоимость — в KStore.</div>
  </div>
</div>'''

    online_sale = p.get('onlineSale', True)
    hw_param    = p.get('hwParam', '')
    buy_click   = 'cfgBuy()' if is_kassa else f"addToCart('{pid}','{p['name'].replace(chr(39),chr(92)+chr(39))}',{p['price']})"
    buy_label   = 'Получить консультацию' if not online_sale else 'В корзину'
    js_vars = f'''var P_ID={pid};var P_PRICE={p['price']};var P_NAME='{p['name'].replace(chr(39),chr(92)+chr(39))}';
var IS_KASSA={'true' if is_kassa else 'false'};var IS_KIT={'true' if is_kit else 'false'};
var HAS_FN={'true' if has_fn else 'false'};var TARIFF='{tariff}';
var HW_PARAM='{hw_param}';var ONLINE_SALE={'true' if online_sale else 'false'};'''

    cfg_js = '''
var CFG={industry:'retail',tier:'optimal',soft:{val:'3',price:3990},fn:{val:'36',price:23100},ofd:{val:'15',price:5300}};
var SP={base:{'3':1490,'12':4990},optimal:{'3':3990,'12':12990},premium:{'3':6990,'12':19990}};
var SM={retail:{base:'base_retail',optimal:'optimal_retail',premium:'premium_retail'},food:{base:'base_cathering',optimal:'optimal_cathering',premium:'premium_cathering'},service:{base:'base_service',optimal:'optimal_service',premium:'premium_service'}};
var FH={retail:'💡 Для розницы рекомендуем 36 мес.',food:'💡 Для общепита — 15 или 36 мес.',service:'💡 Для услуг рекомендуем 36 мес.'};
function cfgSel(el,g){
  document.getElementById('cfg-'+g).querySelectorAll('.cfg-opt').forEach(function(o){o.classList.remove('on')});
  el.classList.add('on');
  var val=el.getAttribute('data-val'),pr=parseInt(el.getAttribute('data-price')||'0');
  if(g==='industry'){
    CFG.industry=val;
    var rec=val==='food'?'15':'36';
    var fp=document.getElementById('cfg-fn');
    if(fp)fp.querySelectorAll('.cfg-opt').forEach(function(o){
      o.classList.remove('on');
      if(o.getAttribute('data-val')===rec){o.classList.add('on');CFG.fn={val:rec,price:parseInt(o.getAttribute('data-price')||'0')}}
    });
    var h=document.getElementById('cfg-fn-hint');if(h)h.textContent=FH[val]||'';
  }else if(g==='tier'){
    CFG.tier=val;
    document.getElementById('cfg-soft').querySelectorAll('.cfg-opt').forEach(function(o){
      var v=o.getAttribute('data-val'),p2=(SP[val]||{})[v]||0;
      o.setAttribute('data-price',p2);
      var s=o.querySelector('.cfg-p');if(s)s.textContent='от '+p2.toLocaleString('ru-RU')+' ₽';
    });
    CFG.soft.price=(SP[val]||{})[CFG.soft.val]||CFG.soft.price;
  }else if(g==='soft'){CFG.soft={val:val,price:(SP[CFG.tier]||{})[val]||pr};
  }else if(g==='fn'){CFG.fn={val:val,price:pr};
  }else if(g==='ofd'){CFG.ofd={val:val,price:pr}}
  cfgRecalc();
}
function cfgRecalc(){
  var total=P_PRICE+CFG.soft.price+(IS_KIT?0:CFG.fn.price)+CFG.ofd.price;
  var rows=document.getElementById('cfg-rows'),tv=document.getElementById('cfg-total');
  if(rows)rows.innerHTML=
    '<div class="cfg-row"><span>'+P_NAME+'</span><span>'+fmt(P_PRICE)+'</span></div>'+
    '<div class="cfg-row"><span>Маркет '+CFG.tier+' '+CFG.soft.val+' мес.</span><span style="color:var(--muted)">от '+fmt(CFG.soft.price)+'</span></div>'+
    (IS_KIT?'<div class="cfg-row"><span>ФН</span><span style="color:var(--mint)">включён</span></div>':'<div class="cfg-row"><span>ФН '+CFG.fn.val+' мес.</span><span>'+fmt(CFG.fn.price)+'</span></div>')+
    '<div class="cfg-row"><span>ОФД '+CFG.ofd.val+' мес.</span><span>'+fmt(CFG.ofd.price)+'</span></div>';
  if(tv)tv.textContent='от '+fmt(total);
}
function cfgBuy(){
  if(!ONLINE_SALE){
    /* EdPOS и PayTor — только заявка на менеджера */
    window.location.href='tel:88005002244';
    return;
  }
  var c=getCart();
  function add(id,nm,pr){var i=c.findIndex(function(x){return String(x.id)===String(id)});if(i>=0){c[i].qty++}else{c.push({id:id,name:nm,price:pr,qty:1})}}
  add(P_ID,P_NAME,P_PRICE);
  add('soft_'+CFG.tier+'_'+CFG.soft.val,'Маркет '+CFG.tier+' '+CFG.soft.val+' мес.',CFG.soft.price);
  if(HAS_FN&&!IS_KIT)add(CFG.fn.val==='15'?16:17,'ФН '+CFG.fn.val+' мес.',CFG.fn.price);
  add(CFG.ofd.val==='13'?20:CFG.ofd.val==='15'?21:22,'ОФД '+CFG.ofd.val+' мес.',CFG.ofd.price);
  saveCart(c);
  var st=(SM[CFG.industry]||{})[CFG.tier]||'optimal_retail';
  /* Формируем тарифы:
     ФН = всегда ofd_kontur_fn (отдельный тариф), months=15 или 36
     km_printer: доп параметр Hardware.Printer
     km_modulecashbox: доп параметр Fn (число) */
  var tariffList = TARIFF+','+st+',km_ofd'+(HAS_FN&&!IS_KIT?',ofd_kontur_fn':'');
  var params = '';
  if(HW_PARAM) params += '&'+TARIFF+'.Hardware.Printer='+HW_PARAM;
  if(TARIFF==='km_modulecashbox_mspos_f20_f'&&HAS_FN&&!IS_KIT) params += '&'+TARIFF+'.Fn='+CFG.fn.val;
  params += '&'+st+'.months='+CFG.soft.val;
  params += '&km_ofd.months='+CFG.ofd.val;
  if(HAS_FN&&!IS_KIT) params += '&ofd_kontur_fn.months='+CFG.fn.val;
  params += '&backurl='+encodeURIComponent(window.location.href);
  localStorage.setItem('kontur_kstore_url','https://online-sales.kontur.ru/sale?tariffs='+tariffList+params);
  updateBadge();showToast('Комплект добавлен в корзину');
  var btn=document.getElementById('btn-buy');
  if(btn){btn.style.background='var(--mint)';btn.textContent='✓ Добавлено!';setTimeout(function(){btn.style.background='';btn.innerHTML='🛒 В корзину'},2000)}
}
cfgRecalc();''' if is_kassa else ''

    return header(f'{p["name"]} — Контур', p['desc']) + f'''
<style>
.kp-wrap{{max-width:1280px;margin:0 auto;padding:32px 40px 64px}}
.bc{{font-size:13px;color:var(--muted);margin-bottom:28px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.bc a{{color:var(--muted)}}.bc a:hover{{color:var(--black)}}.bc-s{{opacity:.4}}
.kp-grid{{display:grid;grid-template-columns:1fr 460px;gap:56px;align-items:start}}
.kp-gal{{position:sticky;top:76px}}
.kp-img{{background:var(--gray);border-radius:18px;padding:36px;display:flex;align-items:center;justify-content:center;min-height:400px}}
.kp-img img{{max-height:320px;width:auto}}
.kp-cat{{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--orange);margin-bottom:10px}}
.kp-name{{font-size:30px;font-weight:700;letter-spacing:-.8px;line-height:1.15;margin-bottom:14px}}
.kp-short{{font-size:15px;color:var(--muted);line-height:1.65;margin-bottom:18px}}
.kp-pbox{{background:var(--gray);border-radius:14px;padding:20px;margin-bottom:18px}}
.kp-price{{font-size:36px;font-weight:700;letter-spacing:-1px;margin-bottom:4px}}
.kp-price-old{{font-size:14px;color:var(--muted);text-decoration:line-through;margin-bottom:4px}}
.kp-price-note{{font-size:12px;color:var(--muted);margin-bottom:8px}}
.kp-avail{{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:500}}
.kp-dot{{width:8px;height:8px;border-radius:50%;background:var(--mint);flex-shrink:0}}
.kp-upd{{font-size:11px;color:var(--muted);margin-top:6px}}
.cfg{{border:1.5px solid var(--border);border-radius:14px;padding:18px;margin-bottom:18px;background:var(--gray)}}
.cfg-lbl{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.8px;color:var(--orange);margin-bottom:14px}}
.cfg-step{{margin-bottom:14px}}
.cfg-ttl{{font-size:13px;font-weight:700;margin-bottom:8px}}
.cfg-opts{{display:flex;flex-wrap:wrap;gap:7px}}
.cfg-opt{{padding:7px 13px;font-size:13px;font-weight:500;border:1.5px solid var(--border);border-radius:10px;background:#fff;cursor:pointer;transition:.15s;display:flex;align-items:center;gap:7px;color:var(--black)}}
.cfg-opt:hover{{border-color:var(--orange)}}.cfg-opt.on{{border-color:var(--orange);background:rgba(255,107,53,.06);color:var(--orange);font-weight:700}}
.cfg-p{{font-size:11px;font-weight:700;padding:2px 6px;background:var(--gray2);border-radius:5px;color:var(--muted)}}
.cfg-opt.on .cfg-p{{background:rgba(255,107,53,.12);color:var(--orange)}}
.cfg-hint{{font-size:12px;color:var(--muted);margin-top:6px;line-height:1.5}}
.cfg-tot{{border-top:1.5px solid var(--border);margin-top:14px;padding-top:12px}}
.cfg-row{{display:flex;justify-content:space-between;font-size:13px;color:var(--muted);margin-bottom:4px}}
.cfg-row span:last-child{{font-weight:500;color:var(--black)}}
.cfg-sum{{display:flex;justify-content:space-between;align-items:center;background:#fff;border-radius:10px;padding:11px 14px;border:1.5px solid var(--border);margin-top:10px}}
.cfg-sum-lbl{{font-size:14px;font-weight:700}}.cfg-sum-val{{font-size:22px;font-weight:700;color:var(--orange)}}
.cfg-note{{font-size:11px;color:var(--muted);margin-top:7px;line-height:1.5}}
.kp-btns{{display:flex;gap:10px;margin-bottom:10px}}
#btn-buy{{flex:1;padding:14px;font-size:15px;font-weight:700;background:var(--black);color:#fff;border:none;border-radius:12px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;transition:.15s}}
#btn-buy:hover{{opacity:.82}}
.btn-fav{{width:50px;height:50px;border-radius:12px;border:1.5px solid var(--border);background:transparent;color:var(--muted);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;transition:.15s}}
.btn-fav:hover{{color:var(--orange);border-color:var(--orange)}}
.btn-consult{{width:100%;padding:12px;font-size:14px;font-weight:500;background:transparent;color:var(--black);border:1.5px solid var(--border);border-radius:12px;cursor:pointer;transition:.15s}}
.btn-consult:hover{{background:var(--gray2)}}
.kp-meta{{display:flex;flex-direction:column;gap:9px;margin:14px 0}}
.kp-mi{{display:flex;align-items:flex-start;gap:9px;font-size:13px}}
.kp-mi-ic{{font-size:15px;flex-shrink:0}}.kp-mi-tx{{color:var(--muted);line-height:1.5}}.kp-mi-tx strong{{color:var(--black)}}
.kp-tabs{{margin-top:36px;border-top:1px solid var(--border)}}
.tabs-nav{{display:flex;border-bottom:1px solid var(--border)}}
.tab-btn{{padding:12px 16px;font-size:14px;font-weight:500;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;background:none;border-top:none;border-left:none;border-right:none}}
.tab-btn.on{{color:var(--black);border-bottom-color:var(--orange);font-weight:700}}
.tab-pane{{display:none;padding:20px 0}}.tab-pane.on{{display:block}}
.specs-tbl{{width:100%;border-collapse:collapse;font-size:14px}}
.specs-tbl tr{{border-bottom:1px solid var(--border)}}
.specs-tbl td{{padding:10px 0;vertical-align:top}}
.specs-tbl td:first-child{{color:var(--muted);width:44%;padding-right:16px}}
.specs-tbl td:last-child{{font-weight:500}}
.del-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.del-card{{border:1.5px solid var(--border);border-radius:12px;padding:16px}}
.del-ic{{font-size:20px;margin-bottom:7px}}.del-nm{{font-size:14px;font-weight:700;margin-bottom:4px}}
.del-ds{{font-size:13px;color:var(--muted);line-height:1.5}}.del-pr{{font-size:13px;font-weight:700;color:var(--mint);margin-top:6px}}
.rel{{padding:56px 0;border-top:1px solid var(--border)}}
.rel-title{{font-size:26px;font-weight:700;letter-spacing:-.5px;margin-bottom:20px}}
.rel-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.rel-card{{border:1.5px solid var(--border);border-radius:14px;overflow:hidden;cursor:pointer;transition:border-color .2s;display:block}}
.rel-card:hover{{border-color:var(--orange)}}
.rel-img{{background:var(--gray);padding:20px;display:flex;align-items:center;justify-content:center;min-height:140px}}
.rel-img img{{max-height:110px;width:auto}}
.rel-body{{padding:14px}}
.rel-cat{{font-size:10px;font-weight:700;text-transform:uppercase;color:var(--muted);margin-bottom:5px}}
.rel-name{{font-size:13px;font-weight:700;line-height:1.3;margin-bottom:7px;color:var(--black)}}
.rel-price{{font-size:16px;font-weight:700;margin-bottom:9px}}
.btn-rel{{width:100%;padding:8px;font-size:12px;font-weight:700;background:var(--black);color:#fff;border:none;border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:4px}}
.btn-rel:hover{{opacity:.8}}
@media(max-width:1100px){{.kp-grid{{grid-template-columns:1fr}}.kp-gal{{position:static}}.rel-grid{{grid-template-columns:1fr 1fr}}}}
@media(max-width:768px){{.kp-wrap{{padding:20px 16px 48px}}.kp-name{{font-size:24px}}.del-grid{{grid-template-columns:1fr}}.rel-grid{{grid-template-columns:1fr}}}}
</style>

<div class="kp-wrap">
  <div class="bc"><a href="/kontur-feed/">Главная</a><span class="bc-s">›</span><span>{p['cat']}</span><span class="bc-s">›</span><span>{p['name']}</span></div>
  <div class="kp-grid">
    <div class="kp-gal">
      <div class="kp-img">{'<img src="'+p["img"]+'" alt="'+p["name"]+'" loading="lazy">' if p['img'] else ''}</div>
    </div>
    <div>
      <div class="kp-cat">{p['cat']}</div>
      <h1 class="kp-name">{p['name']}</h1>
      <p class="kp-short">{p['desc']}</p>
      <div class="kp-pbox">
        {price_html}
        {'<div class="kp-price-note">Цена кассы без комплектации</div>' if is_kassa and not is_kit else ''}
        <div class="kp-avail"><span class="kp-dot"></span> В наличии, доставка 48 часов</div>
        <div class="kp-upd">Цена обновлена: {updated[:10]}</div>
      </div>
      {cfg_html}
      <div class="kp-btns">
        <button id="btn-buy" onclick="{buy_click}">
          {CART_SVG} {buy_label}
        </button>
        <button class="btn-fav">♡</button>
      </div>
      <button class="btn-consult">Получить консультацию</button>
      <div class="kp-meta">
        <div class="kp-mi"><span class="kp-mi-ic">🚚</span><div class="kp-mi-tx"><strong>Доставка по Москве — 48 часов.</strong> По России от 3 рабочих дней.</div></div>
        <div class="kp-mi"><span class="kp-mi-ic">🛡</span><div class="kp-mi-tx"><strong>Гарантия производителя.</strong></div></div>
        <div class="kp-mi"><span class="kp-mi-ic">📋</span><div class="kp-mi-tx"><strong>Регистрируем кассу в ФНС</strong> за 1 день.</div></div>
        <div class="kp-mi"><span class="kp-mi-ic">💳</span><div class="kp-mi-tx"><strong>Рассрочка 0%</strong> до 12 месяцев.</div></div>
      </div>
      <div class="kp-tabs">
        <div class="tabs-nav">
          <button class="tab-btn on" onclick="openTab(this,'t-desc')">Описание</button>
          <button class="tab-btn" onclick="openTab(this,'t-specs')">Характеристики</button>
          <button class="tab-btn" onclick="openTab(this,'t-del')">Доставка</button>
        </div>
        <div id="t-desc" class="tab-pane on"><p style="font-size:15px;line-height:1.7">{p['fullDesc']}</p></div>
        <div id="t-specs" class="tab-pane"><table class="specs-tbl"><tbody>{specs_rows}</tbody></table></div>
        <div id="t-del" class="tab-pane">
          <div class="del-grid">
            <div class="del-card"><div class="del-ic">🚀</div><div class="del-nm">Москва и МО — 48 часов</div><div class="del-ds">Курьером.</div><div class="del-pr">Бесплатно от 5 000 ₽</div></div>
            <div class="del-card"><div class="del-ic">📦</div><div class="del-nm">Россия — от 3 дней</div><div class="del-ds">СДЭК или Почта России.</div><div class="del-pr">По тарифу СДЭК</div></div>
            <div class="del-card"><div class="del-ic">🏪</div><div class="del-nm">Самовывоз</div><div class="del-ds">Пункты выдачи Контура.</div><div class="del-pr">Бесплатно</div></div>
            <div class="del-card"><div class="del-ic">💳</div><div class="del-nm">Рассрочка 0%</div><div class="del-ds">До 12 месяцев.</div><div class="del-pr">Только паспорт</div></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
{related_html}
<script>
{js_vars}
function openTab(btn,id){{document.querySelectorAll('.tab-btn').forEach(function(b){{b.classList.remove('on')}});document.querySelectorAll('.tab-pane').forEach(function(p){{p.classList.remove('on')}});btn.classList.add('on');document.getElementById(id).classList.add('on')}}
{cfg_js}
</script>
''' + footer()

# ──────────────────────────────────────────
# КОРЗИНА
# ──────────────────────────────────────────
def build_cart():
    return header('Корзина — Контур') + '''
<style>
.cart-wrap{max-width:1280px;margin:0 auto;padding:48px 40px 72px}
.cart-layout{display:grid;grid-template-columns:1fr 380px;gap:40px;align-items:flex-start}
.cart-steps{display:flex;align-items:center;margin-bottom:32px}
.cs{display:flex;align-items:center;gap:8px}
.cs-num{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0}
.cs.active .cs-num{background:var(--orange);color:#fff}
.cs.pending .cs-num{background:var(--gray2);color:var(--muted)}
.cs-lbl{font-size:13px;font-weight:500}
.cs.active .cs-lbl{color:var(--black);font-weight:700}
.cs.pending .cs-lbl{color:var(--muted)}
.cs-line{flex:1;height:1px;background:var(--border);margin:0 8px}
.cart-title{font-size:36px;font-weight:700;letter-spacing:-1px;margin-bottom:8px}
.cart-sub{font-size:15px;color:var(--muted);margin-bottom:32px}
.cart-items{display:flex;flex-direction:column}
.ci{display:grid;grid-template-columns:100px 1fr auto;gap:20px;align-items:center;padding:24px 0;border-bottom:1px solid var(--border)}
.ci:first-child{border-top:1px solid var(--border)}
.ci-img{background:var(--gray);border-radius:12px;width:100px;height:100px;display:flex;align-items:center;justify-content:center;overflow:hidden;flex-shrink:0}
.ci-img img{max-width:80px;max-height:80px;object-fit:contain}
.ci-cat{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:6px}
.ci-name{font-size:15px;font-weight:700;line-height:1.3;margin-bottom:8px}
.ci-del{font-size:12px;color:var(--muted);cursor:pointer;transition:.15s;display:inline-flex;align-items:center;gap:4px}
.ci-del:hover{color:#E84040}
.ci-right{display:flex;flex-direction:column;align-items:flex-end;gap:12px}
.ci-price{font-size:20px;font-weight:700;white-space:nowrap}
.ci-qty{display:flex;align-items:center;border:1.5px solid var(--border);border-radius:10px;overflow:hidden}
.qty-btn{width:36px;height:36px;border:none;background:transparent;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-weight:700;transition:.15s}
.qty-btn:hover{background:var(--gray)}
.qty-num{width:40px;height:36px;border:none;border-left:1.5px solid var(--border);border-right:1.5px solid var(--border);text-align:center;font-size:14px;font-weight:700;background:transparent;outline:none;font-family:inherit}
.empty{text-align:center;padding:80px 0}
.empty-icon{font-size:56px;margin-bottom:20px;opacity:.25}
.empty h2{font-size:24px;font-weight:700;margin-bottom:10px}
.empty p{font-size:15px;color:var(--muted);margin-bottom:28px}
.btn-go{padding:13px 28px;font-size:15px;font-weight:700;background:var(--orange);color:#fff;border:none;border-radius:12px;cursor:pointer}
.sidebar{position:sticky;top:80px}
.order-card{background:var(--gray);border-radius:20px;padding:28px;margin-bottom:16px}
.order-ttl{font-size:18px;font-weight:700;margin-bottom:20px}
.order-row{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border);font-size:14px}
.order-row:last-of-type{border-bottom:none}
.order-row-lbl{color:var(--muted)}
.order-total{display:flex;justify-content:space-between;align-items:center;margin-top:16px;padding-top:16px;border-top:2px solid var(--border)}
.order-total-lbl{font-size:15px;font-weight:700}
.order-total-val{font-size:26px;font-weight:700}
.btn-checkout{width:100%;padding:16px;font-size:16px;font-weight:700;background:var(--orange);color:#fff;border:none;border-radius:14px;cursor:pointer;margin-top:16px;transition:opacity .15s}
.btn-checkout:hover{opacity:.88}
.btn-continue{width:100%;padding:14px;font-size:14px;font-weight:500;background:transparent;color:var(--black);border:1.5px solid var(--border);border-radius:14px;cursor:pointer;margin-top:8px}
.btn-continue:hover{background:var(--gray2)}
.order-note{font-size:12px;color:var(--muted);text-align:center;margin-top:12px;line-height:1.5}
.trust-mini{display:flex;flex-direction:column;gap:10px}
.tm{display:flex;align-items:center;gap:10px;font-size:13px}
.tm-ic{width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}
@media(max-width:1100px){.cart-layout{grid-template-columns:1fr}.sidebar{position:static}}
@media(max-width:768px){.cart-wrap{padding:24px 16px 48px}.ci{grid-template-columns:80px 1fr}.ci-right{flex-direction:row;align-items:center;grid-column:1/-1}}
</style>

<div class="cart-wrap">
  <div class="cart-steps">
    <div class="cs active"><div class="cs-num">1</div><span class="cs-lbl">Корзина</span></div>
    <div class="cs-line"></div>
    <div class="cs pending"><div class="cs-num">2</div><span class="cs-lbl">Оформление</span></div>
    <div class="cs-line"></div>
    <div class="cs pending"><div class="cs-num">3</div><span class="cs-lbl">Оплата</span></div>
    <div class="cs-line"></div>
    <div class="cs pending"><div class="cs-num">4</div><span class="cs-lbl">Готово</span></div>
  </div>
  <div class="cart-layout">
    <div>
      <div class="cart-title">Корзина</div>
      <div class="cart-sub" id="cart-sub"></div>
      <div class="cart-items" id="cart-items"></div>
      <div class="empty" id="cart-empty" style="display:none">
        <div class="empty-icon">🛒</div>
        <h2>Корзина пуста</h2>
        <p>Добавьте товары из каталога</p>
        <button class="btn-go" onclick="location.href='/kontur-feed/'">Перейти в каталог</button>
      </div>
    </div>
    <div class="sidebar" id="cart-sidebar" style="display:none">
      <div class="order-card">
        <div class="order-ttl">Итого заказа</div>
        <div class="order-row"><span class="order-row-lbl">Товары</span><span id="s-qty">0 шт.</span></div>
        <div class="order-row"><span class="order-row-lbl">Сумма</span><span id="s-sub">0 ₽</span></div>
        <div class="order-row"><span class="order-row-lbl">Доставка</span><span style="color:var(--mint)">Бесплатно</span></div>
        <div class="order-total"><span class="order-total-lbl">К оплате</span><span class="order-total-val" id="s-total">0 ₽</span></div>
        <button class="btn-checkout" id="btn-checkout">Оформить заказ →</button>
        <button class="btn-continue" onclick="location.href='/kontur-feed/'">Продолжить покупки</button>
        <div class="order-note">Нажимая «Оформить заказ», вы соглашаетесь с условиями публичной оферты</div>
      </div>
      <div class="trust-mini">
        <div class="tm"><div class="tm-ic" style="background:rgba(0,200,150,.1)">🛡</div><div><strong>Гарантия возврата</strong> 14 дней</div></div>
        <div class="tm"><div class="tm-ic" style="background:rgba(255,107,53,.1)">🚚</div><div><strong>Доставка</strong> по Москве 48 ч</div></div>
        <div class="tm"><div class="tm-ic" style="background:rgba(61,127,255,.1)">📋</div><div><strong>Регистрация ККТ</strong> в ФНС за 1 день</div></div>
      </div>
    </div>
  </div>
</div>

<script>
var IMGS={
  4:'https://kontur.ru/Files/Modules/YmlOffer/4i/4b83aa41-cf8f-4132-8810-3595c71b2f06.png?t=1776773407',
  5:'https://kontur.ru/Files/Modules/YmlOffer/5i/6840b2ac-6992-41c3-9291-a48c6d191de9.png?t=1776773632',
  6:'https://kontur.ru/Files/Modules/YmlOffer/6i/7419be63-9635-49cb-8e93-b9ab776297cf.png?t=1776774940',
  7:'https://kontur.ru/Files/Modules/YmlOffer/7i/dcc04420-04d5-4d9c-9a3f-cdb61cb78421.png?t=1776775279',
  8:'https://kontur.ru/Files/Modules/YmlOffer/8i/5b806055-430b-49c4-8e87-96d338f23c6c.png?t=1777896735',
  9:'https://kontur.ru/Files/Modules/YmlOffer/9i/06382d5f-0aae-4ace-915d-9abdc11e8f88.png?t=1776775508',
  10:'https://kontur.ru/Files/Modules/YmlOffer/10i/b74daaed-5b8a-4b03-ba71-a3ba3e01e4c1.png?t=1776776083',
  11:'https://kontur.ru/Files/Modules/YmlOffer/11i/3e0edf39-6ee5-4e08-a289-b7e0b45f69d6.png?t=1776778394',
  12:'https://kontur.ru/Files/Modules/YmlOffer/12i/8f7e876f-8da2-44a5-af73-3e617ae5d201.png?t=1776778742',
  13:'https://kontur.ru/Files/Modules/YmlOffer/13i/f82380ac-4d85-4bae-8a7d-30073b1d8908.png?t=1776778991',
  14:'https://kontur.ru/Files/Modules/YmlOffer/14i/35822efc-46fe-4dcf-8c8a-01d0be4f45f2.png?t=1776779206',
  15:'https://kontur.ru/Files/Modules/YmlOffer/15i/a15c53bc-5a93-4dd7-91ed-55cbc9394bae.png?t=1776779764',
  16:'https://kontur.ru/Files/Modules/YmlOffer/16i/45da6129-24cb-4749-b7d3-348c1573031a.png?t=1776847251',
  17:'https://kontur.ru/Files/Modules/YmlOffer/17i/84156a88-4490-432b-8b2d-7b05d35d7995.png?t=1776847304',
  20:'https://kontur.ru/Files/Modules/YmlOffer/20i/38066f1f-bfd8-4b87-8907-3b302e78786f.png?t=1776847613',
  21:'https://kontur.ru/Files/Modules/YmlOffer/21i/c1d0d06f-9bf6-436c-8424-1ca573181c5b.png?t=1776847659',
  22:'https://kontur.ru/Files/Modules/YmlOffer/22i/e42c0cd8-d6a6-4ea0-aa01-32b8aad41e53.png?t=1776847696',
  23:'https://kontur.ru/Files/Modules/YmlOffer/23i/f9daf0dd-069d-416e-8ed5-9b975a73bed2.png?t=1776848196',
  24:'https://kontur.ru/Files/Modules/YmlOffer/24i/ba750184-ea7a-4cdf-a327-f8fb8bc9c60d.png?t=1776848258',
  25:'https://kontur.ru/Files/Modules/YmlOffer/25i/9f5d7a94-2943-402f-b4d2-0582ba179b4b.png?t=1776848353',
  'soft_base_3':'https://s.kontur.ru/common-v2/icons-products/market/avatar/market-avatar-512.png',
  'soft_optimal_3':'https://s.kontur.ru/common-v2/icons-products/market/avatar/market-avatar-512.png',
  'soft_premium_3':'https://s.kontur.ru/common-v2/icons-products/market/avatar/market-avatar-512.png',
  'soft_base_12':'https://s.kontur.ru/common-v2/icons-products/market/avatar/market-avatar-512.png',
  'soft_optimal_12':'https://s.kontur.ru/common-v2/icons-products/market/avatar/market-avatar-512.png',
  'soft_premium_12':'https://s.kontur.ru/common-v2/icons-products/market/avatar/market-avatar-512.png'
};

function removeItem(id){saveCart(getCart().filter(function(i){return String(i.id)!==String(id)}));renderCart()}
function changeQty(id,d){var c=getCart(),i=c.findIndex(function(x){return String(x.id)===String(id)});if(i<0)return;c[i].qty=Math.max(1,c[i].qty+d);saveCart(c);renderCart()}
function setQty(id,v){var c=getCart(),i=c.findIndex(function(x){return String(x.id)===String(id)});if(i<0)return;c[i].qty=Math.max(1,parseInt(v)||1);saveCart(c);renderCart()}

function renderCart(){
  var cart=getCart();
  var itemsEl=document.getElementById('cart-items'),emptyEl=document.getElementById('cart-empty'),sidebarEl=document.getElementById('cart-sidebar'),subEl=document.getElementById('cart-sub');
  var tQty=cart.reduce(function(s,i){return s+i.qty},0),tSum=cart.reduce(function(s,i){return s+i.qty*i.price},0);
  if(subEl)subEl.textContent=tQty>0?tQty+' '+(tQty===1?'товар':tQty<5?'товара':'товаров')+' на '+fmt(tSum):'';
  var b=document.getElementById('cart-badge');if(b){b.textContent=tQty;b.style.display=tQty>0?'block':'none'}
  if(!cart.length){if(itemsEl)itemsEl.innerHTML='';if(emptyEl)emptyEl.style.display='block';if(sidebarEl)sidebarEl.style.display='none';return}
  if(emptyEl)emptyEl.style.display='none';if(sidebarEl)sidebarEl.style.display='block';
  if(itemsEl)itemsEl.innerHTML=cart.map(function(item){
    var img=IMGS[item.id]||'';var sid=String(item.id);
    return '<div class="ci" data-id="'+sid+'">'+
      '<div class="ci-img">'+(img?'<img src="'+img+'" alt="" loading="lazy">':'<span style="font-size:28px;opacity:.2">📦</span>')+'</div>'+
      '<div><div class="ci-cat">Контур</div><div class="ci-name">'+item.name+'</div><span class="ci-del" data-action="remove">✕ Удалить</span></div>'+
      '<div class="ci-right"><div class="ci-price">'+fmt(item.qty*item.price)+'</div>'+
      '<div class="ci-qty"><button class="qty-btn" data-action="minus">−</button><input class="qty-num" type="number" value="'+item.qty+'" min="1" data-action="input"><button class="qty-btn" data-action="plus">+</button></div>'+
      '</div></div>';
  }).join('');
  var q=document.getElementById('s-qty'),sb=document.getElementById('s-sub'),st=document.getElementById('s-total');
  if(q)q.textContent=tQty+' шт.';if(sb)sb.textContent=fmt(tSum);if(st)st.textContent=fmt(tSum);
}

document.addEventListener('DOMContentLoaded',function(){
  var items=document.getElementById('cart-items');
  if(items){
    items.addEventListener('click',function(e){
      var ci=e.target.closest('.ci');if(!ci)return;
      var id=ci.getAttribute('data-id'),action=e.target.getAttribute('data-action');
      if(!id||!action)return;
      if(action==='remove')removeItem(id);
      if(action==='minus')changeQty(id,-1);
      if(action==='plus')changeQty(id,1);
    });
    items.addEventListener('change',function(e){
      if(e.target.getAttribute('data-action')!=='input')return;
      var ci=e.target.closest('.ci');if(!ci)return;
      setQty(ci.getAttribute('data-id'),e.target.value);
    });
  }
  var btn=document.getElementById('btn-checkout');
  if(btn)btn.addEventListener('click',function(){
    var cart=getCart();if(!cart.length)return;
    var kurl='';try{kurl=localStorage.getItem('kontur_kstore_url')||''}catch(e){}
    if(kurl){window.location.href=kurl;return}
    var KM={4:'km_modulecashbox_mspos_f20_f',5:'km_pos',6:'km_printer',7:'km_printer',8:'km_pos',9:'km_pos',10:'km_pos',11:'km_pos',12:'km_pos',13:'km_pos',14:'km_modulecashbox_mspos_f20_f',15:'km_printer'};
    var kassa=cart.find(function(i){return KM[i.id]});
    var ofd=cart.find(function(i){return [20,21,22].indexOf(Number(i.id))!==-1});
    if(kassa){var om=ofd?(ofd.id==20?'13':ofd.id==21?'15':'36'):'15';window.location.href='https://online-sales.kontur.ru/sale?tariffs='+KM[kassa.id]+',km_ofd&km_ofd.months='+om+'&backurl='+encodeURIComponent(window.location.href)}
    else{alert('Позвоните нам: 8 800 500-22-44')}
  });
  renderCart();
});
</script>
''' + footer()

# ──────────────────────────────────────────
# ГЛАВНЫЙ ЗАПУСК
# ──────────────────────────────────────────
def main():
    print("=== Building site from feed ===")

    # Загружаем фид
    content = fetch_feed()
    products = parse(content)
    updated  = datetime.datetime.utcnow().isoformat() + 'Z'

    print(f"Parsed {len(products)} products")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Главная
    with open(f'{OUTPUT_DIR}/index.html', 'w', encoding='utf-8') as f:
        f.write(build_index(products, updated))
    print("Built: index.html")

    # Корзина → /cart/index.html
    cart_dir = f'{OUTPUT_DIR}/cart'
    os.makedirs(cart_dir, exist_ok=True)
    with open(f'{cart_dir}/index.html', 'w', encoding='utf-8') as f:
        f.write(build_cart())
    print("Built: cart/index.html")

    # Страницы товаров
    for p in products:
        slug = p['slug']
        html = build_product(p, products, updated)
        # Создаём папку slug/index.html — тогда URL будет /slug/ без .html
        slug_dir = f'{OUTPUT_DIR}/{slug}'
        os.makedirs(slug_dir, exist_ok=True)
        path = f'{slug_dir}/index.html'
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Built: {slug}/index.html")

    # 404
    with open(f'{OUTPUT_DIR}/404.html', 'w', encoding='utf-8') as f:
        f.write(header('Страница не найдена') + '''
<div style="text-align:center;padding:120px 40px">
  <div style="font-size:72px;font-weight:700;color:#EBEBEB;margin-bottom:16px">404</div>
  <h1 style="font-size:28px;font-weight:700;margin-bottom:12px">Страница не найдена</h1>
  <p style="color:#7A7A8A;margin-bottom:28px">Возможно, ссылка устарела или товар снят с продажи.</p>
  <a href="/kontur-feed/" style="padding:13px 28px;background:#FF6B35;color:#fff;border-radius:12px;font-weight:700;font-size:14px">На главную</a>
</div>''' + footer())

    print(f"\n✅ Site built: {len(products)+3} pages → {OUTPUT_DIR}/")

if __name__ == '__main__':
    main()
