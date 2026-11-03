"""One tick of a match: strategies -> limits -> safety layer -> setpoints -> referee.

Pure Python. ``plan_guard`` drives it with a simulated aircraft model and
``guard_show`` drives it with mocap and a radio; both call :meth:`Match.step`
the same way, so what is verified offline is the code that flies.

Per tick, in this order (the order is the design):

1. Build the :class:`~crazyflie_shows.guard.world.View` from the best known
   positions (mocap where fresh, the setpoint otherwise).
2. Ask both strategies for a velocity per active drone.
3. Cap each request at its team's speed and the acceleration limit.
4. The safety layer projects ALL requests at once onto the safe set (every
   aircraft pair, the VIP, retiring drones, walls, floor, ceiling). Nothing
   after this step may undo it except the backstop clamp, which should
   never fire and is counted if it does.
5. Integrate into setpoints.
6. The referee integrates the rule set's meters from the AIRCRAFT positions;
   downed drones (either team, if the rules allow) and striking attackers
   start RETIRING (the caller lands them) and become obstacles.

What a strategy may know -- the platform is pointless if a team can read the
other's intent, so this is enforced here, not left to good manners:

* **Opponents are OBSERVED, never asked.** Their position is what mocap sees
  (the setpoint in the simulator, which has no mocap); their velocity is
  ESTIMATED from that position (a low-passed difference, the escort's
  VelocityEstimator). Their commanded velocity -- their strategy's decision --
  is never in an opponent's View. A team sees its OWN commands.
* **Each team gets its own View, built fresh every tick, of copies**: its own
  Agent objects, its own copy of the config, the arena and the rule set. Mutating them
  changes nothing outside that team's strategy.
* **Each team has its own random stream**, so one team's dice cannot move
  the other's.
* Both teams decide on the SAME tick's observations; neither sees the other's
  requests for that tick.

test/test_guard.py has a spy and a vandal that check all of this.
"""

import copy
import dataclasses

from dataclasses import dataclass, field

import numpy as np

from crazyflie_shows import escort
from crazyflie_shows.guard import safety_layer
from crazyflie_shows.guard.rules import Referee
from crazyflie_shows.guard.world import (ACTIVE, ATTACK, DEFENSE, RETIRING,
                                         Agent, Arena, View)


@dataclass
class Tick:
    setpoints: dict                # name -> (position, velocity), active only
    retired: list                  # names that must be landed NOW
    events: list                   # rules.Event, new this tick
    safety: object                 # safety_layer.SafetyResult (or None)
    backstop: list                 # names whose setpoint the clamp moved
    labels: dict = field(default_factory=dict)


