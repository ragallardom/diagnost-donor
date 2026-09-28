#!/usr/bin/env python3
"""
CPU Thermal Health Module
Detects thermal throttling and decides whether a laptop needs cleaning / new
thermal paste, the Linux equivalent of reading HWiNFO64's "Core/Package
Thermal Throttling" and "PROCHOT" sensors.

Data sources (all read-only):
  - CPU temperature: coretemp (Intel), k10temp / zenpower (AMD), x86_pkg_temp.
  - TjMax: coretemp tempN_crit, or MSR IA32_TEMPERATURE_TARGET (0x1A2).
  - Thermal throttling (Intel): /sys/devices/system/cpu/cpuN/thermal_throttle/
    core_throttle_count / *_total_time_ms and package_throttle_* . Counters are
    cumulative since boot and increase every time the CPU enters thermal
    throttling (temperature reached its thermal control limit).
  - Current throttling / PROCHOT (Intel, optional): MSRs IA32_THERM_STATUS
    (0x19C) and IA32_PACKAGE_THERM_STATUS (0x1B1) through /dev/cpu/N/msr
    (msr module). Reading MSRs is allowed under Secure Boot lockdown.

Power-limit throttling (PL1/PL2) is deliberately NOT treated as a problem:
laptops lower their clocks to stay inside their power budget by design, and it
is not fixed by cleaning. Only *thermal* throttling and sustained heat are.

Recommendation criteria (stress test, CPU phase):
  - Sustained heat: CPU >= 95 °C during at least half of the sustained phase
    (after the first 30 s of Turbo / PL2, where short peaks are normal).
  - Thermal throttling: the CPU spent >= 3 s (or >= 10 % of the sustained phase)
    thermally throttled.
  - Thermal safety abort of the stress test (>= 100 °C sustained or >= 104 °C).
"""

import glob
import os
import struct
import time

# Allows tests to point sysfs/procfs/dev reads at a fake tree.
ROOT = ''

HOT_SUSTAINED_C = 95.0          # Field criterion: sustained >= 95 °C -> clean / repaste
WARM_SUSTAINED_C = 90.0         # Borderline zone worth watching
SUSTAINED_RATIO = 0.5           # Share of sustained-phase samples that must be hot
TURBO_WINDOW_SEC = 30           # Initial Turbo/PL2 burst excluded from the evaluation
MIN_SUSTAINED_SEC = 30          # Less than this after the Turbo window -> preliminary
THROTTLE_MIN_MS = 3000          # Thermal throttling time considered significant
THROTTLE_MIN_SHARE = 0.10       # ... or share of the sustained phase
IDLE_HOT_C = 70.0               # CPU this hot while idle suggests dust / dry paste
IDLE_MAX_UTIL = 0.25            # CPU utilisation below this counts as idle
GENERAL_SUSTAINED_SEC = 60      # Seconds >= 95 °C in the general view before warning

MSR_IA32_THERM_STATUS = 0x19C
MSR_IA32_TEMPERATURE_TARGET = 0x1A2
MSR_IA32_PACKAGE_THERM_STATUS = 0x1B1

LEVEL_OK = 'ok'
LEVEL_WATCH = 'watch'
LEVEL_CLEAN = 'clean'
LEVEL_UNKNOWN = 'unknown'


def _p(path):
    return ROOT + path


def _read(path, default=None):
    try:
        with open(_p(path), 'r') as f:
            return f.read().strip()
    except Exception:
        return default


def _read_int(path, default=None):
    val = _read(path)
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def cpu_vendor():
    """'intel', 'amd' or 'unknown'."""
    try:
        with open(_p('/proc/cpuinfo'), 'r') as f:
            for line in f:
                if line.startswith('vendor_id'):
                    v = line.split(':', 1)[1].strip()
                    if v == 'GenuineIntel':
                        return 'intel'
                    if v in ('AuthenticAMD', 'HygonGenuine'):
                        return 'amd'
                    return 'unknown'
    except Exception:
        pass
    return 'unknown'


# ── Temperatures ─────────────────────────────────────────────────────────────

