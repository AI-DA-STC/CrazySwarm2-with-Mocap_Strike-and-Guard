"""The guard show's picture and its end: intents, the near-miss watch, the finale.

    PYTHONPATH=src/crazyswarm2/crazyflie_shows python3 -m pytest -q \\
        src/crazyswarm2/crazyflie_shows/test
"""

import dataclasses

import numpy as np
import pytest

from crazyflie_shows.guard import finale as finale_mod
from crazyflie_shows.guard import rules as rule_sets
from crazyflie_shows.guard import viz
from crazyflie_shows.guard.config import GuardConfig, override, problems
from crazyflie_shows.guard.watch import LAND, OK, PAUSE, NearMissWatch
from crazyflie_shows.guard.world import ATTACK, DEFENSE
from crazyflie_shows.plan_guard import (mark_problems, recommend_marks,
                                        safety_failures, simulate, vip_mark)

CFG = GuardConfig()
MID = np.array([CFG.room_center[0], CFG.room_center[1], 1.5])


def _setup(nd, na, rules):
    vip = vip_mark(CFG)
    D = [f'D{i + 1}' for i in range(nd)]
    A = [f'A{j + 1}' for j in range(na)]
    marks = recommend_marks(CFG, vip, nd, na)
    bad, starts = mark_problems(CFG, rules, vip, marks, D, A)
    assert not bad
    return vip, D, A, starts


# ------------------------------------------------------------------ intents
def test_every_active_drone_says_what_it_means_and_only_its_own_team():
    rules = rule_sets.make('pressure')
    vip, D, A, starts = _setup(3, 2, rules)
    seen = []

    def spy(m, vip_now, tk, res, banner):
        for n, it in tk.intents.items():
            assert m.agents[n].active or n in tk.retired
            if it.target:
                # a target is always an OPPONENT
                assert m.agents[it.target].team != m.agents[n].team
        seen.append({n: it.kind for n, it in tk.intents.items()})

    simulate(CFG, rules, 'shell', 'coordinated', starts, D, A, vip, 0, on_tick=spy)
    kinds = {k for s in seen for k in s.values()}
    assert {'block', 'stage'} <= kinds
    assert all(len(s) >= 1 for s in seen[:20])


def test_intents_do_not_change_the_game():
    """Intents are for the picture: the same seed plays the same match with
    a strategy that never reads them (the engine never hands them over)."""
    rules = rule_sets.make('tag')
    vip, D, A, starts = _setup(4, 3, rules)
    r1, m1, _ = simulate(CFG, rules, 'shell', 'coordinated', starts, D, A, vip, 3)
    r2, m2, _ = simulate(CFG, rules, 'shell', 'coordinated', starts, D, A, vip, 3)
    assert (r1.winner, r1.t, r1.downs) == (r2.winner, r2.t, r2.downs)
    assert m1['sep'] == m2['sep']


# ------------------------------------------------------------------ the viz
def test_intent_symbols_are_segments_for_every_kind():
    here, goal, tgt, vip = MID, MID + [1.0, 0.5, 0.0], MID + [2.0, 1.0, 0.0], MID - [2, 0, 0]
    for kind in ('block', 'pincer', 'post', 'bail', 'stage', 'strike', 'decoy',
                 'feint', 'evade', 'gang', 'unknown-kind'):
        solid, faint = viz.intent_symbol(kind, here, goal, tgt, vip)
        assert solid or faint, kind
        for a, b in solid + faint:
            assert np.all(np.isfinite(a)) and np.all(np.isfinite(b))
    # no goal: nothing drawn, nothing raised
    assert viz.intent_symbol('block', here, None, None, vip) == ([], [])


def test_dashes_cover_the_line_and_stay_on_it():
    a, b = MID, MID + [2.0, 0.0, 0.0]
    segs = viz.seg_dashed(a, b, 0.2, 0.1)
    assert len(segs) == 7
    for p, q in segs:
        assert abs(p[1] - a[1]) < 1e-9 and a[0] - 1e-9 <= p[0] <= q[0] <= b[0] + 1e-9


# ------------------------------------------------------------- near misses
def _pair(gap, dz=0.0):
    return {'a': MID.copy(), 'b': MID + [gap, 0.0, dz]}


