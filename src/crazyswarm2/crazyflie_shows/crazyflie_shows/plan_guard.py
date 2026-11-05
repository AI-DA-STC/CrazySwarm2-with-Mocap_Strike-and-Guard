#!/usr/bin/env python3
"""Check the guard show offline -- and compare strategies -- with no drones.

    ros2 run crazyflie_shows plan_guard                      # 4 v 3, defaults
    ros2 run crazyflie_shows plan_guard --defenders cf1,cf2,cf3,cf4 \
        --attackers cf10,cf11,cf12             # YOUR drones, at their roster marks
    ros2 run crazyflie_shows plan_guard --defenders cf1,cf2 --attackers cf10 --live
                                               # ...at where mocap sees them NOW
    ros2 run crazyflie_shows plan_guard --defenders 3 --attackers 2 --seeds 30
    ros2 run crazyflie_shows plan_guard --defense ring --attack direct
    ros2 run crazyflie_shows plan_guard --matrix             # every pairing
    ros2 run crazyflie_shows plan_guard --marks              # where to stand them
    ros2 run crazyflie_shows plan_guard --rules pressure --rparam reach=1.4
    ros2 run crazyflie_shows plan_guard --matrix --rules all  # x every rule set
    ros2 run crazyflie_shows plan_guard --set v_max_attack=1.2 --set ceiling=4.0
    ros2 run crazyflie_shows plan_guard --policy-module my_lab.strategies --attack mine

Runs whole matches through the SAME engine guard_show flies
(crazyflie_shows.guard.engine), against a stand-in for the aircraft: each
drone follows its setpoint with a first-order lag (``--tau``, 0.25 s), and a
retiring one descends at the land speed. The stand-in is not a measured
model; it exists so that "the setpoints were safe" and "the aircraft were
safe" are checked separately, which is the difference that matters.

Two verdicts, kept apart on purpose:

* **SAFETY** -- over every seed: no two airborne aircraft closer than
  the guard's hard floor (an ellipsoid: min_separation across,
  min_separation_z vertically), nobody closer to the VIP than its keep-out, nobody outside
  the room or the band, the solver never in emergency, the backstop clamp
  never needed. Any failure exits 1: this is the gate before flying.
* **GAME** -- who won, how, how fast. Information, not a gate: a strategy that
  always loses is a fine thing to have measured.
"""

import argparse
import ast
import sys
import time

import numpy as np

from crazyflie_shows import escort, safety
from crazyflie_shows.guard import policies, safety_layer
from crazyflie_shows.guard import rules as rule_sets
from crazyflie_shows.guard.config import GuardConfig, override, problems
from crazyflie_shows.guard.engine import Match
from crazyflie_shows.guard.world import ATTACK, DEFENSE, RETIRING

#: Where the attack comes from, as a bearing about the VIP: the far side from
#: the operator (who stands on +x looking down -x), the escort's encounter
#: geometry (escort.ReactiveAdversary.bearing).
ATTACK_BEARING_DEG = escort.ReactiveAdversary().bearing
DEFENDER_MARK_R = 1.8      # m from the VIP, on the floor
ATTACKER_MARK_R = 4.4      # m from the VIP, on the floor
VIP_Z = 1.3                # m: a point VIP hovers where the DJI would


def vip_mark(cfg):
    """The VIP's default spot: the escort's mark, at DJI hover height."""
    v = escort.vip_home(escort.EscortConfig())
    return np.array([v[0], v[1], VIP_Z])


def recommend_marks(cfg, vip, n_def, n_att):
    """Floor marks: defenders round the VIP, attackers on the far arc."""
    marks = {}
    for i in range(n_def):
        ang = np.radians(ATTACK_BEARING_DEG) + 2.0 * np.pi * i / n_def
        marks[f'D{i + 1}'] = vip[:2] + DEFENDER_MARK_R * np.array([np.cos(ang), np.sin(ang)])
    # attackers spaced 1.3 m apart along the arc, centred on the bearing
    step = 1.3 / ATTACKER_MARK_R
    for j in range(n_att):
        ang = np.radians(ATTACK_BEARING_DEG) + (j - (n_att - 1) / 2.0) * step
        r = ATTACKER_MARK_R
        while r > DEFENDER_MARK_R + 1.0:
            q = vip[:2] + r * np.array([np.cos(ang), np.sin(ang)])
            if float(escort.room_clearance(cfg, q)) >= 0.4:
                break
            r -= 0.1
        marks[f'A{j + 1}'] = q
    return {k: np.array([v[0], v[1], 0.0]) for k, v in marks.items()}


