"""The form-up follows the VIP, and the "not following" watchdog allows for lag.

Both from the 17-11 hardware flights: the form-up laid its ring round where the
DJI was at the gate and never moved it, and every match at 1 m/s aborted
seconds after START because the aircraft (~0.6 s behind their setpoints) read
as 0.6 m "not following".
"""
import dataclasses

import numpy as np

from crazyflie_shows import escort
from crazyflie_shows.guard import formation
from crazyflie_shows.guard import rules as rule_sets
from crazyflie_shows.guard.config import GuardConfig
from crazyflie_shows.plan_guard import mark_problems, recommend_marks, vip_mark

DT = 0.05


def _fly(cfg, aircraft, setpoint, seconds):
    """Feed contain_check; return the first 'land' reason, or None."""
    st = {}
    for k in range(int(seconds / DT)):
        t = k * DT
        act, why = escort.contain_check(cfg, aircraft(t), 0.0, setpoint(t), DT, st)
        if act == 'land':
            return t, why
    return None


def _ramp(t, v=1.0):
    return np.array([-2.0 + v * t, 0.0, 1.0])


def test_a_lagging_drone_at_full_speed_is_following():
    cfg = GuardConfig()
    lag = 0.6
    # 3 s at 1 m/s, the aircraft exactly `lag` behind its setpoint
    assert _fly(cfg, lambda t: _ramp(max(t - lag, 0.0)), _ramp, 3.0) is None
    # the old rule (current setpoint only) called that "not following"
    old = dataclasses.replace(cfg, track_lag_s=0.0)
    assert _fly(old, lambda t: _ramp(max(t - lag, 0.0)), _ramp, 3.0) is not None


def test_a_drone_that_stops_while_its_command_moves_on_still_trips():
    cfg = GuardConfig()
    got = _fly(cfg, lambda t: _ramp(0.0), _ramp, 4.0)
    assert got is not None and 'not following' in got[1]
    # 0.6 m beyond the oldest remembered setpoint, then 0.8 s of it
    assert got[0] <= cfg.track_error_m + cfg.track_lag_s + cfg.track_error_s + 0.2


def test_a_drone_flying_off_sideways_still_trips():
    cfg = GuardConfig()
    hover = np.array([0.0, 0.0, 1.0])
    got = _fly(cfg, lambda t: hover + [0.0, 0.5 * t, 0.0], lambda t: hover, 4.0)
    assert got is not None


def _setup(attackers='follow'):
    cfg = GuardConfig()
    rules = rule_sets.make('pressure')
    vip = vip_mark(cfg)
    D, A = ['D1', 'D2', 'D3', 'D4'], ['A1', 'A2', 'A3']
    marks = recommend_marks(cfg, vip, len(D), len(A))
    pos = {n: np.r_[marks[n][:2], cfg.start_height] for n in D + A}
    f = formation.Follow(cfg, rules, D, A,
                         lambda g, v, reach=True: mark_problems(
                             cfg, rules, v, g, D, A, reach=reach)[0],
                         {'attackers': attackers})
    return cfg, rules, vip, D, A, pos, f


def test_the_formation_moves_with_the_vip():
    cfg, rules, vip, D, A, pos, f = _setup()
    ok, why = f.build(vip, pos)
    assert ok, why
    g0 = f.goals(vip, pos)
    # the 17-11 flight: the pilot moved the DJI ~1.4 m after the gate
    moved = vip + np.array([-0.1, -1.4, 0.0])
    g1 = f.goals(moved, pos)
    if f.rebuilds == 0:
        for n in g0:
            np.testing.assert_allclose(g1[n][:2] - g0[n][:2], [-0.1, -1.4], atol=1e-9)
    for d in D:
        assert abs(np.linalg.norm(g1[d][:2] - moved[:2]) - f.p['r_def']) < 1e-6 \
            or f.rebuilds
    assert not mark_problems(cfg, rules, moved, g1, D, A)[0]


def test_walked_into_a_wall_the_formation_is_laid_out_again():
    cfg, rules, vip, D, A, pos, f = _setup()
    assert f.build(vip, pos)[0]
    # walk the VIP towards the room centre's far side until the rigid layout
    # no longer fits; every goal handed out must still pass the start checks
    c = np.asarray(cfg.room_center, float)[:2]
    away = (vip[:2] - c)
    away = away / (np.linalg.norm(away) or 1.0)
    held = 0
    for k in range(1, 45):
        v = vip.copy()
        v[:2] = vip[:2] - away * 0.1 * k
        g = f.goals(v, pos)
        if not mark_problems(cfg, rules, v, g, D, A)[0]:
            continue
        # nothing fits here at all: the last good goals are held
        assert g is f.last
        held += 1
    assert f.rebuilds > 0 and held > 0


def _away(vip, pos, A):
    c = np.mean([pos[a][:2] for a in A], axis=0)
    return c, (vip[:2] - c) / np.linalg.norm(vip[:2] - c)


def test_held_attackers_stay_put_while_the_defenders_follow():
    # 2026-11-23: the pilot flew the DJI away from the attackers to open a
    # gap and the attackers came along (cf10 5.7 m, round to the far side)
    cfg, rules, vip, D, A, pos, f = _setup('hold')
    assert f.hold
    ok, why = f.build(vip, pos)
    assert ok, why
    start = {a: pos[a].copy() for a in A}
    _, away = _away(vip, pos, A)
    for k in range(1, 30):
        v = vip.copy()
        v[:2] = vip[:2] + away * 0.05 * k
        g = f.goals(v, pos)
        for a in A:
            np.testing.assert_allclose(g[a][:2], start[a][:2], atol=1e-9)
        # every goal handed out passes the safety-side start checks
        assert not mark_problems(cfg, rules, v, g, D, A, reach=False)[0]
    # the defenders went with the VIP
    for d in D:
        assert abs(np.linalg.norm(g[d][:2] - v[:2]) - f.p['r_def']) < 1e-6


def test_held_attackers_too_close_is_reported_then_clears_as_the_vip_moves_away():
    cfg, rules, vip, D, A, pos, f = _setup('hold')
    c, away = _away(vip, pos, A)
    # the VIP close to the attackers: a 1.8 m ring cannot be fair there
    near = vip.copy()
    near[:2] = c + away * 2.6
    ok, why = f.build(near, pos)
    assert ok, why
    assert f.unfair(near), "a defender should be inside an attacker's reach"
    v = near.copy()
    for k in range(1, 60):
        v[:2] = near[:2] + away * 0.05 * k
        f.goals(v, pos)
        if not f.unfair(v):
            break
    assert not f.unfair(v), 'moving the VIP away never made the start fair'


def test_follow_mode_never_reports_an_unfair_start():
    cfg, rules, vip, D, A, pos, f = _setup('follow')
    assert f.build(vip, pos)[0]
    assert f.unfair(vip) == []


def test_unknown_attacker_mode_is_refused():
    import pytest
    with pytest.raises(ValueError):
        formation.params_of({'attackers': 'chase'})
