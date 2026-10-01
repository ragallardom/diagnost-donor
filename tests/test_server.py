"""Tests for the kiosk backend request guards (host, origin, session token)."""

import http.client
import json
import os
import sys
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))

import server  # noqa: E402


class ServerGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.DiagnosticServer(('127.0.0.1', 0), server.DiagnosticHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def request(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        hdrs = {'Host': host or f'127.0.0.1:{self.port}'}
        hdrs.update(headers or {})
        payload = json.dumps(body).encode() if isinstance(body, dict) else body
        conn.request(method, path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp, data

    def post(self, path, body=None, token=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if token is not None:
            headers[server.TOKEN_HEADER] = token
        if origin is not None:
            headers['Origin'] = origin
        return self.request('POST', path, body=body, headers=headers)

    def test_gpu_report_requires_token_and_reaches_the_runner(self):
        resp, _ = self.post('/api/stress/gpu-report', {'frames': 1})
        self.assertEqual(resp.status, 403)
        with mock.patch('server.report_gpu_result', return_value={'success': True}) as rep:
            resp, data = self.post('/api/stress/gpu-report', {'frames': 10, 'avg_fps': 30},
                                   token=server.SESSION_TOKEN, origin=f'http://127.0.0.1:{self.port}')
        self.assertEqual(resp.status, 200)
        rep.assert_called_once_with({'frames': 10, 'avg_fps': 30})

    def test_report_and_bluetooth_routes_need_the_token(self):
        for path in ('/api/report/save', '/api/bluetooth/scan', '/api/bluetooth/send'):
            resp, _ = self.post(path, {})
            self.assertEqual(resp.status, 403, path)

    def test_bluetooth_send_reaches_the_module(self):
        with mock.patch('server.bluetooth_send.send_report', return_value={'success': True}) as send:
            resp, data = self.post('/api/bluetooth/send', {'address': 'AA:BB:CC:DD:EE:01', 'name': 'informe_x.html'},
                                   token=server.SESSION_TOKEN, origin=f'http://127.0.0.1:{self.port}')
        self.assertEqual(resp.status, 200)
        send.assert_called_once_with('AA:BB:CC:DD:EE:01', 'informe_x.html')

    def test_report_save_rejects_empty(self):
        resp, _ = self.post('/api/report/save', {'html': ''}, token=server.SESSION_TOKEN,
                            origin=f'http://127.0.0.1:{self.port}')
        self.assertEqual(resp.status, 400)

    def test_index_injects_session_token(self):
        resp, data = self.request('GET', '/')
        self.assertEqual(resp.status, 200)
        self.assertIn(server.SESSION_TOKEN.encode(), data)
        self.assertNotIn(server.TOKEN_PLACEHOLDER.encode(), data)

    def test_security_headers(self):
        resp, _ = self.request('GET', '/')
        self.assertIn("connect-src 'self'", resp.getheader('Content-Security-Policy'))
        self.assertEqual(resp.getheader('X-Frame-Options'), 'DENY')
        self.assertIsNone(resp.getheader('Access-Control-Allow-Origin'))

    def test_rejects_foreign_host(self):
        resp, _ = self.request('GET', '/api/stress/status', host='attacker.example:8080')
        self.assertEqual(resp.status, 403)

    def test_localhost_host_is_allowed(self):
        resp, _ = self.request('GET', '/api/stress/status', host=f'localhost:{self.port}')
        self.assertEqual(resp.status, 200)

    def test_directory_listing_disabled(self):
        resp, _ = self.request('GET', '/vendor/')
        self.assertEqual(resp.status, 404)

    def test_unknown_api_is_404(self):
        resp, _ = self.request('GET', '/api/does-not-exist')
        self.assertEqual(resp.status, 404)

    def test_post_without_token_is_rejected(self):
        with mock.patch('server.subprocess.Popen') as popen:
            resp, _ = self.post('/api/reboot')
        self.assertEqual(resp.status, 403)
        popen.assert_not_called()

    def test_post_with_wrong_token_is_rejected(self):
        resp, _ = self.post('/api/stress/stop', token='nope')
        self.assertEqual(resp.status, 403)

    def test_post_with_foreign_origin_is_rejected(self):
        resp, _ = self.post('/api/stress/stop', token=server.SESSION_TOKEN,
                            origin='http://attacker.example')
        self.assertEqual(resp.status, 403)

    def test_post_with_token_and_same_origin_is_accepted(self):
        with mock.patch('server.stop_stress_test', return_value={'success': True}):
            resp, data = self.post('/api/stress/stop', token=server.SESSION_TOKEN,
                                   origin=f'http://127.0.0.1:{self.port}')
        self.assertEqual(resp.status, 200)
        self.assertEqual(json.loads(data), {'success': True})

    def test_oversized_body_is_rejected(self):
        body = b'{"x": "' + b'a' * (server.MAX_BODY_BYTES + 1) + b'"}'
        resp, _ = self.post('/api/volume', body=body, token=server.SESSION_TOKEN)
        self.assertEqual(resp.status, 400)

    def test_opal_revert_rejects_partition_without_touching_disk(self):
        with mock.patch('server.execute_psid_revert') as revert:
            resp, data = self.post('/api/opal-revert', token=server.SESSION_TOKEN,
                                   body={'device': '/dev/sda1', 'psid': 'A' * 32})
        self.assertEqual(resp.status, 200)
        self.assertFalse(json.loads(data)['success'])
        revert.assert_not_called()

    def test_opal_revert_runs_on_valid_device(self):
        with mock.patch('server.validate_target_device', return_value=(True, '')), \
             mock.patch('server.execute_psid_revert', return_value={'success': True}) as revert:
            resp, data = self.post('/api/opal-revert', token=server.SESSION_TOKEN,
                                   body={'device': '/dev/nvme0n1', 'psid': 'A' * 32})
        self.assertEqual(resp.status, 200)
        self.assertTrue(json.loads(data)['success'])
        revert.assert_called_once_with('/dev/nvme0n1', 'A' * 32)


if __name__ == '__main__':
    unittest.main()