def roster_marks(names):
    """name -> floor mark from crazyflies.yaml (the installed copy)."""
    import yaml
    from crazyflie_shows.plan_show import default_yaml
    with open(default_yaml()) as fh:
        robots = yaml.safe_load(fh)['robots']
    missing = [n for n in names if n not in robots]
    if missing:
        raise SystemExit(f'not in crazyflies.yaml: {missing}')
    off = [n for n in names if not robots[n].get('enabled', False)]
    if off:
        print(f'  NOTE          enabled: false in the roster, so the server will '
              f'not fly them: {", ".join(off)}')
    return {n: np.array(robots[n]['initial_position'], float) for n in names}


def live_marks(names, wait=4.0):
    """name -> where /poses sees it now (floor height ignored)."""
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from motion_capture_tracking_interfaces.msg import NamedPoseArray
    rclpy.init()
    node = rclpy.create_node('plan_guard_marks')
    got = {}

    def cb(msg):
        for p in msg.poses:
            got[p.name] = np.array([p.pose.position.x, p.pose.position.y, 0.0])
    node.create_subscription(NamedPoseArray, '/poses', cb, qos_profile_sensor_data)
    end = time.time() + wait
    while time.time() < end and not all(n in got for n in names):
        rclpy.spin_once(node, timeout_sec=0.1)
    node.destroy_node()
    rclpy.try_shutdown()
    missing = [n for n in names if n not in got]
    if missing:
        raise SystemExit(f'not on /poses: {missing} (is mocap up, on this '
                         'ROS_DOMAIN_ID, with those rigid-body names?)')
    return {n: got[n] for n in names}


def mark_problems(cfg, rules, vip, marks, defenders, attackers):
    """Why these floor marks cannot start a match (empty = fine)."""
    bad = []
    names = list(defenders) + list(attackers)
    starts = {n: np.array([marks[n][0], marks[n][1], cfg.start_height]) for n in names}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            d = float(np.linalg.norm(starts[a] - starts[b]))
            if d < cfg.d_cc:
                bad.append(f'{a} and {b} start {d:.2f} m apart '
                           f'(need {cfg.d_cc:.2f})')
        r = safety_layer.separation_ratio(cfg, starts[a], vip, 'vip')
        if r < 1.05:
            bad.append(f'{a} starts inside the VIP keep-out '
                       f'({float(np.linalg.norm(starts[a][:2] - vip[:2])):.2f} m '
                       'across) -- move it out')
        c = float(escort.room_clearance(cfg, starts[a]))
        if c < 0.2:
            bad.append(f'{a} starts {c:.2f} m from the arena edge')
    for a in attackers:
        near = min(float(np.linalg.norm(starts[a] - starts[d])) for d in defenders) \
            if defenders else np.inf
        if rules.DOWNABLE and near < rules.reach + 0.5:
            bad.append(f'attacker {a} starts {near:.2f} m from a defender -- '
                       'inside reach before the match begins')
    return bad, starts


def _measure(cfg, m, pos, vip, met):
    """Fold this tick's aircraft positions into the safety metrics."""
    air = [n for n in pos if pos[n][2] > 0.3]
    for i, a in enumerate(air):
        for b in air[i + 1:]:
            d = float(np.linalg.norm(pos[a] - pos[b]))
            if d < met['sep']:
                met['sep'], met['sep_pair'] = d, f'{a}/{b}'
            met['floor'] = min(met['floor'], safety_layer.floor_ratio(cfg, pos[a], pos[b]))
        met['vip'] = min(met['vip'], safety_layer.separation_ratio(cfg, pos[a], vip, 'vip'))
        if m.agents[a].active:
            met['room'] = min(met['room'], float(escort.room_clearance(cfg, pos[a])))
            met['z_lo'] = min(met['z_lo'], pos[a][2])
            met['z_hi'] = max(met['z_hi'], pos[a][2])


def _fly_lag(cfg, m, pos, setpoints, dt, tau, met):
    """The stand-in aircraft: first-order lag; retiring ones descend."""
    for n, (sp, _) in setpoints.items():
        before = pos[n].copy()
        pos[n] = pos[n] + (sp - pos[n]) * min(dt / tau, 1.0)
        met['speed'] = max(met['speed'], float(np.linalg.norm(pos[n] - before)) / dt)
    for n, a in m.agents.items():
        if a.status == RETIRING:
            pos[n][2] = max(0.0, pos[n][2] - cfg.land_speed * dt)


