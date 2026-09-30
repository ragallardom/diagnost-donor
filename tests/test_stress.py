"""Tests for the hardware stress suite (stress_diag + stress_workers).

Everything runs with tiny buffers / short durations: the goal is to prove that the
stress phases really detect faults, not to load the machine running the tests.
"""

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app', 'modules'))

import stress_diag  # noqa: E402
import stress_workers as sw  # noqa: E402


def make_runner(level='quick', components=('cpu',)):
    runner = stress_diag.HardwareStressRunner(components=list(components), level=level)
    runner.start_time = time.time()
    return runner


class InputValidationTests(unittest.TestCase):
    def test_unknown_level_is_rejected(self):
        # An unknown level used to fall back to quick timings but the "deep" RAM/SSD sizes.
        with self.assertRaises(ValueError):
            stress_diag.HardwareStressRunner(level='extreme')
        res = stress_diag.start_stress_test(components=['cpu'], level='extreme')
        self.assertFalse(res['success'])

    def test_unknown_or_malformed_components_are_rejected(self):
        for bad in (['cpu', 'fpga'], 'cpu', [], [1]):
            with self.assertRaises(ValueError):
                stress_diag.HardwareStressRunner(components=bad)

    def test_duplicate_components_run_once(self):
        runner = stress_diag.HardwareStressRunner(components=['ram', 'cpu', 'ram'])
        self.assertEqual(runner.components, ['ram', 'cpu'])

    def test_levels_are_strictly_more_demanding(self):
        totals = [stress_diag.HardwareStressRunner(level=lvl).total_duration_sec
                  for lvl in ('quick', 'medium', 'deep')]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual(len(set(totals)), 3)

    def test_quick_cpu_phase_leaves_a_full_sustained_window(self):
        # The thermal verdict drops the first TURBO_WINDOW_SEC and wants MIN_SUSTAINED_SEC after it.
        import thermal_health
        cpu = stress_diag.HardwareStressRunner(components=['cpu'], level='quick').durations['cpu']
        self.assertGreaterEqual(cpu - thermal_health.TURBO_WINDOW_SEC, thermal_health.MIN_SUSTAINED_SEC)


class ThermalWatchdogTests(unittest.TestCase):
    def test_sustained_heat_is_measured_in_seconds_not_calls(self):
        runner = make_runner()
        clock = [1000.0]
        with mock.patch.object(runner, 'get_cpu_temp', return_value=101.0), \
             mock.patch('stress_diag.time.monotonic', side_effect=lambda: clock[0]):
            # Many quick polls within 2 s (e.g. a fast RAM pattern) must not abort.
            for _ in range(10):
                self.assertTrue(runner.check_thermal_safety())
                clock[0] += 0.2
            clock[0] += 3.0
            self.assertFalse(runner.check_thermal_safety())
        self.assertTrue(runner.thermal_abort)

    def test_cooling_resets_the_timer(self):
        runner = make_runner()
        clock = [50.0]
        temps = iter([101.0, 90.0, 101.0])
        with mock.patch.object(runner, 'get_cpu_temp', side_effect=lambda: next(temps)), \
             mock.patch('stress_diag.time.monotonic', side_effect=lambda: clock[0]):
            self.assertTrue(runner.check_thermal_safety())
            clock[0] += 3.0
            self.assertTrue(runner.check_thermal_safety())   # dipped below 100: timer reset
            clock[0] += 3.0
            self.assertTrue(runner.check_thermal_safety())   # only just above 100 again

    def test_emergency_threshold_aborts_immediately(self):
        runner = make_runner()
        with mock.patch.object(runner, 'get_cpu_temp', return_value=104.5):
            self.assertFalse(runner.check_thermal_safety())


