"""Attack 'flood': spread all round the VIP, then everyone charges at once.

The opposite of the coordinated attack's overload. Instead of picking a
weak side, the attack makes EVERY side weak:

* SPREAD -- the attackers fan out to evenly spaced bearings round the VIP
  (360 / n degrees apart) at ``r_stage``, each at its own height, flying
  ROUND the VIP at that radius to get there (never through the defence).
* FLOOD -- when all are in place (or ``spread_timeout_s`` runs out) they all
  charge the strike circle at full speed, at the same moment, WEAVING
  sideways (``jink_m``, ``jink_period_s``, each out of phase) so an
  intercept aimed at where they are going keeps being slightly wrong.
* REGROUP -- an attacker that gets no closer for ``stall_s`` backs out to
  the stage circle; when they all have, the spread rotates by half a
  spacing and they flood again from the gaps.

A defence with fewer defenders than attackers cannot cover every lane; one
that outnumbers the attack can, which is the honest test of it. Under rule
sets that can down attackers, an attacker whose down meter passes
``evade_share`` outside the strike circle breaks off.
"""

import numpy as np

from crazyflie_shows.guard.policies import Intent, Policy, register
from crazyflie_shows.guard.policies.common import (assign, bearing, into_room,
                                                   seek, unit, wrap)
from crazyflie_shows.guard.world import ATTACK


