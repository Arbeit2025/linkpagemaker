"""リンク集ページ・メーカー linkpagemaker

名前・一言・リンク一覧を入れるだけで、リンク集ページの単一HTMLを
生成するメーカー。生成HTMLは外部CSS/JSなしの自己完結ファイルで、
そのままダウンロードして任意の場所に置ける。
リンク集セットは SQLite に保存し、一覧・表示・削除ができる。
単一ファイル Flask + SQLite。
"""
import html
import io
import os
import sqlite3
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Flask, abort, g, jsonify, redirect, render_template_string, request, send_file, url_for

app = Flask(__name__)
JST = ZoneInfo("Asia/Tokyo")
DB_PATH = os.environ.get("LINKPAGEMAKER_DB", os.path.join(os.path.dirname(__file__), "linkpagemaker.db"))

MAX_LINKS = 50


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS link_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            tagline TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    db.commit()
    db.close()


def now_str():
    return datetime.now(JST).strftime("%Y-%m-%d %H:%M")


def is_valid_url(url):
    """http / https でホスト名があるURLだけを許可する。"""
    if not url or len(url) > 2000:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def validate_link_rows(titles, urls):
    """フォームの（タイトル, URL）ペアを検証し、(links, error) を返す。

    両方空の行は読み飛ばす。片方だけ入力された行や危険なURLはエラー。
    """
    links = []
    for title, url in zip(titles, urls):
        title = (title or "").strip()
        url = (url or "").strip()
        if not title and not url:
            continue
        if not title:
            return None, "リンクのタイトルが空の行があります。"
        if not is_valid_url(url):
            return None, f"URLが正しくありません（http/https のみ許可）：{url}"
        links.append({"title": title, "url": url})
    if not links:
        return None, "リンクを1件以上入力してください。"
    if len(links) > MAX_LINKS:
        return None, f"リンクは最大{MAX_LINKS}件までです。"
    return links, None


