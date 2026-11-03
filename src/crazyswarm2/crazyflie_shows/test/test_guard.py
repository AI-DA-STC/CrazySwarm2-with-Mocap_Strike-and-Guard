"""Tests for the guard engine: the safety layer, the rules, the plug-in contract.

Run from the workspace root:
    PYTHONPATH=src/crazyswarm2/crazyflie_shows python3 -m pytest -q \\
        src/crazyswarm2/crazyflie_shows/test
"""

import numpy as np
import pytest

from crazyflie_shows import escort
from crazyflie_shows.guard import policies, safety_layer
from crazyflie_shows.guard.config import GuardConfig, problems
from crazyflie_shows.guard.engine import Match
from crazyflie_shows.guard.policies import Policy, register
from crazyflie_shows.guard import rules as rule_sets
from crazyflie_shows.guard.rules import Referee
from crazyflie_shows.guard.world import ATTACK, DEFENSE, Agent

CFG = GuardConfig()
MID = np.array([CFG.room_center[0], CFG.room_center[1], 1.5])


def _fly(P, V_nom_fn, steps=200, dt=0.05, fixed=((), (), ())):
    """Integrate positions under the filter; return the closest pair seen."""
    P = np.array(P, float)
    worst = np.inf
    for _ in range(steps):
        res = safety_layer.filter_commands(CFG, P, V_nom_fn(P), *fixed)
        P = P + res.velocities * dt
        for i in range(len(P)):
            for j in range(i + 1, len(P)):
                worst = min(worst, safety_layer.separation_ratio(CFG, P[i], P[j]))
    return worst, P


TAG = rule_sets.make('tag')


def test_default_config_is_consistent():
    assert problems(CFG) == []
    for name in rule_sets.available():
        assert rule_sets.make(name).problems(CFG) == [], name


def test_head_on_pair_never_enters_the_keep_out():
    P = [MID + [-2.0, 0.0, 0.0], MID + [2.0, 0.0, 0.0]]
    worst, _ = _fly(P, lambda P: np.array([[1.0, 0, 0], [-1.0, 0, 0]]))
    assert worst >= 0.98


def test_vertical_stack_is_refused_by_the_tall_keep_out():
    # one drone tries to fly straight down onto another
    P = [MID + [0.0, 0.0, 1.6], MID + [0.0, 0.01, 0.0]]
    worst, _ = _fly(P, lambda P: np.array([[0, 0, -1.0], [0, 0, 0]]))
    assert worst >= 0.98      # held off by the 1.5x taller ellipsoid


def test_fixed_vip_is_never_moved_and_is_avoided():
    vip = MID.copy()
    P = [MID + [-3.0, 0.0, 0.0]]
    fixed = ([vip], [np.zeros(3)], [safety_layer.keep_out(CFG, 'vip')])
    worst = np.inf
    P = np.array(P, float)
    for _ in range(200):
        res = safety_layer.filter_commands(CFG, P, np.array([[1.0, 0, 0]]), *fixed)
        P = P + res.velocities * 0.05
        worst = min(worst, safety_layer.separation_ratio(CFG, P[0], vip, 'vip'))
    assert worst >= 0.98


@pytest.mark.parametrize('heading_deg', range(0, 360, 45))
def test_walls_hold_a_drone_inside_the_room(heading_deg):
    # full speed into the walls, then sliding along them into a corner:
    # every heading meets a different edge or corner, the step included
    h = np.radians(heading_deg)
    push = np.array([[np.cos(h), np.sin(h), 0.4]])
    P = np.array([MID])
    for _ in range(500):
        res = safety_layer.filter_commands(CFG, P, push)
        P = P + res.velocities * 0.05
        _, hit = safety_layer.backstop(CFG, P[0])
        assert not hit
    assert float(escort.room_clearance(CFG, P[0])) >= 0.0
    assert CFG.floor <= P[0, 2] <= CFG.ceiling


def _ticks_to(events_fn, n=200):
    for k in range(n):
        ev = events_fn(k)
        if ev:
            return k + 1, ev
    return None, []


def test_tag_downs_on_time_and_strikes_on_time():
    vip = MID
    ag = {'d': Agent('d', DEFENSE, MID + [3.0, 0, 0], np.zeros(3)),
          'a': Agent('a', ATTACK, MID + [3.0, TAG.reach - 0.05, 0], np.zeros(3)),
          'b': Agent('b', ATTACK, MID + [-TAG.strike_radius + 0.1, 0, 0], np.zeros(3))}
    ref = Referee(TAG)
    events = []
    for k in range(40):
        events += ref.update(0.05 * k, 0.05, ag, vip)
    kinds = {}
    for e in events:
        kinds.setdefault((e.kind, e.who), e)          # the first of each
    assert ('down', 'a') in kinds and ('strike', 'b') in kinds
    # exactly on the clock: 1.1 s = 22 ticks, 1.0 s = 20 ticks
    assert abs(kinds[('down', 'a')].t - 0.05 * 21) < 1e-9
    assert abs(kinds[('strike', 'b')].t - 0.05 * 19) < 1e-9


