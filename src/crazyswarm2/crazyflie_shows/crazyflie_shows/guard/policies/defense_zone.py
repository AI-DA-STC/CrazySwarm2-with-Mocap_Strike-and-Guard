"""Defence 'zone': each defender owns a slice of the sky round the VIP.

Zone defence, as in football, against the shell's man-marking. The space
round the VIP is cut into as many equal SLICES (bearings) as there are
defenders, the first one centred on where the attack starts. Each defender
owns one slice for the whole match and:

* waits at its POST, mid-slice, ``r_post`` from the VIP -- alternate slices a
  little higher and lower, so the posts make a crown, not a flat ring;
* when an attacker comes inside ``engage_r`` within its slice (plus
  ``overlap_deg`` into each neighbour, so a seam is covered twice), it BLOCKS:
  out on the line VIP -> attacker, at the attacker's height, just inside the
  rule set's reach -- but never leaving its slice to chase;
* HELP-SIDE: a defender whose slice is empty slides into a neighbouring
  slice to double a lone attacker there (inside ``help_r``), closing from
  its own side -- under 'pressure' one defender downs nobody, two do;
* falls back to its post when its own down meter fills (rule sets that can
  down defenders).

What it is good for: it never leaves a side empty, and it never sends two
defenders after one attacker while another walks in. What beats it: two
attackers in ONE slice (an overload), or an attack along a seam.

The zones SHIFT: they turn, at most ``shift_rate``, so that one slice is
always centred on the attack's centre of mass and its neighbours' overlap
covers the flanks -- the way a football zone slides toward the ball.

When a defender is downed the slices are re-cut among the rest, keeping the
order round the circle, so nobody crosses the VIP to reach a new slice.
"""

import numpy as np

from crazyflie_shows.guard.policies import Intent, Policy, register
from crazyflie_shows.guard.policies.common import (assign, bearing, into_room,
                                                   seek, wrap)
from crazyflie_shows.guard.policies.common import unit as _unit
from crazyflie_shows.guard.policies.defense_shell import Shell
from crazyflie_shows.guard.world import ATTACK, DEFENSE