def build_page_html(link_set, links):
    """リンク集ページの自己完結HTMLを組み立てる（全入力をエスケープ）。"""
    name = html.escape(str(link_set["name"]))
    tagline = html.escape(str(link_set["tagline"] or ""))
    tagline_html = f'  <p class="tagline">{tagline}</p>\n' if tagline else ""
    items = []
    for link in links:
        url = html.escape(str(link["url"]), quote=True)
        title = html.escape(str(link["title"]))
        items.append(f'    <li><a href="{url}">{title}</a></li>')
    items_html = "\n".join(items)
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} のリンク集</title>
<style>
body {{ font-family: sans-serif; max-width: 640px; margin: 2em auto; padding: 0 1em; background: #fafafa; color: #222; }}
h1 {{ font-size: 1.6em; text-align: center; }}
.tagline {{ text-align: center; color: #555; }}
ul {{ list-style: none; padding: 0; }}
li {{ margin: 0.8em 0; }}
a {{ display: block; padding: 0.9em 1em; background: #fff; border: 1px solid #ddd; border-radius: 8px; color: #0645ad; text-decoration: none; text-align: center; }}
a:hover {{ background: #f0f4ff; }}
</style>
</head>
<body>
<h1>{name}</h1>
{tagline_html}  <ul>
{items_html}
  </ul>
</body>
</html>
"""


INDEX = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>リンク集ページ・メーカー</title>
<style>body{font-family:sans-serif;max-width:720px;margin:2em auto;padding:0 1em}
input[type=text],input[type=url]{margin:.2em 0}fieldset{margin:1em 0}</style>
<script>
function addRow(){
  var box = document.getElementById('link-rows');
  var row = box.querySelector('.link-row').cloneNode(true);
  row.querySelectorAll('input').forEach(function(i){ i.value = ''; });
  box.appendChild(row);
}
</script>
</head><body>
<h1>リンク集ページ・メーカー</h1>
<p>プロフィール名・一言・リンク一覧を入れるだけで、単一HTMLのリンク集ページを作ります。生成されるHTMLは外部ファイル不要の自己完結型です。</p>
{% if error %}<p style="color:red">{{ error }}</p>{% endif %}

<h2>リンク集セットを作る</h2>
<form method="post" action="{{ url_for('create_set') }}">
  <label>プロフィール名 <input type="text" name="name" required size="40" placeholder="例：ココアのリンク集"></label><br>
  <label>一言（任意） <input type="text" name="tagline" size="40" placeholder="例：作ったもの置き場"></label>
  <fieldset>
    <legend>リンク（タイトル＋URL、http/https のみ）</legend>
    <div id="link-rows">
      {% for i in range(3) %}
      <div class="link-row">
        <input type="text" name="link_title" size="25" placeholder="タイトル">
        <input type="url" name="link_url" size="45" placeholder="https://example.com/">
      </div>
      {% endfor %}
    </div>
    <button type="button" onclick="addRow()">リンクを追加</button>
  </fieldset>
  <button type="submit">セットを作る</button>
</form>

<h2>保存したセット（{{ sets|length }}件）</h2>
<ul>
{% for s in sets %}
<li>{{ s.created_at }} <a href="{{ url_for('view_set', sid=s.id) }}">{{ s.name }}</a>（リンク {{ s.link_count }}件）
  <a href="{{ url_for('download_set', sid=s.id) }}">HTMLをダウンロード</a>
  <form method="post" action="{{ url_for('delete_set', sid=s.id) }}" style="display:inline" onsubmit="return confirm('このセットを削除しますか？')"><button>削除</button></form></li>
{% else %}<li>保存したセットはまだありません</li>{% endfor %}
</ul>
</body></html>"""

VIEW = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ s.name }} - リンク集ページ・メーカー</title>
<style>body{font-family:sans-serif;max-width:820px;margin:2em auto;padding:0 1em}
pre{background:#f4f4f4;padding:1em;white-space:pre-wrap;font-size:.85em}
iframe{width:100%;height:420px;border:1px solid #ccc;background:#fff}</style>
</head><body>
<p><a href="{{ url_for('index') }}">トップに戻る</a></p>
<h1>{{ s.name }}</h1>
{% if s.tagline %}<p>{{ s.tagline }}</p>{% endif %}
<p>作成：{{ s.created_at }}／リンク {{ links|length }}件</p>
<ul>
{% for l in links %}<li><a href="{{ l.url }}">{{ l.title }}</a></li>{% endfor %}
</ul>

<p><a href="{{ url_for('download_set', sid=s.id) }}"><button type="button">HTMLをダウンロード</button></a></p>

<h2>プレビュー</h2>
<iframe title="プレビュー" srcdoc="{{ page_html }}"></iframe>

<h2>生成HTML</h2>
<pre>{{ page_html }}</pre>

<form method="post" action="{{ url_for('delete_set', sid=s.id) }}" onsubmit="return confirm('このセットを削除しますか？')">
  <button>このセットを削除</button>
</form>
</body></html>"""

ERROR_PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>エラー - リンク集ページ・メーカー</title>
<style>body{font-family:sans-serif;max-width:720px;margin:2em auto;padding:0 1em}</style>
</head><body>
<h1>入力エラー</h1>
<p style="color:red">{{ error }}</p>
<p><a href="{{ url_for('index') }}">トップに戻る</a></p>
</body></html>"""


def fetch_set(db, sid):
    row = db.execute("SELECT * FROM link_sets WHERE id = ?", (sid,)).fetchone()
    if row is None:
        abort(404)
    links = db.execute(
        "SELECT * FROM links WHERE set_id = ? ORDER BY position, id", (sid,)
    ).fetchall()
    return row, links


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    db = get_db()
    sets = db.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM links l WHERE l.set_id = s.id) AS link_count"
        " FROM link_sets s ORDER BY s.id DESC"
    ).fetchall()
    return render_template_string(INDEX, sets=sets, error=None)


@app.route("/sets", methods=["POST"])
def create_set():
    name = (request.form.get("name") or "").strip()
    tagline = (request.form.get("tagline") or "").strip()
    if not name:
        return render_template_string(ERROR_PAGE, error="プロフィール名を入力してください。"), 400
    links, error = validate_link_rows(
        request.form.getlist("link_title"), request.form.getlist("link_url")
    )
    if error:
        return render_template_string(ERROR_PAGE, error=error), 400
    db = get_db()
    cur = db.execute(
        "INSERT INTO link_sets(name, tagline, created_at) VALUES(?, ?, ?)",
        (name, tagline, now_str()),
    )
    sid = cur.lastrowid
    for i, link in enumerate(links):
        db.execute(
            "INSERT INTO links(set_id, title, url, position) VALUES(?, ?, ?, ?)",
            (sid, link["title"], link["url"], i),
        )
    db.commit()
    return redirect(url_for("view_set", sid=sid))


@app.route("/sets/<int:sid>")
def view_set(sid):
    db = get_db()
    row, links = fetch_set(db, sid)
    page_html = build_page_html(row, links)
    return render_template_string(VIEW, s=row, links=links, page_html=page_html)


@app.route("/sets/<int:sid>/download")
def download_set(sid):
    db = get_db()
    row, links = fetch_set(db, sid)
    page_html = build_page_html(row, links)
    buf = io.BytesIO(page_html.encode("utf-8"))
    return send_file(buf, mimetype="text/html", download_name=f"links_{sid}.html", as_attachment=True)


@app.route("/sets/<int:sid>/delete", methods=["POST"])
def delete_set(sid):
    db = get_db()
    db.execute("DELETE FROM links WHERE set_id = ?", (sid,))
    db.execute("DELETE FROM link_sets WHERE id = ?", (sid,))
    db.commit()
    return redirect(url_for("index"))


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
