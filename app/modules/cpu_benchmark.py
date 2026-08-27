#!/usr/bin/env python3
"""
CPU Fast Stability & Performance Benchmark Module
Spawns parallel threads across all available CPU cores to execute floating-point and integer
arithmetic tests, verifying ALU/FPU stability and calculating execution speed.
"""

import os
import time
import math
import concurrent.futures

def _worker_benchmark(iterations):
    val = 1.0
    for i in range(1, iterations):
        val = math.sin(val) * math.cos(i * 0.001) + math.sqrt(i + val * val)
    return val

def run_cpu_benchmark():
    cores = os.cpu_count() or 4
    iterations_per_chunk = 40_000
    
    start_time = time.time()
    errors = 0
    total_ops = 0

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=cores) as executor:
            futures = [executor.submit(_worker_benchmark, iterations_per_chunk) for _ in range(cores)]
            for fut in concurrent.futures.as_completed(futures):
                res = fut.result()
                if math.isnan(res) or math.isinf(res):
                    errors += 1
                total_ops += iterations_per_chunk * 10

        elapsed = time.time() - start_time
        if elapsed == 0:
            elapsed = 0.001

        mops = round((total_ops / 1_000_000.0) / elapsed, 1)

        if errors > 0:
            return {
                'success': False,
                'cores': cores,
                'errors': errors,
                'mops': mops,
                'elapsed_sec': round(elapsed, 2),
                'message': f"Error en CPU ({errors} fallos en hilos)"
            }

        return {
            'success': True,
            'cores': cores,
            'errors': 0,
            'mops': mops,
            'elapsed_sec': round(elapsed, 2),
            'message': f"{cores} hilos OK ({round(elapsed, 2)}s)"
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
