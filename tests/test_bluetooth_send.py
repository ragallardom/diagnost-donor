"""Report saving and Bluetooth (OBEX push) sending, with gdbus / bluetoothctl mocked."""

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app', 'modules'))

import bluetooth_send as bs  # noqa: E402


class ReportFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch('bluetooth_send.REPORT_DIR', self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_filename_is_safe(self):
        name = bs.report_filename('PF3/../AB 12;rm', now=0)
        self.assertRegex(name, r'^informe_PF3AB12rm_\d{8}-\d{4}\.html$')
        self.assertRegex(bs.report_filename('', now=0), r'^informe_equipo_')

    def test_save_and_resolve(self):
        name = bs.save_report('<html>ok</html>', 'SN1')
        self.assertTrue(os.path.isfile(bs.resolve_report(name)))

    def test_rejects_empty_huge_and_path_names(self):
        for bad in ('', '   ', None, 5):
            with self.assertRaises(ValueError):
                bs.save_report(bad, 'x')
        with self.assertRaises(ValueError):
            bs.save_report('x' * 300_000, 'x')
        for bad in ('../etc/passwd', '/etc/passwd', 'a/b.html', 'x.sh', '', None, 'informe.html\n'):
            with self.assertRaises(ValueError):
                bs.resolve_report(bad)
        with self.assertRaises(ValueError):
            bs.resolve_report('missing.html')


class ScanTests(unittest.TestCase):
    def test_parsers(self):
        out = 'Device AA:BB:CC:DD:EE:01 Galaxy S23\nDevice 11-22-33-44-55-66 x\nnoise\nDevice AA:BB:CC:DD:EE:02 AA-BB-CC-DD-EE-02\n'
        self.assertEqual(bs.parse_devices(out)[0], ('AA:BB:CC:DD:EE:01', 'Galaxy S23'))
        self.assertEqual(bs.parse_info('\tName: X\n\tIcon: phone\n\tRSSI: -60\n')['Icon'], 'phone')

    def test_unnamed_devices_dropped_and_phones_first(self):
        listing = ('Device AA:BB:CC:DD:EE:01 JBL Speaker\nDevice AA:BB:CC:DD:EE:02 Pixel 8\n'
                   'Device AA:BB:CC:DD:EE:03 AA-BB-CC-DD-EE-03\n')
        infos = {'AA:BB:CC:DD:EE:01': 'Icon: audio-card\nRSSI: -40', 'AA:BB:CC:DD:EE:02': 'Icon: phone\nRSSI: -80'}

        def run(cmd, timeout=10):
            if cmd[:2] == ['bluetoothctl', 'devices']:
                return mock.Mock(stdout=listing, returncode=0)
            if cmd[:2] == ['bluetoothctl', 'info']:
                return mock.Mock(stdout=infos[cmd[2]], returncode=0)
            return mock.Mock(stdout='', returncode=0)

        with mock.patch('bluetooth_send._run', side_effect=run):
            devices = bs.scan_devices(seconds=1)
        self.assertEqual([d['name'] for d in devices], ['Pixel 8', 'JBL Speaker'])
        self.assertTrue(devices[0]['phone'])


class SendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch('bluetooth_send.REPORT_DIR', self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.name = bs.save_report('<html>ok</html>', 'SN1')

    def gdbus(self, statuses, create_fail=0):
        calls = {'create': 0, 'cmds': []}
        seq = iter(statuses)

        def fake(args, timeout=10):
            text = ' '.join(args)
            calls['cmds'].append(text)
            if 'NameHasOwner' in text:
                return '(true,)'
            if 'CreateSession' in text:
                calls['create'] += 1
                if calls['create'] <= create_fail:
                    raise RuntimeError('Host is down')
                return "(objectpath '/org/bluez/obex/client/session0',)"
            if 'SendFile' in text:
                return "(objectpath '/org/bluez/obex/client/session0/transfer0', {})"
            if 'Properties.Get' in text:
                return f"(<'{next(seq)}'>,)"
            return '()'

        return fake, calls

    def test_invalid_address_or_file(self):
        self.assertFalse(bs.send_report('nope', self.name)['success'])
        self.assertFalse(bs.send_report('AA:BB:CC:DD:EE:01', '../x.html')['success'])

    def test_success_path(self):
        fake, calls = self.gdbus(['active', 'complete'])
        with mock.patch('bluetooth_send._gdbus', side_effect=fake), mock.patch('bluetooth_send.time.sleep'):
            res = bs.send_report('aa:bb:cc:dd:ee:01', self.name)
        self.assertTrue(res['success'], res)
        self.assertTrue(any('AA:BB:CC:DD:EE:01' in c and 'opp' in c for c in calls['cmds']))
        self.assertTrue(any('RemoveSession' in c for c in calls['cmds']))   # always cleans up

    def test_rejection_on_the_phone_is_final_and_not_retried(self):
        fake, calls = self.gdbus(['error'])
        with mock.patch('bluetooth_send._gdbus', side_effect=fake), mock.patch('bluetooth_send.time.sleep'), \
             mock.patch('bluetooth_send._pair') as pair:
            res = bs.send_report('AA:BB:CC:DD:EE:01', self.name)
        self.assertFalse(res['success'])
        self.assertIn('rechaz', res['message'])
        pair.assert_not_called()
        self.assertEqual(calls['create'], 1)

    def test_connection_failure_pairs_once_then_retries(self):
        fake, calls = self.gdbus(['complete'], create_fail=1)
        with mock.patch('bluetooth_send._gdbus', side_effect=fake), mock.patch('bluetooth_send.time.sleep'), \
             mock.patch('bluetooth_send._pair') as pair:
            res = bs.send_report('AA:BB:CC:DD:EE:01', self.name)
        self.assertTrue(res['success'], res)
        pair.assert_called_once_with('AA:BB:CC:DD:EE:01')
        self.assertEqual(calls['create'], 2)

    def test_persistent_failure_reports_error_without_looping(self):
        fake, calls = self.gdbus([], create_fail=5)
        with mock.patch('bluetooth_send._gdbus', side_effect=fake), mock.patch('bluetooth_send.time.sleep'), \
             mock.patch('bluetooth_send._pair'):
            res = bs.send_report('AA:BB:CC:DD:EE:01', self.name)
        self.assertFalse(res['success'])
        self.assertEqual(calls['create'], 2)

    def test_timeout_waiting_for_the_phone(self):
        fake, _ = self.gdbus(['active'] * 200)
        clock = iter([0, 1, 2, 3, 100, 101, 102, 103])
        with mock.patch('bluetooth_send._gdbus', side_effect=fake), mock.patch('bluetooth_send.time.sleep'), \
             mock.patch('bluetooth_send.time.monotonic', side_effect=lambda: next(clock)):
            res = bs.send_report('AA:BB:CC:DD:EE:01', self.name)
        self.assertFalse(res['success'])
        self.assertIn('Tiempo agotado', res['message'])


if __name__ == '__main__':
    unittest.main()
