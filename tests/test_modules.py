"""Tests for disk target validation and the storage probe cache."""

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app', 'modules'))

import opal_diag  # noqa: E402
import storage_diag  # noqa: E402


class ValidateTargetDeviceTests(unittest.TestCase):
    def validate(self, device, exists=True, boot_disks=(), applicable=True):
        with mock.patch('opal_diag.os.path.exists', return_value=exists), \
             mock.patch('opal_diag.get_boot_medium_disks', return_value=set(boot_disks)), \
             mock.patch('opal_diag.classify_drive', return_value={'opal_applicable': applicable}):
            return opal_diag.validate_target_device(device)

    def test_accepts_whole_disks(self):
        for dev in ('/dev/nvme0n1', '/dev/nvme0', '/dev/sda', '/dev/mmcblk0'):
            self.assertTrue(self.validate(dev)[0], dev)

    def test_rejects_non_ssd(self):
        ok, reason = self.validate('/dev/sdb', applicable=False)
        self.assertFalse(ok)
        self.assertIn('no es un SSD', reason)

    def test_rejects_partitions_and_other_paths(self):
        for dev in ('/dev/sda1', '/dev/nvme0n1p1', '/dev/../etc/passwd', '/etc/passwd',
                    '/dev/sda\n', '', None, '/dev/loop0'):
            self.assertFalse(self.validate(dev)[0], repr(dev))

    def test_rejects_missing_device(self):
        self.assertFalse(self.validate('/dev/sdb', exists=False)[0])

    def test_rejects_boot_medium(self):
        ok, reason = self.validate('/dev/sdb', boot_disks={'sdb'})
        self.assertFalse(ok)
        self.assertIn('arranque', reason)


class ClassifyDriveTests(unittest.TestCase):
    """Opal queries only apply to SSDs: internal NVMe/SATA SSD and external USB SSD."""

    def setUp(self):
        opal_diag.invalidate_opal_cache()

    def classify(self, device, usb=False, rotational=0, removable=0, smart_rate=None):
        values = {'rotational': rotational, 'removable': removable, 'size': 1000}

        def read_int(path):
            return values[path.rsplit('/', 1)[1]]

        path = '/sys/devices/pci0000:00/usb2/2-1/host0/block/sdb' if usb else '/sys/devices/pci0000:00/ata1/block/sda'
        with mock.patch('opal_diag._read_sys_int', side_effect=read_int), \
             mock.patch('opal_diag.os.path.realpath', return_value=path), \
             mock.patch('opal_diag._smart_rotation_rate', return_value=smart_rate) as smart:
            result = opal_diag.classify_drive(device)
        return result, smart

    def test_nvme_is_applicable(self):
        self.assertTrue(opal_diag.classify_drive('/dev/nvme0n1')['opal_applicable'])
        self.assertTrue(opal_diag.classify_drive('/dev/nvme0')['opal_applicable'])

    def test_emmc_sd_card_not_applicable(self):
        self.assertFalse(opal_diag.classify_drive('/dev/mmcblk0')['opal_applicable'])

    def test_internal_sata_ssd(self):
        r, _ = self.classify('/dev/sda', rotational=0)
        self.assertEqual((r['media'], r['opal_applicable']), ('ssd', True))

    def test_internal_hdd(self):
        r, _ = self.classify('/dev/sda', rotational=1)
        self.assertEqual((r['media'], r['opal_applicable']), ('hdd', False))

    def test_usb_pen_drive_removable(self):
        r, smart = self.classify('/dev/sdb', usb=True, rotational=1, removable=1)
        self.assertEqual((r['media'], r['opal_applicable']), ('flash', False))
        smart.assert_not_called()

    def test_usb_ssd_reporting_non_rotational(self):
        r, smart = self.classify('/dev/sdb', usb=True, rotational=0, removable=0)
        self.assertEqual((r['media'], r['opal_applicable']), ('ssd', True))
        smart.assert_not_called()

    def test_usb_ssd_detected_by_smart(self):
        r, _ = self.classify('/dev/sdb', usb=True, rotational=1, removable=0, smart_rate=0)
        self.assertEqual((r['media'], r['opal_applicable']), ('ssd', True))

    def test_usb_external_hdd(self):
        r, _ = self.classify('/dev/sdb', usb=True, rotational=1, removable=0, smart_rate=5400)
        self.assertEqual((r['media'], r['opal_applicable']), ('hdd', False))

    def test_usb_unknown_is_treated_as_pen_drive(self):
        r, _ = self.classify('/dev/sdb', usb=True, rotational=1, removable=0, smart_rate=None)
        self.assertEqual((r['media'], r['opal_applicable']), ('flash', False))


