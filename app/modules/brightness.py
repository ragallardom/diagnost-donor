#!/usr/bin/env python3
"""Screen backlight control through /sys/class/backlight (needs root, like the rest of the kiosk)."""

import glob
import os

BACKLIGHT_DIR = '/sys/class/backlight'
DEFAULT_PERCENT = 90
MIN_PERCENT = 5          # never let a slider turn the panel fully black
_TYPE_PRIORITY = {'raw': 0, 'platform': 1, 'firmware': 2}


def _read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except Exception:
        return None


def _pick_device():
    """Backlight to drive: raw (native driver) before platform before firmware."""
    best = None
    for dev in glob.glob(os.path.join(BACKLIGHT_DIR, '*')):
        max_b = _read_int(os.path.join(dev, 'max_brightness'))
        if not max_b:
            continue
        try:
            with open(os.path.join(dev, 'type')) as f:
                prio = _TYPE_PRIORITY.get(f.read().strip(), 3)
        except Exception:
            prio = 3
        if best is None or prio < best[0]:
            best = (prio, dev, max_b)
    return (best[1], best[2]) if best else (None, None)


def get_brightness():
    dev, max_b = _pick_device()
    if not dev:
        return {'supported': False, 'percent': None}
    cur = _read_int(os.path.join(dev, 'brightness'))
    if cur is None:
        return {'supported': False, 'percent': None}
    return {'supported': True, 'percent': round(cur * 100 / max_b)}


def set_brightness(percent):
    try:
        percent = int(percent)
    except (TypeError, ValueError):
        return {'success': False, 'message': 'Valor inválido'}
    percent = max(MIN_PERCENT, min(100, percent))
    dev, max_b = _pick_device()
    if not dev:
        return {'success': False, 'supported': False, 'message': 'Sin control de brillo'}
    try:
        with open(os.path.join(dev, 'brightness'), 'w') as f:
            f.write(str(max(1, round(max_b * percent / 100))))
    except OSError as exc:
        return {'success': False, 'supported': True, 'message': str(exc)}
    return {'success': True, 'supported': True, 'percent': percent}


def apply_default_once(marker_dir):
    """Set the default brightness the first time the server runs in this boot.

    The marker keeps a supervisor restart of the server from undoing the technician's choice.
    """
    marker = os.path.join(marker_dir, 'diagnost-donor.brightness')
    if os.path.exists(marker):
        return None
    res = set_brightness(DEFAULT_PERCENT)
    if res.get('success') or res.get('supported') is False:
        try:
            open(marker, 'w').close()
        except OSError:
            pass
    return res
