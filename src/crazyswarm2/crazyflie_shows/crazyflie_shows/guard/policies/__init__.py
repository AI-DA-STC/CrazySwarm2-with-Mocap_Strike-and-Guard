"""Strategies: one per team per match, chosen by name, swappable.

Writing one
-----------
Subclass :class:`Policy`, set ``team`` and ``name``, list your tunables in
``DEFAULTS``, and implement ``act``::

    from crazyflie_shows.guard.policies import Policy, register
    from crazyflie_shows.guard.policies.common import seek
    from crazyflie_shows.guard.world import ATTACK

    @register
    class Straight(Policy):
        team = ATTACK
        name = 'straight'
        DEFAULTS = {'aim_height': 0.0}

        def act(self, view):
            out = {}
            for a in view.attackers:
                goal = view.vip_p + [0, 0, self.p['aim_height']]
                out[a.name] = seek(a.p, goal, view.v_max(self.team), view.cfg.a_max)
            return out

``act`` returns a velocity (m/s, world frame, 3-vector) per ACTIVE drone of
its own team; a drone left out holds still. That is the whole contract:
what comes back is a REQUEST. The engine caps it at the team's speed and the
config's acceleration, and the safety layer then changes it as little as
possible to keep every pair, the room and the band safe. So a strategy can
be aggressive, naive or buggy and still not crash anything -- which is what
makes it safe to try one on drones.

Using one without editing this package: put it in any importable module and
pass that module's path (``policy_module:=my_lab.strategies`` to the show,
``--policy-module`` to the planner); importing it runs ``@register``.

Strategies may keep state between ticks (``reset`` is called once, before
the first ``act``) and may set ``self.labels[name]`` to a short word -- shown
in logs and used for the LED cues -- saying what each drone is doing.

Saying what you MEAN (optional, for the picture only): set
``self.intents[name] = Intent(kind, goal, target)`` for a drone -- where it is
going, which opponent it is about, and what kind of move it is -- and
``self.plan`` for the team as a whole (``{'phase': 'stage', 'lanes':
[(bearing_rad, dz), ...], 'decoy': name}``). The viz draws them as an
operations map: screens, pincer hooks, staging areas, axes of attack. The
engine hands them to the picture only; the OTHER team never sees them (that
would be reading the opponent's mind, engine.py). A strategy that sets none
still plays; its drones just get no intent lines.
"""

import importlib
from dataclasses import dataclass
from typing import Optional

import numpy as np

from crazyflie_shows.guard.world import ATTACK, DEFENSE

#: Intent kinds the viz knows how to draw (anything else gets a plain line).
DEFENSE_KINDS = ('post', 'block', 'pincer', 'bail')
ATTACK_KINDS = ('stage', 'strike', 'feint', 'decoy', 'evade', 'gang')


@dataclass
class Intent:
    """What one drone means to do, for the picture (never for the opponent)."""
    kind: str
    goal: Optional[np.ndarray] = None     # where it is heading (3,)
    target: str = ''                      # the opponent it is about, if any

_REGISTRY = {DEFENSE: {}, ATTACK: {}}


class Policy:
    team = None
    name = None
    #: Tunables and their defaults; ``make(..., params)`` may override any of
    #: them and nothing else (a typo is an error, not a silent default).
    DEFAULTS = {}

    def __init__(self, **params):
        unknown = set(params) - set(self.DEFAULTS)
        if unknown:
            raise KeyError(f'{self.team} strategy {self.name!r} has no '
                           f'parameter(s) {sorted(unknown)}; it has '
                           f'{sorted(self.DEFAULTS)}')
        self.p = {**self.DEFAULTS, **params}
        self.labels = {}
        self.intents = {}
        self.plan = {}

    def reset(self, view, rng):
        """Called once before the first ``act``. ``rng``: numpy Generator."""
        self.rng = rng

    def act(self, view):
        raise NotImplementedError


def register(cls):
    if cls.team not in _REGISTRY or not cls.name:
        raise ValueError(f'{cls.__name__}: set team (defense|attack) and name')
    _REGISTRY[cls.team][cls.name] = cls
    return cls


def available(team):
    _load_builtins()
    return sorted(_REGISTRY[team])


def make(team, name, params=None):
    _load_builtins()
    try:
        cls = _REGISTRY[team][name]
    except KeyError:
        raise KeyError(f'no {team} strategy {name!r}; available: '
                       f'{", ".join(available(team))}') from None
    return cls(**(params or {}))


def load_module(path):
    """Import a module of strategies so its ``@register`` calls run."""
    if path:
        importlib.import_module(path)


def describe(team, name):
    _load_builtins()
    cls = _REGISTRY[team][name]
    doc = (cls.__doc__ or '').strip().split('\n')[0]
    return doc


def _load_builtins():
    # Imported lazily so this module has no import cycle with them.
    from crazyflie_shows.guard.policies import (  # noqa: F401
        attack_coordinated, attack_direct, attack_flood, attack_wolfpack,
        defense_hunter, defense_ring, defense_shell, defense_zone)
