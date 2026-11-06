"""Defence 'hunter': a hunter-killer pair goes out; the rest guard close.

Most defences wait for the attack to come to them. This one sends a PAIR of
defenders out to meet it:

* The pair picks its PREY: the attacker that is closest to the VIP, with a
  bonus for one that is alone (``isolation_w``) -- a lone attacker is the
  one two hunters can outnumber. Only prey the RULES say the pair would
  actually down, from spots where neither hunter would itself be downed,
  qualifies (under 'pressure' an attacker with a teammate beside it is not
  worth hunting). It keeps that prey for at least ``retarget_s``.
* The two hunters close on it from TWO sides of the line prey -> VIP,
  ``flank_deg`` apart, just inside the rule set's reach. That is a pincer
  (under 'pressure' one defender alone downs nobody; two do) and, because
  both sit between the prey and the VIP, also a block.
* Everyone else is the GUARD: a tight inner ring at ``r_guard``, each guard
  standing on the line to the most urgent attacker that is NOT the prey, or
  at an even post when there is none.

Roles are re-assigned every tick by one least-cost assignment of all
defenders to (hunter spots + guard posts), with a little stickiness, so the
two defenders nearest the prey hunt and the others guard. A hunter whose
own down meter fills (two attackers turned on it) breaks off to the guard
ring. With two defenders the whole team hunts; with one it only guards.
Under a rule set that cannot down attackers ('timer') there is nothing to
hunt for, so everyone guards.
"""

import numpy as np

from crazyflie_shows.guard.policies import Intent, Policy, register
from crazyflie_shows.guard.policies.common import (assign, bearing, into_room,
                                                   seek, unit)
from crazyflie_shows.guard.policies.defense_shell import Shell
from crazyflie_shows.guard.world import ATTACK, DEFENSE


def _rot_z(v, ang):
    c, s = np.cos(ang), np.sin(ang)
    return np.array([c * v[0] - s * v[1], s * v[0] + c * v[1], v[2]])


