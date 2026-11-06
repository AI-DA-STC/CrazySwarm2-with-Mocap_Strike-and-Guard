"""Attack 'wolfpack': take out the loneliest defender first, then strike.

Under rule sets where defenders can be downed ('pressure', 'zone',
'zone_pressure'), the best way to the VIP is often THROUGH the defence:

* HUNT -- the pack picks its PREY: the defender furthest from its own
  teammates (the one nobody can help), nearest the pack. Every attacker
  closes to a spot just inside the rule set's reach of it, the spots fanned
  ``spread_deg`` apart on the pack's side, so the prey is outnumbered while
  each attacker is backed by its neighbours. A prey whose spots the rules say
  would fill an ATTACKER's meter (another defender is near enough to make it
  even) is skipped for the next loneliest.
* STRIKE -- once the defence is down to ``thin_to`` of its starting size, or
  the hunt has run ``hunt_timeout_s``, or there is nobody left worth hunting,
  the pack spreads to evenly spaced lanes and goes for the VIP together.

Under rule sets where defenders cannot be downed ('tag', 'timer') there is
nothing to hunt: it goes straight to the strike. An attacker whose own down
meter passes ``evade_share`` (outside the strike circle) breaks off.
"""

import numpy as np

from crazyflie_shows.guard.policies import Intent, Policy, register
from crazyflie_shows.guard.policies.common import (assign, bearing, into_room,
                                                   seek, unit, wrap)
from crazyflie_shows.guard.world import ATTACK, DEFENSE


def _rot_z(v, ang):
    c, s = np.cos(ang), np.sin(ang)
    return np.array([c * v[0] - s * v[1], s * v[0] + c * v[1], v[2]])


