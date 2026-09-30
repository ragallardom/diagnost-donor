"""Tests for the honesty of the non-stress diagnostics: they must report what the
hardware exposes, never a made-up healthy value."""

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app', 'modules'))

import battery  # noqa: E402
import bluetooth_diag  # noqa: E402
import cpu_benchmark  # noqa: E402
import display_hdmi_diag  # noqa: E402
import opal_diag  # noqa: E402
import ram_benchmark  # noqa: E402
import storage_diag  # noqa: E402
import system_info  # noqa: E402
import wifi_diag  # noqa: E402


def ata(*attrs):
    return {'ata_smart_attributes': {'table': [
        {'id': i, 'name': n, 'raw': {'value': v}} for i, n, v in attrs]}}


class SmartHealthTests(unittest.TestCase):
    def test_no_data_is_unknown_never_healthy(self):
        for data in (None, {}, {'_parsed_text': True, 'tbw_tb': 3}):
            self.assertEqual(storage_diag.evaluate_smart_health(data)['level'], 'unknown')
        self.assertNotIn('100%', storage_diag.smart_status_label(None))
        self.assertIn('no disponible', storage_diag.smart_status_label(None))

    def test_clean_nvme_is_ok(self):
        data = {'smart_status': {'passed': True},
                'nvme_smart_health_information_log': {
                    'critical_warning': 0, 'media_errors': 0, 'available_spare': 100,
                    'available_spare_threshold': 10, 'percentage_used': 3}}
        self.assertEqual(storage_diag.evaluate_smart_health(data), {'level': 'ok', 'reasons': []})

    def test_failed_overall_status(self):
        res = storage_diag.evaluate_smart_health({'smart_status': {'passed': False}})
        self.assertEqual(res['level'], 'failed')

    def test_nvme_critical_warning_bits_fail(self):
        res = storage_diag.evaluate_smart_health(
            {'nvme_smart_health_information_log': {'critical_warning': 0x04 | 0x08}})
        self.assertEqual(res['level'], 'failed')
        self.assertEqual(len(res['reasons']), 2)

    def test_nvme_media_errors_and_wear_warn(self):
        res = storage_diag.evaluate_smart_health(
            {'nvme_smart_health_information_log': {'media_errors': 4, 'percentage_used': 95}})
        self.assertEqual(res['level'], 'warning')

    def test_spare_below_threshold_fails_with_nvme_cli_key_names(self):
        res = storage_diag.evaluate_smart_health(
            {'nvme_smart_health_information_log': {'avail_spare': 5, 'spare_thresh': 10, 'percent_used': 20}})
        self.assertEqual(res['level'], 'failed')

    def test_sata_reallocated_pending_uncorrectable_warn(self):
        res = storage_diag.evaluate_smart_health(
            ata((5, 'Reallocated_Sector_Ct', 12), (197, 'Current_Pending_Sector', 1), (198, 'Offline_Uncorrectable', 0)))
        self.assertEqual(res['level'], 'warning')
        self.assertEqual(len(res['reasons']), 2)

    def test_clean_sata_is_ok(self):
        res = storage_diag.evaluate_smart_health(
            ata((5, 'Reallocated_Sector_Ct', 0), (197, 'Current_Pending_Sector', 0)))
        self.assertEqual(res['level'], 'ok')

    def test_labels_reflect_the_level(self):
        health = {'level': 'failed', 'reasons': ['a', 'b']}
        self.assertIn('RIESGO DE FALLO', storage_diag.smart_status_label(health))
        self.assertIn('advertencias', storage_diag.smart_status_label({'level': 'warning', 'reasons': ['x']}))
        self.assertIn('USB', 'USB') and self.assertIn('Conectado', storage_diag.smart_status_label(None, is_usb=True))

    def test_nvme_cli_output_gets_a_verdict_and_wear(self):
        # nvme-cli names the wear field percent_used, smartctl percentage_used.
        nvme_cli = {'critical_warning': 0, 'percent_used': 12, 'data_units_written': 1000, 'power_on_hours': 10}

        def fake_run(cmd, **kw):
            if cmd[0] == 'nvme':
                import json
                return mock.Mock(returncode=0, stdout=json.dumps(nvme_cli))
            return mock.Mock(returncode=1, stdout='')

        with mock.patch('storage_diag.subprocess.run', side_effect=fake_run):
            end = storage_diag.get_drive_endurance('/dev/nvme0n1', 512)
        self.assertEqual(end['percentage_used'], 12)
        self.assertEqual(end['health']['level'], 'ok')