def _hwmon_cpu_sensors():
    """Yield (driver, label, temp_c, crit_c) for CPU die sensors."""
    for hw in sorted(glob.glob(_p('/sys/class/hwmon/hwmon*'))):
        driver = (_read(hw[len(ROOT):] + '/name', '') or '').lower()
        if driver not in ('coretemp', 'k10temp', 'zenpower'):
            continue
        for tin in sorted(glob.glob(hw + '/temp*_input')):
            rel = tin[len(ROOT):]
            milli = _read_int(rel)
            if milli is None:
                continue
            temp_c = milli / 1000.0
            if not (5.0 <= temp_c <= 125.0):
                continue
            label = _read(rel.replace('_input', '_label'), '') or ''
            crit = _read_int(rel.replace('_input', '_crit'))
            yield driver, label, temp_c, (crit / 1000.0 if crit else None)


def read_cpu_temp():
    """Hottest CPU die temperature in °C and its source, or (None, None).

    Uses the maximum over coretemp package/core sensors (throttling happens per
    core at TjMax). On AMD prefers Tdie over Tctl, since Tctl can carry an offset.
    Never returns a made-up value: no sensor -> None.
    """
    temps = []
    amd_tdie = []
    amd_tctl = []
    for driver, label, temp_c, _ in _hwmon_cpu_sensors():
        if driver in ('k10temp', 'zenpower'):
            lbl = label.lower()
            if 'tdie' in lbl:
                amd_tdie.append(temp_c)
            elif 'tctl' in lbl:
                amd_tctl.append(temp_c)
            elif not label or lbl.startswith('tccd'):
                amd_tctl.append(temp_c)
        else:
            temps.append(temp_c)
    if amd_tdie:
        temps.extend(amd_tdie)
    elif amd_tctl:
        temps.extend(amd_tctl)
    if temps:
        return round(max(temps), 1), 'hwmon'

    for tz in sorted(glob.glob(_p('/sys/class/thermal/thermal_zone*'))):
        rel = tz[len(ROOT):]
        if (_read(rel + '/type', '') or '').lower() == 'x86_pkg_temp':
            milli = _read_int(rel + '/temp')
            if milli and 5000 <= milli <= 125000:
                return round(milli / 1000.0, 1), 'x86_pkg_temp'
    return None, None


def read_tjmax():
    """CPU thermal limit (TjMax) in °C, or None when the platform does not expose it."""
    crits = [crit for driver, _, _, crit in _hwmon_cpu_sensors() if driver == 'coretemp' and crit]
    if crits:
        return round(max(crits))
    val = read_msr(0, MSR_IA32_TEMPERATURE_TARGET)
    if val is not None:
        tj = (val >> 16) & 0xFF
        if 60 <= tj <= 130:
            return tj
    return None


# ── Throttling counters (Intel therm_throt) ──────────────────────────────────

def read_throttle_counters():
    """Cumulative thermal throttling since boot, summed over cores / packages.

    Returns {'supported': False} when the kernel does not expose the counters
    (AMD CPUs, virtual machines).
    """
    cpu_dirs = sorted(glob.glob(_p('/sys/devices/system/cpu/cpu[0-9]*/thermal_throttle')))
    if not cpu_dirs:
        return {'supported': False}

    core_events = core_ms = 0
    packages = {}
    for d in cpu_dirs:
        rel = d[len(ROOT):]
        core_events += _read_int(rel + '/core_throttle_count', 0) or 0
        core_ms += _read_int(rel + '/core_throttle_total_time_ms', 0) or 0
        pkg_count = _read_int(rel + '/package_throttle_count')
        if pkg_count is not None:
            pkg_id = _read(os.path.dirname(rel) + '/topology/physical_package_id', '0')
            # Package counters are repeated on every CPU of the package: count once.
            packages[pkg_id] = (pkg_count, _read_int(rel + '/package_throttle_total_time_ms', 0) or 0)

    return {
        'supported': True,
        'core_events': core_events,
        'core_time_ms': core_ms,
        'package_events': sum(c for c, _ in packages.values()),
        'package_time_ms': sum(t for _, t in packages.values()),
    }


def throttle_delta(before, after):
    """Throttling that happened between two read_throttle_counters() snapshots."""
    if not (before and after and before.get('supported') and after.get('supported')):
        return {'supported': False}
    events = (after['core_events'] - before['core_events']) + (after['package_events'] - before['package_events'])
    # Core and package throttle overlap in time; the larger one is the best estimate.
    time_ms = max(after['core_time_ms'] - before['core_time_ms'],
                  after['package_time_ms'] - before['package_time_ms'])
    return {'supported': True, 'events': max(0, events), 'time_ms': max(0, time_ms)}


