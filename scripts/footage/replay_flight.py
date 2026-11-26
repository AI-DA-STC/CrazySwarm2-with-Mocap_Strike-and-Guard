#!/usr/bin/env python3
"""Rebuild a hardware guard_show flight's console view from its flight-log folder.

    scripts/footage/replay_flight.py ~/.ros/flight_logs/<stamp>_guard_show <out bag dir>

The flight bag has /poses but not /guard/markers (left out on purpose, ~1.5 MB/s;
docs/rig/flight-logs.md). This re-runs the same Match (seed, rules,
strategies from meta.json) on the LOGGED measured positions and the VIP's logged
/poses, checks it against guard_trace.csv (setpoints, intents, events), and writes
a bag of /poses (copied) + /guard/markers (made by guard/viz.py, exactly as
guard_show draws them) that the console's 3D view plays back:

    scripts/footage/rig.sh up                 # private domain, kiosk console (docs/guard/details/footage.md)
    ros2 bag play <out bag dir> --rate 0.5    # and film it, as film.sh does

The match is re-run with each tick's setpoints locked to the logged ones (what was
flown), so the picture cannot drift; the printed agreement (events, intents) is the
check that the re-run decided what the flight decided. Needs the workspace sourced.
"""
import argparse
import json
import sys
from collections import OrderedDict

import numpy as np
import rclpy.serialization as ser
import rosbag2_py
import yaml
from builtin_interfaces.msg import Time
from motion_capture_tracking_interfaces.msg import NamedPoseArray

from crazyflie_shows import escort
from crazyflie_shows.guard import finale as finale_mod
from crazyflie_shows.guard import policies
from crazyflie_shows.guard import rules as rule_sets
from crazyflie_shows.guard.config import GuardConfig
from crazyflie_shows.guard.engine import Match
from crazyflie_shows.guard.viz import GuardViz
from crazyflie_shows.guard.world import ATTACK, DEFENSE


def params_of(meta):
    P, argv = {}, meta['argv']
    for i, a in enumerate(argv):
        if a == '-p' and i + 1 < len(argv) and ':=' in argv[i + 1]:
            k, v = argv[i + 1].split(':=', 1)
            P[k] = v
    return P


def load_trace(path):
    """[(t, phase, {name: row})], one entry per tick."""
    ticks = []
    for line in open(path).read().splitlines()[1:]:
        t, ph, n, team, st, mx, my, mz, sx, sy, sz, it = line.split(',')
        m = None if mx == '' else np.array([float(mx), float(my), float(mz)])
        row = dict(team=team, status=st, m=m, sp=np.array([float(sx), float(sy), float(sz)]),
                   intent=it)
        if not ticks or ticks[-1][0] != float(t) or ticks[-1][1] != ph or n in ticks[-1][2]:
            ticks.append((float(t), ph, OrderedDict()))
        ticks[-1][2][n] = row
    return ticks


def load_poses(bag):
    rd = rosbag2_py.SequentialReader()
    rd.open(rosbag2_py.StorageOptions(uri=bag, storage_id='mcap'), rosbag2_py.ConverterOptions('', ''))
    rd.set_filter(rosbag2_py.StorageFilter(topics=['/poses']))
    raw, track = [], {}
    while rd.has_next():
        _, data, tns = rd.read_next()
        raw.append((tns, data))
        for p in ser.deserialize_message(data, NamedPoseArray).poses:
            q = p.pose.position
            track.setdefault(p.name, []).append((tns * 1e-9, q.x, q.y, q.z))
    return raw, {k: np.array(v) for k, v in track.items()}


class _Clock:
    t = 0.0

    def now(self):
        return self

    def to_msg(self):
        s = int(self.t)
        return Time(sec=s, nanosec=int((self.t - s) * 1e9))


