#!/usr/bin/env python3
"""Turn one recorded flight into numbers: what was commanded against what flew.

    ros2 run crazyflie_shows flight_report ~/.ros/flight_logs/20261105_163111_guard
    ros2 run crazyflie_shows flight_report <dir> --json      # also print report.json

A flight folder (docs/details/flight-logs.md) holds ``bag/`` (a ros2 bag of
/poses, every drone's commands, onboard pose and status, and /rosout),
``output.log`` (everything the show printed) and ``meta.json``. This reads
them offline -- no ROS graph, no node -- and writes ``report.txt`` and
``report.json`` next to them.

Per drone:

* **Tracking** -- every streamed command (cmd_full_state / cmd_position)
  against the mocap position at the same instant: the error, and the LAG
  (the time shift that best lines the aircraft up with its commands) with
  the error left once that lag is taken out. A big raw error with a small
  residual is a drone that follows faithfully but late; a big residual is
  one that does not follow.
* **Command stream** -- rate, and stalls (gaps between commands while
  streaming). The firmware falls back after a stall; on this rig a stall
  usually means the radio.
* **Mocap** -- rate, dropouts, longest gap, and JUMPS (a pose that moves
  further than a Crazyflie can fly in one frame: a swapped or ghost rigid
  body).
* **Onboard estimate vs mocap** -- position and YAW disagreement. A large
  yaw error is the fly-away precursor (docs/troubleshooting.md).
* **Radio and battery** (the 1 Hz status) -- voltage at start, lowest,
  end; signal strength; unicast latency; packets received; any tumbled /
  locked / crashed flag.
* **Envelope** -- airborne time, top speed, height range.
* **Effort** (needs the ``downwash`` log block, crazyflies.yaml) -- the
  highest motor PWM (near 100 % = saturated, it can no longer hold height),
  the largest tilt, thrust above its own median.

**Downwash detector.** A drone is OVERFLOWN while another drone is above it
(within ``DW_RADIUS`` across and ``DW_DZ`` above; the DJI or any other rigid
body with a wider, taller cone). An overflight is a downwash EVENT when the
drone underneath sank: its measured height fell ``DW_SINK`` below its command
(below where it was, for high-level flights with no streamed command), more
than it usually trails. Each event is listed with who was above, how close,
how far it sank, and -- when the downwash block was logged -- how hard it
fought it: thrust, peak motor PWM, tilt, and the dip in vertical acceleration.

For the fleet: the closest measured pair (and how far apart their commands
were at that instant), every pair inside ``--close`` m, the closest any drone
came to another rigid body (the DJI), what the server logged (commands,
warnings, errors) and the show's own alarm lines (NEAR MISS, ABORT, ...).
"""

import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np

DRONE = re.compile(r'^cf\d+$')
CMD_TOPIC = re.compile(r'^/(?P<n>cf\d+)/(?P<k>cmd_full_state|cmd_position)$')
SHOW_ALARMS = re.compile(r'NEAR MISS|SAFETY PAUSE|MOCAP GLITCH|ABORT|CONTAINMENT|HOLD --'
                         r'|CBF emergency|WINS|DOWNED|STRUCK|REFUSED|FINALE|Traceback'
                         r'|\bError\b|\[ERROR\]|\[FATAL\]')
SUP_BITS = {32: 'tumbled', 64: 'locked', 128: 'crashed'}
#: The downwash log block's variables, in crazyflies.yaml's order (the
#: flight's own config/ copy is read first, in case it changed).
DW_VARS = ['stabilizer.roll', 'stabilizer.pitch', 'stabilizer.thrust', 'acc.z',
           'motor.m1', 'motor.m2', 'motor.m3', 'motor.m4']
#: Overflown: another Crazyflie within DW_RADIUS m across and between 0.05
#: and DW_DZ m above (downwash.md-style cone, generous for a 92 mm quad);
#: anything else (the DJI) within DW_RADIUS_BIG / DW_DZ_BIG.
DW_RADIUS, DW_DZ = 0.35, 1.5
DW_RADIUS_BIG, DW_DZ_BIG = 0.9, 3.0
#: An overflight is an event when the drone sank this much more than usual.
DW_SINK = 0.05
PWM_FULL = 65535.0