# ── MSR thermal status (Intel, optional) ─────────────────────────────────────

def read_msr(cpu, reg):
    try:
        fd = os.open(_p(f'/dev/cpu/{cpu}/msr'), os.O_RDONLY)
    except OSError:
        return None
    try:
        data = os.pread(fd, 8, reg)
        return struct.unpack('<Q', data)[0] if len(data) == 8 else None
    except OSError:
        return None
    finally:
        os.close(fd)


def read_msr_thermal_status():
    """Current throttling and PROCHOT from the thermal status MSRs, or None.

    Bit 0: thermal status (throttling right now); bit 1: its sticky log;
    bit 2: PROCHOT# asserted (external, e.g. by the EC/VRM); bit 3: its log.
    """
    if cpu_vendor() != 'intel':
        return None
    pkg = read_msr(0, MSR_IA32_PACKAGE_THERM_STATUS)
    cores = []
    for d in sorted(glob.glob(_p('/dev/cpu/[0-9]*'))):
        try:
            cpu = int(os.path.basename(d))
        except ValueError:
            continue
        val = read_msr(cpu, MSR_IA32_THERM_STATUS)
        if val is not None:
            cores.append(val)
    if pkg is None and not cores:
        return None
    regs = cores + ([pkg] if pkg is not None else [])
    return {
        'throttling_now': any(v & 0x1 for v in regs),
        'throttled_since_boot': any(v & 0x2 for v in regs),
        'prochot_now': any(v & 0x4 for v in regs),
        'prochot_since_boot': any(v & 0x8 for v in regs),
    }


# ── CPU frequency / utilisation ──────────────────────────────────────────────

def read_cpu_freq():
    """(average current MHz, base MHz or None) across CPUs."""
    cur = []
    for f in glob.glob(_p('/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq')):
        khz = _read_int(f[len(ROOT):])
        if khz:
            cur.append(khz)
    base = _read_int('/sys/devices/system/cpu/cpu0/cpufreq/base_frequency')
    avg = round(sum(cur) / len(cur) / 1000) if cur else None
    return avg, (round(base / 1000) if base else None)


def read_cpu_times():
    """(busy, total) jiffies from /proc/stat."""
    line = (_read('/proc/stat', '') or '').split('\n', 1)[0]
    parts = line.split()
    if not parts or parts[0] != 'cpu':
        return None
    vals = [int(x) for x in parts[1:9]]
    idle = vals[3] + vals[4]
    total = sum(vals)
    return total - idle, total


# ── Evaluation ───────────────────────────────────────────────────────────────

RECOMMENDATION_CLEAN = ('Se recomienda limpieza interna (ventilador, disipador y rejillas) '
                        'y cambio de pasta térmica.')


