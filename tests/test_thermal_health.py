"""Tests for CPU thermal health: sensors, throttling counters and the cleaning verdict."""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app', 'modules'))

import thermal_health as th  # noqa: E402


class FakeSysfs:
    """Builds a fake /sys + /proc tree and points thermal_health.ROOT at it."""

    def __init__(self):
        self.root = tempfile.mkdtemp()

    def write(self, path, value):
        full = self.root + path
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w') as f:
            f.write(str(value))

    def hwmon(self, idx, name, sensors):
        """sensors: list of (label, temp_c, crit_c or None)."""
        base = f'/sys/class/hwmon/hwmon{idx}'
        self.write(base + '/name', name)
        for i, (label, temp, crit) in enumerate(sensors, start=1):
            self.write(f'{base}/temp{i}_input', int(temp * 1000))
            if label:
                self.write(f'{base}/temp{i}_label', label)
            if crit:
                self.write(f'{base}/temp{i}_crit', int(crit * 1000))

    def throttle(self, cpu, core_count, core_ms, pkg_count=None, pkg_ms=None, pkg_id=0):
        base = f'/sys/devices/system/cpu/cpu{cpu}'
        self.write(base + '/thermal_throttle/core_throttle_count', core_count)
        self.write(base + '/thermal_throttle/core_throttle_total_time_ms', core_ms)
        if pkg_count is not None:
            self.write(base + '/thermal_throttle/package_throttle_count', pkg_count)
            self.write(base + '/thermal_throttle/package_throttle_total_time_ms', pkg_ms)
        self.write(base + '/topology/physical_package_id', pkg_id)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class SensorTests(unittest.TestCase):
    def setUp(self):
        self.fs = FakeSysfs()
        th.ROOT = self.fs.root

    def tearDown(self):
        th.ROOT = ''
        self.fs.cleanup()

    def test_intel_coretemp_uses_hottest_core_and_tjmax(self):
        self.fs.hwmon(0, 'coretemp', [('Package id 0', 71, 100), ('Core 0', 75, 100), ('Core 1', 73, 100)])
        self.fs.hwmon(1, 'nvme', [('Composite', 90, None)])  # not a CPU sensor
        self.assertEqual(th.read_cpu_temp(), (75.0, 'hwmon'))
        self.assertEqual(th.read_tjmax(), 100)

    def test_amd_prefers_tdie_over_tctl(self):
        self.fs.hwmon(0, 'k10temp', [('Tctl', 88, None), ('Tdie', 78, None)])
        self.assertEqual(th.read_cpu_temp()[0], 78.0)
        self.assertIsNone(th.read_tjmax())

    def test_amd_tctl_only(self):
        self.fs.hwmon(0, 'k10temp', [('Tctl', 91, None)])
        self.assertEqual(th.read_cpu_temp()[0], 91.0)

    def test_x86_pkg_temp_fallback(self):
        self.fs.write('/sys/class/thermal/thermal_zone3/type', 'x86_pkg_temp')
        self.fs.write('/sys/class/thermal/thermal_zone3/temp', 64000)
        self.assertEqual(th.read_cpu_temp(), (64.0, 'x86_pkg_temp'))

    def test_no_sensor_is_none_not_invented(self):
        self.fs.write('/sys/class/thermal/thermal_zone0/type', 'acpitz')
        self.fs.write('/sys/class/thermal/thermal_zone0/temp', 45000)
        self.assertEqual(th.read_cpu_temp(), (None, None))

    def test_throttle_counters_count_package_once(self):
        # 2 CPUs of the same package: core counters add up, package counter counted once.
        self.fs.throttle(0, 3, 1200, pkg_count=5, pkg_ms=4000)
        self.fs.throttle(1, 2, 800, pkg_count=5, pkg_ms=4000)
        c = th.read_throttle_counters()
        self.assertEqual((c['core_events'], c['core_time_ms']), (5, 2000))
        self.assertEqual((c['package_events'], c['package_time_ms']), (5, 4000))

    def test_throttle_counters_unsupported(self):
        self.assertEqual(th.read_throttle_counters(), {'supported': False})

    def test_throttle_delta(self):
        before = {'supported': True, 'core_events': 2, 'core_time_ms': 100, 'package_events': 1, 'package_time_ms': 50}
        after = {'supported': True, 'core_events': 6, 'core_time_ms': 4100, 'package_events': 3, 'package_time_ms': 5050}
        self.assertEqual(th.throttle_delta(before, after), {'supported': True, 'events': 6, 'time_ms': 5000})


def samples(temps_by_second):
    return [{'t': t, 'temp': temp, 'mhz': None} for t, temp in enumerate(temps_by_second)]


NO_THROTTLE = {'supported': True, 'events': 0, 'time_ms': 0}