# ------------------------------------------------------------------ reading
def read_bag(path):
    """{topic: [(t_s, msg), ...]} from a ros2 bag (mcap or sqlite3)."""
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    storage = ''
    meta = os.path.join(path, 'metadata.yaml')
    if os.path.exists(meta):
        import yaml
        with open(meta, encoding='utf-8') as fh:
            info = (yaml.safe_load(fh) or {}).get('rosbag2_bagfile_information', {})
        storage = info.get('storage_identifier', '')
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=path, storage_id=storage),
                rosbag2_py.ConverterOptions('cdr', 'cdr'))
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    cls = {}
    out = defaultdict(list)
    while reader.has_next():
        topic, data, t_ns = reader.read_next()
        if topic not in cls:
            try:
                cls[topic] = get_message(types[topic])
            except Exception:                           # noqa: BLE001
                cls[topic] = None
        if cls[topic] is None:
            continue
        out[topic].append((t_ns * 1e-9, deserialize_message(data, cls[topic])))
    return out


def _yaw(q):
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


def _wrap(a):
    return (np.asarray(a) + np.pi) % (2.0 * np.pi) - np.pi


def series(msgs):
    """Flatten the topics into numpy series per drone / body."""
    s = {'mocap': defaultdict(list), 'cmd': defaultdict(list), 'est': defaultdict(list),
         'status': defaultdict(list), 'dw': defaultdict(list), 'frames': [], 'rosout': []}
    for t, m in msgs.get('/poses', []):
        names = []
        for p in m.poses:
            q = p.pose.orientation
            s['mocap'][p.name].append((t, p.pose.position.x, p.pose.position.y,
                                       p.pose.position.z, _yaw(q)))
            names.append(p.name)
        s['frames'].append((t, names))
    for topic, rows in msgs.items():
        m = CMD_TOPIC.match(topic)
        if m:
            for t, msg in rows:
                if m['k'] == 'cmd_full_state':
                    p = msg.pose.position
                    s['cmd'][m['n']].append((t, p.x, p.y, p.z))
                else:
                    s['cmd'][m['n']].append((t, msg.x, msg.y, msg.z))
            continue
        parts = topic.strip('/').split('/')
        if len(parts) == 2 and DRONE.match(parts[0]):
            n, k = parts
            if k == 'pose':
                for t, msg in rows:
                    p = msg.pose.position
                    s['est'][n].append((t, p.x, p.y, p.z, _yaw(msg.pose.orientation)))
            elif k == 'downwash':
                for t, msg in rows:
                    s['dw'][n].append((t, *[float(v) for v in msg.values]))
            elif k == 'status':
                for t, msg in rows:
                    s['status'][n].append((t, msg.battery_voltage, msg.rssi,
                                           msg.latency_unicast, msg.num_rx_unicast,
                                           msg.supervisor_info))
    for t, msg in msgs.get('/rosout', []):
        s['rosout'].append((t, msg.level, msg.name, msg.msg))
    for k in ('mocap', 'cmd', 'est', 'status'):
        s[k] = {n: np.array(sorted(v), float) for n, v in s[k].items() if v}
    s['dw'] = {n: np.array(sorted(v), float) for n, v in s['dw'].items()
               if v and len({len(r) for r in v}) == 1}
    return s


# ------------------------------------------------------------------ metrics
def _interp(track, t):
    """Positions of ``track`` (rows t,x,y,z,...) at times ``t``; NaN outside it
    or across a gap longer than 0.25 s."""
    out = np.full((len(t), 3), np.nan)
    if len(track) < 2:
        return out
    tt = track[:, 0]
    for k in range(3):
        out[:, k] = np.interp(t, tt, track[:, k + 1], left=np.nan, right=np.nan)
    i = np.clip(np.searchsorted(tt, t), 1, len(tt) - 1)
    out[(tt[i] - tt[i - 1]) > 0.25] = np.nan
    return out


def _stats(x):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if not len(x):
        return None
    return {'mean': float(np.mean(x)), 'p95': float(np.percentile(x, 95)),
            'max': float(np.max(x))}


