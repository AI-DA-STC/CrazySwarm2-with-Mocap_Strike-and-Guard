#!/usr/bin/env python3
"""Fly ONE drone a slow outward spiral and record where mocap actually holds it.

Why this exists
---------------
``measure_arena.py`` measures the volume with a body carried by hand. That is
the safe way to find the edge, but it is not the same question as "will a
DRONE be tracked there": a flying Crazyflie is tilted, vibrating, and its
markers are moving, and the carrier's body is no longer in the way. This flies
the question.

What it deliberately does NOT do
--------------------------------
It does not hunt for the edge. Flying outward until Motive drops the drone is
inducing the fly-away case on purpose -- with no position measurement the
onboard estimator free-runs on IMU bias and the controller chases a diverging
estimate, which is how a drone ends up in a wall. So:

* ``--r-max`` caps the sweep at the radius the PLAN needs, not beyond;
* a watchdog lands immediately if cf1's pose goes stale for ``--stale``;
* the whole thing flies at ``--speed`` (default 0.10 m/s), slowly enough that
  losing tracking at the outer edge costs centimetres of overshoot, not metres.

The answer it gives is "tracking held / did not hold out to R, in every
bearing, at flight height", which is what the escort geometry actually needs.

    # mocap up, server up, nothing else armed, E-STOP in reach
    python3 scripts/arena_flight_sweep.py --drone cf1 --r-max 2.3 --height 1.2
"""

import argparse
import json
import math
import pathlib
import signal
import sys
import time
from collections import deque

import numpy as np
import rclpy
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

from crazyflie_py import Crazyswarm
from motion_capture_tracking_interfaces.msg import NamedPoseArray


def took_off(z_now, z_target, frac=0.6):
    """Did it actually leave the ground? `takeoff()` returning proves nothing."""
    return z_now >= z_target * frac


def following(err, tol, bad_since, now, grace):
    """(still_ok, new_bad_since) for the setpoint-tracking watchdog.

    Returns still_ok=False once the drone has been further than ``tol`` from
    its commanded setpoint for longer than ``grace``. Separated from the flight
    loop because it is the check whose absence let a grounded drone report a
    clean 34-waypoint sweep, and a check like that should be testable without
    a battery.
    """
    if err <= tol:
        return True, None
    if bad_since is None:
        return True, now
    return (now - bad_since) <= grace, bad_since


def goto_progress(tau):
    """Fraction of a firmware goTo() covered at normalised time ``tau``.

    The high-level commander flies goTo as a 7th-order polynomial with zero
    velocity, acceleration and jerk at both ends. The following watchdog
    must compare the drone with THIS moving setpoint, not with the goTo's end
    point: on 2026-11-02 a 3.4 m, 34 s glide to the edge of the big arena was
    aborted 3 s in for being "3.16 m from its setpoint". It was flying
    exactly as commanded. In the old room every move was under the 0.6 m
    tolerance, which hid the bug.
    """
    t = min(max(tau, 0.0), 1.0)
    return t ** 4 * (35 - 84 * t + 70 * t ** 2 - 20 * t ** 3)


def setpoint_at(start, end, t0, dur, now):
    """Where the commander's setpoint is ``now`` along a goTo start->end."""
    f = goto_progress((now - t0) / dur if dur > 0 else 1.0)
    return tuple(s + (e - s) * f for s, e in zip(start, end))


def descent_duration(dz, rate, minimum):
    """Seconds for a descent of ``dz`` metres at an AVERAGE ``rate`` m/s.

    Landing and recovery used fixed 4 s / 3 s, sized for the old room's
    2.3 m cap. From 6 m that is a 1.5 m/s average descent -- the goTo profile
    peaks at about twice its average -- straight into the floor, or blind
    during a recovery. Scale with height instead.
    """
    return max(minimum, abs(dz) / rate)


def battery_low(v, thr, low_since, now, grace):
    """(land_now, new_low_since) for the low-battery watchdog.

    True once the voltage has stayed below ``thr`` for longer than ``grace``:
    a climb sags the voltage for a moment, and one low sample must not end a
    run. ``v is None`` means no /status has arrived, so the check cannot fire.
    """
    if v is None or v >= thr:
        return False, None
    if low_since is None:
        return False, now
    return (now - low_since) > grace, low_since