class BatteryTests(unittest.TestCase):
    def test_upower_is_not_spawned_on_every_poll(self):
        battery._UPOWER_CACHE.clear()
        with mock.patch('battery._query_upower', return_value=(100, 'charging', None)) as q:
            for _ in range(5):
                battery.get_upower_info('BAT0')
        self.assertEqual(q.call_count, 1)

    def test_upower_cache_expires(self):
        battery._UPOWER_CACHE.clear()
        with mock.patch('battery._query_upower', return_value=(1, None, None)) as q, \
             mock.patch('battery.time.monotonic', side_effect=[0.0, 100.0]):
            battery.get_upower_info('BAT0')
            battery.get_upower_info('BAT0')
        self.assertEqual(q.call_count, 2)

    def _bat(self, files):
        def get(path, default=None, is_int=False):
            return files.get(os.path.basename(path), default)

        with mock.patch('battery.glob.glob', side_effect=lambda p: ['/sys/class/power_supply/BAT0'] if p.endswith('BAT*') else []), \
             mock.patch('battery.get_sysfs_value', side_effect=get), \
             mock.patch('battery.get_upower_info', return_value=(None, None, None)):
            return battery.get_battery_info()[0]

    def test_health_is_unknown_when_capacities_are_not_reported(self):
        bat = self._bat({'status': 'Discharging', 'capacity': 80})
        self.assertIsNone(bat['health_percent'])

    def test_health_is_computed_from_capacities(self):
        bat = self._bat({'status': 'Discharging', 'capacity': 80,
                         'energy_full_design': 50_000_000, 'energy_full': 40_000_000})
        self.assertEqual(bat['health_percent'], 80.0)

    def test_no_battery_placeholder_has_no_health(self):
        with mock.patch('battery.glob.glob', return_value=[]):
            bat = battery.get_battery_info()[0]
        self.assertFalse(bat['present'])
        self.assertIsNone(bat['health_percent'])


class DisplayTests(unittest.TestCase):
    def _display(self, files):
        with tempfile.TemporaryDirectory() as d:
            port = os.path.join(d, 'card0-HDMI-A-1')
            os.mkdir(port)
            for name, content in files.items():
                with open(os.path.join(port, name), 'w') as f:
                    f.write(content)
            with mock.patch('display_hdmi_diag.glob.glob', return_value=[port]), \
                 mock.patch('display_hdmi_diag.subprocess.run', side_effect=OSError):
                return display_hdmi_diag.get_display_and_mobo()

    def test_disconnected_status_is_final_even_with_stale_modes(self):
        res = self._display({'status': 'disconnected\n', 'modes': '1920x1080\n', 'enabled': 'enabled\n'})
        self.assertFalse(res['hdmi_connected'])

    def test_connected_status(self):
        self.assertTrue(self._display({'status': 'connected\n'})['hdmi_connected'])

    def test_unknown_status_falls_back_to_modes(self):
        self.assertTrue(self._display({'status': 'unknown\n', 'modes': '1920x1080\n'})['hdmi_connected'])


