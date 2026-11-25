#!/usr/bin/env python3
"""Circle every drone in the hall camera's footage of a flight, from mocap.

    # 1. the clock: when was this video's first frame, on the flight log's clock?
    scripts/footage/camera_overlay.py sync   <flight folder> <video.mp4>
    # 2. (only if the camera moved) refit its model from the drones' LEDs
    scripts/footage/camera_overlay.py calibrate <flight folder> <video.mp4> --out cam.json
    # 3. the clip: every drone circled, team colours, the VIP named
    scripts/footage/camera_overlay.py render <flight folder> <video.mp4> out.mp4 [--pip]

The camera model (camera01.json, next to this script) maps a mocap position to a 4K
pixel: a 3x4 projection plus radial distortion, fitted 2026-11-25 to ~350 LED
detections over a whole flight (median error 2.6 px). It holds while Camera 01 is
not moved or re-zoomed; `calibrate` refits it from a flight's LEDs, starting from the
current model. Read docs/details/flight-replay-footage.md first.

Time: a hall-camera export starts at the time in its name (D04_YYYYmmddHHMMSS), but
the camera's clock and the laptop's differ by a fraction of a second, so `sync`
measures it: every frame's LED blobs against every drone's predicted pixel, over a
grid of offsets. Needs the workspace sourced (rclpy for the bag) and scipy, Pillow.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys

import numpy as np
import rclpy.serialization as ser
from motion_capture_tracking_interfaces.msg import NamedPoseArray
from PIL import Image, ImageDraw, ImageFont
from rosbag2_py import ConverterOptions, SequentialReader, StorageFilter, StorageOptions
from scipy import ndimage
from scipy.optimize import least_squares

HERE = os.path.dirname(os.path.abspath(__file__))
W4, H4 = 3840, 2160
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
BLUE, RED, VIP, GREY = (77, 163, 255), (255, 92, 70), (255, 255, 255), (170, 170, 170)
CLOCK_ROWS = 220          # the camera burns its clock into the top rows: never crop into them


# ---------------------------------------------------------------- the flight
class Flight:
    """What a flight-log folder says: who flew, the mocap tracks, MATCH LIVE, the downs."""

    def __init__(self, folder):
        meta = json.load(open(f'{folder}/meta.json'))
        P, argv = {}, meta['argv']
        for i, a in enumerate(argv):
            if a == '-p' and i + 1 < len(argv) and ':=' in argv[i + 1]:
                k, v = argv[i + 1].split(':=', 1)
                P[k] = v
        self.defense = [n for n in P.get('defenders', '').split(',') if n]
        self.attack = [n for n in P.get('attackers', '').split(',') if n]
        self.vip = P.get('vip_name', 'operator')
        self.match_t0, self.downed = None, {}
        for line in open(f'{folder}/output.log', encoding='utf-8', errors='replace'):
            if 'MATCH LIVE' in line and self.match_t0 is None:
                self.match_t0 = dt.datetime.fromisoformat(line[:23]).timestamp()
            m = re.search(r't\+\s*([\d.]+)s\s+(\w+) DOWNED (\w+)', line)
            if m:
                self.downed.setdefault(m.group(3), float(m.group(1)))
        r = SequentialReader()
        r.open(StorageOptions(uri=f'{folder}/bag', storage_id='mcap'), ConverterOptions('', ''))
        r.set_filter(StorageFilter(topics=['/poses']))
        tr = {}
        while r.has_next():
            _, d, ns = r.read_next()
            for p in ser.deserialize_message(d, NamedPoseArray).poses:
                q = p.pose.position
                tr.setdefault(p.name, []).append((ns * 1e-9, q.x, q.y, q.z))
        self.track = {k: np.array(v) for k, v in tr.items()}
        self.drones = [n for n in self.defense + self.attack if n in self.track]

    def at(self, name, wall):
        a = self.track[name]
        return np.array([np.interp(wall, a[:, 0], a[:, k]) for k in (1, 2, 3)])

    def airborne_span(self):
        ts = [a[a[:, 3] > 0.25, 0] for n, a in self.track.items() if n in self.drones]
        ts = [t for t in ts if len(t)]
        return min(t[0] for t in ts), max(t[-1] for t in ts)


# ---------------------------------------------------------------- the camera
class Camera:
    def __init__(self, path):
        c = json.load(open(path))
        self.params = np.array(c['params'], float)
        self.C0, self.S0 = np.array(c['C0'], float), float(c['S0'])
        self.raw = c

    def project(self, X, params=None):
        prm = self.params if params is None else params
        X = np.atleast_2d(X)
        h = np.c_[X, np.ones(len(X))] @ prm[:12].reshape(3, 4).T
        u = h[:, :2] / h[:, 2:3]
        q = (u - self.C0) / self.S0
        r2 = (q ** 2).sum(1, keepdims=True)
        return self.C0 + self.S0 * q * (1 + prm[12] * r2 + prm[13] * r2 ** 2)


def video_start(video):
    """The time in a hall-camera export's name (D04_YYYYmmddHHMMSS.mp4)."""
    m = re.search(r'(\d{14})', os.path.basename(video))
    if not m:
        sys.exit('no YYYYmmddHHMMSS in the video name: pass --t0')
    return dt.datetime.strptime(m.group(1), '%Y%m%d%H%M%S').timestamp()


