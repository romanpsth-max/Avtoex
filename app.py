import os, re, sqlite3, secrets
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, redirect, url_for, session, render_template_string, flash, abort

DB = os.environ.get('AVTOEX_DB', 'avtoex.db')
ADMIN_USER = os.environ.get('AVTOEX_ADMIN_USER', 'admin')
ADMIN_PASSWORD = os.environ.get('AVTOEX_ADMIN_PASSWORD', '')
app = Flask(__name__)
app.secret_key = os.environ.get('AVTOEX_SECRET', 'CHANGE-ME-BEFORE-PUBLISHING')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('AVTOEX_HTTPS', '0') == '1')

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE, source_url TEXT NOT NULL, product_code TEXT NOT NULL, image_url TEXT NOT NULL, price TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cols = [r['name'] for r in c.execute('PRAGMA table_info(products)').fetchall()]
        if 'slug' not in cols:
            c.execute('ALTER TABLE products ADD COLUMN slug TEXT')
        for r in c.execute("SELECT id FROM products WHERE slug IS NULL OR slug='' ").fetchall():
            c.execute('UPDATE products SET slug=? WHERE id=?', (secrets.token_urlsafe(7), r['id']))

def admin_required():
    if session.get('admin') is not True:
        abort(403)

def get_code(url):
    m = re.search(r'(\d{7,})', urlparse(url).path)
    return m.group(1) if m else 'ID не визначено'

def get_image(url):
    r = requests.get(url, headers={'User-Agent':'Mozilla/5.0'}, timeout=12)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    for attrs in ({'property':'og:image'}, {'name':'twitter:image'}):
        tag = soup.find('meta', attrs=attrs)
        value = (tag.get('content') or '').strip() if tag else ''
        if value.startswith('https://'):
            return value
    return ''

STYLE = '''
*{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#17191d;font-family:Arial,sans-serif}
header{background:#111827;color:white;padding:17px max(18px,calc((100% - 1000px)/2));display:flex;justify-content:space-between;align-items:center;gap:12px}
.logo{font-weight:900;letter-spacing:1.5px;font-size:23px;text-decoration:none;color:white}.logo span{color:#fb923c}
nav a{color:white;text-decoration:none;font-size:14px}main{max-width:1000px;margin:28px auto;padding:0 16px}
h1{font-size:clamp(25px,4vw,36px);margin:0 0 8px}h2{font-size:21px}.muted{color:#6b7280;font-size:14px}
.panel,.product{background:white;border:1px solid #e5e7eb;border-radius:16px;padding:22px;margin:20px 0}
input{width:100%;padding:12px;border:1px solid #d1d5db;border-radius:9px;margin:6px 0 14px;font:inherit}
label{font-size:13px;font-weight:bold}button,.btn{display:inline-block;background:#111827;color:white;padding:11px 14px;border:0;border-radius:9px;font:inherit;font-weight:bold;text-decoration:none;cursor:pointer}
.orange{background:#f97316}.light{background:#e5e7eb;color:#111827}.flash{background:#fff7ed;border:1px solid #fed7aa;padding:12px;border-radius:9px;margin:12px 0}
.row{display:grid;grid-template-columns:2fr 1fr;gap:14px}.tablewrap{overflow:auto}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #e5e7eb}td img{width:60px;height:48px;object-fit:contain}.actions{display:flex;gap:6px;flex-wrap:wrap}.actions form{margin:0}
.product{max-width:600px;margin:25px auto;text-align:center;padding:18px}.product img{width:100%;height:min(60vh,480px);object-fit:contain}.price{font-size:32px;font-weight:900;margin:18px 0}
footer{max-width:1000px;margin:35px auto;padding:0 16px 25px;color:#6b7280;font-size:12px}
@media(max-width:620px){.row{grid-template-columns:1fr}.panel{padding:15px}}
'''
BASE = """<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{{title}} — Avtoex</title><style>""" + STYLE + """</style></head><body><header><a class="logo" href="{{url_for('index')}}">AVTO<span>EX</span></a><nav>{% if admin %}<a href="{{url_for('admin')}}">Адмін-панель</a> · <a href="{{url_for('logout')}}">Вийти</a>{% else %}<a href="{{url_for('login')}}">Вхід адміністратора</a>{% endif %}</nav></header><main>{% with msgs=get_flashed_messages() %}{% for msg in msgs %}<div class="flash">{{msg}}</div>{% endfor %}{% endwith %}{{body|safe}}</main><footer>Avtoex · Використовуй фотографії з дотриманням прав власників.</footer></body></html>"""