def simulate(cfg, rules, dname, aname, starts, defenders, attackers, vip0, seed,
             dparams=None, aparams=None, tau=0.25, vip_move=0.0, record=False,
             on_tick=None, finale=False, fparams=None):
    """One match on the stand-in aircraft. Returns (result, metrics, trace).

    ``on_tick(match, vip, tick, result, banner)`` is called after every tick
    (the --rviz player uses it to draw and to pace the match in real time).
    ``finale``: fly guard.finale after the result, through the same engine,
    measured like the match (``met['finale']`` is the phase it reached).
    """
    rng = np.random.default_rng(seed)
    # Nobody stands a drone exactly on its mark: jitter the starts by a few
    # cm per seed, so seeds differ even before any strategy rolls a die.
    jit = np.random.default_rng(10_000 + seed)
    starts = {n: np.asarray(p, float) + np.r_[jit.normal(0.0, 0.08, 2), 0.0]
              for n, p in starts.items()}
    m = Match(cfg, rules, policies.make(DEFENSE, dname, dparams),
              policies.make(ATTACK, aname, aparams), starts, defenders,
              attackers, vip0, rng)
    pos = {n: np.asarray(p, float).copy() for n, p in starts.items()}
    dt = 1.0 / cfg.rate_hz
    vip = np.asarray(vip0, float).copy()
    met = {'sep': np.inf, 'sep_pair': '', 'floor': np.inf, 'vip': np.inf, 'room': np.inf,
           'z_lo': np.inf, 'z_hi': -np.inf, 'speed': 0.0}
    trace = [] if record else None
    def vip_at(t):
        # an optional drifting VIP: a slow circle, the DJI pilot wandering
        if vip_move <= 0.0:
            return np.asarray(vip0, float).copy(), np.zeros(3)
        w = vip_move / 0.6
        return (np.asarray(vip0, float) + 0.6 * np.array(
                    [np.cos(w * t) - 1.0, np.sin(w * t), 0.0]),
                vip_move * np.array([-np.sin(w * t), np.cos(w * t), 0.0]))

    while True:
        vip, vip_v = vip_at(m.t)
        tk = m.step(dt, vip, vip_v, pos)
        _fly_lag(cfg, m, pos, tk.setpoints, dt, tau, met)
        _measure(cfg, m, pos, vip, met)
        if record:
            trace.append((m.t, vip.copy(), {n: pos[n].copy() for n in pos},
                          dict(tk.labels)))
        res = m.result()
        if on_tick is not None:
            on_tick(m, vip, tk, res, '')
        if res.winner:
            break
    met.update(m.stats)
    met['finale'] = ''
    if not finale:
        return res, met, trace

    # -- the finale, on the same stand-in aircraft and the same metrics
    from crazyflie_shows.guard.engine import Tick
    from crazyflie_shows.guard.finale import Finale
    if res.winner == ATTACK:
        for e in tk.events:
            if e.kind == 'strike' and m.agents[e.who].status == RETIRING:
                m.reinstate(e.who, pos[e.who])
    fin = Finale(cfg, res.winner, m.agents, starts, vip, m.t, fparams)
    t = m.t
    while True:
        t += dt
        vip, vip_v = vip_at(t)
        fs = fin.update(t, vip, m.agents)
        for n in fs.land:
            m.retire(n)
        sp = m.steer(dt, vip, vip_v, fs.goals, fin.p['speed'], pos)
        _fly_lag(cfg, m, pos, sp, dt, tau, met)
        _measure(cfg, m, pos, vip, met)
        if record:
            trace.append((t, vip.copy(), {n: pos[n].copy() for n in pos},
                          {n: fs.phase for n in fs.goals}))
        if on_tick is not None:
            on_tick(m, vip, Tick(sp, fs.land, [], None, [],
                                 {n: fs.phase for n in fs.goals}), res, fs.banner)
        if fs.done or t - m.t > 45.0:
            break
    met['finale'] = fs.phase
    for k in ('emergency', 'backstop', 'not_converged'):
        met[k] = m.stats[k]
    return res, met, trace