def evaluate_stress_samples(samples, throttle, tjmax=None, base_mhz=None,
                            thermal_abort=False, fans=None):
    """Evaluate the CPU phase of a stress test.

    samples: list of dicts {'t': seconds since phase start, 'temp': °C or None,
             'mhz': avg MHz or None}.
    throttle: throttle_delta() over the phase.
    fans: list of fan RPM readings taken during the phase (None if not exposed).
    """
    valid = [s for s in samples if s.get('temp') is not None]
    result = {
        'level': LEVEL_UNKNOWN,
        'title': 'Sin datos de temperatura',
        'recommendation': '',
        'reasons': [],
        'preliminary': False,
        'hot_threshold_c': HOT_SUSTAINED_C,
        'tjmax_c': tjmax,
        'peak_c': None,
        'sustained_avg_c': None,
        'sustained_hot_pct': None,
        'sustained_sec': 0,
        'throttle': throttle if throttle and throttle.get('supported') else {'supported': False},
        'avg_mhz': None,
        'base_mhz': base_mhz,
    }
    if not valid:
        result['reasons'].append('El equipo no expone un sensor de temperatura de CPU; no se puede evaluar.')
        return result

    result['peak_c'] = round(max(s['temp'] for s in valid), 1)
    sustained = [s for s in valid if s['t'] >= TURBO_WINDOW_SEC]
    if len(sustained) < MIN_SUSTAINED_SEC:
        # Short test: evaluate what we have but flag it as preliminary.
        result['preliminary'] = True
        sustained = sustained if len(sustained) >= 10 else valid

    temps = [s['temp'] for s in sustained]
    result['sustained_sec'] = int(round(sustained[-1]['t'] - sustained[0]['t'])) + 1
    result['sustained_avg_c'] = round(sum(temps) / len(temps), 1)
    hot_ratio = sum(1 for t in temps if t >= HOT_SUSTAINED_C) / len(temps)
    warm_ratio = sum(1 for t in temps if t >= WARM_SUSTAINED_C) / len(temps)
    result['sustained_hot_pct'] = int(round(hot_ratio * 100))
    mhz = [s['mhz'] for s in sustained if s.get('mhz')]
    if mhz:
        result['avg_mhz'] = int(round(sum(mhz) / len(mhz)))

    reasons = []
    clean = watch = False

    if thermal_abort:
        clean = True
        reasons.append('La prueba se detuvo por protección térmica (CPU ≥100 °C sostenido o ≥104 °C).')

    if hot_ratio >= SUSTAINED_RATIO:
        clean = True
        reasons.append(f'La CPU se mantuvo en ≥{int(HOT_SUSTAINED_C)} °C durante el {result["sustained_hot_pct"]}% '
                       f'de la carga sostenida (promedio {result["sustained_avg_c"]} °C).')
    elif warm_ratio >= SUSTAINED_RATIO:
        watch = True
        reasons.append(f'Carga sostenida en {result["sustained_avg_c"]} °C promedio: cerca del umbral de {int(HOT_SUSTAINED_C)} °C.')
    elif hot_ratio > 0:
        watch = True
        reasons.append(f'Picos breves de ≥{int(HOT_SUSTAINED_C)} °C ({result["sustained_hot_pct"]}% del tiempo sostenido).')

    thr = result['throttle']
    if thr.get('supported'):
        sustained_ms = result['sustained_sec'] * 1000
        if thr['events'] > 0:
            significant = thr['time_ms'] >= THROTTLE_MIN_MS or thr['time_ms'] >= THROTTLE_MIN_SHARE * sustained_ms
            secs = round(thr['time_ms'] / 1000.0, 1)
            if significant:
                clean = True
                reasons.append(f'Throttling térmico: la CPU bajó su rendimiento para protegerse '
                               f'({thr["events"]} eventos, {secs} s en total).')
            else:
                watch = True
                reasons.append(f'Throttling térmico breve ({thr["events"]} eventos, {secs} s).')

    if base_mhz and result['avg_mhz'] and result['avg_mhz'] < base_mhz and result['sustained_avg_c'] >= WARM_SUSTAINED_C:
        watch = True
        reasons.append(f'Frecuencia sostenida ({result["avg_mhz"]} MHz) bajo la frecuencia base ({base_mhz} MHz) con la CPU caliente.')

    if fans is not None and fans and max(fans) == 0 and result['peak_c'] >= 80:
        clean = True
        reasons.append('Los ventiladores reportan 0 RPM con la CPU sobre 80 °C: revisar ventilador (bloqueado, sucio o dañado).')

    if clean:
        result['level'] = LEVEL_CLEAN
        result['title'] = 'Enfriamiento insuficiente'
        result['recommendation'] = RECOMMENDATION_CLEAN
    elif watch:
        result['level'] = LEVEL_WATCH
        result['title'] = 'Temperatura elevada, vigilar'
        result['recommendation'] = ('Revisar que las rejillas no estén obstruidas y que el ventilador suba de RPM. '
                                    'Si se repite en una prueba Media o Profunda, hacer limpieza y cambio de pasta.')
    else:
        result['level'] = LEVEL_OK
        result['title'] = 'Enfriamiento correcto'
        result['recommendation'] = 'No se requiere limpieza ni cambio de pasta térmica.'
        reasons.append(f'Temperatura sostenida promedio {result["sustained_avg_c"]} °C'
                       + (', sin throttling térmico.' if thr.get('supported') else '.'))

    if not thr.get('supported'):
        reasons.append('Contadores de throttling no disponibles en esta CPU (p. ej. AMD): evaluación solo por temperatura.')
    if result['preliminary']:
        reasons.append('Prueba corta: resultado preliminar. Para confirmar usa el nivel Media o Profunda '
                       '(la carga sostenida empieza tras los primeros 30 s de Turbo).')
    result['reasons'] = reasons
    return result


