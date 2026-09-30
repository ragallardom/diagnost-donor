"""Top-bar model names (js/ui.js formatModelWithBrand) for the Lenovo / HP families in use.

The JS runs under node; the test is skipped when node is not installed.
"""

import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_JS = os.path.join(ROOT, 'app', 'static', 'js', 'ui.js')

RUNNER = r'''
const vm = require("vm"), fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
const pick = (re) => src.match(re)[0];
const code = pick(/const BRAND_PATTERNS[\s\S]*?\];/) + pick(/function detectBrand[\s\S]*?\n}\n/)
  + pick(/function formatModelWithBrand[\s\S]*?\n}\n/) + pick(/function normalizeGeneration[\s\S]*?\n}\n/)
  + pick(/function formatModelShortName[\s\S]*?\n}\n/);
const ctx = {}; vm.createContext(ctx); vm.runInContext(code, ctx);
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
console.log(JSON.stringify(cases.map(([model, vendor]) => ctx.formatModelWithBrand(model, vendor))));
'''

# (model as built by system_info, vendor, expected top-bar text)
CASES = [
    # Lenovo T14: Intel/AMD, Gen 1 to 6
    ('LENOVO ThinkPad T14 Gen 1', 'LENOVO', 'Lenovo T14 Gen 1'),
    ('LENOVO ThinkPad T14 Gen 2', 'LENOVO', 'Lenovo T14 Gen 2'),
    ('LENOVO ThinkPad T14 Gen 3', 'LENOVO', 'Lenovo T14 Gen 3'),
    ('LENOVO ThinkPad T14 Gen 4', 'LENOVO', 'Lenovo T14 Gen 4'),
    ('LENOVO ThinkPad T14 Gen 5', 'LENOVO', 'Lenovo T14 Gen 5'),
    ('LENOVO ThinkPad T14 Gen 6', 'LENOVO', 'Lenovo T14 Gen 6'),
    ('LENOVO ThinkPad T14s Gen 4', 'LENOVO', 'Lenovo T14s Gen 4'),
    # X1 Carbon Gen 6 .. 12, old "6th" firmware naming included
    ('LENOVO ThinkPad X1 Carbon 6th', 'LENOVO', 'Lenovo X1 Carbon Gen 6'),
    ('LENOVO ThinkPad X1 Carbon 7th', 'LENOVO', 'Lenovo X1 Carbon Gen 7'),
    ('LENOVO ThinkPad X1 Carbon Gen 8', 'LENOVO', 'Lenovo X1 Carbon Gen 8'),
    ('LENOVO ThinkPad X1 Carbon Gen 9', 'LENOVO', 'Lenovo X1 Carbon Gen 9'),
    ('LENOVO ThinkPad X1 Carbon Gen 10', 'LENOVO', 'Lenovo X1 Carbon Gen 10'),
    ('LENOVO ThinkPad X1 Carbon Gen 11', 'LENOVO', 'Lenovo X1 Carbon Gen 11'),
    ('LENOVO ThinkPad X1 Carbon Gen 12', 'LENOVO', 'Lenovo X1 Carbon Gen 12'),
    ('LENOVO ThinkPad X1 Yoga 3rd', 'LENOVO', 'Lenovo X1 Yoga Gen 3'),
    ('LENOVO ThinkPad X1 Yoga Gen 8', 'LENOVO', 'Lenovo X1 Yoga Gen 8'),
    ('LENOVO ThinkPad X1 Extreme Gen 4', 'LENOVO', 'Lenovo X1 Extreme Gen 4'),
    ('LENOVO ThinkPad X1 Nano Gen 2', 'LENOVO', 'Lenovo X1 Nano Gen 2'),
    ('LENOVO ThinkPad X1 2-in-1 Gen 9', 'LENOVO', 'Lenovo X1 2-in-1 Gen 9'),
    ('LENOVO ThinkPad X13 Yoga Gen 2', 'LENOVO', 'Lenovo X13 Yoga Gen 2'),
    ('LENOVO ThinkPad P14s Gen 3', 'LENOVO', 'Lenovo P14s Gen 3'),
    ('LENOVO ThinkPad L14 Gen 2', 'LENOVO', 'Lenovo L14 Gen 2'),
    # Machine type before the name (older mapping) still resolves
    ('LENOVO 21HDCTO1WW ThinkPad T14 Gen 4', 'LENOVO', 'Lenovo T14 Gen 4'),
    # HP EliteBook / Aero / ZBook / others
    ('HP EliteBook 845 G8 Notebook PC', 'HP', 'HP EliteBook 845 G8'),
    ('HP EliteBook 840 G8 Notebook PC', 'HP', 'HP EliteBook 840 G8'),
    ('HP EliteBook 840 Aero G8 Notebook PC', 'HP', 'HP EliteBook 840 Aero G8'),
    ('HP EliteBook 840 14 inch G9 Notebook PC', 'HP', 'HP EliteBook 840 G9'),
    ('HP EliteBook x360 1040 G8 Notebook PC', 'HP', 'HP EliteBook x360 1040 G8'),
    ('HP HP EliteBook 830 G7 Notebook PC', 'HP', 'HP EliteBook 830 G7'),
    ('HP ZBook Firefly 14 inch G8 Mobile Workstation PC', 'HP', 'HP ZBook Firefly 14 G8'),
    ('HP ZBook Firefly 16 inch G9 Mobile Workstation PC', 'HP', 'HP ZBook Firefly 16 G9'),
    ('HP ZBook Fury 16 G9 Mobile Workstation PC', 'HP', 'HP ZBook Fury 16 G9'),
    ('HP ZBook Studio G5', 'HP', 'HP ZBook Studio G5'),
    ('HP ZBook Power G9 Mobile Workstation PC', 'HP', 'HP ZBook Power G9'),
    ('HP ZBook 15 G3', 'HP', 'HP ZBook 15 G3'),
    ('HP Elite Dragonfly G3 Notebook PC', 'HP', 'HP Elite Dragonfly G3'),
    ('HP ProBook 450 G8 Notebook PC', 'HP', 'HP ProBook 450 G8'),
    ('Hewlett-Packard HP ProBook 450 G5', 'Hewlett-Packard', 'HP ProBook 450 G5'),
    # Placeholder / unknown vendors get no invented brand
    ('Generico Laptop / PC', 'Generico', '--'),
]


@unittest.skipUnless(shutil.which('node'), 'node is not installed')
class ModelNameTests(unittest.TestCase):
    def test_top_bar_names(self):
        res = subprocess.run(['node', '-e', RUNNER, UI_JS], input=json.dumps([[m, v] for m, v, _ in CASES]),
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        got = json.loads(res.stdout)
        for (model, _vendor, expected), actual in zip(CASES, got):
            self.assertEqual(actual, expected, model)


if __name__ == '__main__':
    unittest.main()
