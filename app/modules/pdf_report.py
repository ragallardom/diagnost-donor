#!/usr/bin/env python3
"""
Tiny dependency-free PDF writer for the QA report.

Why not print the HTML with Chrome: the kiosk Chrome policy blocks file:// and printing
(PrintingEnabled=false), so headless Chrome never produces a PDF. This renders the report model
directly: A4, built-in Helvetica (no embedded fonts, ~5 KB per page), tables, colored badges.
"""

import re
import unicodedata

PAGE_W, PAGE_H = 595.0, 842.0
MARGIN = 40.0
LINE = 1.28

# Helvetica advance widths (1/1000 em) for ASCII 32..126; bold is ~6% wider.
_W = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
      556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
      1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
      667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
      333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
      556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]

COLORS = {
    'ok': ((0.86, 0.96, 0.91), (0.04, 0.48, 0.27)),
    'fail': ((0.99, 0.89, 0.89), (0.71, 0.14, 0.09)),
    'pending': ((0.92, 0.93, 0.96), (0.35, 0.38, 0.45)),
    'warn': ((1.0, 0.94, 0.82), (0.60, 0.36, 0.0)),
}
INK = (0.11, 0.12, 0.16)
MUTED = (0.35, 0.38, 0.45)
ACCENT = (0.36, 0.25, 0.82)
RULE = (0.88, 0.89, 0.93)


def char_width(ch):
    code = ord(ch)
    if 32 <= code <= 126:
        return _W[code - 32]
    base = unicodedata.normalize('NFD', ch)[:1]
    if base and 32 <= ord(base) <= 126:
        return _W[ord(base) - 32]          # accented letter: same advance as its base letter
    return 556


def text_width(text, size, bold=False):
    return sum(char_width(c) for c in text) * size / 1000.0 * (1.06 if bold else 1.0)


def wrap(text, width, size, bold=False):
    """Greedy word wrap; words longer than the column are split."""
    lines = []
    for para in str(text).split('\n'):
        cur = ''
        for word in para.split(' '):
            while text_width(word, size, bold) > width and len(word) > 1:
                cut = len(word)
                while cut > 1 and text_width(word[:cut], size, bold) > width:
                    cut -= 1
                if cur:
                    lines.append(cur)
                    cur = ''
                lines.append(word[:cut])
                word = word[cut:]
            trial = f'{cur} {word}'.strip() if cur else word
            if cur and text_width(trial, size, bold) > width:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
    return lines or ['']


def _pdf_str(text):
    data = str(text).encode('cp1252', 'replace')
    return b'(' + data.replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)') + b')'


class _Doc:
    def __init__(self):
        self.pages = []            # list of bytearray content streams
        self.y = 0.0
        self._new_page()

    def _new_page(self):
        self.pages.append(bytearray())
        self.y = PAGE_H - MARGIN

    def emit(self, data):
        self.pages[-1].extend(data)

    def ensure(self, height):
        if self.y - height < MARGIN:
            self._new_page()

    def rect(self, x, y, w, h, color):
        self.emit(b'%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f\n' % (*color, x, y, w, h))

    def line(self, x1, x2, y, color=RULE):
        self.emit(b'%.3f %.3f %.3f RG 0.5 w %.2f %.2f m %.2f %.2f l S\n' % (*color, x1, y, x2, y))

    def text(self, x, y, txt, size=9.5, bold=False, color=INK):
        self.emit(b'BT %.3f %.3f %.3f rg /%s %.2f Tf %.2f %.2f Td ' % (*color, b'F2' if bold else b'F1', size, x, y)
                  + _pdf_str(txt) + b' Tj ET\n')

    # ── building blocks ──
    def title(self, txt, sub):
        self.ensure(40)
        self.y -= 18
        self.text(MARGIN, self.y, txt, 18, True)
        self.y -= 14
        self.text(MARGIN, self.y, sub, 9, False, MUTED)
        self.y -= 8

    def heading(self, txt):
        self.ensure(40)
        self.y -= 22
        self.text(MARGIN, self.y, txt.upper(), 10, True, ACCENT)
        self.y -= 5

    def paragraph(self, txt, size=9.5, bold=False, color=INK, indent=0.0):
        for ln in wrap(txt, PAGE_W - 2 * MARGIN - indent, size, bold):
            self.ensure(size * LINE)
            self.y -= size * LINE
            self.text(MARGIN + indent, self.y, ln, size, bold, color)

    def badge(self, x, y, label, kind, size=8):
        bg, fg = COLORS.get(kind, COLORS['pending'])
        w = text_width(label, size, True) + 10
        self.rect(x, y - 3, w, size + 5, bg)
        self.text(x + 5, y, label, size, True, fg)
        return w

    def rows(self, rows, col1=92.0, col2=None, kind_col=True):
        """rows: [(label, (badge text, kind) or None, detail)]."""
        size = 9
        col2 = col2 if col2 is not None else (78.0 if kind_col else 0.0)
        detail_x = MARGIN + col1 + col2
        detail_w = PAGE_W - MARGIN - detail_x
        for label, badge, detail in rows:
            lines = wrap(detail or '', detail_w, size) if detail else ['']
            lab = wrap(label, col1 - 6, size, True)
            height = max(len(lines), len(lab)) * size * LINE + 7
            self.ensure(height)
            top = self.y
            self.y -= 4 + size * LINE - 2
            for i, ln in enumerate(lab):
                self.text(MARGIN, self.y - i * size * LINE, ln, size, True, MUTED if not kind_col else INK)
            if badge:
                self.badge(MARGIN + col1, self.y, badge[0], badge[1])
            for i, ln in enumerate(lines):
                self.text(detail_x, self.y - i * size * LINE, ln, size, False, INK)
            self.y = top - height
            self.line(MARGIN, PAGE_W - MARGIN, self.y + 2)

    def pills(self, items):
        self.ensure(24)
        self.y -= 18
        x = MARGIN
        for label, kind in items:
            x += self.badge(x, self.y, label, kind, 9) + 8


