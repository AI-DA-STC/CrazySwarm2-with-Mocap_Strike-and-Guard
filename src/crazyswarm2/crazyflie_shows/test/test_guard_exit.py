"""A downed or struck drone exits under command before it is landed (2026-11-19).

It used to be landed on the spot at once: it stopped dead while its neighbours'
aircraft (~0.6 s behind their setpoints) carried on into it, and a hand-flown
DJI could drift over it while it was coming down and could not dodge.
"""
import numpy as np

from crazyflie_shows.guard import rules as rule_sets
from crazyflie_shows.guard.config import GuardConfig, override
from crazyflie_shows.guard.engine import Match
from crazyflie_shows.guard.policies import Policy
from crazyflie_shows.guard.world import ATTACK, DEFENSE, RETIRING

CFG = GuardConfig()
MID = np.array([CFG.room_center[0], CFG.room_center[1], 1.0])
RIM = CFG.d_vip + CFG.exit_land_clear
DT = 0.05


class _StillD(Policy):
    team, name = DEFENSE, 'test_still_d'

    def act(self, view):
        return {}


class _StillA(Policy):
    team, name = ATTACK, 'test_still_a'

    def act(self, view):
        return {}


def _match(cfg, d_at, vip, rules='tag'):
    starts = {'d': d_at, 'a': MID + [3.5, 3.5, 0.0]}
    return Match(cfg, rule_sets.make(rules), _StillD(), _StillA(), starts, ['d'], ['a'],
                 vip, np.random.default_rng(0))


def _retire(m, n, v):
    """What Match.step does when the referee downs a drone at speed v."""
    m.agents[n].status = RETIRING
    m.v[n] = np.asarray(v, float)
    m.exiting[n] = 0.0


def _run_exit(m, vip, n='d', limit=10.0):
    t, seen = 0.0, []
    while t < limit:
        sp = m.hold(DT, vip, np.zeros(3))
        t += DT
        due = m.pop_landing()
        if n in due:
            return t, m.sp[n].copy(), seen
        seen.append(n in sp)
    raise AssertionError('never landed')


def test_a_drone_downed_next_to_the_vip_flies_out_before_it_is_landed():
    vip = MID + [0.0, 0.0, 0.3]
    m = _match(CFG, MID + [1.3, 0.0, 0.0], vip)
    _retire(m, 'd', [-1.0, 0.0, 0.0])          # it was diving at the VIP
    t, where, seen = _run_exit(m, vip)
    assert all(seen)                            # commanded (streamed) all along
    assert t >= CFG.exit_min_s
    assert np.linalg.norm(where[:2] - vip[:2]) >= RIM
    assert np.linalg.norm(m.v['d']) == 0.0


def test_a_drone_downed_in_the_clear_brakes_and_is_landed_after_exit_min_s():
    vip = MID + [0.0, 0.0, 0.3]
    start = MID + [-3.0, 0.0, 0.0]
    m = _match(CFG, start, vip)
    _retire(m, 'd', [1.0, 0.0, 0.0])
    t, where, _ = _run_exit(m, vip)
    assert abs(t - CFG.exit_min_s) < 2 * DT
    # braked at a_max from 1 m/s: 0.25 m, not the 0.6 m its aircraft lags
    assert np.linalg.norm(where - start) < 0.35


def test_exit_min_s_zero_lands_at_once_as_before():
    cfg = override(GuardConfig(), {'exit_min_s': 0.0})   # override() edits in place
    vip = MID + [0.0, 0.0, 0.3]
    # pressure: one defender between two attackers is downed
    starts = {'d': MID + [-3.0, 0.0, 0.0], 'a': MID + [-3.0, 0.9, 0.0],
              'b': MID + [-3.0, -0.9, 0.0]}
    m = Match(cfg, rule_sets.make('pressure'), _StillD(), _StillA(), starts, ['d'],
              ['a', 'b'], vip, np.random.default_rng(0))
    for _ in range(100):
        tk = m.step(DT, vip, np.zeros(3))
        if 'd' in tk.retired:
            assert 'd' not in tk.setpoints and m.pop_landing() == ['d']
            assert 'd' not in m.exiting
            return
    raise AssertionError('never downed')


def test_a_downed_drone_exits_in_a_real_match_and_is_not_a_player():
    vip = MID + [0.0, 0.0, 0.3]
    starts = {'d': MID + [-3.0, 0.0, 0.0], 'a': MID + [-3.0, 0.9, 0.0],
              'b': MID + [-3.0, -0.9, 0.0]}
    m = Match(CFG, rule_sets.make('pressure'), _StillD(), _StillA(), starts, ['d'],
              ['a', 'b'], vip, np.random.default_rng(0))
    for _ in range(100):
        tk = m.step(DT, vip, np.zeros(3))
        if 'd' in tk.retired:
            break
    assert 'd' in m.exiting and not m.agents['d'].active
    tk = m.step(DT, vip, np.zeros(3))
    assert 'd' in tk.setpoints                  # still streamed while it exits
    assert 'd' not in m.pop_landing()


def test_a_reinstated_striker_stops_exiting():
    vip = MID + [0.0, 0.0, 0.3]
    m = _match(CFG, MID + [1.3, 0.0, 0.0], vip)
    _retire(m, 'd', [-1.0, 0.0, 0.0])
    m.hold(DT, vip, np.zeros(3))
    m.reinstate('d', m.sp['d'])
    assert m.agents['d'].active and 'd' not in m.exiting
    for _ in range(200):
        m.hold(DT, vip, np.zeros(3))
        assert 'd' not in m.pop_landing()