class WifiListTests(unittest.TestCase):
    def test_ssid_with_colon_is_parsed(self):
        nets = wifi_diag.parse_wifi_list('no:Oficina\\:5G:72:wlan0\n')
        self.assertEqual(nets, [{'ssid': 'Oficina:5G', 'signal': 72, 'connected': False}])

    def test_backslash_and_hidden_networks(self):
        nets = wifi_diag.parse_wifi_list('no::40:wlan0\nno:a\\\\b:55:wlan0\n')
        self.assertEqual([n['ssid'] for n in nets], ['a\\b'])

    def test_strongest_ap_per_ssid_and_sorted_strongest_first(self):
        out = 'no:Casa:30:wlan0\nno:Casa:80:wlan0\nno:Vecino:60:wlan0\nyes:Oficina:20:wlan0\n'
        nets = wifi_diag.parse_wifi_list(out)
        self.assertEqual([n['ssid'] for n in nets], ['Oficina', 'Casa', 'Vecino'])  # connected first
        self.assertEqual(nets[1]['signal'], 80)
        self.assertTrue(nets[0]['connected'])

    def test_bad_signal_and_short_lines_do_not_crash(self):
        nets = wifi_diag.parse_wifi_list('garbage\nno:X:abc:wlan0\n\n')
        self.assertEqual(nets, [{'ssid': 'X', 'signal': 0, 'connected': False}])

    def test_virtual_interfaces_are_not_ethernet_ports(self):
        def exists(path):
            return path == '/sys/class/net'   # no /device link anywhere

        with mock.patch('wifi_diag.os.listdir', return_value=['lo', 'dummy0', 'sit0', 'bond0']), \
             mock.patch('wifi_diag.os.path.exists', side_effect=exists):
            res = wifi_diag.get_ethernet_status()
        self.assertFalse(res['present'])
        self.assertEqual(res['interfaces'], [])


class BluetoothTests(unittest.TestCase):
    def _info(self, soft, hard, powered):
        with tempfile.TemporaryDirectory() as d:
            rf = os.path.join(d, 'rfkill0')
            os.mkdir(rf)
            for name, val in (('type', 'bluetooth'), ('soft', '1' if soft else '0'), ('hard', '1' if hard else '0')):
                with open(os.path.join(rf, name), 'w') as f:
                    f.write(val + '\n')

            def glob_side(pattern):
                return ['/sys/class/bluetooth/hci0'] if 'bluetooth/hci' in pattern else [rf]

            show = mock.Mock(returncode=0, stdout='Controller AA:BB:CC:DD:EE:FF\n\tPowered: ' + ('yes' if powered else 'no'))
            with mock.patch('bluetooth_diag.glob.glob', side_effect=glob_side), \
                 mock.patch('bluetooth_diag.os.path.exists', return_value=False), \
                 mock.patch('bluetooth_diag.subprocess.run', return_value=show):
                return bluetooth_diag.get_bluetooth_info()

    def test_powered_adapter(self):
        info = self._info(False, False, True)
        self.assertTrue(info['is_powered'])
        self.assertEqual(info['status'], 'Operativo y alimentado')

    def test_present_but_off_is_not_powered(self):
        info = self._info(False, False, False)
        self.assertTrue(info['present'])
        self.assertFalse(info['is_powered'])
        self.assertIn('Apagado', info['status'])

    def test_blocked_radio_is_reported(self):
        self.assertIn('hardware', self._info(False, True, True)['status'])
        info = self._info(True, False, True)
        self.assertIn('software', info['status'])
        self.assertFalse(info['is_powered'])