class StorageOpalScopeTests(unittest.TestCase):
    def test_no_opal_query_or_inference_on_non_ssd(self):
        failing = mock.Mock(returncode=1, stdout='', stderr='')
        with mock.patch('storage_diag.subprocess.run', return_value=failing), \
             mock.patch('storage_diag.sedutil_query') as sed:
            r = storage_diag.check_drive_read_and_opal('/dev/sdb', is_usb=True, opal_applicable=False)
        sed.assert_not_called()
        self.assertFalse(r['is_opal_locked'])
        self.assertEqual(r['read_diagnostic'], 'FAILED')

    def test_ssd_read_failure_flags_possible_opal(self):
        failing = mock.Mock(returncode=1, stdout='', stderr='')
        with mock.patch('storage_diag.subprocess.run', return_value=failing), \
             mock.patch('storage_diag.sedutil_query', return_value='') as sed:
            r = storage_diag.check_drive_read_and_opal('/dev/nvme0n1', opal_applicable=True)
        sed.assert_called_once()
        self.assertTrue(r['is_opal_locked'])


class StorageProbeCacheTests(unittest.TestCase):
    def setUp(self):
        storage_diag.invalidate_storage_cache()

    def tearDown(self):
        storage_diag.invalidate_storage_cache()

    def test_probe_is_cached_until_invalidated(self):
        with mock.patch('storage_diag._probe_drive', return_value={'diag': {}}) as probe:
            args = ('nvme0n1', '/dev/nvme0n1', False, 512.1, 'MODEL')
            storage_diag._get_cached_probe(*args)
            storage_diag._get_cached_probe(*args)
            self.assertEqual(probe.call_count, 1)

            storage_diag.invalidate_storage_cache('/dev/nvme0n1')
            storage_diag._get_cached_probe(*args)
            self.assertEqual(probe.call_count, 2)

    def test_probe_reruns_when_drive_changes(self):
        with mock.patch('storage_diag._probe_drive', return_value={'diag': {}}) as probe:
            storage_diag._get_cached_probe('sda', '/dev/sda', True, 32.0, 'STICK A')
            storage_diag._get_cached_probe('sda', '/dev/sda', True, 64.0, 'STICK B')
            self.assertEqual(probe.call_count, 2)

    def test_probe_expires_after_ttl(self):
        with mock.patch('storage_diag._probe_drive', return_value={'diag': {}}) as probe, \
             mock.patch('storage_diag.time.monotonic', side_effect=[0.0, 0.0, storage_diag.PROBE_TTL_SEC + 1, 0.0]):
            storage_diag._get_cached_probe('sda', '/dev/sda', False, 256.0, 'SSD')
            storage_diag._get_cached_probe('sda', '/dev/sda', False, 256.0, 'SSD')
            self.assertEqual(probe.call_count, 2)

    def test_scan_is_skipped_during_disk_operation(self):
        snapshot = {'internal': [{'device': '/dev/nvme0n1'}], 'usb': [], 'all': []}
        with mock.patch('storage_diag._scan_storage', return_value=snapshot):
            self.assertEqual(storage_diag.get_storage_info(), snapshot)

        with mock.patch('storage_diag._scan_storage', side_effect=AssertionError('drive touched')):
            with storage_diag.exclusive_disk_access():
                self.assertEqual(storage_diag.get_storage_info(), snapshot)


if __name__ == '__main__':
    unittest.main()
