#!/usr/bin/env python3
"""
RAM Integrity & Speed Benchmark Module
Fills a RAM buffer with bit patterns (0xAA, 0x55, 0x00, 0xFF and pseudo-random data),
reads every byte back, and measures RAM write+read throughput in GB/s.
"""

import json
import time

import stress_workers

CHUNK_BYTES = 32 * 1024 * 1024
# Solid patterns plus one random pattern (catches address-line aliasing).
PATTERNS = [('solid', 0xAA), ('solid', 0x55), ('solid', 0x00), ('solid', 0xFF), ('random', 0)]


def run_ram_benchmark(chunk_mb=256, patterns=PATTERNS, corrupt=None):
    """
    Runs a fast (~2-4 s) memory integrity test.
    Allocates chunk_mb megabytes, writes each pattern over the whole buffer and verifies it.
    `corrupt` is a test hook applied between write and verify.
    """
    pool = []
    try:
        remaining = chunk_mb * 1024 * 1024
        while remaining > 0:
            pool.append(bytearray(min(CHUNK_BYTES, remaining)))
            remaining -= CHUNK_BYTES

        errors = 0
        start_time = time.time()
        for kind, arg in patterns:
            bad_bytes, _where, complete = stress_workers.ram_pattern_pass(pool, kind, arg, corrupt=corrupt)
            errors += bad_bytes
        elapsed = max(time.time() - start_time, 0.001)

        # Each pattern is one full write and one full read of the buffer.
        total_data_gb = (chunk_mb * 1024 * 1024 * 2 * len(patterns)) / (1000 * 1000 * 1000)
        speed_gbs = round(total_data_gb / elapsed, 2)

        return {
            'success': errors == 0,
            'errors': errors,
            'tested_mb': chunk_mb,
            'speed_gbs': speed_gbs,
            'elapsed_sec': round(elapsed, 3),
            'message': (f"{chunk_mb} MB OK · {speed_gbs} GB/s"
                        if errors == 0 else f"{errors} bytes con error")
        }
    except Exception as e:
        return {
            'success': False,
            'errors': 1,
            'tested_mb': 0,
            'speed_gbs': 0.0,
            'elapsed_sec': 0,
            'message': f"Error en prueba de RAM: {str(e)}"
        }
    finally:
        pool.clear()


if __name__ == '__main__':
    print(json.dumps(run_ram_benchmark(256), indent=2))
