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
* the VIP: ``vip_mode`` point | mocap | manual, ``vip_name`` (mocap rigid
  body, default ``operator``), ``vip_point`` [x, y, z].
* every :class:`~crazyflie_shows.guard.config.GuardConfig` field by name
  (``-p v_max_attack:=1.2 -p tagging:=false -p ceiling:=4.0``).
* ``dry_run``, ``paced`` (wait for Enter to arm and to start), ``lights``,
  ``seed``, ``check_placement``.

What is shared with the escort, and why it is not copied: the /poses cache,
the setpoint stream helpers and the operator gates (escort_show), the room
helpers and the per-drone containment watchdog (escort), the abort and the
supervisor go/no-go (abort, preflight). One implementation of each.
"""

import sys
from dataclasses import fields

import numpy as np
import rclpy
from crazyflie_py import Crazyswarm

from crazyflie_shows import escort, safety
from crazyflie_shows.abort import ShowAborted, abort_land, take_signals
from crazyflie_shows.constellation import LIGHT
from crazyflie_shows.constellation_show import cue
from crazyflie_shows.escort_show import (LAND_DURATION, LAND_HEIGHT,
                                         TAKEOFF_DURATION, TAKEOFF_HEIGHT,
                                         PointCache, PoseCache, _clock, _live,
                                         _stream, operator_gate)
from crazyflie_shows.escort_teleop import VIP_TOPIC
from crazyflie_shows.guard import policies, safety_layer
from crazyflie_shows.guard.config import GuardConfig, override, problems
from crazyflie_shows.guard.engine import Match
from crazyflie_shows.guard.viz import GuardViz
from crazyflie_shows.guard.world import ATTACK, DEFENSE
from crazyflie_shows.plan_guard import _kv, mark_problems, vip_mark
from crazyflie_shows.preflight import report_supervisor
from crazyflie_shows.swarm_show import _param, check_placement, wait_for_mocap

LED_DEFENSE = LIGHT['deep_blue']
LED_ATTACK = LIGHT['red']
LED_OUT = LIGHT['amber']


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
    print(f'  rules         {"tag" if cfg.tagging else "deny"}: strike '
          f'{cfg.strike_radius:.2f} m/{cfg.strike_time:.1f} s, tag '
          f'{cfg.tag_radius:.2f} m/{cfg.tag_time:.1f} s, {cfg.duration:.0f} s')
    print(f'  speeds        defence {cfg.v_max_defense:.2f}, attack '
          f'{cfg.v_max_attack:.2f}, safety cap {cfg.v_max_safety:.2f} m/s; band '
          f'{cfg.floor:.2f}..{cfg.ceiling:.2f} m')
    bad = problems(cfg)
    if vip_mode != 'mocap':
        more, _ = mark_problems(cfg, vip_point, marks, D, A)
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
        more, _ = mark_problems(cfg, poses.pos[vip_name], marks, D, A)
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
    armed = streaming = False
    match = None
    streamed = set()
    try:
        take_signals()
        armed = True
        if paced:
            operator_gate('ARM and take off? Everyone clear of the volume, '
                          'E-STOP in hand.',
                          spin=lambda: rclpy.spin_once(node, timeout_sec=0.02))
        for n in flying:
            fcfs[n].arm(True)
        timeHelper.sleep(1.0)
        if lights_on:
            for n in D:
                cue(allcfs, [fcfs[n]], [LED_DEFENSE])
            for n in A:
                cue(allcfs, [fcfs[n]], [LED_ATTACK])
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
        match = Match(cfg, dpol, apol, seeds, D, A, p_vip,
                      np.random.default_rng(seed))
        viz = GuardViz(node)
        vel = escort.VelocityEstimator()
        watch = {n: {} for n in flying}

        def stream_hold():
            """Keep every flying drone fed on its current setpoint."""
            for n in flying:
                if n in streamed or match.agents[n].active:
                    _stream(fcfs[n], match.sp[n], np.zeros(3))
                    streamed.add(n)

        def pump():
            rclpy.spin_once(node, timeout_sec=0.0)
            stream_hold()
            timeHelper.sleepForRate(cfg.rate_hz)

        streaming = True
        if paced:
            operator_gate('START the match?', pump=pump)
        t0 = timeHelper.time()
        print(f'  MATCH LIVE   t0 = {_clock()}   streaming at {cfg.rate_hz:g} Hz\n')
        last = t0
        min_live = np.inf
        while True:
            rclpy.spin_once(node, timeout_sec=0.0)
            now = timeHelper.time()
            dt = max(now - last, 1e-3)
            last = now

            p_vip = vip_now(now)
            if p_vip is None:
                if vip_age(now) > cfg.vip_stale_land_s:
                    raise ShowAborted(f'VIP pose lost for {vip_age(now):.1f} s')
                stream_hold()                   # hold still until it is back
                timeHelper.sleepForRate(cfg.rate_hz)
                continue
            v_vip = vel.update(p_vip, dt)

            # per-drone watchdog (the escort's): stale, outside, not following
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
            # the aircraft themselves: the CBF holds SETPOINTS apart
            live = [(n, p) for n, p in measured.items()
                    if p is not None and p[2] > 0.3]
            for i, (n1, p1) in enumerate(live):
                for n2, p2 in live[i + 1:]:
                    d = float(np.linalg.norm(p1 - p2))
                    min_live = min(min_live, d)
                    if safety_layer.floor_ratio(cfg, p1, p2) < cfg.near_miss_ratio:
                        raise ShowAborted(f'NEAR MISS {n1}/{n2} {d:.2f} m apart')
            if holding:
                print(f'  [t+{now - t0:5.1f}s] HOLD -- {"; ".join(holding)}', flush=True)
                stream_hold()
                timeHelper.sleepForRate(cfg.rate_hz)
                continue

            tk = match.step(dt, p_vip, v_vip, measured or None)
            for n, (sp, v) in tk.setpoints.items():
                _stream(fcfs[n], sp, v)
                streamed.add(n)
            for n in tk.retired:
                fcfs[n].notifySetpointsStop()
                streamed.discard(n)
                fcfs[n].land(targetHeight=LAND_HEIGHT, duration=LAND_DURATION)
                if lights_on:
                    cue(allcfs, [fcfs[n]], [LED_OUT])
            for e in tk.events:
                print(f'  [{_clock()}] {e}', flush=True)
            if tk.safety is not None and tk.safety.emergency:
                print(f'  [t+{match.t:5.1f}s] CBF emergency push-apart', flush=True)
            res = match.result()
            viz.publish(match.t, cfg, p_vip, match.agents, tk.labels, res,
                        f'{dname} v {aname}')
            if res.winner:
                break
            timeHelper.sleepForRate(cfg.rate_hz)

        # ------------------------------------------------------------ land
        print(f'\n  {res.winner.upper()} WINS -- {res.reason} '
              f'(t+{res.t:.1f}s, strikes {res.strikes}, tags {res.tags})')
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
        _report(match, min_live)
        return 0

    except ShowAborted as e:
        if armed:
            _stop(fcfs, streamed if streaming else ())
            abort_land(allcfs, cfs, timeHelper, LAND_HEIGHT, str(e))
        else:
            print(f'\n  ended before arming: {e}\n', flush=True)
        if match is not None:
            _report(match, np.inf)
        return 130
    except BaseException as e:                         # noqa: BLE001
        if armed:
            _stop(fcfs, streamed if streaming else ())
            abort_land(allcfs, cfs, timeHelper, LAND_HEIGHT, repr(e))
        raise


def _stop(fcfs, streamed):
    """Hand streamed drones back to the high-level commander before landing."""
    for n in streamed:
        try:
            fcfs[n].notifySetpointsStop()
        except Exception:                               # noqa: BLE001
            pass


def _report(match, min_live):
    s = match.stats
    print(f'\n  SAFETY LAYER  {s["ticks"]} ticks; corrected {s["corrected"]} '
          f'drone-ticks; emergency {s["emergency"]}; not converged '
          f'{s["not_converged"]}; backstop {s["backstop"]}')
    if np.isfinite(min_live):
        print(f'  closest pair  {min_live:.2f} m measured (floor '
              f'{match.cfg.min_separation:.2f} across)')
    for e in match.referee.events:
        print(f'    {e}')
    print(flush=True)


if __name__ == '__main__':
    sys.exit(main())