def led_blobs(video, times):
    """Per sampled frame: the centroids of bright, saturated blobs (drone LEDs).
    The ceiling lights are bright but white, so saturation drops them."""
    sel = '+'.join(f'between(t,{t - 0.026:.3f},{t + 0.024:.3f})' for t in times)
    p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-i', video, '-vf', f"select='{sel}'",
                          '-vsync', '0', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                         stdout=subprocess.PIPE)
    out, n = [], W4 * H4 * 3
    for t in times:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        img = np.frombuffer(b, np.uint8).reshape(H4, W4, 3).astype(np.int16)
        v, s = img.max(2), img.max(2) - img.min(2)
        mask = (v > 200) & (s > 60)
        mask[:CLOCK_ROWS] = False
        lab, k = ndimage.label(mask)
        if k:
            sizes = ndimage.sum(mask, lab, range(1, k + 1))
            cents = np.array(ndimage.center_of_mass(mask, lab, range(1, k + 1)))[:, ::-1]
            cents = cents[(sizes >= 3) & (sizes <= 2500)]
        else:
            cents = np.zeros((0, 2))
        out.append((t, cents))
    p.stdout.close()
    p.wait()
    return out


def predictions(flight, cam, frames, t0, params=None):
    """(name, frame time, predicted pixel) for every airborne drone in every frame."""
    out = []
    for t, _ in frames:
        L = t0 + t
        for n in flight.drones:
            X = flight.at(n, L)
            if X[2] > 0.25:
                out.append((n, t, X, cam.project(X, params)[0]))
    return out


def match_error(flight, cam, frames, t0, cap=60.0):
    blobs = dict(frames)
    e = []
    for _, t, _, uv in predictions(flight, cam, frames, t0):
        c = blobs[t]
        e.append(min(cap, float(np.min(np.linalg.norm(c - uv, axis=1)))) if len(c) else cap)
    return float(np.median(e)) if e else cap


def sample_times(flight, t0_guess, step):
    a, b = flight.airborne_span()
    return list(np.arange(max(a - t0_guess, 0.5), b - t0_guess, step))


def fit_t0(flight, cam, frames, guess, span):
    coarse = np.arange(guess - span, guess + span + 1e-6, 0.1)
    best = min(coarse, key=lambda t0: match_error(flight, cam, frames, t0))
    fine = np.arange(best - 0.15, best + 0.15 + 1e-6, 0.01)
    best = min(fine, key=lambda t0: match_error(flight, cam, frames, t0))
    return float(best), match_error(flight, cam, frames, best)


# ---------------------------------------------------------------- commands
def cmd_sync(a):
    flight, cam = Flight(a.flight), Camera(a.camera)
    guess = a.t0 if a.t0 is not None else video_start(a.video)
    frames = led_blobs(a.video, sample_times(flight, guess - a.span, 0.5))
    t0, err = fit_t0(flight, cam, frames, guess, a.span)
    stamp = dt.datetime.fromtimestamp(t0).isoformat(timespec='milliseconds')
    print(f'video t=0 is {stamp} on the flight log clock ({t0 - video_start(a.video):+.2f} s from '
          f'the time in its name); median LED-to-prediction distance {err:.1f} px')
    out = a.out or os.path.splitext(os.path.basename(a.video))[0] + '.sync.json'
    json.dump({'video': os.path.basename(a.video), 'flight': os.path.basename(a.flight.rstrip('/')),
               't0': t0, 't0_iso': stamp, 'median_px': err}, open(out, 'w'), indent=1)
    print(f'wrote {out}')