@register
class Hunter(Policy):
    """Hunter-killer: a pair goes out to outnumber one attacker; the rest guard the VIP close."""

    team = DEFENSE
    name = 'hunter'
    DEFAULTS = {
        'pairs': 1,            # hunting pairs (two defenders each); the rest guard
        'r_guard': 1.7,        # m from the VIP: the inner guard ring
        'hunt_r': 5.5,         # m from the VIP: prey further out than this is left alone
        'r_hunt_min': 1.9,     # m from the VIP: the innermost a hunter spot may be
        'gap': 0.15,           # m inside reach the hunters close to
        'flank_deg': 140.0,    # angle between the two hunters round the prey (wide: beside
                               # it, not head-on in its path -- lag-tolerant)
        'isolation_w': 0.5,    # how much being alone makes an attacker the prey
        'lead_s': 0.5,         # s of prey motion to aim ahead of
        'retarget_s': 1.5,     # s a prey is kept before switching
        'bail': 0.35,          # own down meter at which a hunter breaks off
        'stick_s': 0.4,        # s of travel a role swap must save
    }

    def reset(self, view, rng):
        super().reset(view, rng)
        self._prey = None
        self._prey_since = -np.inf
        self._role = {}

    # -- choosing ----------------------------------------------------------
    def _worth(self, view, prey, A, D):
        """Would the pair down ``prey`` from its spots -- and stay standing?

        Asked of the RULES, like the referee: the prey's down rate with both
        hunters at their spots (its teammates near it count against it), and
        each hunter's own rate there (the partner counts for it)."""
        rules = view.rules
        vip = view.vip_p
        spots = self._spots(view, prey)
        mates = np.array([a.p for a in A if a is not prey], float).reshape(1, -1, 3)
        rate = float(rules.down_rates(ATTACK, prey.p[None],
                                      np.array(spots, float).reshape(1, -1, 3),
                                      mates, vip)[0])
        if rate <= 0.0:
            return False
        opp = np.array([a.p for a in A], float).reshape(1, -1, 3)
        guards = [d.p for d in D][: max(len(D) - 2, 0)]
        for k, q in enumerate(spots):
            allies = np.array([spots[1 - k]] + guards, float).reshape(1, -1, 3)
            if float(rules.down_rates(DEFENSE, q[None], opp, allies, vip)[0]) > 0.0:
                return False
        return True

    def _choose_prey(self, view, A, D):
        vip = view.vip_p
        cand = [a for a in A if float(np.linalg.norm(a.p - vip)) <= self.p['hunt_r']
                and self._worth(view, a, A, D)]
        if not cand:
            return None
        names = {a.name for a in cand}
        if (self._prey in names and view.t - self._prey_since < self.p['retarget_s']):
            return next(a for a in cand if a.name == self._prey)

        def score(a):
            r = float(np.linalg.norm(a.p - vip))
            others = [float(np.linalg.norm(a.p - b.p)) for b in A if b is not a]
            iso = min(min(others), 4.0) if others else 4.0
            return -r + self.p['isolation_w'] * iso

        best = max(cand, key=score)
        if best.name != self._prey:
            self._prey, self._prey_since = best.name, view.t
        return best

    def _spots(self, view, prey):
        """The two pincer spots round the prey, between it and the VIP."""
        p = self.p
        vip = view.vip_p
        reach = view.rules.reach
        pred = prey.p + prey.v * p['lead_s']
        toward = unit(vip - pred)
        out = []
        for side in (-1.0, 1.0):
            q = pred + _rot_z(toward, side * np.radians(p['flank_deg']) / 2.0) * (reach - p['gap'])
            q[2] = pred[2]
            r = float(np.linalg.norm((q - vip)[:2]))
            if r < p['r_hunt_min']:
                d = unit(np.r_[(q - vip)[:2], 0.0])
                q[:2] = vip[:2] + d[:2] * p['r_hunt_min']
            out.append(into_room(q, view.arena))
        return out

    def _guard_posts(self, view, A, n, prey):
        """``n`` inner-ring posts: on the lines to the most urgent non-prey
        attackers first, then spread evenly."""
        vip = view.vip_p
        r = self.p['r_guard']
        threats = sorted((a for a in A if prey is None or a.name != prey.name),
                         key=lambda a: float(np.linalg.norm(a.p - vip)))
        posts, tgts = [], []
        for a in threats[:n]:
            u = unit(np.r_[(a.p - vip)[:2], 0.0])
            q = vip + u * r
            q[2] = float(np.clip(a.p[2], view.arena.floor + 0.3, view.arena.ceiling - 0.3))
            posts.append(into_room(Shell._allowed(view, q, A), view.arena))
            tgts.append(a.name)
        base = bearing(threats[0].p, vip) if threats else 0.0
        k = 0
        while len(posts) < n:
            ang = base + np.pi + 2.0 * np.pi * k / max(n, 1)
            q = vip + r * np.array([np.cos(ang), np.sin(ang), 0.0])
            posts.append(into_room(q, view.arena))
            tgts.append('')
            k += 1
        return posts, tgts

    # -- acting ------------------------------------------------------------
    def act(self, view):
        p, cfg = self.p, view.cfg
        D, A = view.defenders, view.attackers
        vmax = view.v_max(self.team)
        out = {}
        self.intents = {}
        if not D:
            return out
        rules = view.rules
        hunting = bool(A) and rules.can_down(ATTACK) and len(D) >= 2
        prey = self._choose_prey(view, A, D) if hunting else None
        n_hunt = min(2 * int(p['pairs']), len(D)) if prey is not None else 0
        n_hunt -= n_hunt % 2
        spots = self._spots(view, prey) if n_hunt else []
        posts, tgts = self._guard_posts(view, A, len(D) - n_hunt, prey)
        cols = [('hunt', s, prey.name) for s in spots[:n_hunt]]
        cols += [('guard', q, t) for q, t in zip(posts, tgts)]
        cost = np.zeros((len(D), len(cols)))
        for i, d in enumerate(D):
            for j, (role, q, _) in enumerate(cols):
                cost[i, j] = float(np.linalg.norm(q - d.p)) / max(vmax, 1e-6)
                if self._role.get(d.name) == role:
                    cost[i, j] -= p['stick_s']
                # a hunter whose meter is filling is not sent back out
                if role == 'hunt' and view.meters.get(d.name, {}).get('down', 0.0) >= p['bail']:
                    cost[i, j] += 100.0
        self._role = {}
        for i, j in assign(cost):
            d = D[i]
            role, q, tgt = cols[j]
            self._role[d.name] = role
            if role == 'hunt':
                out[d.name] = seek(d.p, q, vmax, cfg.a_max, prey.v * 0.7)
                self.labels[d.name] = f'hunt {tgt}'
                self.intents[d.name] = Intent('pincer', np.array(q, float), tgt)
            elif tgt:
                out[d.name] = seek(d.p, q, vmax, cfg.a_max, view.vip_v)
                self.labels[d.name] = f'guard {tgt}'
                self.intents[d.name] = Intent('block', np.array(q, float), tgt)
            else:
                out[d.name] = seek(d.p, q, vmax, cfg.a_max, view.vip_v)
                self.labels[d.name] = 'guard'
                self.intents[d.name] = Intent('post', np.array(q, float))
        self.plan = {'phase': 'hunt' if prey is not None else 'guard',
                     'prey': prey.name if prey is not None else ''}
        return out
