"""Rules: how a match is scored, chosen by name like the strategies.

Every rule set is written as METERS. Each drone has a DOWN meter, and each
attacker a STRIKE meter. They run from 0 to 1, and a full meter is an event:
the drone is downed (it lands), or the attacker strikes (it scores, then
lands). A rule set says only three things:

* how fast each meter fills, given where everybody is (``down_rates``,
  ``strike_rates``: per second, so 1/rate is the time to fill from empty);
* how fast it drains when nothing fills it (``drain``: per second; inf
  means it resets the moment the condition stops, the old 'tag' clock);
* who has won (``result``).

That one shape covers a clock ("within range for 1.1 s": rate 1/1.1, reset
on leaving), a graded counter ("faster the more opponents are near"), zones,
and anything else that can be said as a rate.

**One definition, two uses.** The referee integrates the meters to decide
what happened (the STL monitor's true/false). Strategies get the SAME rule
object in their View, plus everybody's current meters (public, like a
scoreboard), so they can evaluate the rules on PREDICTED positions while
planning -- how fast would my meter fill if I went there? That is the
quantitative side of the same rules, and it is what lets one strategy play
under any rule set without knowing which.

**Rules never touch safety.** The CBF and the watchdogs sit underneath every
rule set. ``problems(cfg)`` refuses a rule set that could only be satisfied
by contact (a reach inside the keep-out, a strike radius inside the VIP's).

Writing one: subclass :class:`Rules`, set ``name``, ``DEFAULTS`` and
``DOWNABLE``, implement ``down_rates`` (and ``drain`` if it is not a plain
reset), decorate with ``@register``. ``standard.py`` holds the built-in sets.
"""

from dataclasses import dataclass, field

import numpy as np

from crazyflie_shows.guard.world import ATTACK, DEFENSE

_REGISTRY = {}

#: A meter at or above this is full. A sum of 20 Hz ticks lands a hair under
#: an exact 1.0 (22 x 0.05/1.1 = 0.9999999999999999), which would cost a
#: tick against the old seconds-based clock.
FULL = 1.0 - 1e-9


class Rules:
    name = None
    #: The tunables every rule set has; a subclass adds its own.
    COMMON = {
        'strike_radius': 2.4,      # m, attacker to VIP (3D)
        'strike_time': 1.0,        # s inside it to strike
        'strikes_to_win': 1,
        'duration': 90.0,          # s on the clock
    }
    DEFAULTS = {}
    #: The teams whose drones can be downed under this rule set.
    DOWNABLE = ()

    def __init__(self, **params):
        allowed = {**self.COMMON, **self.DEFAULTS}
        unknown = set(params) - set(allowed)
        if unknown:
            raise KeyError(f'rule set {self.name!r} has no parameter(s) '
                           f'{sorted(unknown)}; it has {sorted(allowed)}')
        self.p = {**allowed, **params}

    # -- what strategies plan with ------------------------------------------
    @property
    def strike_radius(self):
        return float(self.p['strike_radius'])

    @property
    def strike_time(self):
        return float(self.p['strike_time'])

    @property
    def duration(self):
        return float(self.p['duration'])

    @property
    def reach(self):
        """Distance within which an opponent counts against a drone (0 = none)."""
        return float(self.p.get('reach', 0.0))

    @property
    def down_time(self):
        """Time to down a drone at the slowest non-zero rate (one unit)."""
        return float(self.p.get('down_time', np.inf))

    def can_down(self, team):
        return team in self.DOWNABLE

    def strike_rates(self, att_p, vip_p):
        """(K,) strike-meter rate for attackers at ``att_p`` (K, 3)."""
        d = np.linalg.norm(np.asarray(att_p, float) - np.asarray(vip_p, float), axis=-1)
        return np.where(d <= self.strike_radius, 1.0 / self.strike_time, 0.0)

    def down_rates(self, victim_team, victim_p, opp_p, ally_p, vip_p):
        """(K,) down-meter rate for drones of ``victim_team``.

        ``victim_p`` (K, 3); ``opp_p`` (K, M, 3) the active opponents and
        ``ally_p`` (K, A, 3) the victim's active teammates (not itself), per
        case -- K cases at once, so a planner can score a whole rollout in one
        call. M or A may be 0.
        """
        return np.zeros(len(np.asarray(victim_p).reshape(-1, 3)))

    def drain(self, kind):
        """Per-second drain of a meter nothing is filling ('down' | 'strike')."""
        return np.inf

    def problems(self, cfg):
        bad = []
        if self.strike_radius <= cfg.d_vip:
            bad.append(f'strike_radius {self.strike_radius:.2f} m is inside the '
                       f'{cfg.d_vip:.2f} m keep-out round the VIP: nobody could '
                       'ever strike')
        if self.DOWNABLE and self.reach <= cfg.d_cc:
            bad.append(f'reach {self.reach:.2f} m is inside the {cfg.d_cc:.2f} m '
                       'the safety layer keeps between drones: nobody could '
                       'ever be downed')
        return bad

    def describe(self):
        return self.name

    def result(self, t, agents, events):
        strikes = sum(e.kind == 'strike' for e in events)
        downs = sum(e.kind == 'down' for e in events)
        live = {team: [a for a in agents.values() if a.team == team and a.active]
                for team in (DEFENSE, ATTACK)}

        def r(winner, why):
            return Result(winner, why, strikes, downs, t, list(events))

        if strikes >= int(self.p['strikes_to_win']):
            return r(ATTACK, f'{strikes} strike(s)')
        if not live[ATTACK]:
            return r(DEFENSE, 'no attacker left in play')
        if self.can_down(DEFENSE) and not live[DEFENSE]:
            return r(ATTACK, 'no defender left in play')
        if t >= self.duration:
            return r(DEFENSE, 'held to the end of the clock')
        return r('', '')


