"""The strategies added for play: zone, hunter (defence), flood, wolfpack (attack).

    PYTHONPATH=src/crazyswarm2/crazyflie_shows python3 -m pytest -q \\
        src/crazyswarm2/crazyflie_shows/test
"""

import numpy as np
import pytest

from crazyflie_shows.guard import policies
from crazyflie_shows.guard import rules as rule_sets
from crazyflie_shows.guard.config import GuardConfig
from crazyflie_shows.guard.engine import Match
from crazyflie_shows.guard.world import ATTACK, DEFENSE
from crazyflie_shows.plan_guard import (mark_problems, recommend_marks,
                                        safety_failures, simulate, vip_mark)

CFG = GuardConfig()
NEW = [(DEFENSE, 'zone'), (DEFENSE, 'hunter'), (ATTACK, 'flood'), (ATTACK, 'wolfpack')]
OPPONENT = {DEFENSE: 'coordinated', ATTACK: 'shell'}


def _setup(nd, na, rules):
    vip = vip_mark(CFG)
    D = [f'D{i + 1}' for i in range(nd)]
    A = [f'A{j + 1}' for j in range(na)]
    bad, starts = mark_problems(CFG, rules, vip, recommend_marks(CFG, vip, nd, na), D, A)
    assert not bad
    return vip, D, A, starts


def _pair(team, name):
    return (name, OPPONENT[team]) if team == DEFENSE else (OPPONENT[team], name)


def test_the_new_strategies_are_registered():
    for team, name in NEW:
        assert name in policies.available(team)
        assert policies.describe(team, name)
        with pytest.raises(KeyError):
            policies.make(team, name, {'no_such_knob': 1})


@pytest.mark.parametrize('team, name', NEW)
@pytest.mark.parametrize('rules_name', ['tag', 'pressure'])
def test_every_active_drone_has_an_intent_and_only_its_own_team_is_commanded(
        team, name, rules_name):
    rules = rule_sets.make(rules_name)
    vip, D, A, starts = _setup(4, 3, rules)
    dname, aname = _pair(team, name)
    dpol, apol = policies.make(DEFENSE, dname), policies.make(ATTACK, aname)
    mine = dpol if team == DEFENSE else apol
    seen_kinds = set()
    act = mine.act

    def spy(view):
        out = act(view)
        own = {a.name for a in view.team(team)}
        assert set(out) <= own                        # only its own, only active
        assert set(mine.intents) == own               # an intent for every one
        for n, it in mine.intents.items():
            assert it.goal is None or np.all(np.isfinite(it.goal))
            if it.target:
                assert view.agents[it.target].team != team
            seen_kinds.add(it.kind)
        for v in out.values():
            assert np.all(np.isfinite(v))
        return out

    mine.act = spy
    m = Match(CFG, rules, dpol, apol, starts, D, A, vip, np.random.default_rng(1))
    pos = {n: np.asarray(p, float).copy() for n, p in starts.items()}
    for _ in range(400):
        tk = m.step(0.05, vip, np.zeros(3), pos)
        for n, (sp, _) in tk.setpoints.items():
            pos[n] = pos[n] + (sp - pos[n]) * 0.2
        if m.result().winner:
            break
    known = policies.DEFENSE_KINDS if team == DEFENSE else policies.ATTACK_KINDS
    assert seen_kinds and seen_kinds <= set(known)


@pytest.mark.parametrize('team, name', NEW)
def test_the_same_seed_plays_the_same_match(team, name):
    rules = rule_sets.make('pressure')
    vip, D, A, starts = _setup(4, 3, rules)
    dname, aname = _pair(team, name)
    r1, m1, _ = simulate(CFG, rules, dname, aname, starts, D, A, vip, 5)
    r2, m2, _ = simulate(CFG, rules, dname, aname, starts, D, A, vip, 5)
    assert (r1.winner, r1.t, r1.strikes, r1.downs) == (r2.winner, r2.t, r2.strikes, r2.downs)
    assert m1['sep'] == m2['sep']


@pytest.mark.parametrize('team, name', NEW)
@pytest.mark.parametrize('rules_name, nd, na, tau', [
    ('tag', 4, 3, 0.25), ('pressure', 4, 3, 0.6), ('pressure', 2, 1, 0.25)])
def test_a_short_match_each_is_safe(team, name, rules_name, nd, na, tau):
    rules = rule_sets.make(rules_name)
    vip, D, A, starts = _setup(nd, na, rules)
    dname, aname = _pair(team, name)
    res, met, _ = simulate(CFG, rules, dname, aname, starts, D, A, vip, 0, tau=tau)
    assert res.winner
    assert safety_failures(CFG, met) == []