def _gaps(t, stall=0.15, brk=2.0):
    """(count of gaps in (stall, brk), longest such gap): a stream's stalls,
    not the deliberate breaks between streaming segments."""
    if len(t) < 2:
        return 0, 0.0
    d = np.diff(t)
    g = d[(d > stall) & (d < brk)]
    return int(len(g)), float(g.max()) if len(g) else 0.0


def tracking(cmd, mocap):
    t = cmd[:, 0]
    meas = _interp(mocap, t)
    err = np.linalg.norm(meas - cmd[:, 1:4], axis=1)
    ok = np.isfinite(err)
    if ok.sum() < 5:
        return None
    hz = np.linalg.norm((meas - cmd[:, 1:4])[:, :2], axis=1)
    vz = np.abs((meas - cmd[:, 1:4])[:, 2])
    # the lag: the shift that best lines the aircraft up with its commands
    best = (np.nanmean(err), 0.0)
    for lag in np.arange(0.02, 0.62, 0.02):
        e = np.linalg.norm(_interp(mocap, t + lag) - cmd[:, 1:4], axis=1)
        if np.isfinite(e).sum() > 0.8 * ok.sum():
            m = float(np.nanmean(e))
            if m < best[0]:
                best = (m, float(lag))
    resid = np.linalg.norm(_interp(mocap, t + best[1]) - cmd[:, 1:4], axis=1)
    worst = int(np.nanargmax(err))
    return {'error': _stats(err), 'horizontal': _stats(hz), 'vertical': _stats(vz),
            'lag_s': best[1], 'residual': _stats(resid),
            'worst_at': float(t[worst] - 0.0), 'samples': int(ok.sum())}


def mocap_health(track, jump_m=0.30, v_max=1.2):
    t = track[:, 0]
    if len(t) < 2:
        return {'frames': int(len(t))}
    d = np.diff(t)
    step = np.linalg.norm(np.diff(track[:, 1:4], axis=0), axis=1)
    allow = jump_m + v_max * np.maximum(0.0, d - 0.02)
    return {'frames': int(len(t)), 'hz': float(1.0 / np.median(d)),
            'dropouts': int(np.sum(d > 0.1)), 'longest_gap_s': float(d.max()),
            'jumps': int(np.sum(step > allow)),
            'jump_times': [float(x) for x in t[1:][step > allow][:50]],
            'jump_max_m': float(step[step > allow].max()) if np.any(step > allow) else 0.0}


def estimate_vs_mocap(est, mocap):
    meas = _interp(mocap, est[:, 0])
    err = np.linalg.norm(meas - est[:, 1:4], axis=1)
    ym = np.interp(est[:, 0], mocap[:, 0], np.unwrap(mocap[:, 4]))
    yerr = np.degrees(np.abs(_wrap(ym - est[:, 4])))
    yerr[~np.isfinite(err)] = np.nan
    return {'position': _stats(err), 'yaw_deg': _stats(yerr)}


def status_summary(st):
    v = st[:, 1]
    sup = st[:, 5].astype(int)
    flags = sorted({w for b, w in SUP_BITS.items() if np.any(sup & b)})
    return {'battery_start': float(v[0]), 'battery_min': float(v.min()),
            'battery_end': float(v[-1]), 'rssi_median': float(np.median(st[:, 2])),
            'rssi_worst': float(st[:, 2].max()),
            'latency_ms_median': float(np.median(st[:, 3])),
            'latency_ms_max': float(st[:, 3].max()),
            'rx_unicast_min': int(st[:, 4].min()), 'flags': flags}


def envelope(track):
    t, p = track[:, 0], track[:, 1:4]
    air = p[:, 2] > 0.15
    if len(t) < 3:
        return {}
    dt = np.diff(t)
    v = np.linalg.norm(np.diff(p, axis=0), axis=1) / np.maximum(dt, 1e-3)
    v = v[(dt > 0.005) & (dt < 0.1)]
    # median of 5 kills single-frame noise before taking the top speed
    if len(v) >= 5:
        v = np.array([np.median(v[i:i + 5]) for i in range(len(v) - 4)])
    return {'airborne_s': float(np.sum(np.diff(t)[air[:-1]])),
            'top_speed': float(v.max()) if len(v) else 0.0,
            'z_min_airborne': float(p[air, 2].min()) if air.any() else None,
            'z_max': float(p[:, 2].max())}


