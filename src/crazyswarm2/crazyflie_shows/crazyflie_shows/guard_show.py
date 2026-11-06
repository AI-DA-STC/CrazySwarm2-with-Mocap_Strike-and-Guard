#!/usr/bin/env python3
"""Fly the guard show: N defenders against M attackers, strategies plugged in.

    # ALWAYS the planner, then sim, first
    ros2 run crazyflie_shows plan_guard --defenders 4 --attackers 3
    ros2 launch crazyflie launch.py backend:=sim
    ros2 run crazyflie_shows guard_show --ros-args -p use_sim_time:=true

    # hardware: scan, sync the marks, plan_guard --marks, dry run, THEN
    ros2 run crazyflie_shows guard_show --ros-args -p dry_run:=true
    ros2 run crazyflie_shows guard_show --ros-args \\
        -p defenders:=cf1,cf2,cf3,cf4 -p attackers:=cf5,cf6,cf7 \\
        -p defense:=shell -p attack:=coordinated -p vip_mode:=mocap

Every tick runs :class:`crazyflie_shows.guard.engine.Match` -- the code
``plan_guard`` verifies -- on live mocap: the strategies ask, the safety
layer (AirStack's CBF, ported) decides, the referee judges, and this script
streams the setpoints and lands whoever is tagged or strikes.

Parameters, all ``-p name:=value``:

* roles: ``defenders`` / ``attackers`` (comma-separated names) or, if both
  are empty, ``n_attackers`` (default 3): the drones parked FURTHEST from the
  VIP attack, the rest defend.
* strategies: ``defense`` (default shell), ``attack`` (default coordinated),
  ``policy_module`` (import your own), ``defense_params`` /
  ``attack_params`` as ``key=value,key=value``.
* rules: ``rules`` (default tag; ``plan_guard --list`` names them) and
  ``rules_params`` as ``key=value,key=value``.
* the VIP: ``vip_mode`` point | mocap | manual, ``vip_name`` (mocap rigid
  body, default ``operator``), ``vip_point`` [x, y, z].
* every :class:`~crazyflie_shows.guard.config.GuardConfig` field by name
  (``-p v_max_attack:=1.2 -p min_separation:=0.6 -p ceiling:=4.0``).
* ``dry_run``, ``paced`` (wait for Enter to arm and to start), ``lights``,
  ``seed``, ``check_placement``.
* the end: ``finale`` (default true; guard/finale.py -- winners rally round
  the VIP and emote, losers go dark and home) and ``finale_params`` as
  ``key=value,key=value``.
* ``role_lights`` (default true): mid-match LED cues -- white while a drone is
  scoring (a defender tagging, an attacker in the strike zone), magenta for a
  decoy, dark once out of play.
* ``controller`` (default ``pid``: leave the server's setting): ``mellinger``
  switches the flying drones' onboard controller (``stabilizer.controller``
  2) before arming and back to PID (1) afterwards, landing or abort. Why:
  the PID position controller OVERWRITES the streamed velocity in modeAbs,
  so on hardware every drone trailed its setpoint by ~0.56 s (0.5-0.7 m at
  1 m/s, 2026-11-06); Mellinger uses the full state. Hover-test it on the
  drones before a match: the simulator always runs Mellinger, so it cannot
  show the difference.
* ``trace`` (default true): every tick's measured and commanded position,
  phase and intent per drone, as guard_trace.csv in the flight's folder
  ($FLIGHT_LOG_DIR, set by the console and scripts/record_flight.sh; else a
  new folder under ~/.ros/flight_logs/) -- the evidence for any near miss.

Gates (``paced:=true``): ARM and take off; with ``vip_mode:=mocap``, the
PILOT takes the DJI off; START the match; the finale (no gate); at the end,
the pilot lands the DJI (mocap) or you confirm the landing. While a gate waits, every drone holds
through the safety layer -- it still dodges the DJI -- and every watchdog
runs. The match itself has no legs and so no gates inside it.

What is shared with the escort, and why it is not copied: the /poses cache,
the setpoint stream helpers and the operator gates (escort_show), the room
helpers and the per-drone containment watchdog (escort), the abort and the
supervisor go/no-go (abort, preflight). One implementation of each.
"""