class Match:
    def __init__(self, cfg, rules, defense, attack, starts, defenders, attackers,
                 vip_p, rng):
        """``rules``: a rule set (guard.rules.make). ``starts``: name -> 3D
        start position (where streaming begins)."""
        self.cfg = cfg
        self.rules = rules
        self.defense, self.attack = defense, attack
        self.agents = {}
        for team, names in ((DEFENSE, defenders), (ATTACK, attackers)):
            for n in names:
                self.agents[n] = Agent(n, team, np.asarray(starts[n], float).copy(),
                                       np.zeros(3))
        self.sp = {n: np.asarray(starts[n], float).copy() for n in self.agents}
        self.v = {n: np.zeros(3) for n in self.agents}
        self._est = {n: escort.VelocityEstimator() for n in self.agents}
        self.v_obs = {n: np.zeros(3) for n in self.agents}
        self.referee = Referee(rules)
        self.t = 0.0
        self.stats = {'ticks': 0, 'corrected': 0, 'emergency': 0,
                      'not_converged': 0, 'backstop': 0}
        # one independent random stream per team, both from the match seed
        s_def, s_att = rng.integers(0, 2 ** 63 - 1, size=2)
        self._rng = {DEFENSE: np.random.default_rng(int(s_def)),
                     ATTACK: np.random.default_rng(int(s_att))}
        vip_p = np.asarray(vip_p, float)
        self._observe(0.0, None)
        defense.reset(self._view_for(DEFENSE, 0.0, vip_p, np.zeros(3)),
                      self._rng[DEFENSE])
        attack.reset(self._view_for(ATTACK, 0.0, vip_p, np.zeros(3)),
                     self._rng[ATTACK])

    # ------------------------------------------------------------------
    def _observe(self, dt, measured):
        """Where every aircraft is (mocap, else setpoint), and how fast it is
        moving, ESTIMATED from those positions."""
        for n, a in self.agents.items():
            m = None if measured is None else measured.get(n)
            a.p = np.asarray(m if m is not None else self.sp[n], float).copy()
            a.v = self.v[n].copy()
            self.v_obs[n] = self._est[n].update(a.p, dt)

    def _view_for(self, team, dt, vip_p, vip_v):
        """One team's View: copies only; opponents observed, not asked."""
        cfg = copy.deepcopy(self.cfg)
        agents = {}
        for n, a in self.agents.items():
            v = self.v[n] if a.team == team else self.v_obs[n]
            agents[n] = Agent(a.name, a.team, a.p.copy(), np.array(v, float),
                              a.status, a.outcome)
        return View(self.t, dt, np.array(vip_p, float), np.array(vip_v, float),
                    agents, Arena(cfg), cfg, copy.deepcopy(self.rules),
                    {n: dict(m) for n, m in self.referee.meters.items()},
                    [dataclasses.replace(e) for e in self.referee.events])

    def resync(self, positions):
        """Re-seed setpoints (after a high-level gather, from live poses)."""
        for n, p in positions.items():
            self.sp[n] = np.asarray(p, float).copy()
            self.v[n] = np.zeros(3)

    def result(self):
        return self.referee.result(self.t, self.agents)

    # ------------------------------------------------------------------
    def step(self, dt, vip_p, vip_v, measured=None):
        cfg = self.cfg
        self.t += dt
        # A retiring drone is being landed by the high-level commander. Model
        # its descent in the setpoint, so that with no mocap (the simulator)
        # it is still an obstacle where it really is, not frozen in mid-air.
        for n, a in self.agents.items():
            if a.status == RETIRING:
                self.sp[n][2] = max(0.0, self.sp[n][2] - cfg.land_speed * dt)
        vip_p = np.asarray(vip_p, float)
        vip_v = np.asarray(vip_v, float)
        self._observe(dt, measured)

        want = {}
        for pol in (self.defense, self.attack):
            got = pol.act(self._view_for(pol.team, dt, vip_p, vip_v)) or {}
            for n, v in got.items():
                a = self.agents.get(n)
                if a is None or a.team != pol.team or not a.active:
                    continue          # a strategy may only steer its own
                want[n] = np.asarray(v, float)

        active = [n for n, a in self.agents.items() if a.active]
        retiring = [n for n, a in self.agents.items() if a.status == RETIRING]
        nominal = []
        for n in active:
            a = self.agents[n]
            v = want.get(n, np.zeros(3))
            cap = cfg.v_max_defense if a.team == DEFENSE else cfg.v_max_attack
            s = float(np.linalg.norm(v))
            if s > cap:
                v = v * (cap / s)
            dv = v - self.v[n]
            lim = cfg.a_max * dt
            s = float(np.linalg.norm(dv))
            if s > lim:
                v = self.v[n] + dv * (lim / s)
            nominal.append(v)

        # fixed bodies: the VIP, then every retiring drone (descending)
        P_fix = [vip_p]
        V_fix = [vip_v]
        ax_fix = [safety_layer.keep_out(cfg, 'vip')]
        for n in retiring:
            P_fix.append(self.agents[n].p)
            down = self.agents[n].p[2] > cfg.floor * 0.5
            V_fix.append(np.array([0.0, 0.0, -cfg.land_speed if down else 0.0]))
            ax_fix.append(safety_layer.keep_out(cfg, 'cf'))

        res = None
        sp_out, clamped = {}, []
        if active:
            P = np.array([self.sp[n] for n in active])
            res = safety_layer.filter_commands(cfg, P, np.array(nominal),
                                               P_fix, V_fix, ax_fix)
            self.stats['corrected'] += int(np.count_nonzero(res.corrected))
            self.stats['emergency'] += int(res.emergency)
            self.stats['not_converged'] += int(not res.converged)
            for i, n in enumerate(active):
                v = res.velocities[i]
                sp, hit = safety_layer.backstop(cfg, self.sp[n] + v * dt)
                if hit:
                    clamped.append(n)
                    v = (sp - self.sp[n]) / max(dt, 1e-6)
                self.sp[n], self.v[n] = sp, v
                sp_out[n] = (sp.copy(), v.copy())
        self.stats['backstop'] += len(clamped)
        self.stats['ticks'] += 1

        # the referee judges the aircraft: refresh positions to this tick's
        for n, a in self.agents.items():
            m = None if measured is None else measured.get(n)
            a.p = np.asarray(m if m is not None else self.sp[n], float).copy()
        events = self.referee.update(self.t, dt, self.agents, vip_p)
        retired = []
        for e in events:
            a = self.agents[e.who]
            if a.status == ACTIVE:
                a.status = RETIRING
                a.outcome = 'downed' if e.kind == 'down' else 'struck'
                self.v[a.name] = np.zeros(3)
                retired.append(a.name)
                sp_out.pop(a.name, None)
        labels = {**self.defense.labels, **self.attack.labels}
        return Tick(sp_out, retired, events, res, clamped, labels)