def safety_failures(cfg, met):
    bad = []
    if met['floor'] < 1.0:
        bad.append(f'two aircraft got inside the hard floor ({met["floor"]:.2f} '
                   f'of it; closest pair {met["sep_pair"]} at {met["sep"]:.2f} m)')
    if met['vip'] < 0.9:
        bad.append(f'an aircraft got to {met["vip"]:.2f} of the VIP keep-out')
    if met['room'] < -cfg.contain_margin:
        bad.append(f'an aircraft went {-met["room"]:.2f} m past the room clamp')
    if met['z_lo'] < cfg.floor - 0.15 or met['z_hi'] > cfg.ceiling + 0.15:
        bad.append(f'altitude {met["z_lo"]:.2f}..{met["z_hi"]:.2f} m left the '
                   f'{cfg.floor:.2f}..{cfg.ceiling:.2f} m band')
    if met['emergency']:
        bad.append(f'solver emergency push-apart on {met["emergency"]} ticks')
    if met['backstop']:
        bad.append(f'backstop clamp fired {met["backstop"]} times')
    return bad


def run_series(cfg, rules, dname, aname, starts, D, A, vip, seeds, dparams, aparams,
               tau, vip_move, verbose, finale=False, fparams=None):
    rows = []
    for s in seeds:
        res, met, _ = simulate(cfg, rules, dname, aname, starts, D, A, vip, s, dparams,
                               aparams, tau, vip_move, finale=finale, fparams=fparams)
        bad = safety_failures(cfg, met)
        rows.append((s, res, met, bad))
        if verbose:
            print(f'    seed {s:3d}  {res.winner:7s} t={res.t:5.1f}s  '
                  f'strikes {res.strikes} downs {res.downs}  '
                  f'min sep {met["sep"]:.2f} m  VIP {met["vip"]:.2f}  '
                  f'room {met["room"]:+.2f}  CBF {met["corrected"]}'
                  f'{"  finale " + met["finale"] if met["finale"] else ""}'
                  f'{"  *** " + "; ".join(bad) if bad else ""}')
    return rows


def summarise(rows):
    n = len(rows)
    dw = sum(r[1].winner == DEFENSE for r in rows)
    t = np.mean([r[1].t for r in rows])
    unsafe = [r for r in rows if r[3]]
    sep = min(r[2]['sep'] for r in rows)
    return dw, n, t, unsafe, sep