import os
import sys
import time
from dataclasses import fields

import numpy as np
import rclpy
from crazyflie_py import Crazyswarm

from crazyflie_shows import escort, safety
from crazyflie_shows.abort import ShowAborted, abort_land, take_signals
from crazyflie_shows.constellation import LIGHT, wrgb
from crazyflie_shows.constellation_show import cue
from crazyflie_shows.escort_show import (LAND_DURATION, LAND_HEIGHT,
                                         TAKEOFF_DURATION, TAKEOFF_HEIGHT,
                                         PointCache, PoseCache, _clock, _live,
                                         _stream, drain, drain_count,
                                         operator_gate)
from crazyflie_shows.escort_teleop import VIP_TOPIC
from crazyflie_shows.guard import finale as finale_mod
from crazyflie_shows.guard import policies
from crazyflie_shows.guard import rules as rule_sets
from crazyflie_shows.guard.config import GuardConfig, override, problems
from crazyflie_shows.guard.engine import Match
from crazyflie_shows.guard.viz import GuardViz
from crazyflie_shows.guard.watch import LAND, PAUSE, NearMissWatch
from crazyflie_shows.guard.world import ATTACK, DEFENSE
from crazyflie_shows.plan_guard import _kv, mark_problems, vip_mark
from crazyflie_shows.preflight import report_supervisor
from crazyflie_shows.swarm_show import _param, check_placement, wait_for_mocap

LED_DEFENSE = LIGHT['deep_blue']
LED_ATTACK = LIGHT['red']
#: Out of play: DARK. It was amber, which reads as red across a room (the
#: escort found the same, 2026-10-06), so a downed attacker looked live.
LED_OUT = 0
#: Scoring right now: a defender tagging, an attacker inside the strike zone.
LED_SCORING = LIGHT['blocker']
LED_DECOY = LIGHT['magenta']
LED_WIN = wrgb(g=0xFF)
TEAM_LED = {'defense': LED_DEFENSE, 'attack': LED_ATTACK}


class Lights:
    """LED cues that only go out when the colour CHANGES, at most one per
    drone every ``gap`` s (each is a radio packet amid 20 Hz streaming; a
    change that comes too soon is simply sent on a later tick)."""

    def __init__(self, allcfs, fcfs, on, gap=0.25):
        self.allcfs, self.fcfs, self.on, self.gap = allcfs, fcfs, on, gap
        self.cur, self.last = {}, {}

    def set(self, name, value, now=None):
        if not self.on or self.cur.get(name) == value:
            return
        now = time.monotonic() if now is None else now
        if now - self.last.get(name, -1e9) < self.gap:
            return
        cue(self.allcfs, [self.fcfs[name]], [value])
        self.cur[name], self.last[name] = value, now


def role_light(a, intent, meters, agents, rules):
    """The mid-match cue for one active drone."""
    m = meters.get(a.name, {})
    if a.team == ATTACK:
        if m.get('strike', 0.0) > 0.0:
            return LED_SCORING
        if intent is not None and intent.kind == 'decoy':
            return LED_DECOY
        return LED_ATTACK
    if intent is not None and intent.target in agents:
        t = agents[intent.target]
        if (t.active and meters.get(t.name, {}).get('down', 0.0) > 0.0
                and float(np.linalg.norm(t.p - a.p)) <= max(rules.reach, 1e-6)):
            return LED_SCORING
    return LED_DEFENSE