@register
class Zone(Policy):
    """Zone defence: each defender owns a slice of the sky round the VIP and only fights there."""

    team = DEFENSE
    name = 'zone'
    DEFAULTS = {
        'r_post': 1.9,         # m from the VIP: where a defender waits, mid-slice
        'r_min': 1.7,          # m: the innermost a blocker holds
        'r_max': 2.8,          # m: the furthest it goes out
        'engage_r': 5.0,       # m from the VIP: an attacker inside this, in my slice, is mine
        'overlap_deg': 12.0,   # a slice reaches this far into each neighbour
        'press_gap': 0.0,      # m short of the attacker; 0 = from the rules
        'lead_s': 0.5,         # s of attacker motion to aim ahead of
        'post_dz': 0.5,        # m: alternate posts sit this much higher / lower
        'follow': 0.6,         # share of the attacker's velocity fed forward
        'bail': 0.35,          # own down meter at which a defender falls back
        'stick_rad': 0.6,      # rad of slice-bearing a re-assignment must save
        'shift_rate': 0.5,     # rad/s the zones turn to keep one centred on the attack
                               # (0 = zones fixed where the attack started)
        'help_r': 3.5,         # m from the VIP: a defender with an empty slice helps a
                               # neighbour against an attacker inside this
    }

    def reset(self, view, rng):
        super().reset(view, rng)
        A = view.team(ATTACK, active_only=False)
        vip = view.vip_p
        self._base = (float(np.angle(np.mean([np.exp(1j * bearing(a.p, vip)) for a in A])))
                      if A else 0.0)
        self._slice = {}       # defender name -> slice index (sticky)

    def _press(self, view):
        if self.p['press_gap'] > 0.0:
            return self.p['press_gap']
        rules = view.rules
        return rules.reach - 0.1 if rules.can_down(ATTACK) else view.cfg.d_cc + 0.2

    def _shift(self, view, A):
        """Turn the zones, rate-limited, so one slice centre faces the
        attack's centre of mass (a zone defence shifts toward the ball)."""
        if not A or self.p['shift_rate'] <= 0.0:
            return
        vip = view.vip_p
        want = float(np.angle(np.mean([np.exp(1j * bearing(a.p, vip)) for a in A])))
        n = max(len(view.defenders), 1)
        width = 2.0 * np.pi / n
        # the nearest slice centre to the attack's bearing, not slice 0
        err = wrap(want - self._base)
        err = wrap(err - width * np.round(err / width))
        step = self.p['shift_rate'] * view.dt
        self._base = float(wrap(self._base + np.clip(err, -step, step)))

    def _slices(self, view, D):
        """Slice centre bearing per defender, assigned by least turning."""
        n = len(D)
        centres = [self._base + 2.0 * np.pi * k / n for k in range(n)]
        vip = view.vip_p
        cost = np.zeros((n, n))
        for i, d in enumerate(D):
            b = bearing(d.p, vip)
            for k, c in enumerate(centres):
                cost[i, k] = abs(wrap(b - c))
                if self._slice.get(d.name) == k:
                    cost[i, k] -= self.p['stick_rad']
        self._slice = {D[i].name: k for i, k in assign(cost)}
        return {name: centres[k] for name, k in self._slice.items()}, 2.0 * np.pi / n

    def _help_spot(self, view, a, c, press, lo, hi, A):
        """Just inside reach of attacker ``a``, on my own slice's side."""
        vip = view.vip_p
        post = vip + self.p['r_post'] * np.array([np.cos(c), np.sin(c), 0.0])
        q = a.p + _unit(np.r_[(post - a.p)[:2], 0.0]) * press
        q[2] = float(np.clip(a.p[2], lo, hi))
        return into_room(Shell._allowed(view, q, A), view.arena)

    @staticmethod
    def _helps(view, a, q, blocker, me, A, D):
        """The RULES' verdict on helping: does the double team down ``a``,
        and does the helper stay standing at ``q``?"""
        rules = view.rules
        vip = view.vip_p
        pair = np.array([blocker.p, q], float).reshape(1, -1, 3)
        mates = np.array([b.p for b in A if b is not a], float).reshape(1, -1, 3)
        if float(rules.down_rates(ATTACK, a.p[None], pair, mates, vip)[0]) <= 0.0:
            return False
        opp = np.array([b.p for b in A], float).reshape(1, -1, 3)
        allies = np.array([x.p for x in D if x is not me], float).reshape(1, -1, 3)
        return float(rules.down_rates(DEFENSE, q[None], opp, allies, vip)[0]) <= 0.0

    def act(self, view):
        p, cfg = self.p, view.cfg
        D, A = view.defenders, view.attackers
        vip = view.vip_p
        vmax = view.v_max(self.team)
        out = {}
        self.intents = {}
        if not D:
            return out
        self._shift(view, A)
        centre, width = self._slices(view, D)
        half = width / 2.0 + np.radians(p['overlap_deg'])
        press = self._press(view)
        lo, hi = view.arena.floor + 0.3, view.arena.ceiling - 0.3
        engaged = {}                       # attacker name -> (slice index, defender)
        plans = {}
        for d in D:
            c = centre[d.name]
            k = self._slice[d.name]
            mine = []
            for a in A:
                r = float(np.linalg.norm(a.p - vip))
                if r <= p['engage_r'] and abs(wrap(bearing(a.p, vip) - c)) <= half:
                    closing = -float((a.p - vip) @ a.v) / max(r, 1e-6)
                    mine.append((r - p['lead_s'] * max(closing, 0.0), a))
            if view.meters.get(d.name, {}).get('down', 0.0) >= p['bail']:
                back = into_room(vip + np.array([np.cos(c), np.sin(c), 0.0]) * p['r_min'],
                                 view.arena)
                out[d.name] = seek(d.p, back, vmax, cfg.a_max)
                self.labels[d.name] = 'bail'
                self.intents[d.name] = Intent('bail', back.copy())
                continue
            if mine:
                _, a = min(mine, key=lambda x: x[0])
                engaged[a.name] = (k, d)
                pred = a.p + a.v * p['lead_s']
                # block on the VIP -> attacker line, but only inside my slice
                b = bearing(pred, vip)
                off = float(np.clip(wrap(b - c), -width / 2.0, width / 2.0))
                rr = float(np.linalg.norm((pred - vip)[:2]))
                br = float(np.clip(rr - press, p['r_min'], p['r_max']))
                q = vip + br * np.array([np.cos(c + off), np.sin(c + off), 0.0])
                q[2] = float(np.clip(pred[2], lo, hi))
                q = into_room(Shell._allowed(view, q, A), view.arena)
                out[d.name] = seek(d.p, q, vmax, cfg.a_max, a.v * p['follow'])
                self.labels[d.name] = f'zone {a.name}'
                self.intents[d.name] = Intent('block', q.copy(), a.name)
            else:
                plans[d.name] = (k, c)
        # help-side: an empty slice's defender doubles a neighbour's attacker
        n = len(D)
        helped = set()
        for d in D:
            if d.name not in plans:
                continue
            k, c = plans[d.name]
            help_on, help_q = None, None
            if n > 2 and view.rules.can_down(ATTACK):
                for a in A:
                    if (a.name not in engaged or a.name in helped
                            or float(np.linalg.norm(a.p - vip)) > p['help_r']):
                        continue
                    k2, blocker = engaged[a.name]
                    if (k2 - k) % n in (1, n - 1) and help_on is None:
                        q = self._help_spot(view, a, c, press, lo, hi, A)
                        if self._helps(view, a, q, blocker, d, A, D):
                            help_on, help_q = a, q
            if help_on is not None:
                a, q = help_on, help_q
                helped.add(a.name)
                out[d.name] = seek(d.p, q, vmax, cfg.a_max, a.v * p['follow'])
                self.labels[d.name] = f'help {a.name}'
                self.intents[d.name] = Intent('pincer', q.copy(), a.name)
            else:
                dz = (p['post_dz'] if k % 2 else -p['post_dz']) if len(D) > 2 else 0.0
                q = vip + p['r_post'] * np.array([np.cos(c), np.sin(c), 0.0])
                q[2] = float(np.clip(vip[2] + dz, lo, hi))
                q = into_room(q, view.arena)
                out[d.name] = seek(d.p, q, vmax, cfg.a_max, view.vip_v)
                self.labels[d.name] = 'post'
                self.intents[d.name] = Intent('post', q.copy())
        self.plan = {'phase': 'zone',
                     'slices': {n: float(c) for n, c in centre.items()}}
        return out
