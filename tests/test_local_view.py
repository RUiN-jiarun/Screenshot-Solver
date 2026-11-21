import json
import unittest
import urllib.error
import urllib.request

from screen_solver.local_view import LiveResult
from screen_solver.results import result_html


class LiveResultTests(unittest.TestCase):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def test_live_page_shows_partial_and_final_states(self):
        with LiveResult() as view:
            with self.opener.open(view.url, timeout=5) as response:
                self.assertIn('正在思考', response.read().decode())
            view.append('第一段')
            with self.opener.open(view.url + '/state', timeout=5) as response:
                self.assertEqual(json.load(response), {'text': '第一段', 'status': 'running', 'error': ''})
            self.assertFalse(view.seen.is_set())
            view.append('第二段')
            view.finish()
            with self.opener.open(view.url + '/state', timeout=5) as response:
                self.assertEqual(json.load(response), {'text': '第一段第二段', 'status': 'done', 'error': ''})
            self.assertTrue(view.wait_for_viewer(1))
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.opener.open(view.url.rsplit('/', 1)[0] + '/wrong', timeout=5)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()

    def test_live_script_is_appended_after_intact_vendor_scripts(self):
        with LiveResult() as view:
            page = view._page()
            static_page = result_html("")
            closing = "</body></html>"
            # 第三方脚本本身可能包含 HTML 片段，不能全局替换结束标签。
            self.assertTrue(page.startswith(static_page[:-len(closing)]))
            self.assertTrue(page.endswith(closing))

    def test_error_state_preserves_partial(self):
        with LiveResult() as view:
            view.append('部分')
            view.finish('连接中断')
            with self.opener.open(view.url + '/state', timeout=5) as response:
                self.assertEqual(json.load(response), {'text': '部分', 'status': 'error', 'error': '连接中断'})


if __name__ == '__main__':
    unittest.main()
