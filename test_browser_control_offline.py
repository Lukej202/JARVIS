"""Offline tests: never opens Chrome or makes real internet requests."""
from __future__ import annotations
import unittest
from unittest.mock import patch
import jarvis_browser_control as browser

PUBLIC_IP = [(2, 1, 0, '', ('93.184.215.14', 443))]

class BrowserTests(unittest.TestCase):
    def test_block_private_targets(self):
        bad = [
            'file:///etc/passwd', 'http://localhost:5000',
            'http://127.0.0.1:9222', 'http://192.168.1.10',
            'https://example.com:8080', 'https://person:secret@example.com',
        ]
        with patch.object(browser.socket, 'getaddrinfo', return_value=PUBLIC_IP):
            for url in bad:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    browser.validate_web_url(url)

    def test_single_browser_research_only_public_links(self):
        links = [
            {'url':'https://www.google.com/search?q=example', 'title':'Google'},
            {'url':'http://127.0.0.1/admin', 'title':'Local forbidden'},
            {'url':'https://www.python.org/about/', 'title':'Python'},
            {'url':'https://docs.python.org/3/', 'title':'Docs'},
        ]
        def fake_navigate(_tab, url):
            if '/search?' in url:
                return {'title':'Google', 'url':url, 'text':'Search results', 'links':links}
            return {'title':'Test documentation', 'url':url, 'text':'Python documentation and resources. '*20}
        with (patch.object(browser.socket, 'getaddrinfo', return_value=PUBLIC_IP),
              patch.object(browser, '_new_research_tab', return_value='DEDICATED_TAB_ID'),
              patch.object(browser, '_navigate', side_effect=fake_navigate)):
            result = browser.research_public_web('Python documentation', max_pages=2)
            self.assertEqual([p['url'] for p in result['pages']],
                             ['https://www.python.org/about/', 'https://docs.python.org/3/'])
            self.assertEqual(result['errors'], [])

    def test_stop_is_available(self):
        browser.reset_stop()
        self.assertFalse(browser._stopped())
        browser.request_stop()
        self.assertTrue(browser._stopped())
        browser.reset_stop()

if __name__ == '__main__':
    unittest.main()