def _s(value, limit=300):
    return str(value if value is not None else '')[:limit]


def render_pdf(model):
    """PDF bytes for a report model (the structure js/report.js builds)."""
    if not isinstance(model, dict):
        raise ValueError('Informe inválido')
    d = _Doc()
    d.title('Informe de diagnóstico', _s(model.get('date')))

    info = [(_s(k, 40), None, _s(v)) for k, v in (model.get('info') or [])[:20] if v]
    if info:
        d.heading('Equipo')
        d.rows(info, col1=70.0, kind_col=False)

    checklist = (model.get('checklist') or [])[:60]
    counts = model.get('counts') or {}
    d.heading('Checklist')
    d.pills([(f"{int(counts.get('ok') or 0)} aprobadas", 'ok'), (f"{int(counts.get('fail') or 0)} con fallo", 'fail'),
             (f"{int(counts.get('pending') or 0)} pendientes", 'pending')])
    d.y -= 4
    label = {'ok': 'Aprobado', 'fail': 'Falló', 'pending': 'Pendiente'}
    d.rows([(_s(c.get('label'), 40), (label.get(c.get('status'), 'Pendiente'), c.get('status') if c.get('status') in label else 'pending'),
             _s(c.get('detail'))) for c in checklist])

    st = model.get('stress')
    if isinstance(st, dict) and st.get('rows'):
        d.heading('Prueba de estrés' + (f" · {_s(st.get('title'), 20)}" if st.get('title') else ''))
        text = {'ok': 'OK', 'fail': 'Falló', 'warn': 'Sin verificar'}
        d.rows([(_s(r.get('name'), 20), (text.get(r.get('status'), 'Sin verificar'), r.get('status') if r.get('status') in text else 'warn'),
                 _s(r.get('message'))) for r in st['rows'][:8]], col1=60.0)
        d.y -= 8
        line = [f"Temp. máx: {_s(st.get('max'), 12) or 'N/D'}", f"Prom.: {_s(st.get('avg'), 12) or 'N/D'}",
                f"Estado: {_s(st.get('state'), 20)}"]
        d.paragraph('   ·   '.join(line), 9.5, True)
        extra = [_s(st.get('verdict'), 60), _s(st.get('throttle'), 100), _s(st.get('caution'), 100)]
        extra = [e for e in extra if e]
        if extra:
            d.paragraph('  ·  '.join(extra), 9, False, MUTED)

    note = _s(model.get('comments'), 1000).strip()
    if note:
        d.heading('Comentarios')
        d.paragraph(note, 9.5)

    return _assemble(d.pages, _s(model.get('serial'), 40))


def _assemble(pages, title):
    objs = {}
    objs[1] = b'<< /Type /Catalog /Pages 2 0 R >>'
    kids = ' '.join(f'{5 + 2 * i} 0 R' for i in range(len(pages))).encode()
    objs[2] = b'<< /Type /Pages /Kids [' + kids + b'] /Count ' + str(len(pages)).encode() + b' >>'
    objs[3] = b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'
    objs[4] = b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>'
    for i, content in enumerate(pages):
        page_id, content_id = 5 + 2 * i, 6 + 2 * i
        objs[page_id] = (b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.0f %.0f] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> '
                         b'/Contents %d 0 R >>' % (PAGE_W, PAGE_H, content_id))
        objs[content_id] = b'<< /Length %d >>\nstream\n' % len(content) + bytes(content) + b'\nendstream'
    info_id = 5 + 2 * len(pages)
    objs[info_id] = b'<< /Title ' + _pdf_str('Informe ' + title) + b' /Producer (Diagnost-Donor) >>'

    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += b'%d 0 obj\n' % num + objs[num] + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n' % (info_id + 1) + b'0000000000 65535 f \n'
    for num in range(1, info_id + 1):
        out += b'%010d 00000 n \n' % offsets[num]
    out += b'trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (info_id + 1, info_id, xref)
    return bytes(out)