class Trace:
    """Every tick's measured and commanded position per drone, as CSV."""

    def __init__(self, on):
        self.fh = None
        if not on:
            return
        try:
            # the flight's own folder when a recorder made one (the console,
            # scripts/record_flight.sh), else a folder of its own
            d = os.environ.get('FLIGHT_LOG_DIR') or os.path.join(
                os.path.expanduser(os.environ.get('FLIGHT_LOG_ROOT', '~/.ros/flight_logs')),
                time.strftime('%Y%m%d_%H%M%S_guard_show'))
            os.makedirs(d, exist_ok=True)
            self.path = os.path.join(d, 'guard_trace.csv')
            self.fh = open(self.path, 'w', encoding='utf-8')
            self.fh.write('t,phase,name,team,status,mx,my,mz,sx,sy,sz,intent\n')
        except OSError as e:
            print(f'  (trace off: {e})')
            self.fh = None

    def write(self, t, phase, match, measured, intents):
        if self.fh is None:
            return
        try:
            for n, a in match.agents.items():
                m = measured.get(n)
                mm = ',,' if m is None else ','.join(f'{v:.4f}' for v in m)
                sp = ','.join(f'{v:.4f}' for v in match.sp[n])
                it = intents.get(n)
                self.fh.write(f'{t:.3f},{phase},{n},{a.team},{a.status},{mm},{sp},'
                              f'{it.kind if it is not None else ""}\n')
        except Exception:                               # noqa: BLE001
            pass

    def close(self):
        if self.fh is not None:
            self.fh.close()
            print(f'  trace         {self.path}')
            self.fh = None


def _names(node, name):
    return [n for n in str(_param(node, name, '')).replace(' ', '').split(',') if n]


def _params_kv(text):
    return _kv([x for x in str(text).split(',') if x.strip()])


def _cfg_from_params(node):
    cfg = GuardConfig()
    vals = {}
    for f in fields(cfg):
        cur = getattr(cfg, f.name)
        if isinstance(cur, tuple):
            continue                      # room_center comes from arena.yaml
        vals[f.name] = _param(node, f.name, cur)
    return override(cfg, vals)


class _Starts:
    """``check_placement`` wants a plan; all it reads is ``.starts``."""

    def __init__(self, cfs):
        self.starts = [np.array(cf.initialPosition, float) for cf in cfs]