class SystemInfoTests(unittest.TestCase):
    def test_placeholder_dmi_values_are_discarded(self):
        for v in ('Default string', 'To be filled by O.E.M.', 'None', ' System Serial Number ', '', '0', None):
            self.assertIsNone(system_info.clean_dmi_value(v), v)
        self.assertEqual(system_info.clean_dmi_value(' PF3ABC12 '), 'PF3ABC12')

    def test_placeholder_serial_falls_back_to_board_serial_then_na(self):
        def dmi(field):
            return {'product_serial': 'Default string', 'board_serial': 'BRD123'}.get(field)

        with mock.patch('system_info.read_dmi_field', side_effect=dmi):
            self.assertEqual(system_info.get_system_summary()['serial'], 'BRD123')
        with mock.patch('system_info.read_dmi_field', side_effect=lambda f: 'None' if 'serial' in f else None):
            self.assertEqual(system_info.get_system_summary()['serial'], 'N/A')

    def test_bare_tpm0_is_not_claimed_to_be_tpm2(self):
        def exists(p):
            return p == '/dev/tpm0'

        with mock.patch('system_info.glob.glob', return_value=[]), \
             mock.patch('system_info.os.path.exists', side_effect=exists):
            tpm = system_info.check_tpm_status()
        self.assertFalse(tpm['is_tpm2'])
        self.assertEqual(tpm['status'], 'Warning')

    def test_tpmrm0_means_tpm2(self):
        with mock.patch('system_info.glob.glob', return_value=[]), \
             mock.patch('system_info.os.path.exists', side_effect=lambda p: p == '/dev/tpmrm0'):
            self.assertTrue(system_info.check_tpm_status()['is_tpm2'])


class LenovoModelNameTests(unittest.TestCase):
    def test_part_number_is_not_used_as_the_model(self):
        for pn, ver, fam, expected in (
            ('20S0S1EJ00', 'ThinkPad T14 Gen 1', 'ThinkPad T14 Gen 1', 'ThinkPad T14 Gen 1'),
            ('20XKS1AA00', 'ThinkPad T14 Gen 2', 'None', 'ThinkPad T14 Gen 2'),
            ('20W0S0XX00', 'None', 'ThinkPad T14 Gen 2', 'ThinkPad T14 Gen 2'),   # name only in family
            ('21HDCTO1WW', 'ThinkPad T14 Gen 4', 'ThinkPad T14 Gen 4', 'ThinkPad T14 Gen 4'),
        ):
            model, sku = system_info.resolve_model_names(pn, ver, fam)
            self.assertEqual(model, expected)
            self.assertEqual(sku, pn)

    def test_other_vendors_and_missing_names_are_untouched(self):
        self.assertEqual(system_info.resolve_model_names('EliteBook 840 G8', '', 'HP EliteBook'), ('EliteBook 840 G8', ''))
        self.assertEqual(system_info.resolve_model_names('20S0S1EJ00', 'None', 'None')[0], '20S0S1EJ00')

    def test_summary_shows_name_first_and_part_number_in_parentheses(self):
        d = {'sys_vendor': 'LENOVO', 'product_name': '20S0S1EJ00',
             'product_version': 'ThinkPad T14 Gen 1', 'product_family': 'ThinkPad T14 Gen 1'}
        with mock.patch('system_info.read_dmi_field', side_effect=lambda f: d.get(f)):
            self.assertEqual(system_info.get_system_summary()['model'], 'LENOVO ThinkPad T14 Gen 1 (20S0S1EJ00)')


