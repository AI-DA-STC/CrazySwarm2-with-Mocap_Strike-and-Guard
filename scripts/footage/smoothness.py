#!/usr/bin/env python3
"""How many times a second a recording REALLY changes picture.

    smoothness.py <video> [start-s] [seconds]

A screen capture at 30 fps of a page that renders at 3 fps is 27 repeated frames a
second; this counts frames that differ from the previous one by more than video noise
(>15 pixels changed by >40 grey levels, at 750 px wide). A good take reads ~30 fps.
"""

import subprocess
import sys

import numpy as np

W = 750


def main(path, ss='0', t='10'):
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v', '-show_entries',
                            'stream=width,height', '-of', 'csv=p=0', path],
                           capture_output=True, text=True, check=True).stdout.split(',')
    h = int(round(int(probe[1]) * W / int(probe[0]) / 2)) * 2
    raw = subprocess.run(['ffmpeg', '-loglevel', 'error', '-ss', ss, '-t', t, '-i', path,
                          '-vf', f'scale={W}:{h},format=gray', '-f', 'rawvideo', '-'],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(-1, h, W).astype(np.int16)
    moved = (np.abs(np.diff(a, axis=0)) > 40).sum(axis=(1, 2))
    real = int((moved > 15).sum())
    print(f'{path}: {len(a)} frames over {t} s, {real} real changes -> {real / float(t):.1f} fps')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(*sys.argv[1:4])