def main():
    safety.require_measured_arena('guard_show')
    swarm = Crazyswarm()
    timeHelper = swarm.timeHelper
    allcfs = swarm.allcfs
    node = allcfs
    cfs = allcfs.crazyflies
    names = [cf.prefix.lstrip('/') for cf in cfs]
    idx = {n: i for i, n in enumerate(names)}

    sim = bool(_param(node, 'use_sim_time', False))
    dry_run = bool(_param(node, 'dry_run', False))
    paced = bool(_param(node, 'paced', False))
    lights_on = bool(_param(node, 'lights', not sim))
    want_placement = bool(_param(node, 'check_placement', True))
    seed = int(_param(node, 'seed', 0))
    vip_mode = str(_param(node, 'vip_mode', 'point'))
    vip_name = str(_param(node, 'vip_name', 'operator'))
    cfg = _cfg_from_params(node)
    vip_point = np.array(list(_param(node, 'vip_point', vip_mark(cfg).tolist())), float)
    policies.load_module(str(_param(node, 'policy_module', '')))
    dname = str(_param(node, 'defense', 'shell'))
    aname = str(_param(node, 'attack', 'coordinated'))
    dparams = _params_kv(_param(node, 'defense_params', ''))
    aparams = _params_kv(_param(node, 'attack_params', ''))
    rules = rule_sets.make(str(_param(node, 'rules', 'tag')),
                           _params_kv(_param(node, 'rules_params', '')))
    finale_on = bool(_param(node, 'finale', True))
    fparams = _params_kv(_param(node, 'finale_params', ''))
    role_on = bool(_param(node, 'role_lights', True))
    trace_on = bool(_param(node, 'trace', True))
    controller = str(_param(node, 'controller', 'pid')).lower()
    if controller not in CONTROLLERS:
        raise SystemExit(f'controller must be one of {sorted(CONTROLLERS)}, not {controller!r}')
    if vip_mode not in ('point', 'mocap', 'manual'):
        raise SystemExit(f'vip_mode must be point | mocap | manual, not {vip_mode!r}')

    # ------------------------------------------------------------ who is who
    marks = {n: np.array(cf.initialPosition, float) for n, cf in zip(names, cfs)}
    D, A = _names(node, 'defenders'), _names(node, 'attackers')
    if not D and not A:
        n_att = int(_param(node, 'n_attackers', min(3, max(len(names) - 1, 0))))
        by_dist = sorted(names, key=lambda n: float(
            np.linalg.norm(marks[n][:2] - vip_point[:2])))
        A = by_dist[len(by_dist) - n_att:] if n_att else []
        D = [n for n in by_dist if n not in A]
    missing = [n for n in D + A if n not in idx]
    if missing:
        raise SystemExit(f'{missing} are not enabled in the yaml (enabled: {names})')
    if set(D) & set(A):
        raise SystemExit(f'{sorted(set(D) & set(A))} cannot be on both teams')
    if not D or not A:
        raise SystemExit(f'need at least one defender and one attacker; '
                         f'defenders {D}, attackers {A}')
    flying = D + A
    fcfs = {n: cfs[idx[n]] for n in flying}
    dpol = policies.make(DEFENSE, dname, dparams)
    apol = policies.make(ATTACK, aname, aparams)

    print('\n  GUARD SHOW\n')
    print(f'  defence       {dname} with {", ".join(D)}')
    print(f'  attack        {aname} with {", ".join(A)}')
    print(f'  VIP           {vip_mode} '
          f'{np.round(vip_point, 2).tolist() if vip_mode != "mocap" else vip_name}')
    print(f'  rules         {rules.describe()}: '
          + ', '.join(f'{k} {v}' for k, v in sorted(rules.p.items())))
    print(f'  controller    {controller}'
          + ('' if controller == 'pid' else ' (switched for this show, PID restored after)'))
    print(f'  speeds        defence {cfg.v_max_defense:.2f}, attack '
          f'{cfg.v_max_attack:.2f}, safety cap {cfg.v_max_safety:.2f} m/s; band '
          f'{cfg.floor:.2f}..{cfg.ceiling:.2f} m')
    bad = problems(cfg) + rules.problems(cfg)
    if finale_on:
        bad += finale_mod.check(cfg, fparams)
    if vip_mode != 'mocap':
        more, _ = mark_problems(cfg, rules, vip_point, marks, D, A)
        bad += more
    for b in bad:
        print(f'  *** {b}')
    if bad:
        raise SystemExit('\n  REFUSED (plan_guard reproduces this with no drones).\n')
    idle = [n for n in names if n not in flying]
    if idle:
        print(f'  grounded (no role): {", ".join(idle)}')

    # ------------------------------------------------------------- preflight
    poses = PoseCache(node)
    manual_vip = PointCache(node, VIP_TOPIC) if vip_mode == 'manual' else None
    if vip_mode == 'mocap':
        print(f'  waiting for the VIP rigid body {vip_name!r} on /poses')
        deadline = timeHelper.time() + 10.0
        while timeHelper.time() < deadline and vip_name not in poses.pos:
            rclpy.spin_once(node, timeout_sec=0.1)
        if vip_name not in poses.pos:
            raise SystemExit(f'  no /poses entry for {vip_name!r}.\n')
        more, _ = mark_problems(cfg, rules, poses.pos[vip_name], marks, D, A)
        for b in more:
            print(f'  *** {b}')
        if more:
            raise SystemExit('\n  REFUSED: the drones are too close to the VIP.\n')
    if manual_vip is not None:
        print(f'  waiting for the VIP teleop on {VIP_TOPIC}')
        deadline = timeHelper.time() + 20.0
        while timeHelper.time() < deadline and manual_vip.pos is None:
            rclpy.spin_once(node, timeout_sec=0.1)
        if manual_vip.pos is None:
            raise SystemExit(f'\n  nothing is publishing {VIP_TOPIC}.\n')
    if want_placement and not sim:
        print('  MOCAP CHECK (every flying drone must be on /poses)')
        live = wait_for_mocap(node, flying)
        print('  PLACEMENT CHECK (mocap vs initial_position)')
        check_placement(node, [fcfs[n] for n in flying], flying,
                        _Starts([fcfs[n] for n in flying]),
                        float(_param(node, 'placement_tol', 0.25)), live=live)
        print('    all drones within tolerance\n')
    if not sim and not report_supervisor(node, flying):
        return 1
    if dry_run:
        print('  dry_run - checks done; nothing armed.\n')
        return 0

    def vip_now(now):
        if vip_mode == 'point':
            return vip_point.copy()
        if vip_mode == 'manual':
            p = manual_vip.get(now, cfg.vip_stale_hold_s)
            return None if p is None else p + [0.0, 0.0, vip_point[2]]
        return poses.get(vip_name, now, cfg.vip_stale_hold_s)

    def vip_age(now):
        if vip_mode == 'point':
            return 0.0
        return manual_vip.age(now) if vip_mode == 'manual' else poses.age(vip_name, now)

    # ------------------------------------------------------------------ fly
    armed = streaming = switched = False
    match = near = None
    trace = Trace(False)
    streamed = set()
    try:
        take_signals()
        armed = True
        if paced:
            operator_gate('ARM and take off? Everyone clear of the volume, '
                          'E-STOP in hand.',
                          spin=lambda: rclpy.spin_once(node, timeout_sec=0.02))
        if controller != 'pid':
            set_controller(fcfs, flying, CONTROLLERS[controller])
            switched = True
        for n in flying:
            fcfs[n].arm(True)
        timeHelper.sleep(1.0)
        leds = Lights(allcfs, fcfs, lights_on)
        for n in flying:
            leds.set(n, LED_DEFENSE if n in D else LED_ATTACK, 0.0)
        for n in flying:
            fcfs[n].takeoff(targetHeight=TAKEOFF_HEIGHT, duration=TAKEOFF_DURATION)
        timeHelper.sleep(TAKEOFF_DURATION + 0.5)

        # lift straight up off the marks to the start height: the marks were
        # checked apart on the ground, so a vertical leg cannot close a pair
        starts = {n: np.array([marks[n][0], marks[n][1], cfg.start_height])
                  for n in flying}
        lift = max(3.0, (cfg.start_height - TAKEOFF_HEIGHT) / 0.3)
        print(f'  lifting to {cfg.start_height:.2f} m ({lift:.1f} s)')
        for n in flying:
            fcfs[n].goTo(starts[n], 0.0, lift)
        timeHelper.sleep(lift + 0.5)
        rclpy.spin_once(node, timeout_sec=0.05)
        now = timeHelper.time()
        seeds = {}
        for n in flying:
            p, ok = _live(poses, n, fcfs[n], now, expect=starts[n], tol=0.5)
            if not ok:
                print(f'    {n}: no believable live pose -- seeding from its '
                      f'start {"(expected in sim)" if sim else "*** CHECK MOCAP ***"}')
            seeds[n] = p
        p_vip = vip_now(now)
        if p_vip is None:
            raise ShowAborted('no fresh VIP pose at the start')
        match = Match(cfg, rules, dpol, apol, seeds, D, A, p_vip,
                      np.random.default_rng(seed))
        # Callbacks to drain per tick: /poses (50 Hz) plus each drone's own
        # /cfN/pose (10 Hz) and /cfN/status (1 Hz) that crazyflie_py subscribes
        # to, twice over for slack.
        spins = drain_count(len(cfs), cfg.rate_hz)
        viz = GuardViz(node, trail=20, bodies=False)   # real drones are in the picture; 2 s trails at 10 Hz
        # Markers at ~10 Hz, not every tick: a picture needs no more, and RViz
        # and the console redraw every marker for every message (the console
        # fell 3.3 s behind at 20 Hz, 2026-11-06). Events between two
        # publishes are carried to the next one, so no burst is lost.
        viz_every = max(1, int(round(cfg.rate_hz / 10.0)))
        vz = {'n': 0, 'events': []}

        def viz_due(final=False):
            vz['n'] += 1
            return final or vz['n'] % viz_every == 0
        vel = escort.VelocityEstimator()
        watch = {n: {} for n in flying}
        near = NearMissWatch(cfg)
        trace = Trace(trace_on)
        clk = {'last': timeHelper.time(), 't0': timeHelper.time()}
        vip_last = {'p': np.asarray(p_vip, float).copy()}
        title = f'{dname} v {aname} | {rules.name}'

        def tick_clock():
            drain(node, spins)
            now = timeHelper.time()
            dt = max(now - clk['last'], 1e-3)
            clk['last'] = now
            return now, dt

        def vip_fresh(now, dt):
            """(VIP position, velocity, fresh?). A stale VIP is held at its
            last pose until vip_stale_land_s, then the show lands."""
            p = vip_now(now)
            if p is None:
                if vip_age(now) > cfg.vip_stale_land_s:
                    raise ShowAborted(f'VIP pose lost for {vip_age(now):.1f} s')
                return vip_last['p'], np.zeros(3), False
            vip_last['p'] = np.asarray(p, float).copy()
            return vip_last['p'], vel.update(p, dt), True

        def observe(now, dt):
            """The watchdogs, every tick, gates included:
            (measured, holding, near-miss verdict).

            Per drone (the escort's contain_check): stale mocap, outside the
            room, not following its setpoint. Then the aircraft themselves:
            the CBF holds SETPOINTS apart, guard/watch.py checks the measured
            pairs -- a hard near miss lands everything (raised here), a soft
            one pauses the match (the caller holds). A drone whose mocap
            jumped is flown on its setpoint for that tick.
            """
            measured, holding = {}, []
            for n in flying:
                a = match.agents[n]
                if n not in poses.stamp:
                    if not sim:
                        raise ShowAborted(f'{n}: never seen on /poses')
                    continue
                measured[n] = poses.get(n, now, cfg.self_stale_s)
                if not a.active:
                    continue
                act, why = escort.contain_check(cfg, poses.pos.get(n),
                                                poses.age(n, now), match.sp[n],
                                                dt, watch[n])
                if act == 'land':
                    raise ShowAborted(f'CONTAINMENT {n}: {why}')
                if act == 'hold':
                    holding.append(f'{n}: {why}')
            g0 = near.glitches
            nm = near.update(now - clk['t0'], measured,
                             {n: match.sp[n] for n in flying})
            if near.glitches > g0:
                print(f'  [t+{now - clk["t0"]:5.1f}s] MOCAP GLITCH -- a pose jumped '
                      f'over {cfg.mocap_jump_m:.2f} m in one tick; flying '
                      f'{", ".join(sorted(nm.glitched))} on setpoints', flush=True)
            if nm.action == LAND:
                raise ShowAborted(nm.why)
            if nm.why:
                print(f'  [t+{now - clk["t0"]:5.1f}s] {nm.why}', flush=True)
            for n in nm.glitched:
                measured[n] = None
            return measured, holding, nm

        def stream(setpoints):
            for n, (sp, v) in setpoints.items():
                _stream(fcfs[n], sp, v)
                streamed.add(n)

        def hold_tick():
            """One paused tick: the drones hold where they are THROUGH the
            safety layer (so they still dodge the DJI and keep their spacing),
            every watchdog runs, the match clock does not. Used by every gate
            and whenever the match itself has to pause."""
            now, dt = tick_clock()
            p, v, _ = vip_fresh(now, dt)
            measured, _, _ = observe(now, dt)
            stream(match.hold(dt, p, v, measured or None))
            trace.write(now - clk['t0'], 'hold', match, measured, {})
            if viz_due():
                viz.publish(match.t, cfg, rules, p, match.agents, {}, match.result(),
                            f'{title} | HOLDING', match.referee.meters,
                            corrected=match.corrected)
            timeHelper.sleepForRate(cfg.rate_hz)

        streaming = True
        if paced and vip_mode == 'mocap':
            # FIRST IN: the Crazyflies are up and holding; the DJI goes up
            # into a volume whose every drone is already dodging it.
            operator_gate('PILOT: take off the DJI now and bring it to the VIP '
                          'spot. The drones hold and dodge it. Continue when it '
                          'is steady.', pump=hold_tick)
        if paced:
            operator_gate('START the match?', pump=hold_tick)
        clk['t0'] = timeHelper.time()
        print(f'  MATCH LIVE   t0 = {_clock()}   streaming at {cfg.rate_hz:g} Hz\n')
        intents = {}
        while True:
            now, dt = tick_clock()
            p_vip, v_vip, fresh = vip_fresh(now, dt)
            measured, holding, nm = observe(now, dt)
            if not fresh or holding or nm.action == PAUSE:
                if holding:
                    print(f'  [t+{now - clk["t0"]:5.1f}s] HOLD -- {"; ".join(holding)}',
                          flush=True)
                stream(match.hold(dt, p_vip, np.zeros(3), measured or None))
                trace.write(now - clk['t0'], 'pause' if nm.action == PAUSE else 'hold',
                            match, measured, intents)
                if viz_due():
                    viz.publish(match.t, cfg, rules, p_vip, match.agents, {},
                                match.result(),
                                f'{title} | {"SAFETY PAUSE" if nm.action == PAUSE else "HOLDING"}',
                                match.referee.meters, corrected=match.corrected)
                timeHelper.sleepForRate(cfg.rate_hz)
                continue

            tk = match.step(dt, p_vip, v_vip, measured or None)
            intents = tk.intents
            stream(tk.setpoints)
            res = match.result()
            for n in tk.retired:
                if (finale_on and res.winner == ATTACK
                        and match.agents[n].outcome == 'struck'):
                    # the winning blow: it stays up, for the finale's capture
                    match.reinstate(n, match.sp[n])
                    continue
                fcfs[n].notifySetpointsStop()
                streamed.discard(n)
                fcfs[n].land(targetHeight=LAND_HEIGHT, duration=LAND_DURATION)
                leds.set(n, LED_OUT, 1e9)            # always: out of play is final
            for e in tk.events:
                line = str(e)
                if match.agents[e.who].active:          # reinstated, see above
                    line = line.replace('-- it lands', '-- it stays up for the finale')
                print(f'  [{_clock()}] {line}', flush=True)
            if tk.safety is not None and tk.safety.emergency:
                print(f'  [t+{match.t:5.1f}s] CBF emergency push-apart', flush=True)
            if role_on:
                for n, a in match.agents.items():
                    if a.active:
                        leds.set(n, role_light(a, intents.get(n), match.referee.meters,
                                               match.agents, rules))
            trace.write(now - clk['t0'], 'match', match, measured, intents)
            vz['events'].extend(tk.events)
            if viz_due(final=bool(res.winner)):
                viz.publish(match.t, cfg, rules, p_vip, match.agents, tk.labels, res,
                            title, match.referee.meters, intents, tk.plans,
                            match.corrected, vz['events'])
                vz['events'] = []
            if res.winner:
                break
            timeHelper.sleepForRate(cfg.rate_hz)

        print(f'\n  {res.winner.upper()} WINS -- {res.reason} '
              f'(t+{res.t:.1f}s, strikes {res.strikes}, downs {res.downs})', flush=True)

        # ---------------------------------------------------------- finale
        if finale_on:
            now = timeHelper.time()
            fin = finale_mod.Finale(cfg, res.winner, match.agents, marks,
                                    vip_last['p'], now - clk['t0'], fparams)
            print(f'  FINALE  {fin.banner}: winners {", ".join(fin.winners) or "none"}'
                  f'{"; losers home: " + ", ".join(fin.losers) if fin.losers else ""}',
                  flush=True)
            started = now
            while True:
                now, dt = tick_clock()
                p_vip, v_vip, fresh = vip_fresh(now, dt)
                measured, holding, nm = observe(now, dt)
                fs = fin.update(now - clk['t0'], p_vip, match.agents)
                for n in fs.land:
                    fcfs[n].notifySetpointsStop()
                    streamed.discard(n)
                    fcfs[n].land(targetHeight=LAND_HEIGHT, duration=LAND_DURATION)
                    match.retire(n)
                for n, how in fs.lights.items():
                    leds.set(n, {'win': LED_WIN, 'off': LED_OUT}.get(
                        how, TEAM_LED[match.agents[n].team]))
                if not fresh or holding or nm.action == PAUSE:
                    stream(match.hold(dt, p_vip, np.zeros(3), measured or None))
                else:
                    stream(match.steer(dt, p_vip, v_vip, fs.goals, fin.p['speed'],
                                       measured or None))
                trace.write(now - clk['t0'], f'finale-{fs.phase}', match, measured, {})
                if viz_due(final=fs.done):
                    viz.publish(match.t, cfg, rules, p_vip, match.agents,
                                {n: fs.phase for n in fs.goals}, res,
                                f'{title} | FINALE {fs.phase}', match.referee.meters,
                                corrected=match.corrected, banner=fs.banner)
                if fs.done:
                    break
                if now - started > 60.0:
                    print('  finale ran over 60 s -- landing from where they are',
                          flush=True)
                    break
                timeHelper.sleepForRate(cfg.rate_hz)
            print('  FINALE done -- the winners hold over their marks', flush=True)

        # ------------------------------------------------------------ land
        if paced and vip_mode == 'mocap':
            # LAST OUT is the Crazyflies: the DJI comes down past drones that
            # are still holding and dodging it.
            operator_gate('Match over. PILOT: land the DJI now; the drones hold '
                          'and dodge it. Continue when it is on the ground.',
                          pump=hold_tick)
        elif paced:
            operator_gate('Match over. LAND the drones?', pump=hold_tick)
        for n in flying:
            if n in streamed:
                fcfs[n].notifySetpointsStop()
        streaming = False
        for n in flying:
            if match.agents[n].active:
                fcfs[n].land(targetHeight=LAND_HEIGHT, duration=LAND_DURATION)
        timeHelper.sleep(LAND_DURATION + 0.5)
        for n in flying:
            fcfs[n].arm(False)
        armed = False
        print('  landed and disarmed -- done', flush=True)
        trace.close()
        _report(match, near)
        return 0

    except ShowAborted as e:
        if armed:
            _stop(fcfs, streamed if streaming else ())
            abort_land(allcfs, cfs, timeHelper, LAND_HEIGHT, str(e))
        else:
            print(f'\n  ended before arming: {e}\n', flush=True)
        if match is not None:
            trace.close()
            _report(match, near)
        return 130
    except BaseException as e:                         # noqa: BLE001
        if armed:
            _stop(fcfs, streamed if streaming else ())
            abort_land(allcfs, cfs, timeHelper, LAND_HEIGHT, repr(e))
        raise
    finally:
        if switched:
            # after the landing: every other show expects the server's PID
            set_controller(fcfs, flying, CONTROLLERS['pid'])


