"""The finale: after the result, make the winner obvious from across the room.

A match ends on one tick: a strike, the last down, or the clock. On the
drones that moment was easy to miss -- the striker just landed, the rest held
-- so who won lived in the console. The finale is a short piece of
choreography, the same for every strategy and rule set:

* **Rally.** The WINNERS take a formation round the VIP. The LOSERS go dark,
  sink to a low height and go home to their marks, where they land -- but
  only clear of the VIP (``land_clear`` beyond its keep-out): a drone being
  landed cannot dodge, and a hand-flown DJI can drift onto it.
* **Emote.**
  - Defence wins, *VIP secure*: an honour guard -- a ring round the VIP that
    turns slowly with a Mexican wave running round it.
  - Attack wins, *VIP compromised*: a capture ring -- tight round the VIP and
    squeezing in and out. The attacker that struck stays up for it instead of
    landing. Everything is VIP-relative, so a hand-flown DJI that moves now
    drags its captors (or its guard) along with it.
* **Home.** The winners fly to their marks at start height and hold there;
  ``guard_show`` then runs its usual end gates and lands them.

Lights: winners flash green against their team colour, then hold green;
losers go dark.

Pure Python like the engine. Every move goes through ``Match.steer``, so the
safety layer is still underneath all of it; ``plan_guard`` flies the finale
on its stand-in aircraft and checks it like the match.
"""

from dataclasses import dataclass, field

import numpy as np

from crazyflie_shows.guard.policies.common import assign, into_room
from crazyflie_shows.guard.world import DEFENSE, Arena

DEFAULTS = {
    'speed': 0.6,           # m/s for every finale move (capped at both team caps)
    'rally_s': 7.0,         # longest the winners get to reach formation
    'emote_s': 10.0,        # how long the emote runs
    'home_s': 12.0,         # longest the winners get to reach their marks
    'guard_r': 1.9,         # m from the VIP: the defence's honour guard
    'capture_r': 1.80,      # m from the VIP: the attack's capture ring
    'squeeze': 0.12,        # m the capture ring breathes in and out
    'turn_rate': 0.30,      # rad/s the formation turns during the emote
    'wave_dz': 0.20,        # m: the honour guard's Mexican wave
    'period_s': 2.5,        # s per wave / squeeze
    'loser_dz': 0.15,       # m above the floor the losers sink to
    'flash_hz': 2.0,        # winners' green flash
    'arrive_m': 0.30,       # within this of its slot counts as arrived
    'clear_m': 0.55,        # a home this close to a grounded drone moves
    'land_clear': 0.8,      # m beyond the VIP keep-out a loser must be to land
}

RALLY, EMOTE, HOME, DONE = 'rally', 'emote', 'home', 'done'


@dataclass
class FinaleStep:
    goals: dict                    # name -> 3D goal, for Match.steer
    land: list                     # losers to land NOW (once each)
    lights: dict                   # name -> 'win' | 'team' | 'off'
    phase: str
    done: bool = False
    banner: str = ''
    slots: dict = field(default_factory=dict)   # the formation, for the picture


def check(cfg, params):
    """What is wrong with a finale's numbers (plain sentences)."""
    p = {**DEFAULTS, **params}
    bad = []
    if p['capture_r'] - p['squeeze'] < cfg.d_vip + 0.2:
        bad.append(f'finale capture ring comes to {p["capture_r"] - p["squeeze"]:.2f} m '
                   f'from the VIP, inside its {cfg.d_vip:.2f} m keep-out + 0.2')
    if p['guard_r'] < cfg.d_vip + 0.2:
        bad.append(f'finale honour guard at {p["guard_r"]:.2f} m is inside the '
                   f'VIP keep-out + 0.2')
    if p['speed'] <= 0.0:
        bad.append('finale speed must be positive')
    return bad