@dataclass
class Event:
    t: float
    kind: str              # 'strike' | 'down'
    who: str               # the drone it happened to
    by: str = ''           # for a down: the nearest opponent

    def __str__(self):
        if self.kind == 'down':
            return f't+{self.t:5.1f}s  {self.by} DOWNED {self.who} -- it lands'
        return f't+{self.t:5.1f}s  {self.who} STRUCK the VIP -- it lands'


@dataclass
class Result:
    winner: str            # 'defense' | 'attack' | '' (still playing)
    reason: str
    strikes: int
    downs: int
    t: float
    events: list = field(default_factory=list)


class Referee:
    """Integrates the meters from the AIRCRAFT positions. Rule-set-blind."""

    def __init__(self, rules):
        self.rules = rules
        self.meters = {}
        self.events = []

    def update(self, t, dt, agents, vip_p):
        rules = self.rules
        vip_p = np.asarray(vip_p, float)
        act = [a for a in agents.values() if a.active]
        for a in act:
            self.meters.setdefault(a.name, {'down': 0.0, 'strike': 0.0})
        # every rate from the SAME positions, before any event: simultaneous
        rate = {}
        for a in act:
            s = (float(rules.strike_rates(a.p[None], vip_p)[0])
                 if a.team == ATTACK else 0.0)
            d = 0.0
            if rules.can_down(a.team):
                opp = [b.p for b in act if b.team != a.team]
                ally = [b.p for b in act if b.team == a.team and b is not a]
                d = float(rules.down_rates(
                    a.team, a.p[None],
                    np.asarray(opp, float).reshape(1, -1, 3),
                    np.asarray(ally, float).reshape(1, -1, 3), vip_p)[0])
            rate[a.name] = {'strike': s, 'down': d}
        new = []
        for a in act:
            m = self.meters[a.name]
            for kind in ('strike', 'down'):
                r = rate[a.name][kind]
                m[kind] = (min(1.0, m[kind] + r * dt) if r > 0.0
                           else max(0.0, m[kind] - rules.drain(kind) * dt))
            # A full meter fires once and empties: the engine retires the
            # drone at once, and nothing may fire twice for one fill.
            if a.team == ATTACK and m['strike'] >= FULL:
                new.append(Event(t, 'strike', a.name))
                m['strike'] = m['down'] = 0.0
            elif m['down'] >= FULL:
                opp = [b for b in act if b.team != a.team]
                by = min(opp, key=lambda b: float(np.linalg.norm(b.p - a.p))).name if opp else ''
                new.append(Event(t, 'down', a.name, by))
                m['strike'] = m['down'] = 0.0
        self.events.extend(new)
        return new

    def result(self, t, agents):
        return self.rules.result(t, agents, self.events)


def register(cls):
    if not cls.name:
        raise ValueError(f'{cls.__name__}: set name')
    _REGISTRY[cls.name] = cls
    return cls


def available():
    _load_builtins()
    return sorted(_REGISTRY)


def make(name, params=None):
    _load_builtins()
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise KeyError(f'no rule set {name!r}; available: '
                       f'{", ".join(available())}') from None
    return cls(**(params or {}))


def describe(name):
    _load_builtins()
    return (_REGISTRY[name].__doc__ or '').strip().split('\n')[0]


def _load_builtins():
    from crazyflie_shows.guard.rules import standard  # noqa: F401
