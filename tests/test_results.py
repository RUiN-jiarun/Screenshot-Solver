import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from screen_solver.results import result_html, show_result


class ResultTests(unittest.TestCase):
    def test_answer_is_safely_embedded_in_standalone_html(self):
        answer = '# 标题\n**粗体**\n</script><script>alert("xss")</script>'
        html = result_html(answer)
        data = html.split('<script type="application/json" id="answer-data">', 1)[1].split('</script>', 1)[0]
        self.assertEqual(json.loads(data), answer)
        self.assertNotIn('</script>', data)
        self.assertIn('DOMPurify.sanitize', html)
        self.assertIn('marked.parse', html)

    def test_write_and_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path = (Path(directory) / 'result.html').resolve()
            with patch('screen_solver.results.webbrowser.open', return_value=True) as browser:
                result_path, opened = show_result('**答案**', path)
            self.assertEqual(result_path, path)
            self.assertTrue(opened)
            browser.assert_called_once_with(path.as_uri())
            self.assertIn('**答案**', path.read_text())
            if os.name == 'posix':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                show_result('其他', path)

    def test_browser_failure_keeps_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = (Path(directory) / 'result.html').resolve()
            with patch('screen_solver.results.webbrowser.open', side_effect=OSError('无浏览器')):
                result_path, opened = show_result('答案', path)
            self.assertEqual(result_path, path)
            self.assertFalse(opened)
            self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()