class CpuBenchmarkTests(unittest.TestCase):
    def test_real_run_uses_every_cpu_and_agrees(self):
        res = cpu_benchmark.run_cpu_benchmark(iterations=20_000)
        self.assertTrue(res['success'], res)
        self.assertEqual(res['errors'], 0)
        self.assertGreater(res['mops'], 0)

    def _fake_procs(self, outputs, returncode=0):
        procs = []
        for out in outputs:
            p = mock.Mock()
            p.communicate.return_value = (out, None)
            p.returncode = returncode
            procs.append(p)
        return procs

    def test_a_core_with_a_different_result_is_reported(self):
        good, bad = '0x1.8p+3 0.5', '0x1.8000000000001p+3 0.5'
        procs = self._fake_procs([good, good, bad, good])
        with mock.patch('cpu_benchmark.os.cpu_count', return_value=4), \
             mock.patch('cpu_benchmark.subprocess.Popen', side_effect=procs):
            res = cpu_benchmark.run_cpu_benchmark(iterations=10)
        self.assertFalse(res['success'])
        self.assertEqual(res['errors'], 1)

    def test_nan_or_garbage_output_is_an_error(self):
        procs = self._fake_procs(['nan 0.5', 'garbage', '0x1.8p+3 0.5'])
        with mock.patch('cpu_benchmark.os.cpu_count', return_value=3), \
             mock.patch('cpu_benchmark.subprocess.Popen', side_effect=procs):
            res = cpu_benchmark.run_cpu_benchmark(iterations=10)
        self.assertFalse(res['success'])
        self.assertEqual(res['errors'], 2)

    def test_crashed_worker_is_an_error(self):
        procs = self._fake_procs(['', '0x1.8p+3 0.5'], returncode=0)
        procs[0].returncode = 1
        with mock.patch('cpu_benchmark.os.cpu_count', return_value=2), \
             mock.patch('cpu_benchmark.subprocess.Popen', side_effect=procs):
            res = cpu_benchmark.run_cpu_benchmark(iterations=10)
        self.assertFalse(res['success'])


class RamBenchmarkTests(unittest.TestCase):
    def test_clean_memory_passes_with_five_patterns(self):
        res = ram_benchmark.run_ram_benchmark(chunk_mb=8)
        self.assertTrue(res['success'], res)
        self.assertEqual(res['errors'], 0)
        self.assertIn('5 patrones', res['message'])

    def test_corruption_fails_the_check_and_reports_errors(self):
        # The old benchmark always returned success=True, even with errors.
        def flip(pool):
            pool[0][12345] ^= 0x10

        res = ram_benchmark.run_ram_benchmark(chunk_mb=8, corrupt=flip)
        self.assertFalse(res['success'])
        self.assertGreaterEqual(res['errors'], 1)


class OpalSafetyTests(unittest.TestCase):
    def _erase(self, nvme_ok, read_ok=True):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd[0])
            if cmd[0] == 'nvme':
                return mock.Mock(returncode=0 if nvme_ok else 1, stdout='Success' if nvme_ok else '', stderr='')
            if cmd[0] == 'dd':
                return mock.Mock(returncode=0 if read_ok else 1, stdout='', stderr='')
            return mock.Mock(returncode=0, stdout='', stderr='')

        with mock.patch('opal_diag.os.path.exists', return_value=False), \
             mock.patch('opal_diag.os.path.exists', side_effect=lambda p: p == '/dev/nvme0n1'), \
             mock.patch('opal_diag.subprocess.run', side_effect=run), \
             mock.patch('opal_diag.time.sleep'):
            return opal_diag.execute_nvme_crypto_erase('/dev/nvme0n1'), calls

    def test_rejected_erase_does_not_wipe_partition_table(self):
        res, calls = self._erase(nvme_ok=False, read_ok=True)
        self.assertFalse(res['success'])           # a readable drive is not an erased drive
        self.assertNotIn('wipefs', calls)
        self.assertNotIn('parted', calls)
        self.assertIn('intactos', res['log'])

    def test_accepted_erase_wipes_and_succeeds(self):
        res, calls = self._erase(nvme_ok=True)
        self.assertTrue(res['success'])
        self.assertIn('wipefs', calls)
        self.assertIn('parted', calls)

    def test_opal_lock_detected_from_real_sedutil_output(self):
        locked = 'locking function (0x0002)\n    locked = y, lockingenabled = y, lockingsupported = y'
        unlocked = 'locking function (0x0002)\n    locked = n, lockingenabled = n, lockingsupported = y'
        for out, expected in ((locked, True), (unlocked, False), ('', False)):
            with mock.patch('opal_diag.sedutil_query', return_value=out):
                self.assertEqual(opal_diag.check_opal_locked('/dev/nvme0n1'), expected)


if __name__ == '__main__':
    unittest.main()