def _kv(items):
    out = {}
    for it in items or ():
        k, _, v = it.partition('=')
        try:
            out[k] = ast.literal_eval(v)       # numbers, tuples, True/False
        except (ValueError, SyntaxError):
            out[k] = v
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--defense', default='shell')
    ap.add_argument('--attack', default='coordinated')
    ap.add_argument('--defenders', default='4',
                    help='a count (planned marks) or names cf1,cf2,... '
                         '(their initial_position in crazyflies.yaml)')
    ap.add_argument('--attackers', default='3', help='as --defenders')
    ap.add_argument('--live', action='store_true',
                    help='with names: plan from where /poses sees the drones '
                         'now, not from the roster (mocap must be up)')
    ap.add_argument('--vip', default='',
                    help='x,y,z of a point VIP (default: the escort VIP mark '
                         'at DJI height)')
    ap.add_argument('--seeds', type=int, default=12)
    ap.add_argument('--seed0', type=int, default=0)
    ap.add_argument('--tau', type=float, default=0.25,
                    help='aircraft lag behind the setpoint, s')
    ap.add_argument('--vip-move', type=float, default=0.0,
                    help='VIP drifts on a 0.6 m circle at this speed, m/s')
    ap.add_argument('--set', action='append', metavar='FIELD=VALUE',
                    help='override a GuardConfig field (repeatable)')
    ap.add_argument('--dparam', action='append', metavar='KEY=VALUE',
                    help='defence strategy parameter (repeatable)')
    ap.add_argument('--aparam', action='append', metavar='KEY=VALUE',
                    help='attack strategy parameter (repeatable)')
    ap.add_argument('--rules', default='tag',
                    help="rule set (--list names them), or 'all' with --matrix")
    ap.add_argument('--rparam', action='append', metavar='KEY=VALUE',
                    help='rule-set parameter (repeatable)')
    ap.add_argument('--policy-module', default='',
                    help='import this module first (your own strategies)')
    ap.add_argument('--matrix', action='store_true',
                    help='every defence against every attack')
    ap.add_argument('--marks', action='store_true',
                    help='print where to stand the drones, and check the yaml')
    ap.add_argument('--plot', default='', help='plot seed0 to this .png')
    ap.add_argument('--list', action='store_true',
                    help='list the strategies and rule sets')
    ap.add_argument('--rviz', action='store_true',
                    help='play the matches in real time on /guard/markers '
                         '(open rviz2 -d <share>/crazyflie_shows/data/guard.rviz)')
    ap.add_argument('--speed', type=float, default=1.0,
                    help='--rviz playback speed (2 = twice real time)')
    ap.add_argument('--no-finale', action='store_true',
                    help='stop at the result (by default the finale is flown and '
                         'checked too; --matrix never flies it)')
    ap.add_argument('--fparam', action='append', metavar='KEY=VALUE',
                    help='finale parameter (repeatable; guard/finale.py DEFAULTS)')
    a = ap.parse_args(argv)

    safety.require_measured_arena('plan_guard')
    policies.load_module(a.policy_module)
    cfg = override(GuardConfig(), _kv(a.set))
    if a.list:
        for team in (DEFENSE, ATTACK):
            print(f'\n  {team}:')
            for n in policies.available(team):
                print(f'    {n:14s} {policies.describe(team, n)}')
        print('\n  rules:')
        for n in rule_sets.available():
            print(f'    {n:14s} {rule_sets.describe(n)}')
        print()
        return 0
    rule_names = (rule_sets.available() if a.rules == 'all' else [a.rules])
    if len(rule_names) > 1 and not a.matrix:
        raise SystemExit("--rules all needs --matrix")
    rules = rule_sets.make(rule_names[0], _kv(a.rparam))

    vip = (np.array([float(x) for x in a.vip.split(',')]) if a.vip
           else vip_mark(cfg))
    named = not (a.defenders.isdigit() and a.attackers.isdigit())
    if named:
        D = [n for n in a.defenders.split(',') if n]
        A = [n for n in a.attackers.split(',') if n]
        marks = (live_marks(D + A) if a.live else roster_marks(D + A))
    else:
        D = [f'D{i + 1}' for i in range(int(a.defenders))]
        A = [f'A{j + 1}' for j in range(int(a.attackers))]
        marks = recommend_marks(cfg, vip, len(D), len(A))
    bad_cfg = problems(cfg)
    for name in rule_names:
        bad_cfg += [f'rules {name}: {b}' for b in
                    rule_sets.make(name, _kv(a.rparam) if name == a.rules else None)
                    .problems(cfg)]
    bad_marks, starts = mark_problems(cfg, rules, vip, marks, D, A)
    fparams = _kv(a.fparam)
    if not a.no_finale:
        from crazyflie_shows.guard import finale as finale_mod
        bad_cfg += finale_mod.check(cfg, fparams)

    print(f'\n  GUARD - offline check   {len(D)} defenders v {len(A)} '
          f'attackers   rules: {", ".join(rule_names)}')
    if named:
        src = 'live /poses' if a.live else 'crazyflies.yaml initial_position'
        print(f'  drones        defence {",".join(D)}; attack {",".join(A)} '
              f'(from {src})')
    print(f'  arena         {escort.describe_room(cfg)}; band '
          f'{cfg.floor:.2f}..{cfg.ceiling:.2f} m')
    print(f'  VIP           [{vip[0]:+.2f}, {vip[1]:+.2f}, {vip[2]:.2f}]'
          f'{f", drifting at {a.vip_move:.2f} m/s" if a.vip_move else ", still"}')
    print(f'  speeds        defence {cfg.v_max_defense:.2f}, attack '
          f'{cfg.v_max_attack:.2f}, dodging up to {cfg.v_max_safety:.2f} m/s')
    print(f'  keep-outs     drone {cfg.d_cc:.2f} m across x '
          f'{cfg.d_cc * cfg.cc_z_ratio:.2f} m up/down; VIP {cfg.d_vip:.2f} x '
          f'{cfg.d_vip * cfg.vip_z_ratio:.2f} m')
    if len(rule_names) == 1:
        print(f'  rules         {rules.describe()}: '
              + ', '.join(f'{k} {v}' for k, v in sorted(rules.p.items())))
    for b in bad_cfg + bad_marks:
        print(f'  *** {b}')
    if bad_cfg or bad_marks:
        print('\n  REFUSED\n')
        return 1

    if a.marks:
        return report_marks(cfg, vip, marks, D, A)

    dparams, aparams = _kv(a.dparam), _kv(a.aparam)
    seeds = list(range(a.seed0, a.seed0 + a.seeds))
    if a.rviz:
        sets = [rules] + [rule_sets.make(n) for n in rule_names[1:]]
        return play_rviz(cfg, sets, a, starts, D, A, vip, seeds, dparams, aparams,
                         fparams)
    t0 = time.time()
    if a.matrix:
        print(f'\n  MATRIX  ({len(seeds)} seeds each; defence wins / matches)')
        dn, an = policies.available(DEFENSE), policies.available(ATTACK)
        any_unsafe = False
        for name in rule_names:
            rs = rules if name == rule_names[0] else rule_sets.make(name)
            print(f'\n  rules: {rs.describe()}')
            print('  ' + ' ' * 14 + ''.join(f'{x:>26s}' for x in an))
            for d in dn:
                cells = []
                for at in an:
                    rows = run_series(cfg, rs, d, at, starts, D, A, vip, seeds,
                                      None, None, a.tau, a.vip_move, False)
                    dw, n, t, unsafe, sep = summarise(rows)
                    lost = sum(sum(e.kind == 'down' and e.who in D
                                   for e in r[1].events) for r in rows)
                    any_unsafe |= bool(unsafe)
                    cells.append(f'{dw:>3d}/{n:<3d} {t:5.1f}s {sep:4.2f}m D-{lost:<2d}'
                                 + ('!' if unsafe else ' '))
                print(f'  {d:14s}' + ''.join(f'{c:>26s}' for c in cells))
        print('\n  cell: defence wins/matches, mean match time, closest pair, '
              'defenders downed in all; "!" = a safety failure')
        print(f'  ({time.time() - t0:.0f} s)\n')
        return 1 if any_unsafe else 0

    print(f'\n  {a.defense} (defence) v {a.attack} (attack), seeds '
          f'{seeds[0]}..{seeds[-1]}\n')
    rows = run_series(cfg, rules, a.defense, a.attack, starts, D, A, vip, seeds,
                      dparams, aparams, a.tau, a.vip_move, True,
                      not a.no_finale, fparams)
    dw, n, t, unsafe, sep = summarise(rows)
    worst = min(rows, key=lambda r: r[2]['sep'])[2]
    print(f'\n  GAME     defence won {dw}/{n}, attack {n - dw}/{n}; mean match '
          f'{t:.1f} s; strikes {sum(r[1].strikes for r in rows)}, downs '
          f'{sum(r[1].downs for r in rows)}')
    print(f'  SAFETY   closest airborne pair {sep:.2f} m '
          f'(floor {cfg.min_separation:.2f} across, {cfg.min_separation_z:.2f} '
          f'vertically; worst {min(r[2]["floor"] for r in rows):.2f} of it); peak speed '
          f'{max(r[2]["speed"] for r in rows):.2f} m/s; CBF corrected '
          f'{sum(r[2]["corrected"] for r in rows)} drone-ticks, emergency '
          f'{sum(r[2]["emergency"] for r in rows)}, backstop '
          f'{sum(r[2]["backstop"] for r in rows)}; closest to the VIP '
          f'{min(r[2]["vip"] for r in rows):.2f} of its keep-out; room '
          f'{min(r[2]["room"] for r in rows):+.2f} m; worst pair '
          f'{worst["sep_pair"]}')
    print(f'  ({time.time() - t0:.0f} s)')
    if a.plot:
        _, _, tr = simulate(cfg, rules, a.defense, a.attack, starts, D, A, vip,
                            seeds[0], dparams, aparams, a.tau, a.vip_move, True)
        plot(tr, cfg, D, A, a.plot)
    if unsafe:
        print(f'\n  SAFETY FAILED on {len(unsafe)} seed(s) -- do not fly this.\n')
        return 1
    print('\n  SAFE on every seed.\n')
    return 0


