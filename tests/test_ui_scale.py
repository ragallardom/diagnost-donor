"""UI scale factor (js/kiosk.js computeUiZoom): shrink on small screens, never above 1.0 up to Full HD."""

import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIOSK_JS = os.path.join(ROOT, 'app', 'static', 'js', 'kiosk.js')

RUNNER = r'''
const vm = require("vm"), fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const code = src.match(/const UI_ZOOM_MIN[\s\S]*?\n}\n/)[0] + src.match(/function computeUiZoom[\s\S]*?\n}\n/)[0];
const ctx = {}; vm.createContext(ctx); vm.runInContext(code, ctx);
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
console.log(JSON.stringify(cases.map(([w, h]) => ctx.computeUiZoom(w, h))));
'''

CASES = [  # (width, height, expected)
    (1920, 1080, 1.0), (1600, 900, 1.0), (1366, 768, 0.85), (1280, 720, 0.8),
    (1024, 600, 0.72), (800, 480, 0.72),          # floor: never unreadably small
    (1280, 1024, 0.8),                             # limited by the narrower side
    (2560, 1440, 1.33), (3840, 2160, 1.5),         # 2K / 4K are enlarged, capped
]


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class UiScaleTests(unittest.TestCase):
    def test_zoom_values(self):
        res = subprocess.run(['node', '-e', RUNNER, KIOSK_JS], input=json.dumps([[w, h] for w, h, _ in CASES]),
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        for (w, h, expected), actual in zip(CASES, json.loads(res.stdout)):
            self.assertAlmostEqual(actual, expected, places=2, msg=f'{w}x{h}')


if __name__ == '__main__':
    unittest.main()
