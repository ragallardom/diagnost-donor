"""Tests for the telemetry performance changes (no behaviour change for the user)."""

import os
import sys
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app', 'modules'))

import storage_diag  # noqa: E402
import wifi_diag  # noqa: E402


class StorageSnapshotTests(unittest.TestCase):
    def setUp(self):
        storage_diag._has_snapshot = False
        storage_diag._last_snapshot = {'internal': [], 'usb': [], 'all': []}

    def test_telemetry_does_not_wait_for_running_scan(self):
        started, release = threading.Event(), threading.Event()

        def slow_scan():
            started.set()
            release.wait(5)
            return {'internal': [{'device': '/dev/nvme0n1'}], 'usb': [], 'all': []}

        with mock.patch('storage_diag._scan_storage', side_effect=slow_scan):
            t = threading.Thread(target=storage_diag.get_storage_info)
            t.start()
            started.wait(5)
            # First scan still running and no snapshot yet: telemetry skips storage.
            self.assertIsNone(storage_diag.get_storage_snapshot())
            release.set()
            t.join(5)

        with mock.patch('storage_diag._scan_storage', side_effect=AssertionError('should not scan')):
            storage_diag._SCAN_LOCK.acquire()
            try:
                # Scan in progress but a snapshot exists: return it immediately.
                self.assertEqual(storage_diag.get_storage_snapshot()['internal'][0]['device'], '/dev/nvme0n1')
            finally:
                storage_diag._SCAN_LOCK.release()


class EthernetLoopbackCacheTests(unittest.TestCase):
    def setUp(self):
        wifi_diag._ETH_LOOPBACK_CACHE.clear()

    def tearDown(self):
        wifi_diag._ETH_LOOPBACK_CACHE.clear()

    def test_no_echo_is_not_reprobed_every_poll(self):
        with mock.patch('wifi_diag.os.geteuid', return_value=0), \
             mock.patch('wifi_diag.socket.socket') as sock_cls, \
             mock.patch('wifi_diag.select.select', return_value=([], [], [])), \
             mock.patch('wifi_diag.time.monotonic', side_effect=[100.0, 101.0, 106.0, 106.0]):
            sock_cls.return_value.recv.side_effect = BlockingIOError  # nothing pending on the wire
            self.assertEqual(wifi_diag.test_ethernet_loopback('eth0'), (False, 'no_echo'))
            self.assertEqual(wifi_diag.test_ethernet_loopback('eth0'), (False, 'no_echo'))  # cached (1 s later)
            self.assertEqual(sock_cls.call_count, 1)
            wifi_diag.test_ethernet_loopback('eth0')                                          # 6 s after the probe: re-probe
            self.assertEqual(sock_cls.call_count, 2)

    def test_verified_loopback_stays_cached(self):
        wifi_diag._ETH_LOOPBACK_CACHE['eth0'] = {'verified': True, 'rtt_ms': 0.4}
        with mock.patch('wifi_diag.socket.socket') as sock_cls:
            self.assertEqual(wifi_diag.test_ethernet_loopback('eth0'), (True, 0.4))
        sock_cls.assert_not_called()


class WifiRescanTests(unittest.TestCase):
    def setUp(self):
        wifi_diag._wifi_rescan.update({'proc': None, 'last': 0.0})

    def test_rescan_is_background_and_rate_limited(self):
        with mock.patch('wifi_diag.subprocess.Popen') as popen, \
             mock.patch('wifi_diag.time.monotonic', side_effect=[50.0, 55.0, 61.0]):
            popen.return_value.poll.return_value = 0  # previous scan finished
            wifi_diag._trigger_wifi_rescan()
            wifi_diag._trigger_wifi_rescan()   # 5 s later: skipped
            wifi_diag._trigger_wifi_rescan()   # 11 s later: new scan
        self.assertEqual(popen.call_count, 2)
        self.assertEqual(popen.call_args[0][0], ['nmcli', 'dev', 'wifi', 'rescan'])

    def test_list_never_waits_for_a_scan(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            out = 'enabled' if cmd[:3] == ['nmcli', 'radio', 'wifi'] else 'no:Oficina:80:wlan0\n'
            return mock.Mock(returncode=0, stdout=out)

        with mock.patch('wifi_diag.shutil.which', return_value='/usr/bin/nmcli'), \
             mock.patch('wifi_diag.subprocess.run', side_effect=run), \
             mock.patch('wifi_diag._trigger_wifi_rescan'), \
             mock.patch('wifi_diag.get_ethernet_status', return_value={}):
            status = wifi_diag.get_wifi_status()
        list_cmds = [c for c in calls if 'ACTIVE,SSID,SIGNAL,DEVICE' in c]
        self.assertEqual(list_cmds[0][-2:], ['--rescan', 'no'])
        self.assertFalse(any(c[-1] == 'rescan' for c in calls))
        self.assertEqual(status['nearby_networks'][0]['ssid'], 'Oficina')


if __name__ == '__main__':
    unittest.main()