def play_rviz(cfg, rule_list, a, starts, D, A, vip, seeds, dparams, aparams,
              fparams=None):
    """Play each seed in real time on /guard/markers, one after another,
    rotating through every pairing (--matrix) and rule set (--rules all)."""
    import rclpy
    from crazyflie_shows.guard.viz import GuardViz

    rclpy.init()
    node = rclpy.create_node('plan_guard_viz')
    viz = GuardViz(node)
    dt = 1.0 / cfg.rate_hz
    clock = {'next': time.monotonic()}
    # --matrix --rviz: rotate through every pairing, so consecutive matches
    # actually look different; otherwise the one pairing, seed after seed.
    if a.matrix:
        pairs = [(d, at) for d in policies.available(DEFENSE)
                 for at in policies.available(ATTACK)]
    else:
        pairs = [(a.defense, a.attack)]

    def tick(m, vip_now, tk, res, banner):
        # rclpy's signal handlers shut the context down WITHOUT raising here
        # (SIGINT and SIGTERM alike), so check, or a stopped player keeps
        # playing into a dead publisher and ignores every polite kill.
        if not rclpy.ok():
            raise KeyboardInterrupt
        viz.publish(m.t, cfg, tick.rules, vip_now, m.agents, tk.labels, res,
                    f'{tick.pair[0]} v {tick.pair[1]} | {tick.rules.name} | seed {tick.seed}',
                    m.referee.meters, tk.intents, tk.plans, m.corrected, tk.events,
                    banner)
        clock['next'] += dt / max(a.speed, 1e-3)
        pause = clock['next'] - time.monotonic()
        if pause > 0:
            time.sleep(pause)
        else:
            clock['next'] = time.monotonic()

    try:
        for s in seeds:
            for rules in rule_list:
                for pair in pairs:
                    tick.seed, tick.pair, tick.rules = s, pair, rules
                    viz.clear()
                    clock['next'] = time.monotonic()
                    own = pair == (a.defense, a.attack)
                    res, met, _ = simulate(cfg, rules, pair[0], pair[1], starts, D, A, vip,
                                           s, dparams if own else None,
                                           aparams if own else None, a.tau, a.vip_move,
                                           on_tick=tick, finale=not a.no_finale,
                                           fparams=fparams)
                    bad = safety_failures(cfg, met)
                    print(f'  {rules.name:14s} {pair[0]} v {pair[1]:12s} seed {s:3d}  {res.winner:7s} '
                          f'{res.reason:28s} t={res.t:5.1f}s '
                          f'strikes {res.strikes} downs {res.downs}  min sep '
                          f'{met["sep"]:.2f} m{"  *** " + "; ".join(bad) if bad else ""}',
                          flush=True)
                    time.sleep(2.0)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


