import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["LINKPAGEMAKER_DB"] = _tmp.name

import app as app_module  # noqa: E402


class LinkPageMakerTest(unittest.TestCase):
    def setUp(self):
        app_module.init_db()
        self.client = app_module.app.test_client()
        with app_module.app.app_context():
            conn = app_module.get_db()
            conn.execute("DELETE FROM links")
            conn.execute("DELETE FROM link_sets")
            conn.commit()

    def create(self, name="ココアのリンク集", tagline="作ったもの置き場",
               titles=("ブログ", "GitHub"), urls=("https://example.com/blog", "https://github.com/Arbeit2025")):
        return self.client.post(
            "/sets",
            data={"name": name, "tagline": tagline,
                  "link_title": list(titles), "link_url": list(urls)},
        )

    def create_and_get_id(self, **kwargs):
        res = self.create(**kwargs)
        self.assertEqual(res.status_code, 302)
        return int(res.headers["Location"].rstrip("/").split("/")[-1])

    def test_healthz(self):
        res = self.client.get("/healthz")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "ok")

    def test_index_ok(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("リンク集ページ・メーカー", body)
        self.assertIn("保存したセットはまだありません", body)

    def test_create_set_and_list(self):
        res = self.create()
        self.assertEqual(res.status_code, 302)
        body = self.client.get("/").get_data(as_text=True)
        self.assertIn("ココアのリンク集", body)
        self.assertIn("リンク 2件", body)
        with app_module.app.app_context():
            conn = app_module.get_db()
            row = conn.execute("SELECT * FROM link_sets").fetchone()
            self.assertEqual(row["name"], "ココアのリンク集")
            self.assertEqual(row["tagline"], "作ったもの置き場")
            links = conn.execute("SELECT * FROM links ORDER BY position").fetchall()
            self.assertEqual(len(links), 2)
            self.assertEqual(links[0]["title"], "ブログ")
            self.assertEqual(links[1]["url"], "https://github.com/Arbeit2025")

    def test_create_requires_name(self):
        res = self.client.post(
            "/sets",
            data={"name": "", "link_title": ["x"], "link_url": ["https://example.com/"]},
        )
        self.assertEqual(res.status_code, 400)

    def test_create_requires_at_least_one_link(self):
        res = self.client.post(
            "/sets",
            data={"name": "名前だけ", "link_title": [""], "link_url": [""]},
        )
        self.assertEqual(res.status_code, 400)
        with app_module.app.app_context():
            conn = app_module.get_db()
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM link_sets").fetchone()["c"], 0)

    def test_view_set(self):
        sid = self.create_and_get_id()
        res = self.client.get(f"/sets/{sid}")
        self.assertEqual(res.status_code, 200)
        body = res.get_data(as_text=True)
        self.assertIn("ココアのリンク集", body)
        self.assertIn("作ったもの置き場", body)
        self.assertIn("ブログ", body)
        self.assertIn("HTMLをダウンロード", body)
        self.assertIn("プレビュー", body)

    def test_view_missing_set_404(self):
        self.assertEqual(self.client.get("/sets/999").status_code, 404)
        self.assertEqual(self.client.get("/sets/999/download").status_code, 404)

    def test_generated_html_contains_inputs(self):
        page = app_module.build_page_html(
            {"name": "テスト名前", "tagline": "テスト一言"},
            [{"title": "リンクA", "url": "https://example.com/a"},
             {"title": "リンクB", "url": "http://example.org/b"}],
        )
        self.assertIn("テスト名前", page)
        self.assertIn("テスト一言", page)
        self.assertIn('<a href="https://example.com/a">リンクA</a>', page)
        self.assertIn('<a href="http://example.org/b">リンクB</a>', page)

    def test_generated_html_is_self_contained(self):
        page = app_module.build_page_html(
            {"name": "名前", "tagline": ""},
            [{"title": "A", "url": "https://example.com/"}],
        )
        self.assertNotIn("<link", page)
        self.assertNotIn("<script", page)
        self.assertIn("<style>", page)

    def test_generated_html_escapes_inputs(self):
        page = app_module.build_page_html(
            {"name": '<script>alert("x")</script>', "tagline": "<b>太字</b>"},
            [{"title": "<img src=x onerror=alert(1)>", "url": 'https://example.com/?a="b"'}],
        )
        self.assertNotIn('<script>alert("x")</script>', page)
        self.assertNotIn("<b>太字</b>", page)
        self.assertNotIn("<img src=x onerror=alert(1)>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("&lt;b&gt;太字&lt;/b&gt;", page)
        self.assertIn("&quot;", page)

    def test_view_page_escapes_generated_html_in_preview(self):
        sid = self.create_and_get_id(name='<script>alert(1)</script>')
        body = self.client.get(f"/sets/{sid}").get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', body)
        self.assertIn("&lt;script&gt;", body)

    def test_is_valid_url(self):
        self.assertTrue(app_module.is_valid_url("https://example.com/"))
        self.assertTrue(app_module.is_valid_url("http://example.com/path?q=1"))
        self.assertFalse(app_module.is_valid_url("javascript:alert(1)"))
        self.assertFalse(app_module.is_valid_url("data:text/html;base64,AAAA"))
        self.assertFalse(app_module.is_valid_url("ftp://example.com/"))
        self.assertFalse(app_module.is_valid_url("https://"))
        self.assertFalse(app_module.is_valid_url("example.com"))
        self.assertFalse(app_module.is_valid_url(""))

    def test_dangerous_scheme_rejected_on_create(self):
        res = self.create(urls=("javascript:alert(1)", "https://example.com/"))
        self.assertEqual(res.status_code, 400)
        self.assertIn("http/https のみ許可", res.get_data(as_text=True))
        with app_module.app.app_context():
            conn = app_module.get_db()
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM link_sets").fetchone()["c"], 0)

    def test_download(self):
        sid = self.create_and_get_id()
        res = self.client.get(f"/sets/{sid}/download")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.headers["Content-Type"])
        disposition = res.headers["Content-Disposition"]
        self.assertIn("attachment", disposition)
        self.assertIn(f"links_{sid}.html", disposition)
        body = res.get_data(as_text=True)
        self.assertIn("ココアのリンク集", body)
        self.assertIn('<a href="https://example.com/blog">ブログ</a>', body)
        self.assertIn('<a href="https://github.com/Arbeit2025">GitHub</a>', body)

    def test_delete_set(self):
        sid = self.create_and_get_id()
        res = self.client.post(f"/sets/{sid}/delete")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.client.get(f"/sets/{sid}").status_code, 404)
        with app_module.app.app_context():
            conn = app_module.get_db()
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM link_sets").fetchone()["c"], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM links").fetchone()["c"], 0)

    def test_blank_rows_are_skipped(self):
        res = self.client.post(
            "/sets",
            data={"name": "1件だけ", "tagline": "",
                  "link_title": ["有効リンク", "", ""],
                  "link_url": ["https://example.com/", "", ""]},
        )
        self.assertEqual(res.status_code, 302)
        with app_module.app.app_context():
            conn = app_module.get_db()
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM links").fetchone()["c"], 1)


if __name__ == "__main__":
    unittest.main()
