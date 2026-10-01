#!/usr/bin/env python3
"""
Load generators used by the hardware stress suite (stress_diag).

  - CpuLoad:        one worker per logical CPU that *verifies* its own results
                    (stress-ng --verify, or real subprocesses in pure Python).
  - RAM patterns:   full-coverage pattern sweeps over the whole buffer.
  - DiskReadStress: non-destructive O_DIRECT reads (sequential + random +
                    re-read consistency) against the real internal drives.

Kept free of any HTTP / UI concerns so it can be unit-tested with tiny inputs.
"""

import hashlib
import mmap
import os
import random
import subprocess
import sys
import tempfile
import threading
import time

# ─────────────────────────────────────────────────────────────────────────
# CPU
# ─────────────────────────────────────────────────────────────────────────

# Exit code a verifying worker uses when a computation differs from its own
# reference value (stress-ng uses 2 for the same condition).
CPU_MISMATCH_EXIT = 3
STRESS_NG_FAIL_EXIT = 2

# Each worker computes an FP chain, an integer chain and a SHA-256 digest once
# (the reference) and then repeats them until the deadline, exiting non-zero on
# the first difference. A CPU/FPU/cache fault under heat shows up as a mismatch.
CPU_WORKER_SRC = r'''
import hashlib, math, sys, time
deadline = time.monotonic() + float(sys.argv[1])
rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 60000

def fp(n):
    x = 1.0000001
    for i in range(1, n):
        x = math.sin(x) * math.cos(i * 0.001) + math.sqrt(i + x * x)
        x += math.exp(math.log(abs(x) + 1.1)) * 1e-9
    return x.hex()

def integer(n):
    a = 0x9E3779B97F4A7C15
    for i in range(n):
        a = ((a ^ (a >> 29)) * 0xBF58476D1CE4E5B9 + i) & 0xFFFFFFFFFFFFFFFF
    return a

BLOCK = bytes(range(256)) * 1024

def digest():
    h = hashlib.sha256()
    for _ in range(16):
        h.update(BLOCK)
    return h.hexdigest()

ref = (fp(rounds), integer(rounds), digest())
while time.monotonic() < deadline:
    if (fp(rounds), integer(rounds), digest()) != ref:
        sys.exit(%d)
''' % CPU_MISMATCH_EXIT