def cmd_calibrate(a):
    flight, cam = Flight(a.flight), Camera(a.camera)
    t0 = load_t0(a)
    frames = led_blobs(a.video, sample_times(flight, t0, 0.5))
    blobs = dict(frames)
    params = cam.params.copy()
    for it in range(3):
        pts = []
        pred = predictions(flight, cam, frames, t0, params)
        for k, (n, t, X, uv) in enumerate(pred):
            others = [q for (m, s, _, q) in pred if s == t and m != n]
            if others and np.min(np.linalg.norm(np.array(others) - uv, axis=1)) < 90:
                continue                    # two drones that close: which blob is whose?
            c = blobs[t]
            if not len(c):
                continue
            d = np.linalg.norm(c - uv, axis=1)
            j = int(np.argmin(d))
            if d[j] < 45 and np.sum(d < 45) == 1:
                pts.append((X, c[j]))
        X = np.array([p[0] for p in pts])
        U = np.array([p[1] for p in pts])

        def res(z):
            return (cam.project(X, z) - U).ravel()
        params = least_squares(res, params, loss='soft_l1', f_scale=6.0).x
        params[:12] /= np.linalg.norm(params[:12])
        e = np.linalg.norm(res(params).reshape(-1, 2), axis=1)
        print(f'iteration {it}: {len(pts)} LED points, median {np.median(e):.1f} px, '
              f'90th percentile {np.percentile(e, 90):.1f} px (4K)')
    out = dict(cam.raw)
    out.update(params=params.tolist(), residual_px={'median': round(float(np.median(e)), 2),
                                                    'p90': round(float(np.percentile(e, 90)), 2)},
               fitted=f'{dt.date.today()} from {os.path.basename(a.flight.rstrip("/"))}, '
                      f'{os.path.basename(a.video)}, {len(pts)} LED points')
    json.dump(out, open(a.out, 'w'), indent=1)
    print(f'wrote {a.out} (run sync again with it)')


def load_t0(a):
    if a.t0 is not None:
        return a.t0
    s = a.sync or os.path.splitext(os.path.basename(a.video))[0] + '.sync.json'
    if not os.path.exists(s):
        sys.exit(f'no {s}: run `sync` first, or pass --t0')
    return json.load(open(s))['t0']