class CpuLoadTests(unittest.TestCase):
    def test_python_worker_runs_and_exits_clean(self):
        import subprocess
        res = subprocess.run([sys.executable, '-c', sw.CPU_WORKER_SRC, '0.3', '3000'], timeout=60)
        self.assertEqual(res.returncode, 0)

    def test_python_engine_uses_real_processes(self):
        load = sw.CpuLoad(2, 1)
        load.start()
        try:
            self.assertEqual(len(load.procs), 2)
            self.assertEqual({p.pid for p in load.procs} & {os.getpid()}, set())
            time.sleep(0.5)
            self.assertIsNone(load.check())
        finally:
            self.assertIsNone(load.stop())

    def _fake_proc(self, poll, returncode=None):
        return mock.Mock(poll=mock.Mock(return_value=poll), returncode=returncode if returncode is not None else poll,
                         terminate=mock.Mock(), wait=mock.Mock())

    def test_python_worker_mismatch_is_a_failure(self):
        load = sw.CpuLoad(1, 10)
        load.procs = [self._fake_proc(sw.CPU_MISMATCH_EXIT)]
        self.assertIn('error de cálculo', load.check())

    def test_stress_ng_verify_failure_is_a_failure(self):
        load = sw.CpuLoad(1, 10, stress_ng_bin='/usr/bin/stress-ng')
        load.procs = [self._fake_proc(sw.STRESS_NG_FAIL_EXIT)]
        self.assertIn('--verify', load.check())

    def test_early_exit_is_a_failure_even_with_code_zero(self):
        load = sw.CpuLoad(1, 10, stress_ng_bin='/usr/bin/stress-ng')
        load.procs = [self._fake_proc(0)]
        self.assertIn('antes de tiempo', load.check())

    def test_verify_failure_reported_while_winding_down(self):
        load = sw.CpuLoad(1, 10, stress_ng_bin='/usr/bin/stress-ng')
        proc = self._fake_proc(None, returncode=sw.STRESS_NG_FAIL_EXIT)
        load.procs = [proc]
        self.assertIsNone(load.check())
        self.assertIn('--verify', load.stop())

    def test_stress_ng_command_is_verifying_and_oversubscribed(self):
        with mock.patch('stress_workers.subprocess.Popen') as popen:
            load = sw.CpuLoad(4, 60, stress_ng_bin='/usr/bin/stress-ng')
            load.start()
            load._stderr.close()
        cmd = popen.call_args[0][0]
        for flag in ('--verify', '--cpu', '--matrix', '--vecmath'):
            self.assertIn(flag, cmd)
        self.assertEqual(cmd[cmd.index('--cpu') + 1], '4')

    def test_cpu_phase_fails_when_calculations_are_wrong(self):
        runner = make_runner()

        class BadLoad:
            engine = 'python'
            failure = None

            def __init__(self, *a, **k):
                pass

            def start(self):
                pass

            def check(self):
                return 'un hilo calculó un resultado distinto al de referencia (error de cálculo)'

            def stop(self):
                return self.check()

        with mock.patch('stress_workers.CpuLoad', BadLoad), \
             mock.patch('stress_diag.time.sleep'):
            runner._run_cpu_stress(5)
        res = runner.results['cpu']
        self.assertFalse(res['passed'])
        self.assertEqual(res['calc_errors'], 1)
        self.assertIn('errores de cálculo', res['message'])


class RamPatternTests(unittest.TestCase):
    def setUp(self):
        self.pool = [bytearray(2 * sw.RAM_BLOCK), bytearray(sw.RAM_BLOCK + 4096)]  # last block is partial

    def test_patterns_include_solid_random_and_walking_bits(self):
        names = sw.ram_pattern_names()
        solid = {a for k, a in names if k == 'solid'}
        self.assertTrue({0x00, 0xFF, 0x55, 0xAA} <= solid)
        self.assertTrue({1 << b for b in range(8)} <= solid)                  # walking ones
        self.assertTrue({(~(1 << b)) & 0xFF for b in range(8)} <= solid)      # walking zeros
        self.assertGreaterEqual(sum(1 for k, _ in names if k == 'random'), 2)
        # Discriminating patterns come first so a short run still gets them.
        self.assertEqual({names[i][1] for i in range(4)}, {0x00, 0xFF, 0x55, 0xAA})

    def test_clean_memory_passes_every_pattern_over_every_byte(self):
        for kind, arg in sw.ram_pattern_names():
            errors, bad, complete = sw.ram_pattern_pass(self.pool, kind, arg)
            self.assertEqual((errors, bad, complete), (0, [], True), (kind, arg))

    def test_pattern_actually_covers_the_whole_buffer(self):
        # The old test only touched 2 bytes every 2048; here every byte must be written.
        for c in self.pool:
            c[:] = b'\x5a' * len(c)
        sw.ram_pattern_pass(self.pool, 'solid', 0x00, corrupt=None)
        self.assertTrue(all(b == 0 for c in self.pool for b in c))

    def test_single_flipped_bit_between_old_sampling_points_is_found(self):
        def flip(pool):
            pool[0][1000] ^= 0x01      # offset the old stride (0, 2048, ...) never looked at

        errors, bad, complete = sw.ram_pattern_pass(self.pool, 'solid', 0xAA, corrupt=flip)
        self.assertEqual(errors, 1)
        self.assertEqual(bad, [(0, 0)])
        self.assertTrue(complete)

    def test_corruption_in_partial_last_block_is_found(self):
        def flip(pool):
            pool[1][-1] ^= 0x80

        errors, bad, _ = sw.ram_pattern_pass(self.pool, 'random', 0, corrupt=flip)
        self.assertEqual(errors, 1)
        self.assertEqual(bad[0][0], 1)

    def test_neighbouring_random_blocks_differ(self):
        table = sw._random_table(0)
        blocks = [sw._pattern_block('random', 0, i, table) for i in range(6)]
        for a, b in zip(blocks, blocks[1:]):
            self.assertNotEqual(a, b)

    def test_stop_request_interrupts_the_pass(self):
        errors, bad, complete = sw.ram_pattern_pass(self.pool, 'solid', 0x55, should_stop=lambda: True)
        self.assertFalse(complete)