class Finale:
    def __init__(self, cfg, winner, agents, homes, vip_p, t0, params=None):
        """``agents``: the match's agents AFTER the result (the winning
        striker already reinstated). ``homes``: name -> mark (the floor
        position it took off from)."""
        unknown = set(params or {}) - set(DEFAULTS)
        if unknown:
            raise KeyError(f'finale has no parameter(s) {sorted(unknown)}; it has '
                           f'{sorted(DEFAULTS)}')
        self.p = {**DEFAULTS, **(params or {})}
        # never faster than either team flew: a slowed-down show (the PID
        # controller's ~0.6 s lag, 2026-11-06) slows its finale with it
        self.p['speed'] = min(self.p['speed'], cfg.v_max_defense, cfg.v_max_attack)
        self.cfg = cfg
        self.arena = Arena(cfg)
        self.winner = winner
        self.t0 = t0
        self.phase = RALLY
        self.since = t0
        self.winners = sorted(n for n, a in agents.items()
                              if a.active and a.team == winner)
        self.losers = sorted(n for n, a in agents.items()
                             if a.active and a.team != winner)
        self.team = {n: a.team for n, a in agents.items()}
        self.homes = {n: np.asarray(h, float).copy() for n, h in homes.items()}
        self.landed = set()
        self.banner = ('VIP SECURE -- DEFENCE WINS' if winner == DEFENSE
                       else 'VIP COMPROMISED -- ATTACK WINS')
        # one slot per winner, in the order that costs the least flying
        n = len(self.winners)
        self._offs = 2.0 * np.pi * np.arange(n) / max(n, 1)
        vip = np.asarray(vip_p, float)
        pos = {k: agents[k].p for k in self.winners}
        self._psi0 = (float(np.arctan2(*(np.mean([pos[k] - vip for k in self.winners],
                                                 axis=0)[[1, 0]])))
                      if n else 0.0)
        slots = [self._slot(vip, j, self._psi0, 0.0) for j in range(n)]
        cost = np.array([[float(np.linalg.norm(s - pos[k])) for s in slots]
                         for k in self.winners]) if n else np.zeros((0, 0))
        self._slot_of = {self.winners[i]: j for i, j in assign(cost)} if n else {}

    # ------------------------------------------------------------------
    def _height(self, vip):
        lo, hi = self.cfg.floor + 0.35, self.cfg.ceiling - 0.35
        return float(np.clip(vip[2], lo, hi))

    def _slot(self, vip, j, psi, tau):
        """Slot ``j`` of the formation at turn ``psi``, ``tau`` s into the emote."""
        p = self.p
        ang = psi + self._offs[j]
        w = 2.0 * np.pi / p['period_s']
        if self.winner == DEFENSE:
            r = p['guard_r']
            n = max(len(self._offs), 1)
            dz = p['wave_dz'] * np.sin(w * tau - 2.0 * np.pi * j / n) if tau > 0 else 0.0
        else:
            r = p['capture_r'] + (p['squeeze'] * np.sin(w * tau) if tau > 0 else 0.0)
            dz = 0.0
        q = np.asarray(vip, float) + r * np.array([np.cos(ang), np.sin(ang), 0.0])
        q[2] = self._height(vip) + dz
        return into_room(q, self.arena, 0.4)

    def _home(self, name, grounded, height):
        h = self.homes[name].copy()
        for g in grounded:
            d = h[:2] - g[:2]
            n = float(np.linalg.norm(d))
            if n < self.p['clear_m']:
                d = d / n if n > 1e-6 else np.array([1.0, 0.0])
                h[:2] = g[:2] + d * self.p['clear_m']
        h[2] = height
        return into_room(h, self.arena, 0.4)

    def lights(self, t):
        out = {}
        flash = int((t - self.t0) * self.p['flash_hz'] * 2.0) % 2 == 0
        for n in self.winners:
            out[n] = 'win' if (self.phase in (HOME, DONE) or flash) else 'team'
        for n in self.losers:
            out[n] = 'off'
        return out

    def update(self, t, vip_p, agents):
        """One finale tick. ``agents``: the match's agents (positions now)."""
        p, cfg = self.p, self.cfg
        vip = np.asarray(vip_p, float)
        grounded = [a.p for a in agents.values() if not a.active]
        goals, land, slots = {}, [], {}

        # the losers: dark, low, home, down
        low = cfg.floor + p['loser_dz']
        for n in self.losers:
            if n in self.landed or not agents[n].active:
                continue
            home = self._home(n, grounded, low)
            # A drone being landed cannot dodge (the landing commander has it,
            # and the safety layer treats it as fixed), and nothing stops the
            # VIP -- a hand-flown DJI -- drifting onto it. So a loser lands
            # only CLEAR of the VIP, and its home is pushed out until it is.
            rim = cfg.d_vip + p['land_clear']
            out = home[:2] - vip[:2]
            r = float(np.linalg.norm(out))
            if r < rim + p['arrive_m']:
                # past the rim by the arrival tolerance, so arriving IS clear
                out = out / r if r > 1e-6 else np.array([1.0, 0.0])
                home[:2] = vip[:2] + out * (rim + p['arrive_m'])
                home = into_room(home, self.arena, 0.4)
            here = agents[n].p
            arrived = float(np.linalg.norm(here[:2] - home[:2])) < p['arrive_m']
            clear = float(np.linalg.norm(here[:2] - vip[:2])) >= rim
            late = t - self.t0 > p['rally_s'] + p['emote_s']
            if clear and (arrived or late):
                land.append(n)
                self.landed.add(n)
            else:
                goals[n] = home

        # the winners: the phase clock
        tau = t - self.since
        if self.phase == RALLY:
            ok = all(float(np.linalg.norm(
                agents[n].p - self._slot(vip, self._slot_of[n], self._psi0, 0.0)))
                < p['arrive_m'] for n in self.winners if agents[n].active)
            if ok or tau > p['rally_s']:
                self.phase, self.since, tau = EMOTE, t, 0.0
        elif self.phase == EMOTE and tau > p['emote_s']:
            self.phase, self.since, tau = HOME, t, 0.0
        elif self.phase == HOME:
            ok = all(float(np.linalg.norm(
                agents[n].p - self._home(n, grounded, cfg.start_height))) < p['arrive_m']
                for n in self.winners if agents[n].active)
            if ok or tau > p['home_s']:
                self.phase = DONE

        for n in self.winners:
            if not agents[n].active:
                continue
            j = self._slot_of[n]
            if self.phase == RALLY:
                goals[n] = self._slot(vip, j, self._psi0, 0.0)
            elif self.phase == EMOTE:
                goals[n] = self._slot(vip, j, self._psi0 + p['turn_rate'] * tau, tau)
            else:
                goals[n] = self._home(n, grounded, cfg.start_height)
            slots[n] = goals[n]

        done = self.phase == DONE and all(n in self.landed or not agents[n].active
                                          for n in self.losers)
        return FinaleStep(goals, land, self.lights(t), self.phase, done,
                          self.banner, slots)