class CpuLoad:
    """Saturate every logical CPU and detect calculation errors.

    Uses stress-ng (cpu + matrix + vecmath stressors, --verify) when available,
    otherwise one Python subprocess per CPU. Subprocesses, not threads: with the
    GIL a thread pool only ever loads a single core.
    """

    def __init__(self, workers, duration_sec, stress_ng_bin=None):
        self.workers = max(1, int(workers))
        self.duration_sec = duration_sec
        self.stress_ng_bin = stress_ng_bin
        self.engine = 'stress-ng' if stress_ng_bin else 'python'
        self.procs = []
        self._stderr = None
        self.started = 0.0
        self.failure = None

    def start(self):
        self.started = time.monotonic()
        if self.stress_ng_bin:
            self._stderr = tempfile.TemporaryFile()
            n = str(self.workers)
            # The timeout is longer than the phase: the runner ends it, so an
            # early exit is always a failure and never a normal completion.
            self.procs = [subprocess.Popen(
                [self.stress_ng_bin, '--cpu', n, '--cpu-method', 'all',
                 '--matrix', n, '--vecmath', n, '--verify',
                 '--timeout', f'{int(self.duration_sec) + 15}s'],
                stdout=subprocess.DEVNULL, stderr=self._stderr)]
        else:
            self.procs = [subprocess.Popen(
                [sys.executable, '-c', CPU_WORKER_SRC, str(self.duration_sec + 15)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                for _ in range(self.workers)]

    def check(self):
        """Return a failure description if any worker died or reported an error."""
        if self.failure:
            return self.failure
        for p in self.procs:
            rc = p.poll()
            if rc is None:
                continue
            if rc == CPU_MISMATCH_EXIT and self.engine == 'python':
                self.failure = 'un hilo calculó un resultado distinto al de referencia (error de cálculo)'
            elif rc == STRESS_NG_FAIL_EXIT and self.engine == 'stress-ng':
                self.failure = 'stress-ng --verify detectó un resultado de cálculo incorrecto'
            else:
                self.failure = f'la carga de CPU terminó antes de tiempo (código {rc})'
            return self.failure
        return None

    def stop(self):
        """Terminate the load and return the final failure description (or None)."""
        for p in self.procs:
            if p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass
        for p in self.procs:
            try:
                p.wait(timeout=2.0)
            except Exception:
                try:
                    p.kill()
                    p.wait(timeout=2.0)
                except Exception:
                    pass
        if not self.failure:
            # A verification failure is reported when stress-ng winds down.
            for p in self.procs:
                if self.engine == 'stress-ng' and p.returncode == STRESS_NG_FAIL_EXIT:
                    self.failure = 'stress-ng --verify detectó un resultado de cálculo incorrecto'
                elif self.engine == 'python' and p.returncode == CPU_MISMATCH_EXIT:
                    self.failure = 'un hilo calculó un resultado distinto al de referencia (error de cálculo)'
        if self.failure and self._stderr is not None:
            try:
                self._stderr.seek(0)
                tail = self._stderr.read().decode('utf-8', 'replace').strip().splitlines()[-2:]
                if tail:
                    self.failure += ' — ' + ' | '.join(tail)
            except Exception:
                pass
        if self._stderr is not None:
            try:
                self._stderr.close()
            except Exception:
                pass
        return self.failure


# ─────────────────────────────────────────────────────────────────────────
# RAM
# ─────────────────────────────────────────────────────────────────────────

RAM_BLOCK = 1024 * 1024  # granularity of fills / compares (and of abort checks)
_RANDOM_TABLE_BLOCKS = 16


def ram_pattern_names():
    """Ordered pattern list. The most discriminating ones come first so a short
    (quick) run still covers solid, alternating and random data over all of RAM."""
    solid = [0x00, 0xFF, 0x55, 0xAA]
    order = [('solid', b) for b in solid]
    order.append(('random', 0))
    order += [('solid', b) for b in (0x0F, 0xF0, 0x33, 0xCC)]
    order.append(('random', 1))
    for bit in range(8):                       # walking ones, then walking zeros
        order.append(('solid', 1 << bit))
    for bit in range(8):
        order.append(('solid', (~(1 << bit)) & 0xFF))
    return order


def _random_table(seed):
    rng = random.Random(0xD1A6 + seed)
    return [rng.randbytes(RAM_BLOCK) for _ in range(_RANDOM_TABLE_BLOCKS)]


def _pattern_block(kind, arg, index, table):
    if kind == 'solid':
        return None
    # Neighbouring blocks get different random data, so two blocks that alias to
    # the same physical cells (address-line faults) cannot both verify.
    return table[(index * 7 + arg) % _RANDOM_TABLE_BLOCKS]


def describe_pattern(kind, arg):
    return f'aleatorio#{arg}' if kind == 'random' else f'0x{arg:02X}'


def ram_pattern_pass(pool, kind, arg, should_stop=lambda: False, corrupt=None):
    """Write one pattern over every byte of `pool` (list of bytearray), read it
    back and return (errors, bad_blocks, complete).

    errors is the number of differing bytes; bad_blocks the first few
    (chunk, offset) locations. `corrupt` is a test hook called after the write.
    """
    table = _random_table(arg) if kind == 'random' else None
    solid = bytes([arg]) * RAM_BLOCK if kind == 'solid' else None
    views = [memoryview(c) for c in pool]
    errors = 0
    bad = []
    try:
        for phase in ('write', 'verify'):
            if phase == 'verify' and corrupt is not None:
                corrupt(pool)
            for ci, mv in enumerate(views):
                for bi, off in enumerate(range(0, len(mv), RAM_BLOCK)):
                    if should_stop():
                        return errors, bad, False
                    end = min(off + RAM_BLOCK, len(mv))
                    block = solid if solid is not None else _pattern_block(kind, arg, ci * 4096 + bi, table)
                    want = block if end - off == RAM_BLOCK else block[:end - off]
                    if phase == 'write':
                        mv[off:end] = want
                        continue
                    got = bytes(mv[off:end])
                    if got != want:
                        errors += sum(1 for a, b in zip(got, want) if a != b)
                        if len(bad) < 5:
                            bad.append((ci, off))
    finally:
        for mv in views:
            mv.release()
    return errors, bad, True


# ─────────────────────────────────────────────────────────────────────────
# Disk (read-only, real device)
# ─────────────────────────────────────────────────────────────────────────

SEQ_IO = 1024 * 1024
MIN_DISK_BYTES = 1_000_000_000
RAND_IO = 4096
_ALIGN = 4096


def _aligned_buffer(size):
    return mmap.mmap(-1, size)  # anonymous mmap is page aligned: valid for O_DIRECT


def internal_disks():
    """Internal (non-USB, non-removable) whole disks, excluding the live medium."""
    try:
        from opal_diag import get_boot_medium_disks
        boot = get_boot_medium_disks()
    except Exception:
        boot = set()
    disks = []
    try:
        names = sorted(os.listdir('/sys/block'))
    except OSError:
        return disks
    for name in names:
        if not name.startswith(('sd', 'nvme', 'mmcblk', 'vd')) or name in boot:
            continue
        base = os.path.join('/sys/block', name)
        try:
            if 'usb' in os.path.realpath(base):
                continue
            with open(os.path.join(base, 'removable')) as f:
                if f.read().strip() == '1':
                    continue
            with open(os.path.join(base, 'size')) as f:
                size = int(f.read().strip()) * 512
        except Exception:
            continue
        if size >= MIN_DISK_BYTES:   # skips config/cloud-init stubs and empty card readers
            disks.append({'device': f'/dev/{name}', 'size_bytes': size})
    return disks


def is_ram_backed(path):
    """True when `path` lives on a filesystem that is (or may be) RAM: a write test
    there would exercise memory, not a drive."""
    best, fstype = '', ''
    try:
        real = os.path.realpath(path)
        with open('/proc/mounts') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    mnt = parts[1].replace('\\040', ' ')
                    if (real == mnt or real.startswith(mnt.rstrip('/') + '/')) and len(mnt) >= len(best):
                        best, fstype = mnt, parts[2]
    except Exception:
        return True
    return fstype in ('tmpfs', 'ramfs', 'overlay', 'aufs', 'squashfs', 'rootfs', '')


class DiskReadStress:
    """Sustained, non-destructive read load on one block device (or file).

    - sequential 1 MiB sweep (bandwidth, thermal throttling of the SSD itself),
    - random 4 KiB reads from several threads (queue depth, latency),
    - a set of fixed sample regions hashed on every visit: a read that returns
      different bytes than the first time is data corruption.
    Never writes to the device.
    """

    def __init__(self, path, size_bytes=None, duration_sec=30, rand_threads=8,
                 stop_check=lambda: False, samples=32):
        self.path = path
        self.duration_sec = duration_sec
        self.rand_threads = rand_threads
        self.stop_check = stop_check
        self.size_bytes = size_bytes
        self.samples = samples
        self.direct = True
        self.io_errors = 0
        self.mismatches = 0
        self.seq_bytes = 0
        self.rand_ops = 0
        self.max_latency_ms = 0.0
        self.seq_speeds = []          # (elapsed_sec, MB/s) per sweep window
        self.first_error = None
        self._lock = threading.Lock()

    def _open(self):
        flags = os.O_RDONLY
        try:
            fd = os.open(self.path, flags | getattr(os, 'O_DIRECT', 0))
            self.direct = hasattr(os, 'O_DIRECT')
        except OSError:
            fd = os.open(self.path, flags)  # e.g. tmpfs without O_DIRECT (tests)
            self.direct = False
        if not self.size_bytes:
            self.size_bytes = os.lseek(fd, 0, os.SEEK_END)
        return fd

    def _note_error(self, exc):
        with self._lock:
            self.io_errors += 1
            if self.first_error is None:
                self.first_error = str(exc)

    def _read(self, fd, buf, length, offset):
        t0 = time.monotonic()
        n = os.preadv(fd, [memoryview(buf)[:length]], offset)
        lat = (time.monotonic() - t0) * 1000.0
        if lat > self.max_latency_ms:
            self.max_latency_ms = lat
        return n

    def run(self):
        fd = self._open()
        try:
            span = (self.size_bytes // _ALIGN) * _ALIGN
            if span < SEQ_IO:
                raise OSError('dispositivo demasiado pequeño para la prueba')
            deadline = time.monotonic() + self.duration_sec
            rng = random.Random(0x55D)
            sample_offsets = sorted({(rng.randrange(0, span - SEQ_IO) // _ALIGN) * _ALIGN
                                     for _ in range(self.samples)})
            reference = {}
            threads = [threading.Thread(target=self._random_worker,
                                        args=(fd, span, deadline, i), daemon=True)
                       for i in range(self.rand_threads)]
            for t in threads:
                t.start()
            self._seq_worker(fd, span, deadline, sample_offsets, reference)
            for t in threads:
                t.join(timeout=10)
        finally:
            os.close(fd)
        return self.summary()

    def _seq_worker(self, fd, span, deadline, sample_offsets, reference):
        buf = _aligned_buffer(SEQ_IO)
        try:
            pos = 0
            win_start, win_bytes = time.monotonic(), 0
            begin = win_start
            next_sample = 0
            while time.monotonic() < deadline and not self.stop_check():
                # Every 16th step revisit one fixed sample region (hash compare).
                if sample_offsets and next_sample % 16 == 15:
                    off = sample_offsets[(next_sample // 16) % len(sample_offsets)]
                    check = True
                else:
                    off = pos
                    check = False
                next_sample += 1
                try:
                    n = self._read(fd, buf, SEQ_IO, off)
                except OSError as exc:
                    self._note_error(exc)
                    pos = (pos + SEQ_IO) % span
                    continue
                if check:
                    digest = hashlib.blake2b(buf[:n], digest_size=16).digest()
                    prev = reference.setdefault(off, digest)
                    if prev != digest:
                        with self._lock:
                            self.mismatches += 1
                else:
                    self.seq_bytes += n
                    win_bytes += n
                    pos += SEQ_IO
                    if pos + SEQ_IO > span:
                        pos = 0
                now = time.monotonic()
                if now - win_start >= 2.0:
                    self.seq_speeds.append((round(now - begin, 1), win_bytes / (now - win_start) / 1e6))
                    win_start, win_bytes = now, 0
        finally:
            buf.close()

    def _random_worker(self, fd, span, deadline, idx):
        rng = random.Random(0xA11 + idx)
        buf = _aligned_buffer(RAND_IO)
        try:
            while time.monotonic() < deadline and not self.stop_check():
                off = rng.randrange(0, span - RAND_IO) // RAND_IO * RAND_IO
                try:
                    self._read(fd, buf, RAND_IO, off)
                except OSError as exc:
                    self._note_error(exc)
                    continue
                with self._lock:
                    self.rand_ops += 1
        finally:
            buf.close()

    def summary(self):
        speeds = [s for _, s in self.seq_speeds]
        drop_pct = None
        if len(speeds) >= 4:
            q = max(1, len(speeds) // 4)
            first = sum(speeds[:q]) / q
            last = sum(speeds[-q:]) / q
            if first > 0:
                drop_pct = round(max(0.0, (first - last) / first * 100.0), 1)
        return {
            'device': self.path,
            'direct_io': self.direct,
            'seq_mb': round(self.seq_bytes / 1e6, 1),
            'seq_mb_s': round(sum(speeds) / len(speeds), 1) if speeds else 0.0,
            'rand_iops': round(self.rand_ops / max(1, self.duration_sec)),
            'io_errors': self.io_errors,
            'mismatches': self.mismatches,
            'max_latency_ms': round(self.max_latency_ms, 1),
            'throughput_drop_pct': drop_pct,
            'first_error': self.first_error,
        }