def cmd_render(a):
    flight, cam = Flight(a.flight), Camera(a.camera)
    t0 = load_t0(a)
    if flight.match_t0 is None:
        sys.exit('no MATCH LIVE line in output.log')
    fps = 20
    ow, oh = (1600, 618) if a.pip else (1280, 720)
    aspect = ow / oh
    start = flight.match_t0 - a.pre                     # flight-log clock
    n = int((a.pre + a.post) * fps)
    scene = []
    for k in range(n):
        L = start + k / fps
        mt = L - flight.match_t0
        items = []
        for name in flight.drones + ([flight.vip] if flight.vip in flight.track else []):
            X = flight.at(name, L)
            down = name in flight.downed and mt >= flight.downed[name]
            if X[2] < 0.15 and (down or name == flight.vip):
                continue                    # landed: out of the picture
            uv = cam.project(X)[0]
            r = float(np.linalg.norm(cam.project(X + [0, 0, 0.18 if name != flight.vip else 0.26])[0] - uv))
            items.append((name, uv, r, down))
        scene.append(items)
    # one fixed frame round everything in play (a panning frame changes every pixel:
    # GIFs of it balloon, and it is harder to watch)
    pts = np.array([u for items in scene for _, u, _, d in items if not d])
    lo, hi = pts.min(0) - [190, 170], pts.max(0) + [230, 150]
    if a.pip:                                           # keep the left 36% for an inset
        w = max((hi[0] - lo[0]) / 0.64, (hi[1] - lo[1]) * aspect)
        cx = (lo[0] + hi[0]) / 2 - 0.18 * w
    else:
        w = max(hi[0] - lo[0], (hi[1] - lo[1]) * aspect)
        cx = (lo[0] + hi[0]) / 2
    w = min(w, W4, (H4 - CLOCK_ROWS) * aspect)
    h = w / aspect
    x0 = float(np.clip(cx - w / 2, 0, W4 - w))
    y0 = float(np.clip((lo[1] + hi[1]) / 2 - h / 2, CLOCK_ROWS, H4 - h))
    s = ow / w
    t_video = start - t0
    pre = min(3.0, t_video)                             # accurate seek: decode the last 3 s
    dec = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-ss', f'{t_video - pre:.3f}', '-i', a.video,
                            '-ss', f'{pre:.3f}', '-frames:v', str(n), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                            '-s', f'{ow}x{oh}', '-r', str(fps), '-i', '-', '-c:v', 'libx264', '-crf', '19',
                            '-preset', 'slow', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', a.out],
                           stdin=subprocess.PIPE)
    font = ImageFont.truetype(FONT, 24 if a.pip else 22)
    for k in range(n):
        b = dec.stdout.read(W4 * H4 * 3)
        if len(b) < W4 * H4 * 3:
            break
        im = Image.frombytes('RGB', (W4, H4), b).crop((int(x0), int(y0), int(x0 + w), int(y0 + h)))
        im = im.resize((ow, oh), Image.LANCZOS)
        d = ImageDraw.Draw(im)
        for name, uv, r4, down in scene[k]:
            px, py = (uv[0] - x0) * s, (uv[1] - y0) * s
            r = max(13.0, r4 * s)
            col = GREY if down else (BLUE if name in flight.defense else RED if name in flight.attack else VIP)
            lab = 'VIP' if name == flight.vip else (f'{name} out' if down else name)
            d.ellipse([px - r, py - r, px + r, py + r], outline=(0, 0, 0), width=6)
            d.ellipse([px - r, py - r, px + r, py + r], outline=col, width=3)
            tw = d.textlength(lab, font=font)
            tx, ty = px + r * 0.75 + 4, py - r - 24
            d.rounded_rectangle([tx - 5, ty - 2, tx + tw + 5, ty + 26], radius=5, fill=(0, 0, 0))
            d.text((tx, ty), lab, fill=col, font=font)
        enc.stdin.write(im.tobytes())
    enc.stdin.close()
    enc.wait()
    dec.stdout.close()
    dec.wait()
    print(f'wrote {a.out}: {n / fps:.1f} s from MATCH LIVE -{a.pre:g} s, {ow}x{oh}, '
          f'frame {int(w)}x{int(h)} at ({int(x0)},{int(y0)}) of the 4K picture')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--camera', default=os.path.join(HERE, 'camera01.json'), help='camera model')
    sub = ap.add_subparsers(dest='cmd', required=True)

    def common(p, out=False):
        p.add_argument('flight', help='a guard_show flight-log folder')
        p.add_argument('video', help='the hall camera export (4K)')
        if out:
            p.add_argument('out')
        p.add_argument('--t0', type=float, help='video t=0 on the flight-log clock (epoch s); '
                                                'skips the sync file')
        p.add_argument('--sync', help='sync file (default <video name>.sync.json in this folder)')
    p = sub.add_parser('sync', help='measure the video clock against the flight log')
    common(p)
    p.add_argument('--span', type=float, default=5.0, help='search +-s round the guess (default 5)')
    p.add_argument('--out', help='sync file to write')
    p.set_defaults(func=cmd_sync)
    p = sub.add_parser('calibrate', help='refit the camera model from the drones\' LEDs')
    common(p)
    p.add_argument('--out', required=True, help='camera model to write')
    p.set_defaults(func=cmd_calibrate)
    p = sub.add_parser('render', help='the match, every drone circled')
    common(p, out=True)
    p.add_argument('--pre', type=float, default=6.0, help='s before MATCH LIVE (default 6)')
    p.add_argument('--post', type=float, default=30.0, help='s after it (default 30)')
    p.add_argument('--pip', action='store_true', help='2.59:1, left 36%% kept clear for an inset')
    p.set_defaults(func=cmd_render)
    a = ap.parse_args()
    a.func(a)


if __name__ == '__main__':
    main()