def pairs(mocap, cmd, drones, close=0.5):
    """Closest measured pair overall and every pair that came inside ``close``."""
    if len(drones) < 2:
        return {}, []
    t0 = max(mocap[n][0, 0] for n in drones)
    t1 = min(mocap[n][-1, 0] for n in drones)
    if t1 <= t0:
        return {}, []
    t = np.arange(t0, t1, 0.02)
    P = {n: _interp(mocap[n], t) for n in drones}
    C = {n: _interp(cmd[n], t) if n in cmd else np.full((len(t), 3), np.nan)
         for n in drones}
    best, near = {}, []
    for i, a in enumerate(drones):
        for b in drones[i + 1:]:
            d = np.linalg.norm(P[a] - P[b], axis=1)
            air = (P[a][:, 2] > 0.3) & (P[b][:, 2] > 0.3)
            d = np.where(air, d, np.nan)
            if not np.isfinite(d).any():
                continue
            k = int(np.nanargmin(d))
            row = {'pair': f'{a}/{b}', 'gap': float(d[k]), 't': float(t[k]),
                   'dz': float(P[a][k, 2] - P[b][k, 2]),
                   'cmd_gap': float(np.linalg.norm(C[a][k] - C[b][k]))}
            if not best or row['gap'] < best['gap']:
                best = row
            if row['gap'] < close:
                near.append(row)
    return best, sorted(near, key=lambda r: r['gap'])


def closest_to_others(mocap, drones):
    """The closest any drone came to a rigid body that is not a drone (the DJI)."""
    others = [n for n in mocap if n not in drones]
    out = {}
    for o in others:
        to = mocap[o]
        best = None
        for n in drones:
            p = _interp(to, mocap[n][:, 0])
            d = np.linalg.norm(p - mocap[n][:, 1:4], axis=1)
            d[mocap[n][:, 3] < 0.3] = np.nan
            if np.isfinite(d).any():
                k = int(np.nanargmin(d))
                if best is None or d[k] < best['gap']:
                    best = {'drone': n, 'gap': float(d[k]), 't': float(mocap[n][k, 0])}
        if best:
            out[o] = best
    return out


def dw_vars(folder):
    """The downwash block's variable order, from the flight's config copy."""
    p = os.path.join(folder, 'config', 'crazyflies.yaml')
    try:
        import yaml
        with open(p, encoding='utf-8') as fh:
            doc = yaml.safe_load(fh) or {}
        v = doc['all']['firmware_logging']['custom_topics']['downwash']['vars']
        return [str(x) for x in v]
    except Exception:                                   # noqa: BLE001
        return list(DW_VARS)


def _col(dw, names, var):
    return dw[:, 1 + names.index(var)] if var in names else None


def effort(dw, names):
    """How hard a drone worked over the whole flight (the downwash block)."""
    motors = [c for c in (_col(dw, names, f'motor.m{i}') for i in range(1, 5)) if c is not None]
    roll, pitch = _col(dw, names, 'stabilizer.roll'), _col(dw, names, 'stabilizer.pitch')
    thrust = _col(dw, names, 'stabilizer.thrust')
    out = {'samples': int(len(dw))}
    if motors:
        m = np.max(np.stack(motors), axis=0) / PWM_FULL
        out['motor_max_pct'] = float(100.0 * m.max())
        out['saturated_s'] = float(np.sum(m > 0.95) * np.median(np.diff(dw[:, 0]))
                                   if len(dw) > 1 else 0.0)
    if roll is not None and pitch is not None:
        out['tilt_max_deg'] = float(np.max(np.hypot(roll, pitch)))
    if thrust is not None:
        busy = thrust[thrust > 1000.0]                  # airborne
        out['thrust_median'] = float(np.median(busy)) if len(busy) else 0.0
    return out