class ThermalMonitor:
    """Rolling thermal health for the general view (fed by the 1 s telemetry poll)."""

    def __init__(self):
        self.hot_since = None
        self.idle_hot_since = None
        self.longest_hot_sec = 0
        self.prev_counters = None
        self.prev_cpu_times = None
        self.last_throttle_at = None

    def sample(self, now=None):
        now = time.monotonic() if now is None else now
        temp, _ = read_cpu_temp()
        counters = read_throttle_counters()
        msr = read_msr_thermal_status()

        util = None
        times = read_cpu_times()
        if times and self.prev_cpu_times:
            busy = times[0] - self.prev_cpu_times[0]
            total = times[1] - self.prev_cpu_times[1]
            if total > 0:
                util = busy / total
        self.prev_cpu_times = times

        throttling_now = bool(msr and msr['throttling_now'])
        if counters.get('supported') and self.prev_counters and self.prev_counters.get('supported'):
            if throttle_delta(self.prev_counters, counters)['events'] > 0:
                throttling_now = True
        self.prev_counters = counters
        if throttling_now:
            self.last_throttle_at = now

        if temp is not None and temp >= HOT_SUSTAINED_C:
            if self.hot_since is None:
                self.hot_since = now
        else:
            self.hot_since = None
        hot_sec = int(now - self.hot_since) if self.hot_since is not None else 0
        self.longest_hot_sec = max(self.longest_hot_sec, hot_sec)

        if temp is not None and temp >= IDLE_HOT_C and util is not None and util < IDLE_MAX_UTIL:
            if self.idle_hot_since is None:
                self.idle_hot_since = now
        else:
            self.idle_hot_since = None
        idle_hot_sec = int(now - self.idle_hot_since) if self.idle_hot_since is not None else 0

        since_boot_events = (counters.get('core_events', 0) + counters.get('package_events', 0)) if counters.get('supported') else None
        recently_throttled = self.last_throttle_at is not None and (now - self.last_throttle_at) < 5

        level, message = LEVEL_OK, 'Sin throttling térmico ni temperaturas sostenidas altas.'
        if hot_sec >= GENERAL_SUSTAINED_SEC:
            level = LEVEL_CLEAN
            message = (f'CPU sobre {int(HOT_SUSTAINED_C)} °C durante {hot_sec} s. ' + RECOMMENDATION_CLEAN)
        elif idle_hot_sec >= GENERAL_SUSTAINED_SEC:
            level = LEVEL_CLEAN
            message = (f'CPU a {temp:.0f} °C en reposo (uso bajo) durante {idle_hot_sec} s: '
                       'posible polvo acumulado o pasta térmica seca. ' + RECOMMENDATION_CLEAN)
        elif recently_throttled:
            level = LEVEL_WATCH
            message = 'Throttling térmico activo en este momento. Confirmar con la prueba de estrés (nivel Media).'
        elif since_boot_events:
            level = LEVEL_WATCH
            message = (f'Se registraron {since_boot_events} eventos de throttling térmico desde el arranque. '
                       'Confirmar con la prueba de estrés (nivel Media).')
        elif temp is None:
            level = LEVEL_UNKNOWN
            message = 'El equipo no expone un sensor de temperatura de CPU.'

        # Only the live PROCHOT# bit: the sticky log bit may be set by firmware at boot.
        prochot = bool(msr and msr['prochot_now'])
        return {
            'level': level,
            'message': message,
            'cpu_temp_c': temp,
            'tjmax_c': read_tjmax(),
            'hot_threshold_c': HOT_SUSTAINED_C,
            'hot_sustained_sec': hot_sec,
            'throttling_supported': bool(counters.get('supported') or msr),
            'throttling_now': recently_throttled,
            'throttle_events_since_boot': since_boot_events,
            'prochot_detected': prochot,
            'prochot_note': ('PROCHOT externo detectado: el EC/placa pidió bajar el rendimiento (cargador, batería '
                             'o VRM). No se soluciona con limpieza; revisar alimentación.') if prochot and not since_boot_events else '',
        }
