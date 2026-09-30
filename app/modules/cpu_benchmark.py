#!/usr/bin/env python3
"""
CPU Fast Stability & Performance Benchmark Module
Runs the same floating-point kernel on every logical CPU at the same time (one
process per CPU, because threads would be serialized by the GIL and only ever load
one core) and checks that all of them return bit-identical results. A core with a
faulty FPU / cache / unstable clock produces a different value and is reported.
"""

import os
import subprocess
import sys
import time
from collections import Counter

ITERATIONS = 1_200_000  # ~0.5 s per core on a current laptop CPU

_WORKER_SRC = r'''
import math, sys, time
n = int(sys.argv[1])
t0 = time.perf_counter()
val = 1.0
for i in range(1, n):
    val = math.sin(val) * math.cos(i * 0.001) + math.sqrt(i + val * val)
print(val.hex(), time.perf_counter() - t0)
'''


def _parse_worker(stdout):
    """(result_hex, compute_seconds) from a worker's output, or (None, None)."""
    try:
        hex_val, secs = stdout.split()
        value = float.fromhex(hex_val)
        if value != value or value in (float('inf'), float('-inf')):
            return None, None
        return hex_val, float(secs)
    except Exception:
        return None, None


def run_cpu_benchmark(iterations=ITERATIONS, timeout=30):
    cores = os.cpu_count() or 4
    start_time = time.time()
    try:
        procs = [subprocess.Popen([sys.executable, '-c', _WORKER_SRC, str(iterations)],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                 for _ in range(cores)]
        results, times, bad = [], [], 0
        for p in procs:
            try:
                out, _ = p.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()
                bad += 1
                continue
            hex_val, secs = _parse_worker(out) if p.returncode == 0 else (None, None)
            if hex_val is None:
                bad += 1
            else:
                results.append(hex_val)
                times.append(secs)

        # The kernel is deterministic: every core must return exactly the same bits.
        errors = bad
        if results:
            expected, _count = Counter(results).most_common(1)[0]
            errors += sum(1 for r in results if r != expected)

        elapsed = max(time.time() - start_time, 0.001)
        busy = max(times) if times else elapsed
        total_ops = iterations * 10 * len(results)
        mops = round((total_ops / 1_000_000.0) / max(busy, 0.001), 1)

        if errors > 0:
            return {
                'success': False,
                'cores': cores,
                'errors': errors,
                'mops': mops,
                'elapsed_sec': round(elapsed, 2),
                'message': f"Error en CPU ({errors} de {cores} hilos con resultado incorrecto o sin respuesta)"
            }

        return {
            'success': True,
            'cores': cores,
            'errors': 0,
            'mops': mops,
            'elapsed_sec': round(elapsed, 2),
            'message': f"{cores} hilos OK, resultados idénticos ({round(elapsed, 2)}s)"
        }
    except Exception as exc:
        return {
            'success': False,
            'cores': cores,
            'errors': 1,
            'mops': 0.0,
            'elapsed_sec': 0,
            'message': f"Fallo en test CPU: {str(exc)}"
        }


if __name__ == '__main__':
    import json
    print(json.dumps(run_cpu_benchmark(), indent=2))