def _intervals(mask, t, min_s=0.1):
    """[(t_start, t_end)] of runs of True lasting at least ``min_s``."""
    out, start = [], None
    for k, m in enumerate(mask):
        if m and start is None:
            start = k
        if (not m or k == len(mask) - 1) and start is not None:
            end = k if m else k - 1
            if t[end] - t[start] >= min_s:
                out.append((float(t[start]), float(t[end])))
            start = None
    return out


def downwash(mocap, cmd, dw, names, drones):
    """(events, overflights that did nothing): see the module docstring."""
    events, harmless = [], 0
    others = [n for n in mocap if n not in drones and not DRONE.match(n)]
    for v in drones:
        mv = mocap[v]
        t = np.arange(mv[0, 0], mv[-1, 0], 0.02)
        pv = _interp(mv, t)
        # how far this drone usually sits below its command (its own trailing)
        if v in cmd:
            cz = _interp(cmd[v][:, :4], t)[:, 2]
            verr = pv[:, 2] - cz
            usual = float(np.nanmedian(verr)) if np.isfinite(verr).any() else 0.0
        else:
            verr, usual = None, 0.0
        for c in [d for d in drones if d != v] + others:
            pc = _interp(mocap[c], t)
            big = c in others
            r, top = (DW_RADIUS_BIG, DW_DZ_BIG) if big else (DW_RADIUS, DW_DZ)
            h = np.linalg.norm(pc[:, :2] - pv[:, :2], axis=1)
            dz = pc[:, 2] - pv[:, 2]
            under = (h < r) & (dz > 0.05) & (dz < top) & (pv[:, 2] > 0.2) & (pc[:, 2] > 0.3)
            under &= np.isfinite(h) & np.isfinite(dz)
            for t0, t1 in _intervals(under, t):
                win = (t >= t0) & (t <= t1 + 0.3)        # it may sink just after
                if verr is not None and np.isfinite(verr[win]).any():
                    sink = usual - float(np.nanmin(verr[win]))
                else:
                    z0 = pv[np.searchsorted(t, t0), 2]
                    sink = float(z0 - np.nanmin(pv[win, 2]))
                if sink < DW_SINK:
                    harmless += 1
                    continue
                k = (t >= t0) & (t <= t1)
                ev = {'victim': v, 'above': c, 't': t0, 'duration': t1 - t0,
                      'across': float(np.nanmin(h[k])), 'dz': float(np.nanmedian(dz[k])),
                      'sink': sink}
                if v in dw:
                    d = dw[v]
                    w = (d[:, 0] >= t0 - 0.2) & (d[:, 0] <= t1 + 0.5)
                    if w.any():
                        e = effort(d[w], names)
                        base = effort(d, names).get('thrust_median') or 0.0
                        thr = _col(d[w], names, 'stabilizer.thrust')
                        accz = _col(d[w], names, 'acc.z')
                        ev.update({k2: e[k2] for k2 in ('motor_max_pct', 'tilt_max_deg')
                                   if k2 in e})
                        if thr is not None and base > 0:
                            ev['thrust_up_pct'] = float(100.0 * (thr.max() / base - 1.0))
                        if accz is not None:
                            ev['acc_z_min_g'] = float(accz.min())
                events.append(ev)
    return sorted(events, key=lambda e: e['t']), harmless


