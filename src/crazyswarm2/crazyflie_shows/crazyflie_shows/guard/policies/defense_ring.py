"""Defence 'ring' (a baseline): the escort's idea, for comparison.

A flat ring at the VIP's height that turns to put a slot on the most urgent
threat, and otherwise stays put. It never leaves the ring to meet anyone.
Useful as the yardstick a smarter defence has to beat.
"""

import numpy as np

from crazyflie_shows.guard.policies import Policy, register
from crazyflie_shows.guard.policies.common import (assign, bearing, into_room,
                                                   seek, wrap)
from crazyflie_shows.guard.world import DEFENSE


@register
class Ring(Policy):
    """A flat ring round the VIP that turns to face the nearest threat."""

    team = DEFENSE
    name = 'ring'
    DEFAULTS = {
        'radius': 1.7,          # m from the VIP
        'turn_rate': 0.6,       # rad/s the ring may rotate at
    }

    def reset(self, view, rng):
        super().reset(view, rng)
        self._psi = 0.0

    def act(self, view):
        D, A = view.defenders, view.attackers
        if not D:
            return {}
        vip = view.vip_p
        n = len(D)
        if A:
            near = min(A, key=lambda a: float(np.linalg.norm(a.p - vip)))
            want = bearing(near.p, vip)
            # the slot nearest the threat takes it
            offs = 2.0 * np.pi * np.arange(n) / n
            err = min((wrap(want - (self._psi + o)) for o in offs), key=abs)
            step = np.clip(err, -self.p['turn_rate'] * view.dt,
                           self.p['turn_rate'] * view.dt)
            self._psi = wrap(self._psi + step)
        slots = []
        for j in range(n):
            ang = self._psi + 2.0 * np.pi * j / n
            q = vip + np.array([np.cos(ang), np.sin(ang), 0.0]) * self.p['radius']
            slots.append(into_room(q, view.arena))
        cost = np.array([[float(np.linalg.norm(s - d.p)) for s in slots] for d in D])
        out = {}
        for di, si in assign(cost):
            out[D[di].name] = seek(D[di].p, slots[si], view.v_max(self.team),
                                   view.cfg.a_max, view.vip_v)
            self.labels[D[di].name] = 'ring'
        return out