def page(title, body):
    return render_template_string(BASE, title=title, body=body, admin=session.get('admin') is True)

@app.route('/')
def index():
    return page('Avtoex', '<section class="panel" style="text-align:center;max-width:650px;margin:50px auto"><h1>Avtoex</h1><p class="muted">Щоб переглянути запчастину, відкрийте персональне посилання від продавця.</p></section>')

@app.route('/p/<slug>')
def product_page(slug):
    with db() as c:
        p = c.execute('SELECT * FROM products WHERE slug=? AND active=1', (slug,)).fetchone()
    if not p: abort(404)
    price = (p['price'] or '').strip() or 'Уточнюйте ціну'
    body = f'<article class="product"><img src="{p["image_url"]}" alt="Автозапчастина" referrerpolicy="no-referrer"><div class="price">{price}</div><div class="muted">Avtoex</div></article>'
    return page('Запчастина', body)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u, pw = request.form.get('username',''), request.form.get('password','')
        if not ADMIN_PASSWORD:
            flash('Пароль адміністратора не налаштований. Дивись README.md.')
        elif secrets.compare_digest(u, ADMIN_USER) and secrets.compare_digest(pw, ADMIN_PASSWORD):
            session.clear(); session['admin'] = True
            return redirect(url_for('admin'))
        else: flash('Неправильний логін або пароль.')
    body = '<section class="panel" style="max-width:450px;margin:40px auto"><h1>Вхід адміністратора</h1><form method="post"><label>Логін</label><input name="username" required autocomplete="username"><label>Пароль</label><input name="password" type="password" required autocomplete="current-password"><button class="orange">Увійти</button></form></section>'
    return page('Вхід', body)

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('index'))

@app.route('/admin')
def admin():
    admin_required()
    with db() as c: products = c.execute('SELECT * FROM products ORDER BY id DESC').fetchall()
    rows = ''
    for p in products:
        link = url_for('product_page', slug=p['slug'], _external=True)
        status = 'Активний' if p['active'] else 'Прихований'
        hide_label = 'Приховати' if p['active'] else 'Опублікувати'
        rows += f'''<tr><td><img src="{p['image_url']}" alt=""></td><td>{p['product_code']}</td><td>{p['price'] or '—'}</td><td>{status}</td><td><div class="actions"><button type="button" class="light" onclick="navigator.clipboard.writeText('{link}').then(()=>alert('Посилання скопійовано'))">Копіювати URL</button><a class="btn light" href="{url_for('edit_product',pid=p['id'])}">Редагувати</a><form method="post" action="{url_for('toggle_product',pid=p['id'])}"><button class="light">{hide_label}</button></form><form method="post" action="{url_for('delete_product',pid=p['id'])}" onsubmit="return confirm('Видалити товар?')"><button>Видалити</button></form></div></td></tr>'''
    if not rows: rows = '<tr><td colspan="5">Товарів поки немає.</td></tr>'
    body = f'''<h1>Адмін-панель</h1><p class="muted">Додай товар, встанови ціну та скопіюй унікальне посилання клієнту.</p>
<section class="panel"><h2>Додати товар з Allegro</h2><form method="post" action="{url_for('add_product')}"><label>Посилання Allegro</label><input name="source_url" type="url" placeholder="https://allegro.pl/oferta/..." required><div class="row"><div><label>Пряме HTTPS-посилання на фото (якщо потрібно)</label><input name="manual_image" type="url" placeholder="https://..."></div><div><label>Твоя ціна</label><input name="price" placeholder="450 zł"></div></div><button class="orange">Додати товар</button></form><p class="muted">Allegro може блокувати автоматичне отримання фото. Якщо не спрацює, додай пряме HTTPS-посилання на зображення.</p></section>
<section class="panel"><h2>Товари</h2><div class="tablewrap"><table><thead><tr><th>Фото</th><th>Код</th><th>Ціна</th><th>Статус</th><th>Дії</th></tr></thead><tbody>{rows}</tbody></table></div></section>'''
    return page('Адмін-панель', body)