def test_one_soft_frame_is_not_a_near_miss_two_pause_then_resume():
    w = NearMissWatch(CFG)
    sp = {'a': MID, 'b': MID + [0.5, 0, 0]}
    assert w.update(0.00, _pair(0.40), sp).action == OK
    assert w.update(0.05, _pair(0.22), sp).action == OK          # one frame
    v = w.update(0.10, _pair(0.22), sp)
    assert v.action == PAUSE and 'SAFETY PAUSE' in v.why
    assert 'aircraft lagged' in v.why                            # the evidence
    assert w.update(0.15, _pair(0.28), sp).action == PAUSE       # not clear yet
    v = w.update(0.20, _pair(0.40), sp)
    assert v.action == OK and v.resumed


def test_hard_near_miss_lands_on_the_first_frame():
    w = NearMissWatch(CFG)
    w.update(0.0, _pair(0.30), {})
    v = w.update(0.05, _pair(0.15), {})
    assert v.action == LAND and 'hard' in v.why


def test_a_pause_that_does_not_clear_lands():
    w = NearMissWatch(CFG)
    t = 0.0
    for _ in range(3):
        v = w.update(t, _pair(0.22), {})
        t += 0.05
    assert v.action == PAUSE
    while t < CFG.near_miss_pause_s + 0.5:
        v = w.update(t, _pair(0.22), {})
        t += 0.05
        if v.action == LAND:
            break
    assert v.action == LAND and 'did not clear' in v.why


def test_the_old_behaviour_is_one_switch_away():
    cfg = override(GuardConfig(), {'near_miss_pause': False})
    w = NearMissWatch(cfg)
    w.update(0.0, _pair(0.22), {})
    assert w.update(0.05, _pair(0.22), {}).action == LAND


def test_a_mocap_jump_is_a_glitch_not_a_near_miss():
    w = NearMissWatch(CFG)
    w.update(0.0, _pair(1.0), {})
    # 'b' teleports onto 'a' for two frames (a swapped rigid body)
    for t in (0.05, 0.10):
        v = w.update(t, {'a': MID.copy(), 'b': MID + [0.05, 0, 0]}, {})
        assert v.action == OK
        assert 'b' in v.glitched
    assert w.glitches == 1


def test_reappearing_after_a_dropout_is_not_a_glitch():
    w = NearMissWatch(CFG)
    w.update(0.0, _pair(1.0), {})
    w.update(0.05, {'a': MID.copy(), 'b': None}, {})            # b stale ...
    v = w.update(0.50, {'a': MID.copy(), 'b': MID + [1.4, 0, 0]}, {})   # ... 0.4 m on
    assert v.glitched == set() and w.glitches == 0


def test_vertical_stack_counts_with_the_tall_floor():
    w = NearMissWatch(CFG)
    w.update(0.0, _pair(0.0, 0.40), {})
    assert w.update(0.05, _pair(0.0, 0.40), {}).action == PAUSE   # 0.40 < 0.43
    w = NearMissWatch(CFG)
    w.update(0.0, _pair(0.0, 0.50), {})
    assert w.update(0.05, _pair(0.0, 0.50), {}).action == OK


def test_near_miss_config_is_checked():
    assert problems(CFG) == []
    for bad in ({'near_miss_land_ratio': 0.8}, {'near_miss_clear_ratio': 0.6},
                {'mocap_jump_m': 0.05}, {'near_miss_ticks': 0}):
        assert problems(override(GuardConfig(), bad)), bad


# ------------------------------------------------------------------ finale
@pytest.mark.parametrize('rules_name, nd, na, seed', [
    ('tag', 4, 3, 0),             # defence wins: honour guard
    ('timer', 4, 3, 0),           # attack strikes: capture ring
    ('pressure', 2, 1, 0),        # 2 v 1
    ('zone_pressure', 5, 5, 1),   # big teams
])
def test_the_finale_is_flown_safely_to_the_end(rules_name, nd, na, seed):
    rules = rule_sets.make(rules_name, {'duration': 25.0} if rules_name == 'timer' else None)
    vip, D, A, starts = _setup(nd, na, rules)
    res, met, _ = simulate(CFG, rules, 'shell', 'coordinated', starts, D, A, vip,
                           seed, finale=True)
    assert res.winner
    assert met['finale'] == 'done'
    assert safety_failures(CFG, met) == []


