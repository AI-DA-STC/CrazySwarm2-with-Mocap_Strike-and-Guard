"""Form-up: fly everyone to a fair starting formation around the live VIP.

Why it exists (2026-11-17): a match used to start wherever the drones lifted
off their floor marks. The marks are chosen for the cameras and the room, not
for the game, and the starting layout decided the match: under the pressure
rules, shell v coordinated was roughly even from the planner's recommended
layout (defence 5/12 at 0.6 m/s, 8/12 at 1.0) and 0/12 from the real marks,
where the attackers stood 3.0-3.5 m from the VIP, bunched on one side. With
the DJI as the VIP the problem is worse: the pilot hovers it wherever is
steady, and the formation should be built round where it actually is.

So, after the drones are up (and after the DJI gate when there is one), every
drone flies to a formation built round the VIP's position at that moment,
THROUGH the safety layer (``Match.steer``), and holds there until START:

* defenders on a ring ``r_def`` from the VIP, one of them facing the attack;
* attackers on an arc ``r_att`` out on the far side, ``spacing`` apart along
  it, pulled in (never past the start-reach rule) where the room is short.

The attack side is wherever the attackers already are (the bearing from the
VIP to their centroid), so nobody crosses over. Who goes to which slot is a
minimum-travel assignment. If no rotation of that layout fits the room and the
checks, there is no form-up and the caller says why.

``plan_guard`` flies the same form-up before every offline match, so what it
verifies is what flies.
"""

import numpy as np

from crazyflie_shows import escort
from crazyflie_shows.guard.policies.common import assign

DEFAULTS = {
    'r_def': 1.8,        # m from the VIP: the defenders' ring (plan_guard's mark radius)
    'r_att': 4.4,        # m from the VIP: the attackers' arc, before any pull-in
    'spacing': 1.3,      # m between attackers along the arc
    'room_margin': 0.4,  # m an attacker slot keeps from the arena edge
    'speed': 0.4,        # m/s for the move (slow: the drones lag their setpoints)
    'reached': 0.15,     # m: a drone this close to its slot has arrived
    'timeout_s': 25.0,   # s: hold where they are after this, arrived or not
}

#: rotations tried, in degrees, when the layout straight on does not fit
_TURNS = (0, 15, -15, 30, -30, 45, -45, 60, -60, 90, -90)


def _slots(cfg, vip, ang0, n_def, n_att, p, min_att_r):
    v = np.asarray(vip, float)[:2]
    z = cfg.start_height
    dslots = []
    for i in range(n_def):
        a = ang0 + 2.0 * np.pi * i / max(n_def, 1)
        dslots.append(np.r_[v + p['r_def'] * np.array([np.cos(a), np.sin(a)]), z])
    aslots = []
    for j in range(n_att):
        r = p['r_att']
        while True:
            step = p['spacing'] / r
            a = ang0 + (j - (n_att - 1) / 2.0) * step
            q = np.r_[v + r * np.array([np.cos(a), np.sin(a)]), z]
            if float(escort.room_clearance(cfg, q)) >= p['room_margin'] or r <= min_att_r:
                break
            r = max(r - 0.1, min_att_r)
        aslots.append(q)
    return dslots, aslots


def _match_slots(pos, names, slots):
    cost = [[float(np.linalg.norm(np.asarray(pos[n])[:2] - s[:2])) ** 2 for s in slots]
            for n in names]
    return {names[r]: slots[c] for r, c in assign(cost)}


def formation(cfg, rules, vip, pos, defenders, attackers, check, params=None):
    """(goals, turn_deg, why).

    ``goals``: name -> 3D slot at the start height, or None when nothing fits.
    ``check(goals) -> list of problems``: the caller's start checks (the same
    ``plan_guard.mark_problems`` the floor marks pass), so a formation is held
    to exactly the rules a start is.
    """
    p = dict(DEFAULTS, **(params or {}))
    defenders, attackers = list(defenders), list(attackers)
    v = np.asarray(vip, float)
    if attackers:
        c = np.mean([np.asarray(pos[a], float)[:2] for a in attackers], axis=0) - v[:2]
    else:
        c = np.array([1.0, 0.0])
    ang0 = float(np.arctan2(c[1], c[0])) if np.linalg.norm(c) > 1e-6 else 0.0
    # never pull an attacker in so far that it starts inside a defender's reach
    min_att_r = p['r_def'] + (rules.reach + 0.5 if getattr(rules, 'DOWNABLE', False) else 1.0)
    why = 'no attackers'
    for turn in _TURNS:
        dslots, aslots = _slots(cfg, v, ang0 + np.radians(turn), len(defenders),
                                len(attackers), p, min_att_r)
        goals = {}
        goals.update(_match_slots(pos, defenders, dslots))
        goals.update(_match_slots(pos, attackers, aslots))
        bad = check(goals)
        if not bad:
            return goals, turn, ''
        why = '; '.join(bad)
    return None, None, why


class Follow:
    """A formation that moves with the VIP (2026-11-19).

    The first form-up (11-17) built its slots once, round where the DJI was
    the moment the gate was passed, and flew to those fixed points; on
    hardware the pilot then moved the DJI 1.4 m, the drones kept flying to
    the old ring (one slot ended up inside the DJI's keep-out, so the form-up
    timed out), and nothing followed. Now the slots are kept as offsets from
    the VIP and re-placed round its live position every tick, so the whole
    formation translates with the DJI, rigidly, slot assignment unchanged.
    Only when the translated layout stops passing the start checks (the DJI
    walked it into a wall) is it rebuilt round the VIP where it is now, from
    where the drones are; if nothing fits there either, the last good goals
    are held (the safety layer still keeps everyone off the VIP).
    """

    def __init__(self, cfg, rules, defenders, attackers, check, params=None):
        # check(goals, vip) -> list of problems: the start checks, round the
        # VIP where it is now
        self.cfg, self.rules = cfg, rules
        self.defenders, self.attackers = list(defenders), list(attackers)
        self.check = check
        self.p = params_of(params)
        self.offsets = None      # name -> (dx, dy, z)
        self.turn = None
        self.rebuilds = 0
        self.last = None         # the last goals that passed the checks

    def build(self, vip, pos):
        """Lay the formation out round ``vip`` from ``pos``. (ok, why)."""
        v = np.asarray(vip, float)
        goals, turn, why = formation(self.cfg, self.rules, v, pos, self.defenders,
                                     self.attackers, lambda g: self.check(g, v), self.p)
        if goals is None:
            return False, why
        self.offsets = {n: np.r_[g[:2] - v[:2], g[2]] for n, g in goals.items()}
        self.turn, self.last = turn, goals
        return True, ''

    def goals(self, vip, pos):
        """The slots round the VIP as it is now (name -> 3D point)."""
        v = np.asarray(vip, float)
        g = {n: np.r_[v[:2] + o[:2], o[2]] for n, o in self.offsets.items()}
        if not self.check(g, v):
            self.last = g
            return g
        if self.build(v, pos)[0]:
            self.rebuilds += 1
        return self.last


def arrived(goals, sp, reached):
    """True when every setpoint is within ``reached`` of its slot."""
    return all(float(np.linalg.norm(np.asarray(sp[n]) - g)) <= reached
               for n, g in goals.items() if n in sp)


def params_of(overrides=None):
    return dict(DEFAULTS, **(overrides or {}))
