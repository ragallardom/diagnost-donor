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
    def validate(self, device, exists=True, boot_disks=()):
        with mock.patch('opal_diag.os.path.exists', return_value=exists), \
             mock.patch('opal_diag.get_boot_medium_disks', return_value=set(boot_disks)):
            return opal_diag.validate_target_device(device)

    def test_accepts_whole_disks(self):
        for dev in ('/dev/nvme0n1', '/dev/nvme0', '/dev/sda', '/dev/mmcblk0'):
            self.assertTrue(self.validate(dev)[0], dev)

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
