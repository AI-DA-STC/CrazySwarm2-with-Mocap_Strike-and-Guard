"""Contested strikes: a defender close to an attacker stops its strike meter.

From the 23-11 hardware match: cf10 struck the DJI with cf4 shadowing it
0.45 m away for the whole second; the block counted for nothing.
"""
import numpy as np

from crazyflie_shows.guard import rules as rule_sets
from crazyflie_shows.guard.config import GuardConfig
from crazyflie_shows.guard.rules import Referee
from crazyflie_shows.guard.world import ATTACK, DEFENSE, Agent

VIP = np.array([0.0, 0.0, 1.0])
DT = 0.05


def _match(rules, shadow):
    """An attacker 1.4 m from the VIP for 2 s, a defender ``shadow`` m off it."""
    agents = {'a': Agent('a', ATTACK, VIP + [1.4, 0.0, 0.0], np.zeros(3)),
              'd': Agent('d', DEFENSE, VIP + [1.4, shadow, 0.0], np.zeros(3))}
    ref = Referee(rules)
    for k in range(int(2.0 / DT)):
        ev = ref.update(k * DT, DT, agents, VIP)
        if any(e.kind == 'strike' for e in ev):
            return True
    return False


def test_off_by_default_a_shadowed_attacker_still_strikes():
    r = rule_sets.make('pressure')
    assert r.strike_block == 0.0
    assert _match(r, 0.45)


def test_a_shadowing_defender_contests_the_strike():
    assert not _match(rule_sets.make('pressure', {'strike_block': 0.8}), 0.45)


def test_a_defender_outside_the_block_does_not():
    assert _match(rule_sets.make('pressure', {'strike_block': 0.8}), 1.0)


def test_every_rule_set_has_it():
    for name in rule_sets.available():
        assert not _match(rule_sets.make(name, {'strike_block': 0.8}), 0.45), name


def test_planner_rates_see_the_block_per_case():
    r = rule_sets.make('tag', {'strike_block': 0.8})
    att = np.array([VIP + [1.4, 0, 0], VIP + [1.4, 0, 0]])
    defs = np.array([[VIP + [1.4, 0.5, 0]], [VIP + [1.4, 1.5, 0]]])   # (K, M, 3)
    rate = r.strike_rates(att, VIP, defs)
    assert rate[0] == 0.0 and rate[1] > 0.0
    # left out: the uncontested estimate, as before
    assert np.all(r.strike_rates(att, VIP) > 0.0)


def test_a_block_inside_the_safety_keep_out_is_refused():
    cfg = GuardConfig()
    r = rule_sets.make('pressure', {'strike_block': cfg.d_cc - 0.05})
    assert any('strike_block' in b for b in r.problems(cfg))
    assert not any('strike_block' in b
                   for b in rule_sets.make('pressure', {'strike_block': 0.8}).problems(cfg))
