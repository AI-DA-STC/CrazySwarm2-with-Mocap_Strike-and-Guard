#!/usr/bin/env python3
"""Title bar and legend strip for the guard clips, in guard/viz.py's own colours.

The colours and glyphs copy guard/viz.py (C_DEF, C_ATT, C_DECOY, C_FEINT, C_OUT, intent_symbol):
change a symbol there and change it here, or the legend lies.

    overlay.py legend <out.png>
    overlay.py title <out.png> "<headline>" "<one line>"
"""
import math
import sys

from PIL import Image, ImageDraw, ImageFont

W = 1080
S = 2                                     # drawn at 2x, then downscaled (antialiasing)
BG = (10, 13, 18)
FG = (225, 230, 238)
FG2 = (150, 160, 175)
DEF = (64, 140, 255)
ATT = (255, 56, 31)
DECOY = (255, 64, 217)
FEINT = (255, 179, 26)
OUT = (140, 140, 140)
VIP = (240, 240, 240)
SECURE = (51, 255, 89)
SANS = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def font(path, px):
    return ImageFont.truetype(path, px * S)


def _dash(d, a, b, col, w, on=7, off=5):
    (x0, y0), (x1, y1) = a, b
    L = math.hypot(x1 - x0, y1 - y0)
    n = max(1, int(L // (on + off)))
    for i in range(n + 1):
        s, e = i * (on + off), min(i * (on + off) + on, L)
        if s >= L:
            break
        d.line([(x0 + (x1 - x0) * s / L, y0 + (y1 - y0) * s / L),
                (x0 + (x1 - x0) * e / L, y0 + (y1 - y0) * e / L)], fill=col, width=w)


def _head(d, a, b, col, w, size=9):
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    for da in (2.6, -2.6):
        d.line([b, (b[0] + size * math.cos(ang + da), b[1] + size * math.sin(ang + da))],
               fill=col, width=w)


def _ring(d, c, r, col, w):
    d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], outline=col, width=w)


def _dashed_ring(d, c, r, col, w, n=16):
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 0.55) / n
        d.arc([c[0] - r, c[1] - r, c[0] + r, c[1] + r], math.degrees(a0), math.degrees(a1),
              fill=col, width=w)


def symbol(d, kind, x, y):
    """One legend glyph in a 44x20 box whose left-centre is (x, y) (unscaled px)."""
    def P(px, py):
        return ((x + px) * S, (y + py) * S)
    w2, w3 = 2 * S, 3 * S
    if kind == 'defender':
        _ring(d, P(22, 0), 7 * S, DEF, w2)
    elif kind == 'attacker':
        _ring(d, P(22, 0), 7 * S, ATT, w2)
    elif kind == 'decoy':
        _ring(d, P(22, 0), 7 * S, DECOY, w2)
    elif kind == 'out':
        d.line([P(16, -6), P(28, 6)], fill=OUT, width=w2)
        d.line([P(16, 6), P(28, -6)], fill=OUT, width=w2)
    elif kind == 'block':
        d.line([P(2, 0), P(30, 0)], fill=DEF, width=w2)
        d.line([P(30, -9), P(30, 9)], fill=DEF, width=w2)
        for k in (-9, 0, 9):
            d.line([P(30, k), P(35, k)], fill=DEF, width=w2)
        _dash(d, P(36, 0), P(44, 0), DEF + (140,), S, 3 * S, 3 * S)
    elif kind == 'pincer':
        pts = [P(2 + 34 * t, 8 - 26 * t * (1 - t) * 1.6 - 8 * t) for t in [i / 12 for i in range(13)]]
        d.line(pts, fill=DEF, width=w2)
        _head(d, pts[-3], pts[-1], DEF, w2, 8 * S)
    elif kind == 'post':
        c = P(22, 0)
        r = 7 * S
        d.polygon([(c[0], c[1] - r), (c[0] + r, c[1]), (c[0], c[1] + r), (c[0] - r, c[1])],
                  outline=DEF, width=w2)
    elif kind == 'bail':
        _dash(d, P(2, 0), P(38, 0), DEF, w2, 6 * S, 4 * S)
        _head(d, P(2, 0), P(40, 0), DEF, w2, 8 * S)
    elif kind == 'stage':
        _dash(d, P(2, 0), P(28, 0), ATT, w2, 5 * S, 4 * S)
        _ring(d, P(36, 0), 7 * S, ATT, w2)
    elif kind == 'strike':
        d.line([P(2, 0), P(40, 0)], fill=ATT, width=w3 + S)
        _head(d, P(2, 0), P(42, 0), ATT, w3, 10 * S)
    elif kind == 'feint':
        _dash(d, P(2, 0), P(38, 0), FEINT, w2, 6 * S, 4 * S)
        _head(d, P(2, 0), P(40, 0), FEINT, w2, 8 * S)
    elif kind == 'gang':
        d.line([P(2, 0), P(28, 0)], fill=ATT, width=w2)
        _head(d, P(2, 0), P(30, 0), ATT, w2, 8 * S)
        _ring(d, P(38, 0), 5 * S, DEF, w2)
    elif kind == 'vip':
        d.ellipse([*P(16, -6), *P(28, 6)], fill=VIP)
        d.ellipse([*P(33, -4), *P(41, 4)], fill=SECURE)
    elif kind == 'strikezone':
        _dashed_ring(d, P(22, 0), 9 * S, ATT, w2)
    elif kind == 'keepout':
        _ring(d, P(22, 0), 9 * S, (120, 125, 135), S)
    elif kind == 'bubble':
        d.ellipse([*P(12, -9), *P(32, 9)], fill=(40, 70, 120), outline=(70, 110, 170), width=S)
        _ring(d, P(22, 0), 5 * S, DEF, w2)
    elif kind == 'burst':
        for r, a in ((4, 255), (8, 170), (12, 90)):
            _ring(d, P(22, 0), r * S, ATT + (a,), w2)
    elif kind == 'lanes':
        for k in (-7, 0, 7):
            _dash(d, P(2, k * 0.4), P(40, k), ATT + (110,), S, 6 * S, 4 * S)


