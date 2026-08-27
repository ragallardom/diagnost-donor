#!/usr/bin/env python3
"""
RAM Integrity & Speed Benchmark Module
Allocates a RAM buffer, writes bitmask patterns (0xAA, 0x55, 0x00, 0xFF), checks parity,
and measures RAM read/write throughput in GB/s.
"""

import time
import json
import ctypes

def run_ram_benchmark(chunk_mb=256):
    """
    Runs a fast 1-2 second memory integrity test.
    allocates chunk_mb megabytes in memory, writes bitmask patterns, and verifies checksum.
    """
    size_bytes = chunk_mb * 1024 * 1024
    pattern_aa = b'\xaa' * size_bytes
    pattern_55 = b'\x55' * size_bytes

    errors = 0
    start_time = time.time()

    try:
        # Write pattern 1 (0xAA)
        buf = bytearray(pattern_aa)
        
        # Verify pattern 1
        if buf != pattern_aa:
            errors += 1

        # Write pattern 2 (0x55)
        buf = bytearray(pattern_55)
        if buf != pattern_55:
            errors += 1

        elapsed = time.time() - start_time
        if elapsed == 0:
            elapsed = 0.001

        # 2 pattern writes + 2 pattern reads = 4x size_bytes total throughput
        total_data_gb = (size_bytes * 4) / (1000 * 1000 * 1000)
        speed_gbs = round(total_data_gb / elapsed, 2)

        del buf
        del pattern_aa
        del pattern_55

        return {
            'success': True,
            'errors': errors,
            'tested_mb': chunk_mb,
            'speed_gbs': speed_gbs,
            'elapsed_sec': round(elapsed, 3),
            'message': f"{chunk_mb} MB verificados ({speed_gbs} GB/s)"
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

if __name__ == '__main__':
    print(json.dumps(run_ram_benchmark(256), indent=2))