class RamPhaseTests(unittest.TestCase):
    def test_phase_passes_and_reports_real_pattern_count(self):
        runner = make_runner(components=('ram',))
        with mock.patch.object(runner, '_ram_alloc_mb', return_value=(1000, 64)), \
             mock.patch('stress_diag.time.sleep'):
            runner._run_ram_stress(3)
        res = runner.results['ram']
        self.assertTrue(res['passed'])
        self.assertGreater(res['patterns_verified'], 0)
        self.assertEqual(res['bit_errors'], 0)

    def test_phase_fails_and_logs_real_error_count(self):
        runner = make_runner(components=('ram',))
        real = sw.ram_pattern_pass

        def faulty(pool, kind, arg, should_stop=lambda: False, corrupt=None):
            return real(pool, kind, arg, should_stop, corrupt=lambda p: p[0].__setitem__(5, p[0][5] ^ 1))

        with mock.patch.object(runner, '_ram_alloc_mb', return_value=(1000, 64)), \
             mock.patch('stress_workers.ram_pattern_pass', faulty), \
             mock.patch('stress_diag.time.sleep'):
            runner._run_ram_stress(2)
        res = runner.results['ram']
        self.assertFalse(res['passed'])
        self.assertGreater(res['bit_errors'], 0)
        self.assertTrue(any(l['type'] == 'error' and 'bytes distintos' in l['message'] for l in runner.logs))
        # The per-pass log never claims "0 fallos" when there were failures.
        self.assertFalse(any('(0 fallos)' in l['message'] and 'Pasada' in l['message'] and l['type'] == 'info'
                             and 'bytes distintos' in l['message'] for l in runner.logs))

    def test_time_budget_never_prevents_the_first_full_pattern(self):
        runner = make_runner(components=('ram',))
        with mock.patch.object(runner, '_ram_alloc_mb', return_value=(1000, 64)), \
             mock.patch('stress_diag.time.sleep'):
            runner._run_ram_stress(0)
        res = runner.results['ram']
        self.assertTrue(res['passed'])
        self.assertEqual(res['patterns_verified'], 1)

    def test_aborted_before_any_pattern_is_not_a_pass(self):
        runner = make_runner(components=('ram',))
        runner.aborted = True
        with mock.patch.object(runner, '_ram_alloc_mb', return_value=(1000, 64)):
            runner._run_ram_stress(3)
        self.assertFalse(runner.results['ram']['passed'])

    def test_allocation_grows_with_level_and_respects_available_ram(self):
        sizes = {}
        for lvl in ('quick', 'medium', 'deep'):
            runner = stress_diag.HardwareStressRunner(components=['ram'], level=lvl)
            with mock.patch('builtins.open', mock.mock_open(read_data='MemAvailable:   16000000 kB\n')):
                free, alloc = runner._ram_alloc_mb()
            sizes[lvl] = alloc
            self.assertLessEqual(alloc, free * 0.8 + 1)
        self.assertLess(sizes['quick'], sizes['medium'])
        self.assertLess(sizes['medium'], sizes['deep'])


class DiskReadStressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.write(os.urandom(6 * 1024 * 1024))
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_read_load_on_healthy_file(self):
        rep = sw.DiskReadStress(self.tmp.name, duration_sec=1.2, rand_threads=2).run()
        self.assertEqual(rep['io_errors'], 0)
        self.assertEqual(rep['mismatches'], 0)
        self.assertGreater(rep['seq_mb'], 0)
        self.assertGreater(rep['rand_iops'], 0)

    def test_load_never_modifies_the_device(self):
        with open(self.tmp.name, 'rb') as f:
            before = f.read()
        sw.DiskReadStress(self.tmp.name, duration_sec=0.6, rand_threads=2).run()
        with open(self.tmp.name, 'rb') as f:
            self.assertEqual(f.read(), before)

    def test_inconsistent_rereads_are_detected(self):
        stop = threading.Event()

        def corrupt_forever():
            fd = os.open(self.tmp.name, os.O_WRONLY)
            try:
                while not stop.is_set():
                    os.pwrite(fd, os.urandom(6 * 1024 * 1024), 0)
                    time.sleep(0.01)
            finally:
                os.close(fd)

        t = threading.Thread(target=corrupt_forever, daemon=True)
        t.start()
        try:
            rep = sw.DiskReadStress(self.tmp.name, duration_sec=2.0, rand_threads=1, samples=4).run()
        finally:
            stop.set()
            t.join(5)
        self.assertGreater(rep['mismatches'], 0)

    def test_stop_check_ends_the_load_early(self):
        t0 = time.monotonic()
        sw.DiskReadStress(self.tmp.name, duration_sec=30, rand_threads=1, stop_check=lambda: True).run()
        self.assertLess(time.monotonic() - t0, 5)

    def test_missing_device_raises(self):
        with self.assertRaises(OSError):
            sw.DiskReadStress('/nonexistent/device', duration_sec=1).run()

    def test_tiny_device_is_rejected_instead_of_looping(self):
        with tempfile.NamedTemporaryFile() as small:
            small.write(b'x' * 8192)
            small.flush()
            with self.assertRaises(OSError):
                sw.DiskReadStress(small.name, duration_sec=1).run()

    def test_throughput_drop_is_computed_from_sweeps(self):
        job = sw.DiskReadStress('x', duration_sec=10)
        job.seq_speeds = [(2, 1000.0), (4, 1000.0), (6, 400.0), (8, 400.0)]
        self.assertEqual(job.summary()['throughput_drop_pct'], 60.0)


class InternalDisksTests(unittest.TestCase):
    def test_no_sys_block_gives_no_disks(self):
        with mock.patch('stress_workers.os.listdir', side_effect=OSError):
            self.assertEqual(sw.internal_disks(), [])

    def test_ram_backed_filesystems_are_detected(self):
        mounts = 'overlay / overlay rw 0 0\ntmpfs /tmp tmpfs rw 0 0\n/dev/nvme0n1p2 /data ext4 rw 0 0\n'
        with mock.patch('builtins.open', mock.mock_open(read_data=mounts)):
            self.assertTrue(sw.is_ram_backed('/tmp/x'))
            self.assertTrue(sw.is_ram_backed('/var/tmp/x'))       # falls to overlay /
            self.assertFalse(sw.is_ram_backed('/data/x'))


    def test_tiny_devices_are_not_probed(self):
        def fake_open(path, *a, **k):
            data = {'removable': '0\n', 'size': '2048\n'}[os.path.basename(path)]
            return mock.mock_open(read_data=data)()

        with mock.patch('stress_workers.os.listdir', return_value=['vdb']), \
             mock.patch('stress_workers.os.path.realpath', side_effect=lambda p: p), \
             mock.patch('builtins.open', side_effect=fake_open):
            self.assertEqual(sw.internal_disks(), [])


class SsdPhaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.write(os.urandom(6 * 1024 * 1024))
        self.tmp.close()
        self.runner = make_runner(components=('ssd',))

    def tearDown(self):
        os.unlink(self.tmp.name)

    def disk(self, path=None):
        return {'device': path or self.tmp.name, 'size_bytes': 6 * 1024 * 1024}

    def test_no_internal_disk_is_skipped_not_passed(self):
        with mock.patch('stress_workers.internal_disks', return_value=[]):
            self.runner._run_ssd_stress(2)
        res = self.runner.results['ssd']
        self.assertIsNone(res['passed'])
        self.assertTrue(res['skipped'])

    def test_healthy_disk_passes(self):
        with mock.patch('stress_workers.internal_disks', return_value=[self.disk()]), \
             mock.patch('stress_diag.time.sleep'):
            self.runner._run_ssd_stress(1)
        res = self.runner.results['ssd']
        self.assertTrue(res['passed'], res['message'])
        self.assertEqual(len(res['drives']), 1)
        self.assertGreater(res['total_mb_read'], 0)

    def test_unreadable_disk_fails_the_phase(self):
        with mock.patch('stress_workers.internal_disks', return_value=[self.disk('/nonexistent/nvme0n1')]), \
             mock.patch('stress_diag.time.sleep'):
            self.runner._run_ssd_stress(1)
        res = self.runner.results['ssd']
        self.assertFalse(res['passed'])
        self.assertIn('error', res['drives'][0])

    def test_one_bad_disk_fails_even_if_another_is_fine(self):
        disks = [self.disk(), self.disk('/nonexistent/sda')]
        with mock.patch('stress_workers.internal_disks', return_value=disks), \
             mock.patch('stress_diag.time.sleep'):
            self.runner._run_ssd_stress(1)
        self.assertFalse(self.runner.results['ssd']['passed'])

    def test_never_writes_a_temp_file(self):
        self.assertFalse(os.path.exists('/tmp/ssd_stress_test.bin'))
        with mock.patch('stress_workers.internal_disks', return_value=[self.disk()]), \
             mock.patch('stress_diag.time.sleep'):
            self.runner._run_ssd_stress(1)
        self.assertFalse(os.path.exists('/tmp/ssd_stress_test.bin'))


class GpuPhaseTests(unittest.TestCase):
    def run_gpu(self, report=None):
        runner = make_runner(components=('gpu',))

        def browser_reports(_seconds):
            # The browser posts while the phase is running (the phase resets stale data first).
            if report is not None:
                runner.report_gpu(report)

        with mock.patch('stress_diag.time.sleep', side_effect=browser_reports), \
             mock.patch.object(runner, 'check_thermal_safety', return_value=True):
            runner._run_gpu_stress(1)
        return runner.results['gpu']

    def test_no_browser_report_is_unverified_not_passed(self):
        # The old code returned "stable, no context loss" without ever asking the browser.
        res = self.run_gpu()
        self.assertIsNone(res['passed'])
        self.assertTrue(res['skipped'])

    def test_healthy_report_passes(self):
        res = self.run_gpu({'frames': 600, 'avg_fps': 58.2, 'min_fps': 41, 'context_lost': False})
        self.assertIs(res['passed'], True)

    def test_context_loss_fails(self):
        res = self.run_gpu({'frames': 100, 'avg_fps': 50, 'min_fps': 3, 'context_lost': True})
        self.assertIs(res['passed'], False)
        self.assertIn('contexto', res['message'])

    def test_shader_error_fails(self):
        res = self.run_gpu({'frames': 0, 'avg_fps': 0, 'error': 'Error compilando shader'})
        self.assertIs(res['passed'], False)

    def test_slideshow_framerate_fails(self):
        res = self.run_gpu({'frames': 20, 'avg_fps': 1.5, 'min_fps': 1})
        self.assertIs(res['passed'], False)

    def test_report_is_sanitised(self):
        runner = make_runner(components=('gpu',))
        runner.report_gpu({'frames': 'many', 'avg_fps': float('nan'), 'error': 'x' * 1000, 'renderer': None})
        self.assertEqual(runner.gpu_report['frames'], 0)
        self.assertEqual(runner.gpu_report['avg_fps'], 0.0)
        self.assertEqual(len(runner.gpu_report['error']), 200)
        with self.assertRaises(ValueError):
            runner.report_gpu('nope')

    def test_report_is_only_accepted_while_running(self):
        with mock.patch.object(stress_diag, '_stress_runner', None):
            self.assertFalse(stress_diag.report_gpu_result({'frames': 1})['success'])


class SuiteVerdictTests(unittest.TestCase):
    def test_failed_and_unverified_components_are_reported(self):
        runner = make_runner(components=('ram', 'gpu'))
        runner.results = {'ram': {'passed': False}, 'gpu': {'passed': None, 'skipped': True}}
        runner.is_running = True
        runner.start_time = time.time()
        # Drive only the finalisation: no components left to run.
        runner.components = []
        runner._run_all_tests()
        self.assertTrue(any(l['type'] == 'error' and 'RAM' in l['message'] for l in runner.logs))
        self.assertEqual(runner.get_status()['failed_components'], ['ram'])


if __name__ == '__main__':
    unittest.main()
