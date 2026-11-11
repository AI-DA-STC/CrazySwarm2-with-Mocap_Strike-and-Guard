"""Defence 'shell' (the default): meet each threat out on its line, in 3D.

Borrowed from the STL game (ideas, not code -- stl_game.py is a port and is
not edited): an urgency-weighted assignment of defenders to threats, kept
sticky so nobody dithers between two; a PREDICTIVE intercept on the line from
the VIP to where the attacker is going; and a pincer, a second defender
closing from the side, whenever defenders outnumber threats. What it adds is
height: the intercept is on the 3D line, so an attacker coming over the top
or along the floor is met at its own altitude, and idle defenders hold posts
above and below the VIP as well as around it.
"""

import numpy as np

from crazyflie_shows.guard.policies import Intent, Policy, register
from crazyflie_shows.guard.policies.common import assign, into_room, rot_z, seek, unit
from crazyflie_shows.guard.world import ATTACK, DEFENSE


@register
class Shell(Policy):
    """Urgency-weighted 3D intercepts, pincers when outnumbering, posts otherwise."""

    team = DEFENSE
    name = 'shell'
    DEFAULTS = {
        'r_shell': 1.7,        # m from the VIP: the innermost a blocker holds
        'r_max': 2.6,          # m from the VIP: the furthest it goes out (further
                               # leaves the VIP open to the next attacker)
        'lead_s': 0.6,         # s of attacker motion to aim ahead of
        'press_gap': 0.0,      # m short of the attacker; 0 = from the rules
        'pincer_deg': 60.0,    # a second defender closes on the attacker this far
                               # round from the first, so both are in reach
        'bail': 0.35,          # own down meter at which a defender falls back
        'urgency_gain': 1.5,   # how much a fast, close threat jumps the queue
        'd_ref': 4.0,          # m: urgency is zero this far from the VIP
        'v_ref': 1.0,          # m/s: closing speed that counts as full urgency
        'stick_s': 0.5,        # s of travel a re-assignment must save
        'post_dz': 0.6,        # m: idle posts alternate above/below the VIP
        'follow': 0.7,         # share of the attacker's velocity fed forward
    }

    def reset(self, view, rng):
        super().reset(view, rng)
        self._prev = {}

    def _press(self, view):
        if self.p['press_gap'] > 0.0:
            return self.p['press_gap']
        # Where attackers can be downed it stands just inside the rule set's
        # reach, so holding the block also scores; otherwise a little outside
        # the keep-out.
        rules = view.rules
        return (rules.reach - 0.1 if rules.can_down(ATTACK)
                else view.cfg.d_cc + 0.2)

    def act(self, view):
        p, cfg = self.p, view.cfg
        D, A = view.defenders, view.attackers
        vip = view.vip_p
        vmax = view.v_max(self.team)
        out = {}
        self.intents = {}
        if not D:
            return out
        if not A:
            return self._posts(view, D, vmax)

        urg = []
        for a in A:
            rel = a.p - vip
            r = float(np.linalg.norm(rel))
            closing = -float(rel @ a.v) / max(r, 1e-6)
            urg.append(0.6 * (1.0 - np.clip(r / p['d_ref'], 0.0, 1.0))
                       + 0.4 * np.clip(closing / p['v_ref'], 0.0, 1.0))
        order = list(np.argsort(urg)[::-1])

        # Columns: one primary per threat, then pincers on the most urgent
        # threats while there are defenders left over.
        cols = [(i, 0) for i in order]
        k = 1
        while len(cols) < len(D):
            for i in order:
                if len(cols) >= len(D):
                    break
                cols.append((i, k))
            k += 1

        press = self._press(view)
        points, feeds = [], []
        for i, kind in cols:
            a = A[i]
            pred = a.p + a.v * p['lead_s']
            u = unit(pred - vip)
            rr = float(np.linalg.norm(pred - vip))
            if kind == 0:
                br = float(np.clip(rr - press, p['r_shell'], p['r_max']))
                q = vip + u * br
            else:
                # PINCER: close on the attacker itself, pincer_deg round from
                # the blocker's side, so both defenders are within reach of it
                # -- under a majority rule one defender alone downs nobody.
                side = 1.0 if kind % 2 else -1.0
                w = rot_z(-u, side * np.radians(p['pincer_deg']) * ((kind + 1) // 2))
                q = pred + w * press
                r_q = float(np.linalg.norm(q - vip))
                if r_q < p['r_shell']:
                    q = vip + unit(q - vip) * p['r_shell']
            points.append(into_room(self._allowed(view, q, A), view.arena))
            feeds.append(a.v * p['follow'])

        cost = np.zeros((len(D), len(cols)))
        for di, d in enumerate(D):
            for ci, (i, kind) in enumerate(cols):
                t_go = float(np.linalg.norm(points[ci] - d.p)) / max(vmax, 1e-6)
                cost[di, ci] = (t_go - p['urgency_gain'] * urg[i]
                                + (0.5 * kind))
                if self._prev.get(d.name) == (A[i].name, kind):
                    cost[di, ci] -= p['stick_s']
        self._prev = {}
        for di, ci in assign(cost):
            d = D[di]
            i, kind = cols[ci]
            if view.meters.get(d.name, {}).get('down', 0.0) >= p['bail']:
                # its own meter is filling: fall back to the shell, where its
                # teammates are, instead of finishing the block
                back = into_room(vip + unit(d.p - vip) * p['r_shell'], view.arena)
                out[d.name] = seek(d.p, back, vmax, cfg.a_max)
                self.labels[d.name] = 'bail'
                self.intents[d.name] = Intent('bail', back.copy(), A[i].name)
                continue
            out[d.name] = seek(d.p, points[ci], vmax, cfg.a_max, feeds[ci])
            self._prev[d.name] = (A[i].name, kind)
            self.labels[d.name] = (f'block {A[i].name}' if kind == 0
                                   else f'pincer {A[i].name}')
            self.intents[d.name] = Intent('block' if kind == 0 else 'pincer',
                                          np.array(points[ci], float), A[i].name)
        return out

    @staticmethod
    def _allowed(view, q, A):
        """``q`` pulled toward the VIP until the RULES would not fill a
        defender's meter there (a post outside home ground under 'zone', or
        next to two attackers under 'pressure'). Rules that cannot down a
        defender leave it where it is."""
        rules = view.rules
        if not rules.can_down(DEFENSE) or not A:
            return q
        vip = view.vip_p
        opp = np.array([a.p for a in A], float).reshape(1, -1, 3)
        allies = np.array([d.p for d in view.defenders], float).reshape(1, -1, 3)
        for _ in range(12):
            if float(rules.down_rates(DEFENSE, q[None], opp, allies, vip)[0]) <= 0.0:
                return q
            r = float(np.linalg.norm(q - vip))
            if r <= view.cfg.d_vip + 0.4:
                return q
            q = vip + (q - vip) * max(r - 0.25, view.cfg.d_vip + 0.4) / r
        return q

    def _posts(self, view, D, vmax):
        """Spread the idle defenders round the VIP, alternating heights."""
        vip = view.vip_p
        out = {}
        n = len(D)
        heights = [0.0, self.p['post_dz'], -self.p['post_dz']]
        slots = []
        for j in range(n):
            ang = 2.0 * np.pi * j / n
            dz = heights[j % 3] if n > 2 else 0.0
            q = vip + np.array([np.cos(ang), np.sin(ang), 0.0]) * self.p['r_shell']
            q[2] += dz
            slots.append(into_room(q, view.arena))
        cost = np.array([[float(np.linalg.norm(s - d.p)) for s in slots] for d in D])
        for di, si in assign(cost):
            out[D[di].name] = seek(D[di].p, slots[si], vmax, view.cfg.a_max)
            self.labels[D[di].name] = 'post'
            self.intents[D[di].name] = Intent('post', np.array(slots[si], float))
        return out