class StressEvaluationTests(unittest.TestCase):
    def test_healthy_laptop_is_ok(self):
        r = th.evaluate_stress_samples(samples([70] * 5 + [82] * 115), NO_THROTTLE, tjmax=100)
        self.assertEqual(r['level'], th.LEVEL_OK)
        self.assertFalse(r['preliminary'])

    def test_turbo_peaks_alone_are_not_a_problem(self):
        # Hot only during the first 30 s (PL2/Turbo), then settles at 84 °C.
        r = th.evaluate_stress_samples(samples([99] * 25 + [84] * 95), NO_THROTTLE)
        self.assertEqual(r['level'], th.LEVEL_OK)
        self.assertEqual(r['peak_c'], 99)

    def test_sustained_95_recommends_cleaning(self):
        r = th.evaluate_stress_samples(samples([90] * 30 + [97] * 90), NO_THROTTLE, tjmax=100)
        self.assertEqual(r['level'], th.LEVEL_CLEAN)
        self.assertIn('pasta térmica', r['recommendation'])
        self.assertEqual(r['sustained_hot_pct'], 100)

    def test_sustained_just_below_threshold_is_watch(self):
        r = th.evaluate_stress_samples(samples([90] * 30 + [92] * 90), NO_THROTTLE)
        self.assertEqual(r['level'], th.LEVEL_WATCH)

    def test_significant_thermal_throttling_recommends_cleaning(self):
        # OEM thermal limit below 95 °C: throttles at 91 °C. Counters catch it.
        r = th.evaluate_stress_samples(samples([91] * 120), {'supported': True, 'events': 40, 'time_ms': 25000})
        self.assertEqual(r['level'], th.LEVEL_CLEAN)

    def test_brief_throttling_is_watch(self):
        r = th.evaluate_stress_samples(samples([85] * 120), {'supported': True, 'events': 1, 'time_ms': 300})
        self.assertEqual(r['level'], th.LEVEL_WATCH)

    def test_thermal_abort_recommends_cleaning(self):
        r = th.evaluate_stress_samples(samples([98] * 20 + [101] * 5), NO_THROTTLE, thermal_abort=True)
        self.assertEqual(r['level'], th.LEVEL_CLEAN)

    def test_quick_test_is_preliminary(self):
        r = th.evaluate_stress_samples(samples([96] * 45), NO_THROTTLE)
        self.assertTrue(r['preliminary'])
        self.assertEqual(r['level'], th.LEVEL_CLEAN)

    def test_stopped_fan_while_hot(self):
        r = th.evaluate_stress_samples(samples([85] * 120), NO_THROTTLE, fans=[0, 0, 0])
        self.assertEqual(r['level'], th.LEVEL_CLEAN)
        self.assertTrue(any('0 RPM' in x for x in r['reasons']))

    def test_amd_without_counters_uses_temperature(self):
        r = th.evaluate_stress_samples(samples([96] * 120), {'supported': False})
        self.assertEqual(r['level'], th.LEVEL_CLEAN)
        self.assertTrue(any('no disponibles' in x for x in r['reasons']))

    def test_no_sensor_is_unknown(self):
        r = th.evaluate_stress_samples(samples([None] * 60), NO_THROTTLE)
        self.assertEqual(r['level'], th.LEVEL_UNKNOWN)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.fs = FakeSysfs()
        th.ROOT = self.fs.root
        self.fs.write('/proc/cpuinfo', 'vendor_id\t: GenuineIntel\n')
        self.busy = 0
        self.total = 0

    def tearDown(self):
        th.ROOT = ''
        self.fs.cleanup()

    def set_state(self, temp, util=1.0, core_events=0):
        self.fs.hwmon(0, 'coretemp', [('Package id 0', temp, 100)])
        self.fs.throttle(0, core_events, core_events * 100)
        self.busy += int(100 * util)
        self.total += 100
        idle = self.total - self.busy
        self.fs.write('/proc/stat', f'cpu {self.busy} 0 0 {idle} 0 0 0 0 0 0\n')

    def test_sustained_hot_in_general_view(self):
        m = th.ThermalMonitor()
        for sec in range(0, 61):
            self.set_state(96)
            h = m.sample(now=float(sec))
        self.assertEqual(h['level'], th.LEVEL_CLEAN)
        self.assertEqual(h['hot_sustained_sec'], 60)

    def test_short_hot_spike_is_ok(self):
        m = th.ThermalMonitor()
        for sec in range(0, 20):
            self.set_state(97)
            m.sample(now=float(sec))
        self.set_state(60)
        self.assertEqual(m.sample(now=21.0)['level'], th.LEVEL_OK)

    def test_hot_while_idle(self):
        m = th.ThermalMonitor()
        for sec in range(0, 62):
            self.set_state(78, util=0.05)
            h = m.sample(now=float(sec))
        self.assertEqual(h['level'], th.LEVEL_CLEAN)
        self.assertIn('reposo', h['message'])

    def test_throttling_events_since_boot_and_active(self):
        m = th.ThermalMonitor()
        self.set_state(70, core_events=4)
        h = m.sample(now=0.0)
        self.assertEqual(h['level'], th.LEVEL_WATCH)
        self.assertEqual(h['throttle_events_since_boot'], 4)
        self.assertFalse(h['throttling_now'])
        self.set_state(70, core_events=5)
        self.assertTrue(m.sample(now=1.0)['throttling_now'])


if __name__ == '__main__':
    unittest.main()