#: What makes two runs "the same path". Speed, dwell and the watchdog limits
#: are deliberately absent: changing them on a resume is fine.
_PATH_KEYS = ('mode', 'centre', 'r_min', 'r_max', 'turns', 'height', 'levels',
              'z_step', 'z_max')


def path_signature(args):
    return {k: (list(getattr(args, k)) if k == 'centre' else getattr(args, k))
            for k in _PATH_KEYS}


def save_progress(path, sig, **where):
    """Record the last waypoint the drone REACHED, atomically: a run that dies
    while writing must not leave a half-file that a resume then trusts."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps({'path': sig, **where}, indent=1))
    tmp.replace(path)


def load_progress(path, sig):
    """The progress of an unfinished run on THIS path, or SystemExit saying why not."""
    path = pathlib.Path(path)
    if not path.exists():
        raise SystemExit(f'  no progress file {path} -- nothing to resume; '
                         'run without --resume')
    prog = json.loads(path.read_text())
    if prog.get('done'):
        raise SystemExit(f'  {path}: that sweep already finished -- nothing to resume')
    diff = [k for k in _PATH_KEYS if prog['path'].get(k) != sig.get(k)]
    if diff:
        raise SystemExit(
            f'  {path} was recorded on a different path ({", ".join(diff)} differ:\n'
            + ''.join(f'    {k}: was {prog["path"].get(k)!r}, now {sig.get(k)!r}\n'
                      for k in diff)
            + '  ) -- resume with the same path arguments, or run without --resume')
    return prog


class Aborted(Exception):
    pass


class LowBattery(Aborted):
    """Land now, and say how to carry on. Not a tracking failure."""


class _Done(Exception):
    """Sweep finished normally; fall through to the landing."""


def selftest():
    """The two watchdogs, without a battery."""
    fail = 0
    cases = [
        ('grounded drone, takeoff "succeeded"', took_off(0.02, 1.20), False),
        ('half way up',                          took_off(0.70, 1.20), False),
        ('airborne',                             took_off(1.18, 1.20), True),
    ]
    for name, got, want in cases:
        ok = got == want
        fail += not ok
        print(f'  {"PASS" if ok else "FAIL"}  took_off: {name} -> {got}')

    # a drone that never follows must abort after the grace period, not before
    bad, t = None, 0.0
    seq = []
    for step in range(10):                     # 0.5 s apart, err 2.0 m
        t = step * 0.5
        ok, bad = following(2.0, 0.60, bad, t, 3.0)
        seq.append((t, ok))
    aborted_at = next((t for t, ok in seq if not ok), None)
    good = aborted_at is not None and 3.0 < aborted_at <= 4.0
    fail += not good
    print(f'  {"PASS" if good else "FAIL"}  following: 2.0 m error aborts at '
          f't={aborted_at}s (want just after the 3.0 s grace)')

    # a drone that follows must never abort, however long it flies
    bad, never = None, True
    for step in range(200):
        ok, bad = following(0.10, 0.60, bad, step * 0.5, 3.0)
        never &= ok
    fail += not never
    print(f'  {"PASS" if never else "FAIL"}  following: 0.10 m error never aborts')

    # a brief excursion inside the grace period must be forgiven
    bad = None
    ok1, bad = following(2.0, 0.60, bad, 0.0, 3.0)      # goes bad
    ok2, bad = following(2.0, 0.60, bad, 1.0, 3.0)      # still bad, inside grace
    ok3, bad = following(0.10, 0.60, bad, 1.5, 3.0)     # recovers
    ok4, bad = following(2.0, 0.60, bad, 2.0, 3.0)      # bad again, clock reset
    forgiven = all((ok1, ok2, ok3, ok4)) and bad == 2.0
    fail += not forgiven
    print(f'  {"PASS" if forgiven else "FAIL"}  following: a brief excursion is '
          'forgiven and the clock restarts')

    # the goTo profile: ends pinned, symmetric, monotonic
    prof = [goto_progress(k / 100) for k in range(101)]
    good = (prof[0] == 0.0 and abs(prof[-1] - 1.0) < 1e-12
            and abs(prof[50] - 0.5) < 1e-12
            and all(b >= a for a, b in zip(prof, prof[1:])))
    fail += not good
    print(f'  {"PASS" if good else "FAIL"}  goto_progress: 0 -> 1, half way at '
          'half time, never backwards')

    # the 2026-11-02 abort, replayed: a drone flying a 3.4 m / 34 s glide
    # exactly as commanded (plus 0.1 m of lag) must never trip the watchdog
    bad, never = None, True
    for step in range(69):
        t = step * 0.5
        sp = setpoint_at((0.0, 0.0, 1.2), (3.4, 0.0, 1.2), 0.0, 34.0, t)
        drone = (max(sp[0] - 0.10, 0.0), 0.0, 1.2)
        ok, bad = following(math.dist(drone, sp), 0.60, bad, t, 3.0)
        never &= ok
    fail += not never
    print(f'  {"PASS" if never else "FAIL"}  following: a long glide flown as '
          'commanded never aborts (the 2026-11-02 false abort)')

    good = (descent_duration(1.2, 0.4, 4.0) == 4.0
            and abs(descent_duration(6.0, 0.4, 4.0) - 15.0) < 1e-9
            and descent_duration(-4.8, 1.0, 3.0) == 4.8)
    fail += not good
    print(f'  {"PASS" if good else "FAIL"}  descent_duration: low landings keep '
          '4 s, a 6 m landing takes 15 s')

    # low battery: one sagging sample is forgiven, a sustained one lands
    land1, s = battery_low(3.20, 3.30, None, 0.0, 2.0)
    land2, s = battery_low(3.20, 3.30, s, 1.0, 2.0)
    land3, s2 = battery_low(3.60, 3.30, s, 1.5, 2.0)       # recovers
    land4, s = battery_low(3.20, 3.30, s, 2.5, 2.0)
    land5, _ = battery_low(None, 3.30, None, 9.0, 2.0)     # no /status yet
    good = (not land1 and not land2 and not land3 and s2 is None
            and land4 and not land5)
    fail += not good
    print(f'  {"PASS" if good else "FAIL"}  battery_low: a sag is forgiven, '
          'a sustained low lands, no reading never lands')

    # progress: round trip, finished run, and a different path all behave
    import tempfile
    from types import SimpleNamespace
    a = SimpleNamespace(mode='spiral', centre=(-0.213, -0.072), r_min=3.3,
                        r_max=3.85, turns=1.0, height=1.2, levels='',
                        z_step=0.1, z_max=3.0)
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / 'p.json'
        save_progress(p, path_signature(a), level=0, leg=7, done=False)
        back = load_progress(p, path_signature(a))
        rt = back['level'] == 0 and back['leg'] == 7
        b = SimpleNamespace(**{**vars(a), 'r_max': 4.0})
        try:
            load_progress(p, path_signature(b))
            other = False
        except SystemExit:
            other = True
        save_progress(p, path_signature(a), done=True)
        try:
            load_progress(p, path_signature(a))
            fin = False
        except SystemExit:
            fin = True
    good = rt and other and fin
    fail += not good
    print(f'  {"PASS" if good else "FAIL"}  progress: round trip, a changed path '
          'refuses, a finished run refuses')

    print(f'\n  {"selftest OK" if not fail else f"{fail} FAILURE(S)"}')
    return 1 if fail else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--drone', default='cf1')
    ap.add_argument('--centre', nargs=2, type=float, default=(0.033, 0.255),
                    metavar=('X', 'Y'), help='volume centre from measure_arena')
    ap.add_argument('--r-min', type=float, default=0.6)
    ap.add_argument('--r-max', type=float, default=2.3,
                    help='HARD cap. The plan needs ~2.15 m; do not raise this '
                         'to go looking for the edge while flying.')
    ap.add_argument('--height', type=float, default=1.2)
    ap.add_argument('--speed', type=float, default=0.10, help='m/s, ground speed')
    ap.add_argument('--turns', type=float, default=2.0)
    ap.add_argument('--mode', choices=('spiral', 'climb'), default='spiral',
                    help='spiral = radius sweep at one height; '
                         'climb = height sweep near the volume centre')
    ap.add_argument('--z-max', type=float, default=2.40,
                    help='HARD ceiling for --mode climb. Hand-carried tracking '
                         'died at 2.33 m; this stops just above that.')
    ap.add_argument('--z-step', type=float, default=0.10)
    ap.add_argument('--z-safe', type=float, default=1.20,
                    help='height to drop back to when the estimate goes stale '
                         '-- deep inside tracked volume, so it RECOVERS there')
    ap.add_argument('--levels', default='',
                    help='comma-separated heights for --mode spiral. Each one '
                         'gets a full spiral, alternating outward/inward so no '
                         'battery is spent flying back to the start. This is '
                         'the VERIFY pattern: it covers the volume you intend '
                         'to use and passes only if nothing ever goes stale.')
    ap.add_argument('--follow-tol', type=float, default=0.60,
                    help='m. Further than this from the commanded setpoint and '
                         'the drone is not flying the path we are measuring.')
    ap.add_argument('--follow-s', type=float, default=3.0,
                    help='s it may stay outside --follow-tol before aborting')
    ap.add_argument('--dwell', type=float, default=2.5,
                    help='s to hold at each height, so a marginal layer shows')
    ap.add_argument('--save', metavar='CSV',
                    default='data/arena/flight_sweep.csv',
                    help='where the raw samples go. Defaults INSIDE THE REPO, '
                         'not /tmp: a sweep costs a battery and somebody '
                         'standing by the E-STOP, and the first one was lost '
                         'to a cleared scratchpad.')
    ap.add_argument('--stale', type=float, default=0.4,
                    help='s without a pose before the sweep lands itself')
    ap.add_argument('--resume', action='store_true',
                    help='carry on an unfinished run (e.g. one that landed on '
                         'low battery) from the last waypoint it reached. Give '
                         'the SAME path arguments; samples are appended to --save')
    ap.add_argument('--progress', metavar='JSON',
                    help='where the last reached waypoint is recorded '
                         '(default: <--save>.progress.json)')
    ap.add_argument('--land-voltage', type=float, default=3.30,
                    help='V. Below this for --land-voltage-s the run lands and '
                         'can be resumed. Under load, so lower than the at-rest '
                         'warning in crazyflies.yaml')
    ap.add_argument('--land-voltage-s', type=float, default=3.0,
                    help='s the voltage must stay low before landing. Every '
                         'climb step sags the pack for a moment; that must '
                         'not end a run')
    ap.add_argument('--min-start-voltage', type=float, default=3.80,
                    help='V AT REST (before arming, no load). Below this the '
                         'run will not arm: same as voltage_warning in '
                         'crazyflies.yaml. Flying sags the pack ~0.3-0.4 V, '
                         'which is why this and --land-voltage differ')
    ap.add_argument('--selftest', action='store_true',
                    help='exercise the watchdogs on the ground and exit')
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    swarm = Crazyswarm()
    timeHelper = swarm.timeHelper
    cf = swarm.allcfs.crazyfliesByName[args.drone]
    node = swarm.allcfs

    # Take the signals back from rclpy: it installs its own SIGINT handler that
    # shuts the context down before KeyboardInterrupt reaches us, so a Ctrl-C
    # abort would otherwise fail exactly when it is needed (docs/details/known-issues.md).
    def take(sig, _frm):
        signal.signal(sig, signal.SIG_DFL)      # a second one kills us outright
        raise Aborted(f'signal {sig}')
    signal.signal(signal.SIGINT, take)
    signal.signal(signal.SIGTERM, take)

    seen = {'t': 0.0, 'p': None}
    samples = deque()
    qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT,
                     history=HistoryPolicy.KEEP_LAST)

    def on_poses(msg):
        for np_ in msg.poses:
            if np_.name == args.drone:
                seen['t'] = time.time()
                seen['p'] = (np_.pose.position.x, np_.pose.position.y, np_.pose.position.z)
    node.create_subscription(NamedPoseArray, '/poses', on_poses, qos)

    # battery, from the server's 1 Hz /<drone>/status
    from crazyflie_interfaces.msg import Status
    from rclpy.qos import qos_profile_sensor_data
    batt = {'v': None, 'low': None}

    def on_status(msg):
        batt['v'] = float(msg.battery_voltage)
    node.create_subscription(Status, f'/{args.drone}/status', on_status,
                             qos_profile_sensor_data)

    def pump(seconds):
        """Spin, sample, and enforce BOTH watchdogs.

        Staleness alone is not enough, and believing otherwise produced a
        34-waypoint "clean sweep" of a drone that never left the floor on
        2026-10-01: mocap tracks a grounded Crazyflie perfectly, so every
        waypoint reported ok. A sweep that cannot tell flying from not flying
        cannot verify a volume. So the commanded setpoint is checked too.
        """
        end = time.time() + seconds
        while time.time() < end:
            rclpy.spin_once(node, timeout_sec=0.0)
            timeHelper.sleep(0.05)
            age = time.time() - seen['t']
            if seen['p'] is not None:
                x, y, z = seen['p']
                samples.append((time.time(), x, y, z, age))
            if seen['t'] and age > args.stale:
                raise Aborted(f'{args.drone} pose stale for {age:.2f} s')
            low, batt['low'] = battery_low(batt['v'], args.land_voltage,
                                           batt['low'], time.time(),
                                           args.land_voltage_s)
            if low:
                raise LowBattery(f'battery {batt["v"]:.2f} V, below '
                                 f'{args.land_voltage:.2f} V for '
                                 f'>{args.land_voltage_s:.0f} s')
            want = (setpoint_at(cmd['from'], cmd['p'], cmd['t0'], cmd['dur'],
                                time.time()) if cmd['p'] is not None else None)
            if want is not None and seen['p'] is not None:
                err = math.dist(seen['p'], want)
                ok, cmd['bad'] = following(err, args.follow_tol, cmd['bad'],
                                           time.time(), args.follow_s)
                if not ok:
                    raise Aborted(
                        f'{args.drone} is {err:.2f} m from its setpoint for '
                        f'>{args.follow_s:.0f} s -- it is not following')

    cmd = {'p': None, 'from': None, 't0': 0.0, 'dur': 0.0, 'bad': None}

    def go(x, y, z, dur):
        # the commander starts from its current setpoint: the previous goTo's
        # end, or (right after takeoff) where the drone actually is
        start = cmd['p'] if cmd['p'] is not None else (seen['p'] or (x, y, z))
        cmd['from'] = tuple(float(v) for v in start)
        cmd['p'] = (float(x), float(y), float(z))
        cmd['t0'], cmd['dur'] = time.time(), float(dur)
        cmd['bad'] = None
        cf.goTo(np.array([x, y, z]), 0.0, dur)

    cx, cy = args.centre
    print(f'\n  ARENA FLIGHT SWEEP - {args.drone}')
    print(f'  centre ({cx:+.3f},{cy:+.3f})  r {args.r_min:.2f}..{args.r_max:.2f} m  '
          f'height {args.height:.2f} m  speed {args.speed:.2f} m/s')
    print(f'  watchdog: lands if the pose is stale for {args.stale:.2f} s')
    print('  E-STOP in reach. Ctrl-C lands and disarms.\n')

    # wait for a pose before arming -- no pose, no flight
    t0 = time.time()
    while seen['p'] is None and time.time() - t0 < 5.0:
        rclpy.spin_once(node, timeout_sec=0.1)
    if seen['p'] is None:
        raise SystemExit(f'  no /poses for {args.drone}; not arming')
    print(f'  {args.drone} tracked at ({seen["p"][0]:+.2f},{seen["p"][1]:+.2f})')

    # battery AT REST, before any load: a resume on a half-empty pack would
    # only land again a minute later
    t0 = time.time()
    while batt['v'] is None and time.time() - t0 < 3.0:
        rclpy.spin_once(node, timeout_sec=0.1)
    if batt['v'] is None:
        print(f'  WARNING: no /{args.drone}/status -- battery unknown, the '
              'low-battery landing CANNOT fire. Watch it yourself.')
    elif batt['v'] < args.min_start_voltage:
        raise SystemExit(f'  battery {batt["v"]:.2f} V at rest, below '
                         f'{args.min_start_voltage:.2f} V -- charge or swap it; not arming')
    else:
        print(f'  battery {batt["v"]:.2f} V at rest; lands below '
              f'{args.land_voltage:.2f} V (in flight, sustained '
              f'{args.land_voltage_s:.0f} s)')

    # the spiral: constant angular step, radius growing linearly
    legs = []
    n = max(24, int(args.turns * 24))
    for k in range(n + 1):
        f = k / n
        r = args.r_min + (args.r_max - args.r_min) * f
        a = 2 * math.pi * args.turns * f
        legs.append((cx + r * math.cos(a), cy + r * math.sin(a), r, math.degrees(a) % 360))

    levels = ([float(v) for v in args.levels.split(',') if v.strip()]
              or [args.height])

    def path_for(li):
        # alternate direction: out at one height, back in at the next, so
        # the climb between levels is the only non-measuring travel
        return legs if li % 2 == 0 else list(reversed(legs))

    # progress: the last waypoint REACHED, so a run that lands on low battery
    # (or is aborted) can be carried on with --resume instead of re-flown
    prog_path = pathlib.Path(args.progress or (args.save + '.progress.json'))
    sig = path_signature(args)
    start_li, start_k, start_z = 0, 0, None
    if args.resume:
        prog = load_progress(prog_path, sig)
        if args.mode == 'climb':
            start_z = float(prog['z'])
            print(f'  RESUMING the climb from {start_z:.2f} m ({prog_path})')
        else:
            start_li, start_k = int(prog['level']), int(prog['leg'])
            _, _, r_, a_ = path_for(start_li)[start_k]
            print(f'  RESUMING level {start_li + 1}/{len(levels)} '
                  f'({levels[start_li]:.2f} m) at waypoint {start_k}/{len(legs) - 1} '
                  f'(r {r_:.2f} m, bearing {a_:.0f} deg) ({prog_path})')
    elif prog_path.exists():
        try:
            if not json.loads(prog_path.read_text()).get('done'):
                print(f'  NOTE: {prog_path} holds an UNFINISHED run; starting '
                      'over overwrites it (Ctrl-C now and add --resume to carry it on)')
        except ValueError:
            pass
    x0, y0 = path_for(start_li)[start_k][:2]

    def recover_and_land(why):
        """Stale at height is worse than stale low down: come DOWN into volume
        we know tracks, confirm the estimate is back, and only then land.
        Landing blind from 2.3 m is a descent with no position feedback."""
        print(f'\n  *** {why} -- dropping to {args.z_safe:.2f} m to recover ***', flush=True)
        try:
            here = seen['p'] or (cx, cy, args.z_safe)
            # ~1 m/s average: quick enough not to free-run on the IMU for
            # long, slow enough not to arrive at z_safe with a dive
            t_down = descent_duration(here[2] - args.z_safe, 1.0, 3.0)
            cf.goTo(np.array([here[0], here[1], args.z_safe]), 0.0, t_down)
        except Exception as e:                              # noqa: BLE001
            t_down = 3.0
            print(f'  could not command the descent ({e!r})')
        t_rec = time.time()
        back = False
        while time.time() - t_rec < t_down + 1.0:
            rclpy.spin_once(node, timeout_sec=0.0)
            timeHelper.sleep(0.05)
            if time.time() - seen['t'] < 0.2:
                back = True
        print(f'  tracking {"RECOVERED" if back else "did NOT recover"} at '
              f'{args.z_safe:.2f} m', flush=True)
        return back

    flying = False
    try:
        cf.arm(True)                 # newer crazyswarm2: no arm, no takeoff
        timeHelper.sleep(1.0)
        cf.takeoff(targetHeight=args.height, duration=4.0)
        flying = True
        cmd['p'] = None                 # nothing to follow during the climb out
        pump(5.0)
        # Did it ACTUALLY leave the ground? `takeoff()` returning means the
        # command was sent, nothing more.
        z_now = seen['p'][2] if seen['p'] else 0.0
        if z_now < args.height * 0.6:
            raise Aborted(f'takeoff did not happen -- {args.drone} is at '
                          f'{z_now:.2f} m, wanted {args.height:.2f} m')
        print(f'  airborne at {z_now:.2f} m', flush=True)
        # ease onto the start of the spiral (or the resume point), at the
        # takeoff height -- inside volume the takeoff just proved
        here = seen['p']
        d = math.dist((here[0], here[1]), (x0, y0))
        go(x0, y0, args.height, max(4.0, d / args.speed))
        pump(max(4.0, d / args.speed) + 1.0)

        def vstr():
            return f'{batt["v"]:.2f}V' if batt['v'] is not None else '  ?V'

        if args.mode == 'climb':
            print(f"\n  {'height':>7} {'pose age':>9} {'radius':>7} {'battery':>8}  state")
            z = args.height
            if start_z is not None and start_z > z:
                # straight back up to the last height that held, slowly
                dz = start_z - z
                here = seen['p'] or (x0, y0, z)
                go(here[0], here[1], start_z, max(2.0, dz / args.speed))
                pump(max(2.0, dz / args.speed) + 1.0)
                z = start_z
                print(f'  back at {z:.2f} m, carrying on', flush=True)
            lost_at = None
            while z < args.z_max:
                z = min(z + args.z_step, args.z_max)
                here = seen['p'] or (cx, cy, z)
                go(here[0], here[1], z, max(1.5, args.z_step / args.speed))
                try:
                    pump(max(1.5, args.z_step / args.speed) + args.dwell)
                except LowBattery:
                    raise                   # not a tracking result: land, resume later
                except Aborted as e:
                    lost_at = z
                    recover_and_land(str(e))
                    break
                p = seen['p']
                r = math.hypot(p[0] - cx, p[1] - cy) if p else float('nan')
                print(f'  {z:>6.2f}m {time.time()-seen["t"]:>8.2f}s {r:>6.2f}m '
                      f'{vstr():>8}  ok', flush=True)
                save_progress(prog_path, sig, z=z, done=False)
            if lost_at is None:
                print(f'\n  reached the {args.z_max:.2f} m cap with tracking intact '
                      '-- the ceiling is above this, not measured')
            else:
                print(f'\n  tracking lost climbing through {lost_at:.2f} m')
            save_progress(prog_path, sig, z=z, lost_at=lost_at, done=True)
            raise _Done()

        print(f"  {'z':>6} {'r':>6} {'bearing':>8} {'tracked':>8} {'battery':>8} {'waypoint':>9}")
        prev = (x0, y0)
        for li in range(start_li, len(levels)):
            z = levels[li]
            path = path_for(li)
            k0 = start_k if li == start_li else 0
            if abs(z - args.height) > 1e-3 or li != start_li:
                go(prev[0], prev[1], z, 3.0)
                pump(3.5)
            for k in range(k0 + 1, len(path)):
                x, y, r, a = path[k]
                leg = math.dist(prev, (x, y))
                dur = max(1.0, leg / args.speed)
                go(x, y, z, dur)
                pump(dur)
                prev = (x, y)
                age = time.time() - seen['t']
                print(f'  {z:>5.2f}m {r:>6.2f} {a:>7.0f}d '
                      f'{"ok" if age < args.stale else "STALE":>8} {vstr():>8} '
                      f'{k:>4}/{len(path) - 1}', flush=True)
                save_progress(prog_path, sig, level=li, leg=k, done=False)
        save_progress(prog_path, sig, level=len(levels) - 1, leg=len(legs) - 1,
                      done=True)
        raise _Done()
    except _Done:
        pass
    except LowBattery as e:
        print(f'\n  *** LOW BATTERY: {e} -- landing where it is ***\n'
              f'  Progress is in {prog_path}. Swap the battery, put {args.drone} '
              'back on its takeoff spot, and run the SAME command with --resume.',
              flush=True)
    except Aborted as e:
        print(f'\n  *** ABORT: {e} -- landing where it is ***', flush=True)
    except Exception as e:                                  # noqa: BLE001
        print(f'\n  *** ERROR: {e!r} -- landing ***', flush=True)
    finally:
        if flying:
            try:
                z_now = seen['p'][2] if seen['p'] else args.height
                t_land = descent_duration(z_now, 0.4, 4.0)
                cf.land(targetHeight=0.04, duration=t_land)
                timeHelper.sleep(t_land + 0.5)
            except Exception as e:                          # noqa: BLE001
                print(f'  could not land cleanly ({e!r}) -- use the E-STOP')
        try:
            cf.arm(False)
        except Exception:                                   # noqa: BLE001
            pass
        print('\n  landed and disarmed.\n')

    if samples and args.save:
        out = pathlib.Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        # a resumed run APPENDS, so the CSV ends up as the whole path
        append = args.resume and out.exists()
        with out.open('a' if append else 'w') as fh:
            if not append:
                fh.write('# t,x,y,z,pose_age\n')
            for row in samples:
                fh.write(','.join(f'{v:.4f}' for v in row) + '\n')
        print(f'  wrote {len(samples)} samples to {out}')
    if samples:
        arr = np.array([(s[1], s[2], s[3], s[4]) for s in samples], float)
        rad = np.hypot(arr[:, 0] - cx, arr[:, 1] - cy)
        print(f'  {len(arr)} samples, max radius flown {rad.max():.2f} m, '
              f'max pose age {arr[:, 3].max():.2f} s')
        print(f"\n  {'radius band':>14} {'samples':>8} {'worst pose age':>15}")
        for lo in np.arange(0.5, max(args.r_max, float(rad.max())) + 0.25, 0.25):
            m = (rad >= lo) & (rad < lo + 0.25)
            if m.any():
                print(f'  {lo:5.2f}-{lo+0.25:5.2f} m {int(m.sum()):>8} '
                      f'{arr[m, 3].max():>14.2f} s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