def test_timer_rules_never_down_anyone():
    ag = {'d': Agent('d', DEFENSE, MID + [3.0, 0, 0], np.zeros(3)),
          'a': Agent('a', ATTACK, MID + [3.0, 0.5, 0], np.zeros(3))}
    ref = Referee(rule_sets.make('timer'))
    assert not any(ref.update(0.05 * k, 0.05, ag, MID) for k in range(60))


def _pressure_rate(n_opp, n_ally, rules=None):
    rules = rules or rule_sets.make('pressure')
    v = MID + [3.0, 0.0, 0.0]
    ring = [v + 0.9 * np.array([np.cos(a), np.sin(a), 0.0])
            for a in np.linspace(0, 2 * np.pi, n_opp + n_ally, endpoint=False)]
    opp = np.array(ring[:n_opp]).reshape(1, -1, 3)
    ally = np.array(ring[n_opp:]).reshape(1, -1, 3)
    return float(rules.down_rates(DEFENSE, v[None], opp, ally, MID)[0]) * rules.down_time


@pytest.mark.parametrize('n_opp,n_ally,want', [
    (0, 0, 0), (1, 0, 0), (2, 0, 1), (3, 0, 2), (2, 1, 0), (3, 1, 1), (3, 2, 0)])
def test_pressure_is_a_graded_local_majority(n_opp, n_ally, want):
    assert _pressure_rate(n_opp, n_ally) == want


def test_pressure_meter_drains_instead_of_resetting():
    rules = rule_sets.make('pressure')
    near = [MID + [3.0, 0.9, 0], MID + [3.0, -0.9, 0]]
    ag = {'d': Agent('d', DEFENSE, MID + [3.0, 0, 0], np.zeros(3)),
          'a1': Agent('a1', ATTACK, near[0], np.zeros(3)),
          'a2': Agent('a2', ATTACK, near[1], np.zeros(3))}
    ref = Referee(rules)
    for k in range(10):                       # 0.5 s of 2 v 1: half full
        ref.update(0.05 * k, 0.05, ag, MID + [-5, 0, 0])
    full = ref.meters['d']['down']
    ag['a2'].p = MID + [3.0, -3.0, 0]         # one attacker leaves: 1 v 1
    ref.update(0.55, 0.05, ag, MID + [-5, 0, 0])
    assert 0.0 < ref.meters['d']['down'] < full


def test_zone_downs_only_on_the_other_teams_ground():
    rules = rule_sets.make('zone')
    home = float(rules.p['home'])
    one = np.zeros((1, 1, 3))
    for team, r, exposed in ((ATTACK, home - 0.5, True), (ATTACK, home + 0.5, False),
                             (DEFENSE, home - 0.5, False), (DEFENSE, home + 0.5, True)):
        v = MID + [r, 0.0, 0.0]
        opp = (v + [0.0, 0.8, 0.0]).reshape(1, 1, 3)
        got = float(rules.down_rates(team, v[None], opp, one[:, :0], MID)[0])
        assert (got > 0) == exposed, (team, r)


def test_downed_defenders_land_and_can_lose_the_match():
    rules = rule_sets.make('pressure')
    ag = {'d': Agent('d', DEFENSE, MID + [3.0, 0, 0], np.zeros(3)),
          'a1': Agent('a1', ATTACK, MID + [3.0, 0.9, 0], np.zeros(3)),
          'a2': Agent('a2', ATTACK, MID + [3.0, -0.9, 0], np.zeros(3))}
    ref = Referee(rules)
    for k in range(40):
        for e in ref.update(0.05 * k, 0.05, ag, MID + [-5, 0, 0]):
            ag[e.who].status = 'retiring'
    assert ag['d'].status == 'retiring'
    assert ref.result(2.0, ag).winner == ATTACK


def test_unknown_rule_parameter_is_an_error():
    with pytest.raises(KeyError):
        rule_sets.make('pressure', {'reech': 1.0})


def test_unknown_strategy_parameter_is_an_error():
    with pytest.raises(KeyError):
        policies.make(DEFENSE, 'shell', {'r_shel': 2.0})


def test_a_strategy_can_be_plugged_in_without_editing_the_package():
    @register
    class Hover(Policy):
        team = ATTACK
        name = 'test_hover'

        def act(self, view):
            return {a.name: np.zeros(3) for a in view.attackers}

    assert 'test_hover' in policies.available(ATTACK)
    assert isinstance(policies.make(ATTACK, 'test_hover'), Hover)