COLUMNS = [
    ('Teams', [('defender', 'defender'), ('attacker', 'attacker'),
               ('decoy', 'decoy: the attacker sent in first'), ('out', 'taken out: it lands')]),
    ('Defence', [('block', 'block: a screen on its way in'), ('pincer', 'pincer: round the side'),
                 ('post', 'post: holding a spot'), ('bail', 'bail: back to the VIP')]),
    ('Attack', [('stage', 'stage: to its assembly point'), ('strike', 'strike at the VIP'),
                ('feint', 'feint: the side it shows'), ('gang', 'gang up on a defender'),
                ('lanes', "the attack's lanes in")]),
    ('The field', [('vip', 'VIP (green: kept safe)'), ('strikezone', 'strike zone'),
                   ('keepout', "VIP keep-out (nobody enters)"),
                   ('bubble', 'safety layer steering it'), ('burst', 'taken out / strike')]),
]


def legend(path):
    rowh, top, colw = 25, 30, W // 4
    H = top + rowh * 5 + 31          # 186: title 46 + scene 648 + 186 must be even for H.264
    im = Image.new('RGBA', (W * S, H * S), BG + (255,))
    d = ImageDraw.Draw(im, 'RGBA')
    d.line([(0, 0), (W * S, 0)], fill=(40, 46, 56), width=S)
    fh, fr, fs = font(BOLD, 13), font(SANS, 12), font(SANS, 11)
    for c, (head, items) in enumerate(COLUMNS):
        x = 14 + c * colw
        d.text((x * S, 9 * S), head.upper(), font=fh, fill=FG2)
        for r, (kind, text) in enumerate(items):
            y = top + 10 + r * rowh
            symbol(d, kind, x, y)
            d.text(((x + 50) * S, (y - 8) * S), text, font=fr, fill=FG)
    d.text((14 * S, (H - 20) * S),
           'Labels: drone, its intent, d40% = how close it is to being taken out, '
           's40% = how close to striking.',
           font=fs, fill=FG2)
    im.resize((W, H), Image.LANCZOS).convert('RGB').save(path)


def title(path, headline, line):
    H = 46
    im = Image.new('RGB', (W * S, H * S), BG)
    d = ImageDraw.Draw(im)
    d.text((14 * S, 7 * S), headline, font=font(BOLD, 17), fill=FG)
    d.text((14 * S, 27 * S), line, font=font(SANS, 12), fill=FG2)
    d.line([(0, H * S - S), (W * S, H * S - S)], fill=(40, 46, 56), width=S)
    im.resize((W, H), Image.LANCZOS).save(path)


if __name__ == '__main__':
    if sys.argv[1] == 'legend':
        legend(sys.argv[2])
    else:
        title(sys.argv[2], sys.argv[3], sys.argv[4])