def test_the_winning_striker_stays_up_for_the_capture():
    rules = rule_sets.make('timer', {'duration': 25.0})
    vip, D, A, starts = _setup(4, 3, rules)
    log = []

    def spy(m, vip_now, tk, res, banner):
        if banner:
            log.append((banner, {n: a.active for n, a in m.agents.items()},
                        set(tk.setpoints)))

    res, met, _ = simulate(CFG, rules, 'shell', 'coordinated', starts, D, A, vip, 0,
                           on_tick=spy, finale=True)
    assert res.winner == ATTACK
    striker = next(e.who for e in res.events if e.kind == 'strike')
    banner, active, flown = log[0]
    assert 'COMPROMISED' in banner
    assert active[striker] and striker in flown
    # every defender goes home and lands: none active at the end
    assert not any(log[-1][1][d] for d in D)


def test_finale_slots_ring_the_vip_outside_its_keep_out():
    rules = rule_sets.make('tag')
    vip, D, A, starts = _setup(4, 3, rules)

    class _A:
        def __init__(self, n, team, p):
            self.name, self.team, self.p, self.active = n, team, np.asarray(p, float), True
    agents = {n: _A(n, DEFENSE if n in D else ATTACK, starts[n]) for n in D + A}
    for winner, r in ((DEFENSE, finale_mod.DEFAULTS['guard_r']),
                      (ATTACK, finale_mod.DEFAULTS['capture_r'])):
        fin = finale_mod.Finale(CFG, winner, agents, starts, vip, 0.0)
        for t in np.arange(0.0, 30.0, 0.5):
            fs = fin.update(t, vip, agents)
            for n, g in fs.slots.items():
                if fs.phase in ('rally', 'emote'):
                    d = float(np.linalg.norm((g - vip)[:2]))
                    assert d > CFG.d_vip + 0.15, (winner, t, d)
            for n, how in fs.lights.items():
                assert how == ('off' if agents[n].team != winner else how)


def test_finale_numbers_are_checked():
    assert finale_mod.check(CFG, {}) == []
    assert finale_mod.check(CFG, {'capture_r': 1.3})
    assert finale_mod.check(CFG, {'speed': 0.0})
    slow = override(GuardConfig(), {'v_max_defense': 0.5, 'v_max_attack': 0.5})
    assert finale_mod.check(slow, {}) == []
    assert finale_mod.Finale(slow, DEFENSE, {}, {}, MID, 0.0).p['speed'] == 0.5
    with pytest.raises(KeyError):
        finale_mod.Finale(CFG, DEFENSE, {}, {}, MID, 0.0, {'sped': 0.5})


def test_dataclass_intent_is_copied_not_shared():
    from crazyflie_shows.guard.policies import Intent
    i = Intent('block', MID.copy(), 'A1')
    j = dataclasses.replace(i)
    assert j == i and j is not i


def test_a_loser_is_never_landed_near_the_vip():
    """A drone being landed cannot dodge, and a DJI can drift onto it: a
    loser whose mark is near where the VIP now is lands further out."""
    rules = rule_sets.make('tag')
    vip, D, A, starts = _setup(4, 3, rules)

    class _A:
        def __init__(self, n, team, p):
            self.name, self.team, self.p, self.active = n, team, np.asarray(p, float), True
    agents = {n: _A(n, DEFENSE if n in D else ATTACK, starts[n]) for n in D + A}
    moved = vip.copy()
    moved[:2] = starts['D1'][:2]          # the DJI has drifted over D1's mark
    fin = finale_mod.Finale(CFG, ATTACK, agents, starts, moved, 0.0)
    rim = CFG.d_vip + finale_mod.DEFAULTS['land_clear']
    for t in np.arange(0.0, 30.0, 0.1):
        fs = fin.update(t, moved, agents)
        for n in fs.land:
            assert float(np.linalg.norm(agents[n].p[:2] - moved[:2])) >= rim
            agents[n].active = False
        for n, g in fs.goals.items():          # teleport: an ideal follower
            agents[n].p = np.asarray(g, float)
    assert all(not agents[d].active for d in D)
