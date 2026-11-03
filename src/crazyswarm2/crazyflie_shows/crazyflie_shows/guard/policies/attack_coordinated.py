"""Attack 'coordinated' (the default): a team play, planned in 3D.

Two levels, neither of them attraction and repulsion.

**The team play** (one state for the whole attack):

* STAGE -- every attacker takes a LANE: a bearing round the VIP, spread so
  the attack comes from as many sides as there are attackers, each at its own
  height (one high, one low, one level...). It waits at the lane's staging
  point, outside the defence's reach.
* COMMIT -- when everyone is staged (or ``stage_timeout_s`` runs out) they go
  TOGETHER, so the defence has to split. With probability ``decoy_prob`` one
  of them goes first as a DECOY and the rest follow ``decoy_lead_s`` later,
  once the defence has turned to it.
* REGROUP -- an attacker that gets no closer for ``stall_s`` backs
  off; when the whole team has, the lanes ROTATE (by a random amount) and the
  play starts again from new sides.

**Each attacker's plan** (every ``replan_s``): candidate goals round its lane
-- bearings either side of it, at several heights, at staging range or at
striking range -- each rolled out over a short horizon against a PREDICTION
of the defence (every defender running for the intercept point between the
VIP and the attacker, at full speed: the STL game's predictive intercept,
turned round). Each is scored by STL-style robustness: the smooth minimum
(the STL game's soft_min) over the horizon of every margin it must keep --
out of tag range, inside the room, inside the altitude band -- plus progress
toward the VIP, the angle to the nearest defender (strike where they are
not) and the pull of its own lane. Robustness CHOOSES the line; it does not
gate the attempt -- waiting for a provably open lane meant never going. It
keeps its plan unless a new one wins by ``commit_margin``. Under the plan sit
the STL intruder's other two layers: a FEINT (show the defence the other side
first, with a cooldown) and an EVADE reflex when a defender gets inside tag range.
"""

import numpy as np

from crazyflie_shows.guard.policies import Policy, register
from crazyflie_shows.guard.policies.common import (bearing, into_room, seek,
                                                   unit, wrap)
from crazyflie_shows.guard.world import ATTACK, DEFENSE


def _soft_min_rows(x, k):
    """Row-wise smooth minimum of a 2D array."""
    m = np.min(x, axis=1, keepdims=True)
    return (m - np.log(np.sum(np.exp(-k * (x - m)), axis=1, keepdims=True)) / k)[:, 0]