def test_a_strategy_cannot_steer_the_other_team():
    @register
    class Hijack(Policy):
        team = ATTACK
        name = 'test_hijack'

        def act(self, view):
            return {d.name: np.array([5.0, 0, 0]) for d in view.defenders}

    starts = {'d': MID + [2.0, 0, -0.5], 'a': MID + [-3.5, 0, -0.5]}
    m = Match(CFG, TAG, policies.make(DEFENSE, 'ring'),
              policies.make(ATTACK, 'test_hijack'), starts, ['d'], ['a'], MID,
              np.random.default_rng(0))
    for _ in range(20):
        tk = m.step(0.05, MID, np.zeros(3))
        assert np.linalg.norm(tk.setpoints['d'][1]) <= CFG.v_max_defense + 1e-6


@pytest.mark.parametrize('d,a,rname', [('shell', 'coordinated', 'tag'),
                                       ('ring', 'direct', 'tag'),
                                       ('shell', 'coordinated', 'pressure'),
                                       ('shell', 'coordinated', 'zone_pressure')])
def test_whole_match_keeps_every_aircraft_apart(d, a, rname):
    rules = rule_sets.make(rname)
    from crazyflie_shows import plan_guard as pg
    vip = pg.vip_mark(CFG)
    D, A = ['D1', 'D2', 'D3', 'D4'], ['A1', 'A2', 'A3']
    bad, starts = pg.mark_problems(CFG, TAG, vip, pg.recommend_marks(CFG, vip, 4, 3), D, A)
    assert bad == []
    res, met, _ = pg.simulate(CFG, rules, d, a, starts, D, A, vip, seed=3)
    assert res.winner
    assert pg.safety_failures(CFG, met) == []
    assert met['floor'] >= 1.0


# ---------------------------------------------------------------------------
# No team may read the other's intent, or reach outside its own View.

def _match_with(defense, attack, seed=0):
    from crazyflie_shows import plan_guard as pg
    vip = pg.vip_mark(CFG)
    D, A = ['D1', 'D2'], ['A1', 'A2']
    _, starts = pg.mark_problems(CFG, TAG, vip, pg.recommend_marks(CFG, vip, 2, 2), D, A)
    return Match(CFG, TAG, defense, attack, starts, D, A, vip,
                 np.random.default_rng(seed)), vip


def test_opponents_commands_are_never_visible():
    seen = []

    @register
    class Spy(Policy):
        team = DEFENSE
        name = 'test_spy'

        def act(self, view):
            seen.append({a.name: a.v.copy()
                         for a in view.team(ATTACK, active_only=False)})
            return {}

    m, vip = _match_with(policies.make(DEFENSE, 'test_spy'),
                         policies.make(ATTACK, 'direct'))
    commanded = []
    for _ in range(60):
        commanded.append({n: m.v[n].copy() for n in ('A1', 'A2')})
        m.step(0.05, vip, np.zeros(3))
    # what the spy saw on tick k is never the command issued on tick k-1
    leaks = sum(np.allclose(seen[k][n], commanded[k][n])
                and np.linalg.norm(commanded[k][n]) > 0.05
                for k in range(1, 60) for n in ('A1', 'A2'))
    assert leaks == 0


def test_a_view_is_a_private_copy():
    @register
    class Vandal(Policy):
        team = ATTACK
        name = 'test_vandal'

        def act(self, view):
            for a in view.defenders:          # try to move and down the other team
                a.p[:] = 99.0
                a.status = 'retiring'
            view.rules.p['reach'] = 9.0       # and to change the rules
            view.cfg.v_max_attack = 50.0
            return {}

    m, vip = _match_with(policies.make(DEFENSE, 'shell'),
                         policies.make(ATTACK, 'test_vandal'))
    for _ in range(20):
        m.step(0.05, vip, np.zeros(3))
    assert TAG.reach < 2.0 and m.rules.reach < 2.0
    assert m.cfg.v_max_attack == CFG.v_max_attack
    assert all(m.agents[n].active for n in ('D1', 'D2'))
    assert all(np.all(np.abs(m.sp[n]) < 20.0) for n in ('D1', 'D2'))


class _RollD(Policy):
    team = DEFENSE
    name = 'test_roll_d'
    draws = []

    def act(self, view):
        type(self).draws.append(float(self.rng.random()))
        return {}


class _RollA(Policy):
    team = ATTACK
    name = 'test_roll_a'
    draws = []

    def act(self, view):
        type(self).draws.append(float(self.rng.random()))
        return {}


class _Greedy(Policy):
    team = DEFENSE
    name = 'test_greedy'

    def act(self, view):
        self.rng.random(1000)          # burns through its own stream
        return {}


for _cls in (_RollD, _RollA, _Greedy):
    register(_cls)


def test_each_team_has_its_own_random_stream():
    # the defence burning dice must not change a single one of the attack's
    for dname in ('test_roll_d', 'test_greedy'):
        _RollA.draws = []
        m, vip = _match_with(policies.make(DEFENSE, dname),
                             policies.make(ATTACK, 'test_roll_a'), seed=7)
        for _ in range(5):
            m.step(0.05, vip, np.zeros(3))
        if dname == 'test_roll_d':
            first = list(_RollA.draws)
    assert _RollA.draws == first and len(first) == 5