def build(folder, close=0.5):
    bagdir = os.path.join(folder, 'bag')
    meta = {}
    if os.path.exists(os.path.join(folder, 'meta.json')):
        with open(os.path.join(folder, 'meta.json'), encoding='utf-8') as fh:
            meta = json.load(fh)
    rep = {'folder': folder, 'meta': meta, 'drones': {}, 'fleet': {}}
    s = series(read_bag(bagdir)) if os.path.isdir(bagdir) else series({})
    # times are reported from the first mocap frame; with no mocap (the
    # simulator), from the first command, else from the start of the run
    firsts = [c[0, 0] for c in s['cmd'].values()]
    t_ref = (s['frames'][0][0] if s['frames']
             else min(firsts) if firsts else float(meta.get('started', 0.0)))
    rep['t_ref'] = t_ref
    names = dw_vars(folder)
    drones = sorted({n for n in list(s['mocap']) + list(s['cmd']) + list(s['status'])
                     if DRONE.match(n)}, key=lambda n: int(n[2:]))
    for n in drones:
        r = {}
        mc = s['mocap'].get(n)
        if mc is not None:
            r['mocap'] = mocap_health(mc)
            r['envelope'] = envelope(mc)
        if n in s['cmd']:
            c = s['cmd'][n]
            stalls, longest = _gaps(c[:, 0])
            r['commands'] = {'count': int(len(c)),
                             'hz': float(1.0 / np.median(np.diff(c[:, 0])))
                             if len(c) > 1 else 0.0,
                             'stalls': stalls, 'longest_stall_s': longest}
            if mc is not None:
                tr = tracking(c, mc)
                if tr:
                    tr['worst_at'] -= t_ref
                    r['tracking'] = tr
        if n in s['est'] and mc is not None:
            r['estimate'] = estimate_vs_mocap(s['est'][n], mc)
        if n in s['status']:
            r['status'] = status_summary(s['status'][n])
        if n in s['dw']:
            r['effort'] = effort(s['dw'][n], names)
        rep['drones'][n] = r
    flying = [n for n in drones if n in s['mocap'] and
              rep['drones'][n].get('envelope', {}).get('airborne_s', 0.0) > 0.5]
    best, near = pairs(s['mocap'], s['cmd'], flying, close)
    for row in {id(r): r for r in [best] + near if r}.values():   # best is in near too
        row['t'] -= t_ref
    # a close pass within 0.15 s of a mocap jump on either drone is most
    # likely a glitch (a swapped or ghost rigid body), not two aircraft
    for row in {id(r): r for r in [best] + near if r}.values():
        jt = [x - t_ref for n in row['pair'].split('/')
              for x in rep['drones'][n].get('mocap', {}).get('jump_times', [])]
        row['mocap_jump_nearby'] = any(abs(x - row['t']) < 0.15 for x in jt)
    rep['fleet']['closest_pair'] = best
    rep['fleet']['close_pairs'] = near
    ev, harmless = downwash(s['mocap'], s['cmd'], s['dw'], names, flying)
    for e in ev:
        e['t'] -= t_ref
    rep['fleet']['downwash'] = {'events': ev, 'overflights_without_effect': harmless,
                                'logged': sorted(s['dw'])}
    rep['fleet']['closest_to_other_bodies'] = {
        k: {**v, 't': v['t'] - t_ref}
        for k, v in closest_to_others(s['mocap'], flying).items()}
    rep['fleet']['mocap_hz'] = (float(1.0 / np.median(np.diff([f[0] for f in s['frames']])))
                                if len(s['frames']) > 2 else 0.0)
    warn = [(t - t_ref, lvl, name, msg) for t, lvl, name, msg in s['rosout'] if lvl >= 30]
    cmds = [(t - t_ref, name, msg) for t, lvl, name, msg in s['rosout']
            if name.endswith('crazyflie_server') and msg.startswith('[')
            and re.search(r'takeoff|land|emergency|arm|go_to|start_trajectory', msg)]
    counts = defaultdict(int)
    for _, lvl, name, msg in warn:
        counts[(lvl, name, re.sub(r'[\d.]+', '#', msg)[:90])] += 1
    rep['fleet']['server_commands'] = [{'t': t, 'msg': m} for t, _, m in cmds][:200]
    rep['fleet']['warnings'] = [{'level': k[0], 'node': k[1], 'msg': k[2], 'count': c}
                                for k, c in sorted(counts.items(), key=lambda kv: -kv[1])]
    alarms = []
    out = os.path.join(folder, 'output.log')
    if os.path.exists(out):
        with open(out, encoding='utf-8', errors='replace') as fh:
            alarms = [ln.rstrip() for ln in fh if SHOW_ALARMS.search(ln)]
    rep['fleet']['show_alarms'] = alarms[:200]
    return rep


# ------------------------------------------------------------------ text
def _f(x, unit='', nd=2):
    return '--' if x is None else f'{x:.{nd}f}{unit}'


