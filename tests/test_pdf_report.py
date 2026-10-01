"""PDF report writer: structural validity, content, wrapping and pagination."""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app', 'modules'))

import pdf_report as pr  # noqa: E402


def model(n_checklist=3, detail='ok', comments='', stress=True):
    m = {'date': '1/10/2026 13:50', 'serial': 'PF3ABC', 'info': [['Modelo', 'Lenovo ThinkPad T14 Gen 1'], ['Serie', 'PF3ABC']],
         'counts': {'ok': n_checklist, 'fail': 0, 'pending': 0},
         'checklist': [{'label': f'Prueba {i}', 'status': 'ok', 'detail': detail} for i in range(n_checklist)],
         'stress': None, 'comments': comments}
    if stress:
        m['stress'] = {'title': 'Rápida', 'rows': [{'name': 'CPU', 'status': 'ok', 'message': '4 hilos'},
                                                    {'name': 'GPU', 'status': 'warn', 'message': 'Sin verificar'}],
                       'max': '98 °C', 'avg': '93 °C', 'state': 'Superado', 'verdict': 'Sobrecalentamiento',
                       'throttle': 'Throttling térmico: 3 eventos (4.2 s)', 'caution': 'Precaución: x'}
    return m


def check_structure(pdf):
    """Assert the PDF is well formed (header, xref offsets, stream lengths, startxref) and return page count."""
    assert pdf.startswith(b'%PDF-1.4') and pdf.rstrip().endswith(b'%%EOF')
    start = int(re.search(rb'startxref\n(\d+)\n', pdf).group(1))
    assert pdf[start:start + 4] == b'xref'
    size = int(re.search(rb'/Size (\d+)', pdf).group(1))
    entries = re.findall(rb'(\d{10}) \d{5} n \n', pdf[start:])
    assert len(entries) == size - 1
    for num, off in enumerate(entries, 1):
        assert pdf[int(off):].startswith(b'%d 0 obj' % num), num
    for m in re.finditer(rb'/Length (\d+) >>\nstream\n', pdf):
        n = int(m.group(1))
        assert pdf[m.end() + n:m.end() + n + 10] == b'\nendstream', 'bad /Length'
    return len(re.findall(rb'/Type /Page ', pdf))


class PdfTests(unittest.TestCase):
    def test_well_formed_single_page(self):
        pdf = pr.render_pdf(model())
        self.assertEqual(check_structure(pdf), 1)
        self.assertLess(len(pdf), 20_000)

    def test_content_is_present_with_spanish_accents(self):
        pdf = pr.render_pdf(model(comments='Batería al 60%, cambiar (ñandú) \\ prueba'))
        for text in ('Informe de diagn\xf3stico'.encode('cp1252'), b'Lenovo ThinkPad T14 Gen 1', b'PRUEBA DE ESTR\xc9S',
                     'Sobrecalentamiento'.encode('cp1252'), 'Bater\xeda'.encode('cp1252')):
            self.assertIn(text, pdf)
        self.assertEqual(check_structure(pdf), 1)

    def test_parentheses_and_backslashes_are_escaped(self):
        pdf = pr.render_pdf(model(detail='a (b) \\ c'))
        self.assertIn(b'a \\(b\\) \\\\ c', pdf)
        check_structure(pdf)

    def test_many_rows_paginate(self):
        pdf = pr.render_pdf(model(n_checklist=60))
        self.assertGreater(check_structure(pdf), 1)

    def test_long_text_wraps_inside_the_column(self):
        lines = pr.wrap('palabra ' * 40, 200, 9)
        self.assertGreater(len(lines), 3)
        self.assertTrue(all(pr.text_width(l, 9) <= 200 for l in lines))
        # one unbroken token longer than the column is split instead of overflowing
        parts = pr.wrap('x' * 200, 100, 9)
        self.assertTrue(all(pr.text_width(p, 9) <= 100 for p in parts))
        self.assertEqual(''.join(parts), 'x' * 200)

    def test_accented_letters_measure_like_their_base(self):
        self.assertEqual(pr.char_width('é'), pr.char_width('e'))
        self.assertEqual(pr.char_width('Ñ'), pr.char_width('N'))

    def test_no_stress_and_no_comments_sections_are_omitted(self):
        pdf = pr.render_pdf(model(stress=False))
        self.assertNotIn(b'ESTR', pdf)
        self.assertNotIn(b'COMENTARIOS', pdf)

    def test_hostile_or_odd_input_does_not_break_the_file(self):
        m = model(detail='\x00\x01 emoji \U0001F600 tab\tx', comments='x' * 5000)
        m['info'].append([None, None])
        m['checklist'].append({'label': None, 'status': 'weird', 'detail': None})
        check_structure(pr.render_pdf(m))
        for bad in (None, 'x', 5, []):
            with self.assertRaises(ValueError):
                pr.render_pdf(bad)


if __name__ == '__main__':
    unittest.main()