@register
class Wolfpack(Policy):
    """Wolfpack: gang up on the loneliest defender first, then strike the VIP once the defence is thin."""

    team = ATTACK
    name = 'wolfpack'
    DEFAULTS = {
        'thin_to': 0.5,            # strike once this share of the defenders is left
        'hunt_timeout_s': 12.0,    # s of hunting before striking anyway
        'gap': 0.15,               # m inside reach the pack closes to
        'spread_deg': 50.0,        # angle between neighbouring wolves round the prey
        'hunt_range': 7.0,         # m: a defender further than this from the pack is not prey
        'inside': 0.3,             # m inside the strike radius it aims for
        'heights': (0.4, -0.3, 0.0, 0.8),   # strike lane heights round the VIP's
        'evade_share': 0.5,        # down meter at which a wolf breaks off
        'retarget_s': 1.0,         # s a prey is kept before switching
    }

    def reset(self, view, rng):
        super().reset(view, rng)
        self._n_def0 = max(len(view.team(DEFENSE, active_only=False)), 1)
        self._phase = 'hunt'
        self._since = view.t
        self._prey = None
        self._prey_since = -np.inf
        self._lane = {}

    # -- the hunt -----------------------------------------------------------
    def _spots(self, view, prey, A):
        """name -> spot round ``prey``, fanned on the pack's side."""
        reach = view.rules.reach
        centre = np.mean([a.p for a in A], axis=0)
        face = unit(centre - prey.p)
        n = len(A)
        angs = [np.radians(self.p['spread_deg']) * (k - (n - 1) / 2.0) for k in range(n)]
        pts = []
        for ang in angs:
            q = prey.p + _rot_z(face, ang) * (reach - self.p['gap'])
            q[2] = prey.p[2]
            pts.append(into_room(q, view.arena, 0.4))
        cost = np.array([[float(np.linalg.norm(q - a.p)) for q in pts] for a in A])
        return {A[i].name: pts[j] for i, j in assign(cost)}

    def _safe(self, view, spots, A):
        """True if no wolf's own meter would fill at its spot."""
        rules = view.rules
        if not rules.can_down(ATTACK):
            return True
        D = np.array([d.p for d in view.defenders], float).reshape(1, -1, 3)
        for a in A:
            mates = np.array([spots[m.name] for m in A if m is not a], float).reshape(1, -1, 3)
            if float(rules.down_rates(ATTACK, spots[a.name][None], D, mates, view.vip_p)[0]) > 0:
                return False
        return True

    def _choose_prey(self, view, A):
        D = view.defenders
        if not D or len(A) < 2:
            return None, None
        centre = np.mean([a.p for a in A], axis=0)
        if (self._prey in {d.name for d in D}
                and view.t - self._prey_since < self.p['retarget_s']):
            d = next(q for q in D if q.name == self._prey)
            return d, self._spots(view, d, A)

        def lonely(d):
            others = [float(np.linalg.norm(d.p - q.p)) for q in D if q is not d]
            return (min(others) if others else 5.0) - 0.3 * float(np.linalg.norm(d.p - centre))

        for d in sorted(D, key=lonely, reverse=True):
            if float(np.linalg.norm(d.p - centre)) > self.p['hunt_range']:
                continue
            spots = self._spots(view, d, A)
            if self._safe(view, spots, A):
                if d.name != self._prey:
                    self._prey, self._prey_since = d.name, view.t
                return d, spots
        return None, None

    # -- the strike ----------------------------------------------------------
    def _assign_lanes(self, view, A):
        vip = view.vip_p
        base = float(np.angle(np.mean([np.exp(1j * bearing(a.p, vip)) for a in A])))
        n = len(A)
        lanes = [base + 2.0 * np.pi * (k - (n - 1) / 2.0) / max(n, 3) for k in range(n)]
        cost = np.array([[abs(wrap(bearing(a.p, vip) - b)) for b in lanes] for a in A])
        self._lane = {A[i].name: (lanes[j], self.p['heights'][j % len(self.p['heights'])])
                      for i, j in assign(cost)}

    def act(self, view):
        p, cfg = self.p, view.cfg
        A, D = view.attackers, view.defenders
        vip = view.vip_p
        rules = view.rules
        v_a = view.v_max(self.team)
        out = {}
        self.intents = {}
        if not A:
            return out

        prey, spots = (None, None)
        if self._phase == 'hunt':
            thin = len(D) <= p['thin_to'] * self._n_def0
            late = view.t - self._since > p['hunt_timeout_s']
            if rules.can_down(DEFENSE) and not thin and not late:
                prey, spots = self._choose_prey(view, A)
            if prey is None:
                self._phase, self._since = 'strike', view.t
                self._lane = {}
        if self._phase == 'strike' and set(self._lane) != {a.name for a in A}:
            self._assign_lanes(view, A)

        r_strike = rules.strike_radius - p['inside']
        for a in A:
            r_now = float(np.linalg.norm(a.p - vip))
            meter = view.meters.get(a.name, {}).get('down', 0.0)
            if (rules.can_down(ATTACK) and r_now > rules.strike_radius
                    and meter >= p['evade_share'] and D):
                d = min(D, key=lambda q: float(np.linalg.norm(q.p - a.p)))
                away = unit(a.p - d.p)
                away[2] = 0.0
                tang = unit(np.array([-(a.p - vip)[1], (a.p - vip)[0], 0.0]))
                out[a.name] = v_a * unit(unit(away) + 0.6 * tang)
                self.labels[a.name] = 'evade'
                self.intents[a.name] = Intent('evade', a.p + out[a.name], d.name)
                continue
            if prey is not None:
                q = spots[a.name]
                out[a.name] = seek(a.p, q, v_a, cfg.a_max, prey.v)
                self.labels[a.name] = f'gang {prey.name}'
                self.intents[a.name] = Intent('gang', q.copy(), prey.name)
                continue
            b, h = self._lane[a.name]
            g = vip + r_strike * np.array([np.cos(b), np.sin(b), 0.0])
            g[2] = vip[2] + h
            g = into_room(g, view.arena, 0.4)
            out[a.name] = seek(a.p, g, v_a, cfg.a_max)
            self.labels[a.name] = 'strike'
            self.intents[a.name] = Intent('strike', g)
        self.plan = {'phase': 'commit' if self._phase == 'strike' else 'stage',
                     'prey': prey.name if prey is not None else '',
                     'lanes': list(self._lane.values()), 'r_stage': 4.2, 'decoy': ''}
        return out