def text(rep):
    L = []
    m = rep['meta']
    L.append(f'FLIGHT REPORT  {rep["folder"]}')
    if m:
        L.append(f'  ran       {m.get("cmdline", "")}')
        L.append(f'  started   {m.get("started_iso", "")}   ended {m.get("ended_iso", "")}   '
                 f'exit {m.get("returncode")}   ({m.get("state", "")})')
        L.append(f'  code      {m.get("git", {}).get("head", "")}'
                 f'{" + uncommitted changes" if m.get("git", {}).get("dirty") else ""}'
                 f'   ROS_DOMAIN_ID {m.get("ros_domain_id", "")}')
    f = rep['fleet']
    L.append(f'  mocap     {f.get("mocap_hz", 0):.0f} Hz'
             + ('   (none: nothing published /poses, so no tracking, mocap or separation '
                'figures)' if not f.get('mocap_hz') else ''))
    if m.get('sim'):
        L.append('  SIMULATED (use_sim_time): rates and stalls are in wall-clock time, so they '
                 'reflect how fast the simulator ran, not the radio')
    L.append('')
    L.append('PER DRONE                     (times are s after the first mocap frame)')
    hdr = (f'  {"drone":6s} {"air s":>6s} {"vmax":>5s}  {"track err mean/p95/max m":>25s} '
           f'{"lag s":>5s} {"resid p95":>9s}  {"cmd Hz":>6s} {"stalls":>6s}  '
           f'{"mocap Hz":>8s} {"drops":>5s} {"jumps":>5s}  {"est yaw p95":>11s}  '
           f'{"batt V start>min>end":>20s} {"lat ms":>6s} {"motor%":>6s} {"tilt":>5s}  flags')
    L.append(hdr)
    for n, r in rep['drones'].items():
        tr, cm = r.get('tracking', {}), r.get('commands', {})
        mo, en = r.get('mocap', {}), r.get('envelope', {})
        es, st = r.get('estimate', {}), r.get('status', {})
        ef = r.get('effort', {})
        e = tr.get('error') or {}
        res = tr.get('residual') or {}
        yaw = (es.get('yaw_deg') or {}).get('p95')
        batt = (f'{st["battery_start"]:.2f}>{st["battery_min"]:.2f}>{st["battery_end"]:.2f}'
                if st else '--')
        L.append(f'  {n:6s} {_f(en.get("airborne_s"), "", 0):>6s} {_f(en.get("top_speed")):>5s}  '
                 f'{(_f(e.get("mean")) + "/" + _f(e.get("p95")) + "/" + _f(e.get("max"))) if e else "--":>25s} '
                 f'{_f(tr.get("lag_s")) if tr else "--":>5s} {_f(res.get("p95")) if res else "--":>9s}  '
                 f'{_f(cm.get("hz"), "", 0) if cm else "--":>6s} '
                 f'{str(cm.get("stalls", "--")):>6s}  {_f(mo.get("hz"), "", 0):>8s} '
                 f'{str(mo.get("dropouts", "--")):>5s} {str(mo.get("jumps", "--")):>5s}  '
                 f'{_f(yaw, " deg", 1):>11s}  {batt:>20s} '
                 f'{_f(st.get("latency_ms_max"), "", 0) if st else "--":>6s} '
                 f'{_f(ef.get("motor_max_pct"), "", 0):>6s} {_f(ef.get("tilt_max_deg"), "", 0):>5s}  '
                 f'{",".join(st.get("flags", [])) if st else ""}'
                 f'{" SATURATED %.1fs" % ef["saturated_s"] if ef.get("saturated_s") else ""}')
    L.append('')
    L.append('  track err: commanded position vs mocap at the same instant; lag: the delay '
             'that best lines them up;')
    L.append('  resid: the error left once that lag is taken out (a drone that follows, '
             'only late, has a small one).')
    worst = [(n, r['tracking']) for n, r in rep['drones'].items() if r.get('tracking')]
    if worst:
        n, tr = max(worst, key=lambda x: x[1]['error']['max'])
        L.append(f'  largest tracking error: {n} {tr["error"]["max"]:.2f} m at t+{tr["worst_at"]:.1f}s')
    L.append('')
    L.append('SEPARATION')
    cp = f.get('closest_pair') or {}
    if cp:
        L.append(f'  closest pair  {cp["pair"]} {cp["gap"]:.2f} m apart (dz {cp["dz"]:+.2f}) '
                 f'at t+{cp["t"]:.1f}s; their commands were {cp["cmd_gap"]:.2f} m apart')
    for r in f.get('close_pairs', [])[:12]:
        why = ('MOCAP GLITCH (a pose jumped at that moment)' if r.get('mocap_jump_nearby')
               else 'the plan put them there' if r['cmd_gap'] < r['gap'] + 0.10
               else 'the aircraft lagged their commands')
        L.append(f'    {r["pair"]:10s} {r["gap"]:.2f} m (dz {r["dz"]:+.2f}) at t+{r["t"]:.1f}s, '
                 f'commands {r["cmd_gap"]:.2f} m apart -- {why}')
    for body, r in f.get('closest_to_other_bodies', {}).items():
        L.append(f'  to {body:10s} closest {r["drone"]} {r["gap"]:.2f} m at t+{r["t"]:.1f}s')
    dwn = f.get('downwash') or {}
    L.append('')
    L.append('DOWNWASH  (a drone that sank while another, or the DJI, was above it)')
    if not dwn.get('logged'):
        L.append('  (no downwash log block in this flight: events from mocap only, no effort figures)')
    for e in dwn.get('events', [])[:30]:
        extra = ', '.join(x for x in (
            f'thrust +{e["thrust_up_pct"]:.0f}%' if 'thrust_up_pct' in e else '',
            f'motors {e["motor_max_pct"]:.0f}%' if 'motor_max_pct' in e else '',
            f'tilt {e["tilt_max_deg"]:.0f} deg' if 'tilt_max_deg' in e else '',
            f'acc.z down to {e["acc_z_min_g"]:.2f} g' if 'acc_z_min_g' in e else '') if x)
        L.append(f'  t+{e["t"]:6.1f}s  {e["victim"]} under {e["above"]} for {e["duration"]:.1f} s: '
                 f'{e["across"]:.2f} m across, {e["dz"]:.2f} m below it; sank {e["sink"]:.2f} m'
                 f'{" (" + extra + ")" if extra else ""}')
    if not dwn.get('events'):
        L.append('  none')
    if dwn.get('overflights_without_effect'):
        L.append(f'  {dwn["overflights_without_effect"]} more overflight(s) with no measurable sink')
    if f.get('show_alarms'):
        L.append('')
        L.append('WHAT THE SHOW SAID (alarm lines from output.log)')
        L += [f'  {a}' for a in f['show_alarms'][:60]]
    if f.get('warnings'):
        L.append('')
        L.append('ROSOUT WARNINGS / ERRORS (grouped; numbers replaced by #)')
        for w in f['warnings'][:25]:
            L.append(f'  {w["count"]:5d}x  [{w["node"]}] {w["msg"]}')
    if f.get('server_commands'):
        L.append('')
        L.append('SERVER COMMANDS')
        for c in f['server_commands'][:40]:
            L.append(f'  t+{c["t"]:6.1f}s  {c["msg"]}')
    return '\n'.join(L) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('folder', help='a flight folder (with bag/, output.log, meta.json)')
    ap.add_argument('--close', type=float, default=0.5,
                    help='list every pair that came closer than this, m')
    ap.add_argument('--json', action='store_true', help='also print report.json')
    a = ap.parse_args(argv)
    folder = os.path.abspath(os.path.expanduser(a.folder))
    if not os.path.isdir(folder):
        raise SystemExit(f'no such folder: {folder}')
    rep = build(folder, a.close)
    txt = text(rep)
    with open(os.path.join(folder, 'report.txt'), 'w', encoding='utf-8') as fh:
        fh.write(txt)
    with open(os.path.join(folder, 'report.json'), 'w', encoding='utf-8') as fh:
        json.dump(rep, fh, indent=1, default=float)
    print(txt)
    if a.json:
        print(json.dumps(rep, indent=1, default=float))
    print(f'wrote {os.path.join(folder, "report.txt")} and report.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