#: stabilizer.controller values (crazyflie-firmware controller.h).
CONTROLLERS = {'pid': 1, 'mellinger': 2, 'brescianini': 4}


def set_controller(fcfs, names, value):
    """Set ``stabilizer.controller`` on each drone; never raises (a failed
    restore is reported, it must not stop a landing)."""
    for n in names:
        try:
            fcfs[n].setParam('stabilizer.controller', int(value))
        except Exception as e:                          # noqa: BLE001
            print(f'  *** {n}: could not set stabilizer.controller={value}: {e}',
                  flush=True)
    print(f'  stabilizer.controller = {value} on {", ".join(names)}', flush=True)


def _stop(fcfs, streamed):
    """Hand streamed drones back to the high-level commander before landing."""
    for n in streamed:
        try:
            fcfs[n].notifySetpointsStop()
        except Exception:                               # noqa: BLE001
            pass


def _report(match, near):
    s = match.stats
    print(f'\n  SAFETY LAYER  {s["ticks"]} ticks; corrected {s["corrected"]} '
          f'drone-ticks; emergency {s["emergency"]}; not converged '
          f'{s["not_converged"]}; backstop {s["backstop"]}')
    if near is not None:
        if near.closest is not None:
            print(f'  closest pair  {near.closest}')
        print(f'  near misses   {len(near.passes)}; mocap glitches {near.glitches}')
        for p in near.passes:
            print(f'    {p}')
    for e in match.referee.events:
        print(f'    {e}')
    print(flush=True)


if __name__ == '__main__':
    sys.exit(main())