@app.route('/admin/add', methods=['POST'])
def add_product():
    admin_required()
    source = request.form.get('source_url','').strip()
    host = (urlparse(source).hostname or '').lower()
    if urlparse(source).scheme != 'https' or not (host == 'allegro.pl' or host.endswith('.allegro.pl')):
        flash('Встав коректне HTTPS-посилання Allegro.pl.'); return redirect(url_for('admin'))
    image = request.form.get('manual_image','').strip()
    if image and urlparse(image).scheme != 'https':
        flash('Посилання на фото має бути HTTPS.'); return redirect(url_for('admin'))
    if not image:
        try: image = get_image(source)
        except Exception: image = ''
    if not image:
        flash('Allegro не віддало фото автоматично. Встав пряме HTTPS-посилання на фото.'); return redirect(url_for('admin'))
    price = request.form.get('price','').strip()
    slug = secrets.token_urlsafe(9).replace('-','').replace('_','')
    with db() as c:
        c.execute('INSERT INTO products(slug,source_url,product_code,image_url,price) VALUES(?,?,?,?,?)', (slug,source,get_code(source),image,price))
    flash('Товар додано. Натисни «Копіювати URL» у таблиці.'); return redirect(url_for('admin'))

@app.route('/admin/edit/<int:pid>', methods=['GET','POST'])
def edit_product(pid):
    admin_required()
    with db() as c:
        p = c.execute('SELECT * FROM products WHERE id=?', (pid,)).fetchone()
        if not p: abort(404)
        if request.method == 'POST':
            price = request.form.get('price','').strip(); image = request.form.get('image_url','').strip()
            if image and urlparse(image).scheme != 'https':
                flash('Посилання на фото має бути HTTPS.'); return redirect(url_for('edit_product',pid=pid))
            c.execute('UPDATE products SET price=?,image_url=COALESCE(NULLIF(?,\'\'),image_url) WHERE id=?', (price,image,pid))
            flash('Збережено.'); return redirect(url_for('admin'))
    body = f'<section class="panel" style="max-width:600px;margin:auto"><h1>Редагувати товар</h1><form method="post"><label>Код товару</label><input value="{p["product_code"]}" disabled><label>Твоя ціна</label><input name="price" value="{p["price"]}"><label>HTTPS-посилання на фото</label><input name="image_url" value="{p["image_url"]}"><button class="orange">Зберегти</button> <a class="btn light" href="{url_for("admin")}">Назад</a></form></section>'
    return page('Редагувати', body)

@app.route('/admin/toggle/<int:pid>', methods=['POST'])
def toggle_product(pid):
    admin_required()
    with db() as c: c.execute('UPDATE products SET active=1-active WHERE id=?', (pid,))
    return redirect(url_for('admin'))

@app.route('/admin/delete/<int:pid>', methods=['POST'])
def delete_product(pid):
    admin_required()
    with db() as c: c.execute('DELETE FROM products WHERE id=?', (pid,))
    flash('Товар видалено.'); return redirect(url_for('admin'))

@app.errorhandler(403)
def forbidden(_):
    return page('Доступ заборонено', '<section class="panel"><h1>Доступ заборонено</h1><p>Увійди як адміністратор.</p><a class="btn orange" href="/login">Вхід</a></section>'), 403

@app.errorhandler(404)
def not_found(_):
    return page('Не знайдено', '<section class="panel"><h1>Сторінку не знайдено</h1><p class="muted">Посилання неправильне або товар приховано.</p></section>'), 404

init_db()
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT','5000')), debug=False)