class _Capture:
    """Stands in for the rclpy node GuardViz publishes through: keeps every
    MarkerArray with the flight time it belongs to."""

    def __init__(self):
        self.clock, self.out = _Clock(), []

    def create_publisher(self, *a):
        return self

    def publish(self, msg):
        self.out.append((self.clock.t, msg))

    def get_clock(self):
        return self.clock

    def get_logger(self):
        return self

    def warn(self, *a, **k):
        print('viz warning:', *a)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('flight', help='a guard_show flight-log folder')
    ap.add_argument('out', help='bag directory to write (must not exist)')
    ap.add_argument('--free', action='store_true',
                    help='do not lock the setpoints to the log (a pure re-run; drifts)')
    a = ap.parse_args()

    meta = json.load(open(f'{a.flight}/meta.json'))
    P = params_of(meta)
    D, A = P['defenders'].split(','), P['attackers'].split(',')
    seed, vip_name = int(P.get('seed', 0)), P.get('vip_name', 'operator')
    ticks = load_trace(f'{a.flight}/guard_trace.csv')
    names = list(ticks[0][2])
    i_match = next(i for i, k in enumerate(ticks) if k[1] == 'match')
    raw, track = load_poses(f'{a.flight}/bag')
    if vip_name not in track:
        sys.exit(f'{vip_name!r} is not on /poses (vip_mode point/manual is not supported here)')

    def at(name, t):
        p = track[name]
        return np.array([np.interp(t, p[:, 0], p[:, c]) for c in (1, 2, 3)])

    def fit_offset(seg):
        """Wall time of the segment's t=0: the measured positions in the trace
        against /poses (the trace clock restarts at MATCH LIVE)."""
        def err(off):
            e = [np.linalg.norm(at(n, t + off) - r['m']) for t, _, rows in seg[::5]
                 for n, r in rows.items() if r['m'] is not None and n in track]
            return np.mean(e)
        b0, b1 = raw[0][0] * 1e-9, raw[-1][0] * 1e-9
        best = min(np.arange(b0 - 5, b1, 0.25), key=err)
        best = min(np.arange(best - 0.3, best + 0.3, 0.005), key=err)
        return best, err(best)

    off_pre, e_pre = fit_offset(ticks[:i_match])
    off_post, e_post = fit_offset(ticks[i_match:])
    print(f'{len(ticks)} ticks; trace clock fitted to /poses: before START {e_pre * 100:.2f} cm, '
          f'match and after {e_post * 100:.2f} cm')
    abs_t = [k[0] + (off_pre if i < i_match else off_post) for i, k in enumerate(ticks)]

    cfg = GuardConfig()
    sb = float(P.get('strike_block', 0))
    rules = rule_sets.make(P.get('rules', 'tag'), {'strike_block': sb} if sb > 0 else {})
    dname, aname = P.get('defense', 'shell'), P.get('attack', 'coordinated')
    title = f'{dname} v {aname} | {rules.name}'
    cap = _Capture()
    viz = GuardViz(cap, trail=20, bodies=False)

    # before START: the drones as logged, the picture guard_show drew at the gates
    pre = Match(cfg, rules, policies.make(DEFENSE, dname, {}), policies.make(ATTACK, aname, {}),
                {n: r['sp'] for n, r in ticks[0][2].items()}, D, A, at(vip_name, abs_t[0]),
                np.random.default_rng(seed))
    for i in range(0, i_match, 2):                      # markers at 10 Hz, as guard_show
        _, ph, rows = ticks[i]
        cap.clock.t = abs_t[i]
        for n, r in rows.items():
            pre.agents[n].p = r['m'] if r['m'] is not None else r['sp']
        viz.publish(pre.t, cfg, rules, at(vip_name, abs_t[i]), pre.agents, {}, pre.result(),
                    f'{title} | {"FORM-UP" if ph == "form-up" else "HOLDING"}', pre.referee.meters)

    # the match: re-run from the formation the match was rebuilt from at START
    vel, prev = escort.VelocityEstimator(), None
    for i in range(i_match):                            # guard_show's estimator ran through the gates
        vel.update(at(vip_name, abs_t[i]), 0.05 if prev is None else abs_t[i] - prev)
        prev = abs_t[i]
    t_start = abs_t[i_match] - ticks[i_match][0]
    match = Match(cfg, rules, policies.make(DEFENSE, dname, {}), policies.make(ATTACK, aname, {}),
                  {n: r['sp'] for n, r in ticks[i_match - 1][2].items()}, D, A,
                  at(vip_name, t_start), np.random.default_rng(seed))
    viz.clear()
    dev, agree, total, events, tprev, res, i = 0.0, 0, 0, [], 0.0, None, i_match
    while i < len(ticks) and ticks[i][1] == 'match':
        t, _, rows = ticks[i]
        dt, tprev = max(t - tprev, 1e-3), t
        p = at(vip_name, abs_t[i])
        tk = match.step(dt, p, vel.update(p, dt),
                        {n: r['m'] for n, r in rows.items() if r['m'] is not None})
        for n, r in rows.items():
            dev = max(dev, float(np.linalg.norm(match.sp[n] - r['sp'])))
            k = tk.intents.get(n)
            total += 1
            agree += (k.kind if k is not None else '') == r['intent']
            if not a.free:
                match.sp[n] = r['sp'].copy()
        res = match.result()
        for n in tk.retired:
            if res.winner == ATTACK and match.agents[n].outcome == 'struck':
                match.reinstate(n, match.sp[n])
        events += [f't+{match.t:5.1f}s {e}' for e in tk.events]
        cap.clock.t = abs_t[i]
        if (i - i_match) % 2 == 0 or res.winner:
            viz.publish(match.t, cfg, rules, p, match.agents, tk.labels, res, title,
                        match.referee.meters, tk.intents, tk.plans, match.corrected, tk.events)
        i += 1
        if res.winner:
            break
    print(f'match re-run: intents agree {agree}/{total}' +
          ('' if not a.free else f', max setpoint drift {dev * 100:.1f} cm'))
    print('events (compare with output.log):', *events, sep='\n  ')
    if res is not None:
        print(f'result: {res.winner} -- {res.reason} (t+{res.t:.1f}s)')

    # the finale: positions as logged, the finale's own picture
    if res is not None and res.winner and i < len(ticks):
        fleet = yaml.safe_load(open(f'{a.flight}/config/crazyflies.yaml'))['robots']
        marks = {n: np.array(fleet[n]['initial_position'], float) for n in names}
        fin = finale_mod.Finale(cfg, res.winner, match.agents, marks, at(vip_name, abs_t[i]),
                                ticks[i][0], {})
        while i < len(ticks) and ticks[i][1].startswith('finale'):
            t, _, rows = ticks[i]
            for n, r in rows.items():
                match.agents[n].p = r['m'] if r['m'] is not None else r['sp']
            fs = fin.update(t, at(vip_name, abs_t[i]), match.agents)
            for n in fs.land:
                match.retire(n)
            cap.clock.t = abs_t[i]
            if i % 2 == 0 or fs.done:
                viz.publish(match.t, cfg, rules, at(vip_name, abs_t[i]), match.agents,
                            {n: fs.phase for n in fs.goals}, res, f'{title} | FINALE {fs.phase}',
                            match.referee.meters, corrected=match.corrected, banner=fs.banner)
            i += 1

    wr = rosbag2_py.SequentialWriter()
    wr.open(rosbag2_py.StorageOptions(uri=a.out, storage_id='mcap'),
            rosbag2_py.ConverterOptions('cdr', 'cdr'))
    wr.create_topic(rosbag2_py.TopicMetadata(
        0, '/poses', 'motion_capture_tracking_interfaces/msg/NamedPoseArray', 'cdr'))
    wr.create_topic(rosbag2_py.TopicMetadata(1, '/guard/markers', 'visualization_msgs/msg/MarkerArray', 'cdr'))
    t_lo, t_hi = abs_t[0] - 2.0, abs_t[-1] + 2.0
    msgs = [(tns, '/poses', d) for tns, d in raw if t_lo <= tns * 1e-9 <= t_hi]
    msgs += [(int(t * 1e9), '/guard/markers', ser.serialize_message(m)) for t, m in cap.out]
    for tns, topic, d in sorted(msgs, key=lambda x: x[0]):
        wr.write(topic, d, tns)
    del wr
    print(f'wrote {a.out}: {len(cap.out)} marker arrays over {t_hi - t_lo:.1f} s; '
          f'MATCH LIVE at bag +{t_start - t_lo:.1f} s')


if __name__ == '__main__':
    main()
