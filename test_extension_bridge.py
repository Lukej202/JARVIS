"""Offline bridge tests. Does NOT require Chrome, Flask or Ollama."""
import importlib
import threading
import time
import unittest
import tempfile
from pathlib import Path

import jarvis_extension_bridge as bridge


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.original = bridge._last_heartbeat
        bridge.heartbeat()

    def tearDown(self):
        bridge._last_heartbeat = self.original

    def test_pairing_key_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            old_file = bridge.KEY_FILE
            try:
                bridge.KEY_FILE = Path(directory) / 'key'
                first = bridge.pairing_key()
                self.assertEqual(first, bridge.pairing_key())
                self.assertTrue(bridge.verify_key(first))
                self.assertFalse(bridge.verify_key('wrong'))
            finally:
                bridge.KEY_FILE = old_file

    def test_approved_browser_report(self):
        result = {}
        def serve():
            for _ in range(200):
                job = bridge.claim_next()
                if job is not None:
                    result['query'] = job['query']
                    bridge.receive_result({'id': job['id'], 'report': {
                        'pages': [{'title':'Python', 'url':'https://www.python.org/doc/', 'preview':'Real documentation'}],
                        'errors': [], 'stopped':False,
                    }})
                    return
                time.sleep(0.005)
        worker = threading.Thread(target=serve)
        worker.start()
        report = bridge.enqueue_research('Python documentation', max_pages=1, timeout=4)
        worker.join()
        self.assertEqual(result['query'], 'Python documentation')
        self.assertEqual(report['pages'][0]['title'], 'Python')

    def test_cancel_and_late_results(self):
        result = {}
        def wait():
            result['report'] = bridge.enqueue_research('Stop this research', timeout=4)
        worker = threading.Thread(target=wait)
        worker.start()
        for _ in range(200):
            with bridge._lock:
                if bridge._jobs: break
            time.sleep(0.005)
        self.assertIn('Stop requested', bridge.request_stop())
        bridge.claim_next()
        worker.join(timeout=4)
        self.assertFalse(worker.is_alive())
        self.assertTrue(result['report']['stopped'])


if __name__ == '__main__':
    unittest.main()