@register
class Flood(Policy):
    """Flood: spread all round the VIP, then everyone charges at once, weaving."""

    team = ATTACK
    name = 'flood'
    DEFAULTS = {
        'r_stage': 4.2,            # m from the VIP: the spread circle
        'heights': (0.6, -0.4, 0.0, 1.0, -0.2),   # per-lane height round the VIP's
        'spread_tol': 0.6,         # m from its slot that counts as in place
        'spread_timeout_s': 9.0,
        'orbit_step_deg': 35.0,    # how far round it heads per waypoint
        'inside': 0.3,             # m inside the strike radius it aims for
        'jink_m': 0.30,            # m of sideways weave while charging
        'jink_period_s': 1.6,
        'stall_s': 3.0,            # s without getting closer before backing off
        'evade_share': 0.6,        # down meter at which a charger breaks off
    }

    def reset(self, view, rng):
        super().reset(view, rng)
        A = view.team(ATTACK, active_only=False)
        vip = view.vip_p
        self._base = (float(np.angle(np.mean([np.exp(1j * bearing(a.p, vip)) for a in A])))
                      if A else 0.0)
        self._phase = 'spread'
        self._since = view.t
        self._lane = {}
        self._jink_phase = {a.name: float(rng.uniform(0.0, 2.0 * np.pi)) for a in A}
        self._best = {}
        self._stuck = {}

    def _assign_lanes(self, view, A):
        n = len(A)
        lanes = [self._base + 2.0 * np.pi * k / n for k in range(n)]
        cost = np.array([[abs(wrap(bearing(a.p, view.vip_p) - b)) for b in lanes] for a in A])
        self._lane = {A[i].name: (lanes[j], self.p['heights'][j % len(self.p['heights'])])
                      for i, j in assign(cost)}

    def _slot(self, view, name):
        b, h = self._lane[name]
        q = view.vip_p + self.p['r_stage'] * np.array([np.cos(b), np.sin(b), 0.0])
        q[2] = view.vip_p[2] + h
        return into_room(q, view.arena, 0.4)

    def _toward(self, view, a):
        """The next waypoint ROUND the VIP toward its slot."""
        goal = self._slot(view, a.name)
        vip = view.vip_p
        here, there = bearing(a.p, vip), bearing(goal, vip)
        gap = wrap(there - here)
        step = np.radians(self.p['orbit_step_deg'])
        if abs(gap) <= step:
            return goal
        b = here + np.sign(gap) * step
        q = vip + self.p['r_stage'] * np.array([np.cos(b), np.sin(b), 0.0])
        q[2] = goal[2]
        return into_room(q, view.arena, 0.4)

    def act(self, view):
        p, cfg = self.p, view.cfg
        A = view.attackers
        vip = view.vip_p
        v_a = view.v_max(self.team)
        rules = view.rules
        out = {}
        self.intents = {}
        if not A:
            return out
        if set(self._lane) != {a.name for a in A}:
            self._assign_lanes(view, A)

        # -- the team phase --
        if self._phase == 'spread':
            ready = all(float(np.linalg.norm(a.p - self._slot(view, a.name))) < p['spread_tol']
                        for a in A)
            if ready or view.t - self._since > p['spread_timeout_s']:
                self._phase, self._since = 'flood', view.t
                self._best, self._stuck = {}, {}
        elif self._phase == 'flood':
            if all(self._stuck.get(a.name, 0.0) >= p['stall_s'] for a in A):
                spacing = 2.0 * np.pi / len(A)
                self._base += spacing / 2.0
                self._assign_lanes(view, A)
                self._phase, self._since = 'spread', view.t

        r_strike = rules.strike_radius - p['inside']
        for a in A:
            r_now = float(np.linalg.norm(a.p - vip))
            if self._phase == 'spread':
                goal = self._toward(view, a)
                out[a.name] = seek(a.p, goal, v_a, cfg.a_max)
                self.labels[a.name] = 'spread'
                self.intents[a.name] = Intent('stage', self._slot(view, a.name))
                continue
            # flood: progress bookkeeping for the stall test
            if r_now < self._best.get(a.name, np.inf) - 0.1:
                self._best[a.name] = r_now
                self._stuck[a.name] = 0.0
            else:
                self._stuck[a.name] = self._stuck.get(a.name, 0.0) + view.dt
            in_strike = r_now <= rules.strike_radius
            meter = view.meters.get(a.name, {}).get('down', 0.0)
            if rules.can_down(ATTACK) and not in_strike and meter >= p['evade_share']:
                D = view.defenders
                d = min(D, key=lambda q: float(np.linalg.norm(q.p - a.p))) if D else None
                away = unit(a.p - (d.p if d is not None else vip))
                away[2] = 0.0
                tang = unit(np.array([-(a.p - vip)[1], (a.p - vip)[0], 0.0]))
                out[a.name] = v_a * unit(unit(away) + 0.6 * tang)
                self.labels[a.name] = 'evade'
                self.intents[a.name] = Intent('evade', a.p + out[a.name], d.name if d else '')
                continue
            if self._stuck.get(a.name, 0.0) >= p['stall_s']:
                goal = self._slot(view, a.name)          # back off to the stage circle
                out[a.name] = seek(a.p, goal, v_a, cfg.a_max)
                self.labels[a.name] = 'regroup'
                self.intents[a.name] = Intent('stage', goal)
                continue
            b, h = self._lane[a.name]
            u = np.array([np.cos(b), np.sin(b), 0.0])
            strike = vip + u * r_strike
            strike[2] = vip[2] + h * 0.5
            strike = into_room(strike, view.arena, 0.4)
            # the weave: sideways to the line in, fading out at the strike circle
            side = np.array([-u[1], u[0], 0.0])
            far = float(np.clip((r_now - r_strike) / max(p['r_stage'] - r_strike, 1e-6), 0.0, 1.0))
            w = 2.0 * np.pi / p['jink_period_s']
            weave = side * p['jink_m'] * far * np.sin(w * (view.t - self._since)
                                                      + self._jink_phase.get(a.name, 0.0))
            out[a.name] = seek(a.p, strike + weave, v_a, cfg.a_max)
            self.labels[a.name] = 'flood'
            self.intents[a.name] = Intent('strike', strike)
        self.plan = {'phase': 'commit' if self._phase == 'flood' else 'stage',
                     'lanes': [self._lane[a.name] for a in A if a.name in self._lane],
                     'r_stage': p['r_stage'], 'decoy': ''}
        return out