@register
class Coordinated(Policy):
    """Team play (stage, commit together or behind a decoy, regroup) + 3D per-drone planning."""

    team = ATTACK
    name = 'coordinated'
    DEFAULTS = {
        # -- the team play --
        'r_stage': 4.2,            # m from the VIP: outside the defence's reach
        'formation': 'overload',   # 'overload' | 'spread' (see _assign_lanes)
        'pair_deg': 60.0,          # angle between the overloading pair
        'arc_deg': 240.0,          # lanes spread over this arc, centred on
                                   # where the attack starts (360 = all round)
        'heights': (0.8, -0.6, 0.0, 1.4),   # lane heights, relative to the VIP
        'stage_tol': 0.6,          # m from its staging point that counts as ready
        'orbit_step_deg': 35.0,    # how far round it heads per waypoint
        'stage_timeout_s': 8.0,
        'decoy_prob': 0.5,         # chance a commit opens with a decoy
        'decoy_lead_s': 1.5,
        'stall_s': 2.5,            # s without getting closer before backing off
        'rotate_deg': (30.0, 75.0),  # lanes turn by a random angle in this range
        # -- each attacker's plan --
        'replan_s': 0.4,
        'bearings_deg': (0.0, 25.0, -25.0, 50.0, -50.0, 80.0, -80.0),
        'dz': (-0.6, 0.0, 0.6),    # height options round the lane height
        'horizon_s': 4.0,
        'samples': 8,
        'soft_k': 8.0,             # smooth-min sharpness (STL game: SOFT_K)
        'meter_share': 0.6,        # how full it will let its down meter get
        'w_progress': 1.0,
        'w_lane': 0.5,             # pull toward its own lane (keeps the spread)
        'w_gap': 1.5,              # pull toward bearings no defender covers
        'w_safe': 2.5,
        'safe_cap': 0.6,
        'commit_margin': 0.3,
        'evade_share': 0.5,        # down meter at which a striker breaks off
        'hunt_range': 2.5,         # in reaches: how far it looks for a defender to gang up on
        'gang_gap': 0.15,          # m inside reach it closes to
        'feint_prob': 0.25,
        'feint_s': 1.2,
        'feint_cool_s': 6.0,
        'evade_extra': 0.3,
    }

    def reset(self, view, rng):
        super().reset(view, rng)
        A = view.team(ATTACK, active_only=False)
        vip = view.vip_p
        centre = np.angle(np.mean([np.exp(1j * bearing(a.p, vip)) for a in A])) if A else 0.0
        self._play = {'state': 'stage', 'since': view.t, 'decoy': None,
                      'go_at': {}, 'base': float(centre)}
        self._st = {a.name: {'goal': None, 'score': -np.inf, 'mode': 'stage',
                             'next': view.t + k * 0.1, 'stuck': 0.0,
                             'feint_until': -1.0, 'cool_until': -1.0}
                    for k, a in enumerate(A)}
        self._assign_lanes(view)

    # -- lanes --------------------------------------------------------------
    def _assign_lanes(self, view):
        A = view.attackers
        n = max(len(A), 1)
        # 'spread': evenly over arc_deg, so the defence has to split.
        # 'overload' (default): a PAIR converges on one side, pair_deg apart,
        # so the one defender marking that side cannot screen both, while the
        # rest spread over the arc to pin the other defenders down. A defender
        # on the line VIP-attacker is a wall (the safety layer will not let
        # anything through it), so a one-on-one is lost by the attacker; the
        # attack has to win two-on-one somewhere.
        arc = np.radians(min(self.p['arc_deg'], 360.0))
        if n == 1:
            offs = [0.0]
        elif self.p['formation'] == 'overload':
            half = np.radians(self.p['pair_deg']) / 2.0
            offs = [-half, half]
            rest = n - 2
            for k in range(rest):
                side = 1.0 if k % 2 == 0 else -1.0
                offs.append(side * (half + (arc / 2.0 - half) * (k // 2 + 1)
                                    / ((rest + 1) // 2)))
        elif arc >= 2.0 * np.pi - 1e-6:
            offs = [arc * k / n for k in range(n)]
        else:
            offs = [arc * (k / (n - 1) - 0.5) for k in range(n)]
        lanes = [self._play['base'] + o for o in offs]
        # nearest attacker to each lane
        free = list(A)
        self._lane = {}
        for k, b in enumerate(lanes):
            if not free:
                break
            a = min(free, key=lambda q: abs(wrap(bearing(q.p, view.vip_p) - b)))
            free.remove(a)
            self._lane[a.name] = (b, self.p['heights'][k % len(self.p['heights'])])

    def _stage_point(self, view, name):
        b, h = self._lane[name]
        g = view.vip_p + self.p['r_stage'] * np.array([np.cos(b), np.sin(b), 0.0])
        g[2] = view.vip_p[2] + h
        return into_room(g, view.arena, 0.4)

    def _toward_lane(self, view, a):
        """The next point on the way to its staging point: ROUND the VIP at
        staging radius, never across the middle. Flying straight to a lane on
        the far side took attackers through the defence, and they were tagged
        before the play began."""
        goal = self._stage_point(view, a.name)
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

    # -- planning -----------------------------------------------------------
    def _candidates(self, view, name, kinds):
        p = self.p
        b0, h0 = self._lane[name]
        out_g, out_k = [], []
        for db in p['bearings_deg']:
            b = b0 + np.radians(db)
            u = np.array([np.cos(b), np.sin(b), 0.0])
            for dz in p['dz']:
                for kind in kinds:
                    r = p['r_stage'] if kind == 'stage' else view.rules.strike_radius - 0.25
                    g = view.vip_p + u * r
                    g[2] = view.vip_p[2] + h0 + dz
                    out_g.append(into_room(g, view.arena, 0.4))
                    out_k.append(kind)
        return np.array(out_g), out_k

    @staticmethod
    def _rate(view, a, where):
        """How fast the rules would fill ``a``'s down meter at ``where``."""
        rules = view.rules
        if not rules.can_down(ATTACK):
            return 0.0
        opp = np.array([d.p for d in view.defenders], float).reshape(1, -1, 3)
        mates = np.array([m.p for m in view.attackers if m.name != a.name],
                         float).reshape(1, -1, 3)
        return float(rules.down_rates(ATTACK, np.asarray(where, float)[None],
                                      opp, mates, view.vip_p)[0])

    def _hunt(self, view, a):
        """(score, spot, defender) for a defender the pack can down, or None.

        Every attacker within ``hunt_range`` reaches of a defender is assumed
        to close to just inside reach of it, on its own side; if the RULES say
        that would fill the defender's meter, and would not fill this
        attacker's own at its spot, that is a hunt. Under 'pressure' it is a
        2 v 1 on an isolated defender; under 'zone', a defender caught
        outside home ground. Rules that cannot down defenders: never.
        """
        rules, p = view.rules, self.p
        if not rules.can_down(DEFENSE) or not view.defenders:
            return None
        r = rules.reach
        A, D = view.attackers, view.defenders
        best = None
        for d in D:
            dd = float(np.linalg.norm(d.p - a.p))
            if dd > p['hunt_range'] * r:
                continue
            pack = [m for m in A
                    if float(np.linalg.norm(m.p - d.p)) <= p['hunt_range'] * r]
            spots = {m.name: d.p + unit(m.p - d.p) * (r - p['gang_gap'])
                     for m in pack}
            opp = np.array(list(spots.values()), float).reshape(1, -1, 3)
            allies = np.array([q.p for q in D if q is not d], float).reshape(1, -1, 3)
            rate_d = float(rules.down_rates(DEFENSE, d.p[None], opp, allies,
                                            view.vip_p)[0])
            if rate_d <= 0.0:
                continue
            mine = spots[a.name]
            others = np.array([spots.get(m.name, m.p) for m in A if m is not a],
                              float).reshape(1, -1, 3)
            risk = float(rules.down_rates(
                ATTACK, mine[None], np.array([q.p for q in D], float).reshape(1, -1, 3),
                others, view.vip_p)[0])
            if risk > 0.0:
                continue
            score = rate_d - 0.1 * dd
            if best is None or score > best[0]:
                best = (score, into_room(mine, view.arena, 0.4), d.name)
        return best

    @staticmethod
    def _markers(view, a):
        """The defenders that will come for ``a``: each defender marks the
        attacker nearest to it. Predicting EVERY defender onto every attacker
        made no lane ever look open, so the attack never committed -- and it
        is also wrong: a defender can only be in one place, which is exactly
        what attacking together exploits."""
        A = view.attackers
        return [d for d in view.defenders
                if min(A, key=lambda q: float(np.linalg.norm(q.p - d.p))) is a]

    def _score(self, view, a, goals, dwell=None):
        """(score, robustness) for every goal (G, 3), vectorised.

        Robustness has two parts, combined with min():

        * SPACE (m): the smooth minimum over the rollout of the room and band
          margins -- these must hold at every instant.
        * TIME, in metres-equivalent: the rules are temporal (a meter has to
          FILL), so the margin is how much of the down meter would be left at
          its fullest along the path -- filled and drained by the rule set's
          own down_rates on the predicted positions, from the meter it has
          now -- times what the attacker covers in one down_time. An
          instantaneous distance margin (the first version) forbade the fast
          pass through range that the rules allow, and the attack never
          struck.

        ``dwell`` (G,) holds the attacker at its goal after arriving -- a
        strike candidate must survive strike_time there.
        """
        p, cfg = self.p, view.cfg
        vip = view.vip_p
        v_a, v_d = view.v_max(ATTACK), view.v_max(DEFENSE)
        rules = view.rules
        reach = rules.reach if rules.can_down(ATTACK) else cfg.d_cc
        G = len(goals)
        dist = np.linalg.norm(goals - a.p, axis=1)                    # (G,)
        dwell = np.zeros(G) if dwell is None else np.asarray(dwell, float)
        T = np.minimum(p['horizon_s'], dist / max(v_a, 1e-6) + 0.3 + dwell)
        s = np.arange(1, p['samples'] + 1) / p['samples']             # (S,)
        t = T[:, None] * s[None, :]                                   # (G,S)
        frac = np.minimum(1.0, t * v_a / np.maximum(dist, 1e-6)[:, None])
        at = a.p + (goals - a.p)[:, None, :] * frac[..., None]        # (G,S,3)
        rel = at - vip
        ra = np.linalg.norm(rel, axis=2, keepdims=True)
        meet = vip + rel / np.maximum(ra, 1e-6) * np.maximum(ra - reach, cfg.d_vip + 0.3)
        dt_s = T / p['samples']                                       # (G,)
        S = p['samples']
        # The defence, predicted: its markers run for the meeting point, the
        # rest stay put; teammates stay put. Then the RULE SET says how fast
        # this attacker's down meter would fill at every sample -- the same
        # down_rates the referee integrates -- from its meter now.
        markers = self._markers(view, a)
        opp = []
        for d in markers:
            to = meet - d.p                                           # (G,S,3)
            n = np.linalg.norm(to, axis=2, keepdims=True)
            step = np.minimum(v_d * t[..., None], n)
            opp.append(d.p + to / np.maximum(n, 1e-9) * step)
        for d in view.defenders:
            if all(d is not m for m in markers):
                opp.append(np.broadcast_to(d.p, (G, S, 3)))
        mates = [m.p for m in view.attackers if m.name != a.name]
        peak = np.zeros(G)
        if rules.can_down(ATTACK):
            K = G * S
            opp_a = (np.stack(opp, axis=2).reshape(K, -1, 3) if opp
                     else np.zeros((K, 0, 3)))
            ally_a = (np.broadcast_to(np.asarray(mates, float), (K, len(mates), 3))
                      if mates else np.zeros((K, 0, 3)))
            rate = rules.down_rates(ATTACK, at.reshape(K, 3), opp_a, ally_a,
                                    vip).reshape(G, S)
            meter = np.full(G, view.meters.get(a.name, {}).get('down', 0.0))
            peak = meter.copy()
            drain = rules.drain('down')
            for k in range(S):
                meter = np.where(rate[:, k] > 0.0,
                                 meter + rate[:, k] * dt_s,
                                 np.maximum(0.0, meter - drain * dt_s))
                peak = np.maximum(peak, meter)
        flat = at.reshape(-1, 3)
        space = np.concatenate([
            np.asarray(view.arena.clearance(flat)).reshape(G, -1) - 0.2,
            np.minimum(at[..., 2] - view.arena.floor,
                       view.arena.ceiling - at[..., 2]) - 0.2], axis=1)
        rob_space = _soft_min_rows(space, p['soft_k'])
        # TIME, in metres-equivalent: how much of the meter is left unspent
        # at its worst along the path, times what the attacker covers in the
        # time that fills it.
        t_unit = rules.down_time if np.isfinite(rules.down_time) else 1.0
        rob_time = ((p['meter_share'] - peak) * t_unit * v_a
                    if rules.can_down(ATTACK) else np.full(G, p['safe_cap']))
        rob = np.minimum(rob_space, rob_time)
        progress = np.linalg.norm(a.p - vip) - np.linalg.norm(goals - vip, axis=1)
        b0, _ = self._lane[a.name]
        gb = np.arctan2(goals[:, 1] - vip[1], goals[:, 0] - vip[0])
        lane = -np.abs((gb - b0 + np.pi) % (2 * np.pi) - np.pi)
        safe = np.minimum(rob, p['safe_cap']) + np.minimum(rob, 0.0)
        # GAP: how far the goal's bearing is from the nearest defender's --
        # strike where they are not (the escort attacker's widest-gap idea).
        if view.defenders:
            db = np.array([bearing(d.p, vip) for d in view.defenders])
            gap = np.min(np.abs((gb[:, None] - db[None, :] + np.pi)
                                % (2 * np.pi) - np.pi), axis=1)
            gap = np.minimum(gap, np.radians(90.0))
        else:
            gap = np.full(G, np.radians(90.0))
        score = (p['w_progress'] * progress + p['w_lane'] * lane
                 + p['w_safe'] * safe + p['w_gap'] * gap)
        return score, rob

    def _replan(self, view, a, st, attacking):
        p = self.p
        if not attacking:
            goals, kinds = self._candidates(view, a.name, ('stage',))
        else:
            goals, kinds = self._candidates(view, a.name, ('stage', 'strike'))
        strike = np.array([k == 'strike' for k in kinds])
        score, rob = self._score(view, a, goals,
                                 np.where(strike, view.rules.strike_time, 0.0))
        # Committed: go for the strike line that scores best. Robustness
        # CHOOSES the line (least exposure, most spread, best height); it no
        # longer GATES the attempt -- waiting for a provably open lane meant
        # never going at all, while a simultaneous rush wins (plan_guard).
        pick = np.where(strike, score, -np.inf)
        mode = 'strike'
        i = int(np.argmax(pick))
        r_now = float(np.linalg.norm(a.p - view.vip_p))
        st['stuck'] = (0.0 if r_now < st.get('best_r', np.inf) - 0.1
                       else st['stuck'] + p['replan_s'])
        st['best_r'] = min(st.get('best_r', np.inf), r_now)
        if st['goal'] is not None and st['mode'] == mode:
            cur, _ = self._score(view, a, st['goal'][None],
                                 [view.rules.strike_time if mode == 'strike' else 0.0])
            if cur[0] >= score[i] - p['commit_margin']:
                return
        # FEINT: during an attack, sometimes show the other side first
        if (attacking and view.t >= st['cool_until']
                and self.rng.random() < p['feint_prob']):
            gb = bearing(goals[i], view.vip_p)
            far = [j for j in range(len(goals)) if not strike[j]
                   and abs(wrap(bearing(goals[j], view.vip_p) - gb)) > np.radians(45)
                   and rob[j] >= 0.0]
            if far:
                j = max(far, key=lambda q: score[q])
                st.update(goal=goals[j], mode='feint',
                          feint_until=view.t + p['feint_s'],
                          cool_until=view.t + p['feint_s'] + p['feint_cool_s'])
                return
        st.update(goal=goals[i], score=float(score[i]), mode=mode)

    # -- the play -----------------------------------------------------------
    def _advance_play(self, view):
        p, play = self.p, self._play
        A = view.attackers
        if not A:
            return
        for a in A:
            if a.name not in self._lane:
                self._assign_lanes(view)
                break
        if play['state'] == 'stage':
            ready = all(float(np.linalg.norm(a.p - self._stage_point(view, a.name)))
                        < p['stage_tol'] for a in A)
            if ready or view.t - play['since'] > p['stage_timeout_s']:
                play.update(state='commit', since=view.t)
                names = [a.name for a in A]
                if len(names) > 1 and self.rng.random() < p['decoy_prob']:
                    decoy = names[int(self.rng.integers(len(names)))]
                    play['go_at'] = {n: view.t + (0.0 if n == decoy else p['decoy_lead_s'])
                                     for n in names}
                    play['decoy'] = decoy
                else:
                    play['go_at'] = {n: view.t for n in names}
                    play['decoy'] = None
                for n in names:
                    self._st[n]['stuck'] = 0.0
        elif play['state'] == 'commit':
            if all(self._st[a.name]['stuck'] >= p['stall_s'] for a in A):
                lo, hi = np.radians(p['rotate_deg'])
                play['base'] += float(self.rng.choice([-1.0, 1.0])
                                      * self.rng.uniform(lo, hi))
                play.update(state='stage', since=view.t, decoy=None, go_at={})
                self._assign_lanes(view)
                for a in A:
                    self._st[a.name].update(goal=None, mode='stage')

    def act(self, view):
        p, cfg = self.p, view.cfg
        self._advance_play(view)
        play = self._play
        D = view.defenders
        rules = view.rules
        v_a = view.v_max(self.team)
        out = {}
        for a in view.attackers:
            st = self._st.setdefault(a.name, {'goal': None, 'score': -np.inf,
                                              'mode': 'stage', 'next': view.t,
                                              'stuck': 0.0, 'feint_until': -1.0,
                                              'cool_until': -1.0})
            attacking = (play['state'] == 'commit'
                         and view.t >= play['go_at'].get(a.name, np.inf))
            feinting = st['mode'] == 'feint' and view.t < st['feint_until']
            if not attacking:
                st.update(goal=self._toward_lane(view, a), mode='stage', best_r=np.inf)
            elif view.t >= st['next'] and not feinting:
                self._replan(view, a, st, True)
                st['next'] = view.t + p['replan_s']
            label = st['mode'] if not (play['decoy'] == a.name and attacking) else 'decoy'

            # GANG UP: where defenders can be downed, join teammates round a
            # defender the rules say the pack can down -- unless striking.
            if st['mode'] != 'strike':
                hunt = self._hunt(view, a)
                if hunt is not None:
                    out[a.name] = seek(a.p, hunt[1], v_a, cfg.a_max)
                    self.labels[a.name] = f'gang {hunt[2]}'
                    continue

            # EVADE, judged by the RULES, not by distance. Staging: leave if
            # its down meter would fill here, or one step nearer the closest
            # defender. Striking: break off only once its public meter is
            # past evade_share and its strike meter is not already running.
            if D:
                d = min(D, key=lambda q: float(np.linalg.norm(q.p - a.p)))
                in_strike = (float(np.linalg.norm(a.p - view.vip_p))
                             <= rules.strike_radius)
                if attacking and st['mode'] == 'strike':
                    flee = (rules.can_down(ATTACK) and not in_strike
                            and view.meters.get(a.name, {}).get('down', 0.0)
                            >= p['evade_share'])
                else:
                    step = a.p + unit(d.p - a.p) * p['evade_extra']
                    flee = (self._rate(view, a, a.p) > 0.0
                            or self._rate(view, a, step) > 0.0)
                if flee:
                    st['stuck'] += view.dt
                    away = a.p - d.p
                    away[2] = 0.0
                    rel = a.p - view.vip_p
                    tang = unit(np.array([-rel[1], rel[0], 0.0]))
                    if st['goal'] is not None and float(tang @ (st['goal'] - a.p)) < 0.0:
                        tang = -tang
                    lo, hi = view.arena.vertical_room(a.p)
                    vert = np.array([0.0, 0.0, 1.0 if hi > lo else -1.0])
                    out[a.name] = v_a * unit(unit(away) + 0.7 * tang + 0.5 * vert)
                    self.labels[a.name] = 'evade'
                    continue
            goal = st['goal'] if st['goal'] is not None else a.p
            out[a.name] = seek(a.p, goal, v_a, cfg.a_max)
            self.labels[a.name] = label
        return out