def report_marks(cfg, vip, marks, D, A):
    print('\n  STAND THE DRONES HERE (metres, floor, world frame)')
    for n in D + A:
        m = marks[n]
        print(f'    {"defender" if n in D else "attacker"} {n:4s} '
              f'[{m[0]:+.2f}, {m[1]:+.2f}]   '
              f'{float(np.linalg.norm(m[:2] - vip[:2])):.2f} m from the VIP, '
              f'{float(escort.room_clearance(cfg, m)):.2f} m inside the edge')
    print('\n  guard_show assigns roles by these marks (nearest the VIP defend) '
          'unless\n  you name them: -p defenders:=cf1,cf2 -p attackers:=cf3,cf4\n')
    return 0


def plot(trace, cfg, D, A, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, (ax, az) = plt.subplots(1, 2, figsize=(13, 6.5))
    if safety.ARENA_POLYGON is not None:
        ax.add_patch(plt.Polygon(safety.ARENA_POLYGON, closed=True, fill=False,
                                 ls='--', color='0.6'))
    t = np.array([s[0] for s in trace])
    vip = np.array([s[1] for s in trace])
    ax.plot(vip[:, 0], vip[:, 1], 'k-', lw=3, label='VIP')
    az.plot(t, vip[:, 2], 'k-', lw=3, label='VIP')
    for n in D + A:
        p = np.array([s[2][n] for s in trace])
        ls = '-' if n in D else '--'
        col = 'tab:blue' if n in D else 'tab:red'
        ax.plot(p[:, 0], p[:, 1], ls, color=col, lw=1, alpha=0.8)
        ax.annotate(n, p[-1, :2], fontsize=7, color=col)
        az.plot(t, p[:, 2], ls, color=col, lw=1, alpha=0.8)
    ax.set_aspect('equal')
    ax.set_title('plan view (blue defence, red attack)')
    az.set_title('height over time')
    az.set_xlabel('t (s)')
    az.axhline(cfg.floor, color='0.6', ls=':')
    az.axhline(cfg.ceiling, color='0.6', ls=':')
    fig.savefig(path, dpi=110, bbox_inches='tight')
    print(f'  wrote {path}')


if __name__ == '__main__':
    sys.exit(main())
