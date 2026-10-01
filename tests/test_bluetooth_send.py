"""Report saving and Bluetooth (OBEX push) sending, with gdbus / bluetoothctl mocked."""

import os
import sys
import tempfile
import time
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

    def fake_chrome(self, body):
        """An executable that behaves like a Chrome we control (arguments are Chrome's own flags)."""
        path = os.path.join(self.tmp.name, 'fake-chrome')
        with open(path, 'w') as f:
            f.write('#!/usr/bin/env python3\nimport sys, time\n'
                    'out = [a for a in sys.argv if a.startswith("--print-to-pdf=")][0].split("=", 1)[1]\n' + body)
        os.chmod(path, 0o755)
        patcher = mock.patch('bluetooth_send.find_chrome', return_value=path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return path

    PDF = 'open(out, "wb").write(b"%PDF-1.4 fake\\n%%EOF\\n")\n'

    def test_pdf_is_created_and_only_the_pdf_is_kept(self):
        self.fake_chrome(self.PDF)
        name = bs.save_report('<html>ok</html>', 'SN1', 'pdf')
        self.assertTrue(name.endswith('.pdf'))
        self.assertIn(name, os.listdir(self.tmp.name))
        self.assertFalse([n for n in os.listdir(self.tmp.name) if n.endswith('.html')])   # temp HTML removed
        self.assertTrue(bs.resolve_report(name).endswith('.pdf'))

    def test_chrome_that_never_exits_does_not_cause_a_timeout(self):
        """The reported bug: Chrome writes the PDF but lingers (offline firewall); we must not wait for it."""
        self.fake_chrome(self.PDF + 'time.sleep(600)\n')
        t0 = time.monotonic()
        name = bs.save_report('<html>ok</html>', 'SN1', 'pdf')
        self.assertLess(time.monotonic() - t0, 10)
        self.assertTrue(name.endswith('.pdf'))

    def test_chrome_flags_keep_it_offline_and_off_the_kiosk_profile(self):
        flags = []

        class P:
            pid = 0
            def poll(self): return 0
            def wait(self, timeout=None): return 0

        def fake_popen(cmd, **kw):
            flags.extend(cmd)
            with open([a for a in cmd if a.startswith('--print-to-pdf=')][0].split('=', 1)[1], 'wb') as f:
                f.write(b'%PDF-1.4 x\n%%EOF\n')
            return P()

        with mock.patch('bluetooth_send.find_chrome', return_value='/usr/bin/chrome'), \
             mock.patch('bluetooth_send.subprocess.Popen', side_effect=fake_popen), \
             mock.patch('bluetooth_send.os.killpg'):
            bs.save_report('<html>ok</html>', 'SN1', 'pdf')
        for flag in ('--headless', '--no-sandbox', '--no-proxy-server', '--disable-background-networking',
                     '--no-pdf-header-footer'):
            self.assertIn(flag, flags)
        self.assertTrue(any(a.startswith('--user-data-dir=') for a in flags))

    def test_pdf_failures_are_reported_and_leave_nothing_behind(self):
        with mock.patch('bluetooth_send.find_chrome', return_value=None):
            with self.assertRaises(ValueError):
                bs.save_report('<html>ok</html>', 'SN1', 'pdf')
        self.assertEqual(os.listdir(self.tmp.name), [])
        self.fake_chrome('sys.exit(3)\n')                       # exits without writing a PDF
        with self.assertRaises(ValueError):
            bs.save_report('<html>ok</html>', 'SN1', 'pdf')
        with self.assertRaises(ValueError):
            bs.save_report('<html>ok</html>', 'SN1', 'docx')

    def test_truly_stuck_chrome_times_out_and_is_killed(self):
        self.fake_chrome('time.sleep(600)\n')                   # never writes anything
        with mock.patch('bluetooth_send.html_to_pdf', wraps=bs.html_to_pdf) as wrapped:
            html = os.path.join(self.tmp.name, 'x.html')
            with open(html, 'w') as fh:
                fh.write('<html></html>')
            t0 = time.monotonic()
            with self.assertRaises(RuntimeError) as ctx:
                bs.html_to_pdf(html, os.path.join(self.tmp.name, 'x.pdf'), timeout=2)
        self.assertIn('Tiempo agotado', str(ctx.exception))
        self.assertLess(time.monotonic() - t0, 12)

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

    def test_obexd_failure_pairs_once_then_uses_the_direct_push(self):
        fake, calls = self.gdbus(['complete'], create_fail=5)
        with mock.patch('bluetooth_send._gdbus', side_effect=fake), mock.patch('bluetooth_send.time.sleep'), \
             mock.patch('bluetooth_send._pair') as pair, mock.patch('bluetooth_send.push_direct') as direct:
            res = bs.send_report('AA:BB:CC:DD:EE:01', self.name)
        self.assertTrue(res['success'], res)
        pair.assert_called_once_with('AA:BB:CC:DD:EE:01')
        direct.assert_called_once()

    def test_both_paths_failing_reports_both_reasons(self):
        fake, _ = self.gdbus([], create_fail=5)
        with mock.patch('bluetooth_send._gdbus', side_effect=fake), mock.patch('bluetooth_send.time.sleep'), \
             mock.patch('bluetooth_send._pair'), mock.patch('bluetooth_send.push_direct', side_effect=RuntimeError('sin canal')):
            res = bs.send_report('AA:BB:CC:DD:EE:01', self.name)
        self.assertFalse(res['success'])
        self.assertIn('Host is down', res['message'])
        self.assertIn('sin canal', res['message'])

    def test_rejection_in_the_direct_push_is_final(self):
        fake, _ = self.gdbus([], create_fail=5)
        with mock.patch('bluetooth_send._gdbus', side_effect=fake), mock.patch('bluetooth_send.time.sleep'), \
             mock.patch('bluetooth_send._pair'), \
             mock.patch('bluetooth_send.push_direct', side_effect=RuntimeError('El celular rechazó o canceló el archivo')):
            res = bs.send_report('AA:BB:CC:DD:EE:01', self.name)
        self.assertEqual(res['message'], 'El celular rechazó o canceló el archivo')

    def test_sendfile_is_retried_while_the_interface_is_not_exported(self):
        """The reported bug: SendFile -> UnknownObject 'doesn't exist' right after CreateSession."""
        fake, calls = self.gdbus(['complete'])
        attempts = {'n': 0}

        def flaky(args, timeout=10):
            if 'SendFile' in ' '.join(args):
                attempts['n'] += 1
                if attempts['n'] < 3:
                    raise RuntimeError('GDBus.Error:org.freedesktop.DBus.Error.UnknownObject: Method "SendFile" '
                                       'with signature "s" on interface "org.bluez.obex.ObjectPush1" doesn\'t exist')
            return fake(args, timeout)

        with mock.patch('bluetooth_send._gdbus', side_effect=flaky), mock.patch('bluetooth_send.time.sleep'), \
             mock.patch('bluetooth_send.push_direct') as direct:
            res = bs.send_report('AA:BB:CC:DD:EE:01', self.name)
        self.assertTrue(res['success'], res)
        self.assertEqual(attempts['n'], 3)
        direct.assert_not_called()

    def test_timeout_waiting_for_the_phone(self):
        fake, _ = self.gdbus(['active'] * 200)
        clock = iter([0, 1, 2, 3, 100, 101, 102, 103])
        with mock.patch('bluetooth_send._gdbus', side_effect=fake), mock.patch('bluetooth_send.time.sleep'), \
             mock.patch('bluetooth_send.time.monotonic', side_effect=lambda: next(clock)):
            res = bs.send_report('AA:BB:CC:DD:EE:01', self.name)
        self.assertFalse(res['success'])
        self.assertIn('Tiempo agotado', res['message'])


class DirectObexTests(unittest.TestCase):
    def test_sdp_request_and_channel_extraction(self):
        req = bs.sdp_request(0x1105)
        self.assertEqual(req[0], 0x06)
        self.assertEqual(int.from_bytes(req[3:5], 'big'), len(req) - 5)
        # ProtocolDescriptorList: L2CAP(0x0100) then RFCOMM(0x0003) on channel 12
        attrs = bytes.fromhex('3514' '0900043510' '35031901 00' '35051900 03080c'.replace(' ', ''))
        self.assertEqual(bs.sdp_rfcomm_channel(attrs), 12)
        self.assertIsNone(bs.sdp_rfcomm_channel(b'\x35\x03\x19\x01\x00'))

    def test_sdp_response_parsing(self):
        attrs = b'\x35\x05\x19\x00\x03\x08\x0c'
        resp = b'\x07' + (1).to_bytes(2, 'big') + (len(attrs) + 3).to_bytes(2, 'big') + len(attrs).to_bytes(2, 'big') + attrs + b'\x00'
        self.assertEqual(bs.sdp_parse_response(resp), (attrs, b'\x00'))
        with self.assertRaises(RuntimeError):
            bs.sdp_parse_response(b'\x01\x00\x00')

    def test_put_packets_single_and_multi(self):
        (code, pkt), = bs.obex_put_packets('a.html', b'hello')
        self.assertEqual(code, 0x82)
        self.assertEqual(int.from_bytes(pkt[1:3], 'big'), len(pkt))
        self.assertIn('a.html'.encode('utf-16-be'), pkt)
        self.assertTrue(pkt.endswith(b'\x49\x00\x08hello'))
        data = bytes(range(256)) * 40                     # 10 KB: needs several packets
        packets = bs.obex_put_packets('big.html', data, conn_id=b'\x00\x00\x00\x01', max_packet=1024)
        self.assertGreater(len(packets), 5)
        self.assertEqual([c for c, _ in packets[:-1]], [0x02] * (len(packets) - 1))
        self.assertEqual(packets[-1][0], 0x82)
        self.assertTrue(all(len(p) <= 1024 for _, p in packets))
        self.assertGreater(sum(len(p) for _, p in packets), len(data))

    def test_headers_parser_finds_connection_id(self):
        self.assertEqual(bs._obex_headers(b'\xCB\x00\x00\x00\x07\x01\x00\x05\x00\x00')[0xCB], b'\x00\x00\x00\x07')

    def test_full_push_against_a_scripted_phone(self):
        sent = []
        replies = [bytes.fromhex('a0000c10002000cb00000005'),   # CONNECT ok + connection id 5
                   bytes.fromhex('a00003')]                     # PUT final ok

        class Phone:
            def __init__(self, *a):
                self.buf = b''

            def settimeout(self, t): pass
            def connect(self, addr): self.addr = addr
            def close(self): pass

            def send(self, data):
                sent.append(data)
                if data[0] in (0x80, 0x82, 0x02):
                    self.buf += replies.pop(0)

            def recv(self, n):
                out, self.buf = self.buf[:n], self.buf[n:]
                return out

        tmp = tempfile.NamedTemporaryFile(suffix='.html', delete=False)
        tmp.write(b'<html>x</html>')
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        with mock.patch('bluetooth_send.find_opp_channel', return_value=12), \
             mock.patch('bluetooth_send.socket.socket', Phone):
            bs.push_direct('AA:BB:CC:DD:EE:01', tmp.name)
        self.assertEqual(sent[0][0], 0x80)
        self.assertEqual(sent[1][0], 0x82)
        self.assertIn(b'\xCB\x00\x00\x00\x05', sent[1])       # connection id is echoed
        self.assertIn(b'<html>x</html>', sent[1])
        self.assertEqual(sent[-1][0], 0x81)                       # DISCONNECT

    def test_phone_refusing_the_put_is_reported(self):
        replies = [bytes.fromhex('a0000710002000'), bytes.fromhex('c30003')]   # CONNECT ok, PUT forbidden

        class Phone:
            def __init__(self, *a): self.buf = b''
            def settimeout(self, t): pass
            def connect(self, addr): pass
            def close(self): pass
            def send(self, data):
                if data[0] in (0x80, 0x82):
                    self.buf += replies.pop(0)
            def recv(self, n):
                out, self.buf = self.buf[:n], self.buf[n:]
                return out

        tmp = tempfile.NamedTemporaryFile(suffix='.html', delete=False)
        tmp.write(b'x')
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        with mock.patch('bluetooth_send.find_opp_channel', return_value=1), mock.patch('bluetooth_send.socket.socket', Phone):
            with self.assertRaises(RuntimeError) as ctx:
                bs.push_direct('AA:BB:CC:DD:EE:01', tmp.name)
        self.assertIn('rechaz', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
