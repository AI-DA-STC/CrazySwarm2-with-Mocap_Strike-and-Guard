"""RViz markers for a guard match, drawn like an operations map.

Used by ``plan_guard --rviz`` (offline matches played in real time) and by
``guard_show`` (a flight); the mission console's 3D view draws the same
messages. Fixed frame ``world``; open it with
``rviz2 -d <share>/crazyflie_shows/data/guard.rviz``.

What it draws (2026-11-05: intent over clutter):

* **Who is who**: a team-coloured halo round each drone and a label (name,
  role, meters). The drone itself is the real one -- TF in RViz, /poses in
  the console -- so no extra dot sits on top of it. ``bodies=True`` (the
  offline player, which has no real drones) adds a small body sphere.
* **What each drone means to do**: the strategy's Intent, as a symbol.

  ====================  =====================================================
  defence ``block``     solid line to its intercept point, a SCREEN bar there
                        facing the attacker, a dotted marking line to it
  defence ``pincer``    a hooked arrow round onto the attacker
  defence ``post``      a small diamond at its post, dotted if it is away
  defence ``bail``      dashed arrow back toward the VIP
  attack ``stage``      dashed line to its lane's staging point, a circle
                        there (the assembly area)
  attack ``strike``     thick arrow to its strike point, dotted on to the VIP
  attack ``decoy``      the same in magenta: the one sent first, to be seen
  attack ``feint``      dashed amber arrow: the side it is SHOWING
  attack ``evade``      short arrow where it is running
  attack ``gang``       arrow to its spot round a defender, dotted to that one
  ====================  =====================================================

* **The attack's plan**: its lanes as axes of advance from the staging ring
  to the strike circle (dashed while staging, arrows once committed), and
  the play's phase on the scoreboard.
* **The safety layer at work**: a drone's keep-out appears only on the ticks
  the CBF is changing its command.
* **Events**: a ring bursts where a drone is downed and at the VIP on a
  strike; the result turns the VIP green (secure) or red (compromised) under
  a banner.

Nothing here may break a flight: every publish is wrapped, so a marker that
fails costs a picture, never a drone.
"""

from collections import deque

import numpy as np

from crazyflie_shows import safety
from crazyflie_shows.guard.world import ATTACK, DEFENSE, RETIRING

try:
    from builtin_interfaces.msg import Duration
    from geometry_msgs.msg import Point
    from std_msgs.msg import ColorRGBA
    from visualization_msgs.msg import Marker, MarkerArray
except ImportError:                                   # pragma: no cover
    Marker = None

TOPIC = '/guard/markers'
FRAME = 'world'

C_DEF = (0.25, 0.55, 1.00, 0.95)
C_ATT = (1.00, 0.22, 0.12, 0.95)
C_DECOY = (1.00, 0.25, 0.85, 0.95)
C_FEINT = (1.00, 0.70, 0.10, 0.95)
C_OUT = (0.55, 0.55, 0.55, 0.70)
C_VIP = (1.00, 1.00, 1.00, 0.95)
C_SECURE = (0.20, 1.00, 0.35, 0.95)
C_LOST = (1.00, 0.15, 0.10, 0.95)
C_ROOM = (0.80, 0.80, 0.80, 0.80)
C_TEXT = (1.00, 1.00, 1.00, 0.95)


def _c(rgba):
    return ColorRGBA(r=float(rgba[0]), g=float(rgba[1]), b=float(rgba[2]),
                     a=float(rgba[3]))


def _pt(p):
    return Point(x=float(p[0]), y=float(p[1]), z=float(p[2]))


def _a(rgba, alpha):
    return (*rgba[:3], alpha)


# ----------------------------------------------------------------- geometry
# Every symbol is a list of segments [(p, q), ...] so one LINE_LIST draws it.

def _unit(v, fallback=(1.0, 0.0, 0.0)):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.asarray(fallback, float)


def _side(d):
    """A horizontal unit vector square to ``d``."""
    s = np.array([-d[1], d[0], 0.0])
    return _unit(s, (0.0, 1.0, 0.0))


def seg_line(a, b):
    return [(np.asarray(a, float), np.asarray(b, float))]


def seg_dashed(a, b, dash=0.16, gap=0.10):
    a, b = np.asarray(a, float), np.asarray(b, float)
    d = b - a
    n = float(np.linalg.norm(d))
    if n < 1e-6:
        return []
    u = d / n
    out, s = [], 0.0
    while s < n:
        e = min(s + dash, n)
        out.append((a + u * s, a + u * e))
        s = e + gap
    return out


def seg_head(a, b, size=0.20, spread=0.45):
    """An arrowhead at ``b`` for a line from ``a``."""
    b = np.asarray(b, float)
    d = _unit(b - np.asarray(a, float))
    s = _side(d)
    back = -d * np.cos(spread) * size
    return [(b, b + back + s * np.sin(spread) * size),
            (b, b + back - s * np.sin(spread) * size)]


def seg_curve(a, b, bulge, n=12):
    """A quadratic curve from ``a`` to ``b`` bowed sideways by ``bulge`` m."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    ctrl = 0.5 * (a + b) + _side(b - a) * bulge
    t = np.linspace(0.0, 1.0, n + 1)[:, None]
    pts = (1 - t) ** 2 * a + 2 * (1 - t) * t * ctrl + t ** 2 * b
    return [(pts[i], pts[i + 1]) for i in range(n)], pts[-2]


def seg_circle(c, r, n=24, dashed=False):
    c = np.asarray(c, float)
    ang = np.linspace(0.0, 2.0 * np.pi, n + 1)
    pts = [c + r * np.array([np.cos(t), np.sin(t), 0.0]) for t in ang]
    segs = [(pts[i], pts[i + 1]) for i in range(n)]
    return segs[::2] if dashed else segs


def seg_diamond(c, r=0.12):
    c = np.asarray(c, float)
    q = [c + [r, 0, 0], c + [0, r, 0], c + [-r, 0, 0], c + [0, -r, 0]]
    return [(q[i], q[(i + 1) % 4]) for i in range(4)]


def seg_cross(c, r=0.18):
    c = np.asarray(c, float)
    return [(c + [-r, -r, 0], c + [r, r, 0]), (c + [-r, r, 0], c + [r, -r, 0])]


def intent_symbol(kind, here, goal, target_p, vip):
    """(solid segments, faint segments) for one drone's intent."""
    solid, faint = [], []
    here = np.asarray(here, float)
    if goal is None:
        return solid, faint
    goal = np.asarray(goal, float)
    far = float(np.linalg.norm(goal - here)) > 0.25
    if kind == 'block':
        if far:
            solid += seg_line(here, goal)
        face = _unit((target_p if target_p is not None else here) - goal)
        s = _side(face)
        solid += [(goal - s * 0.35, goal + s * 0.35)]                  # the screen
        solid += [(goal + s * k, goal + s * k + face * 0.12) for k in (-0.35, 0.0, 0.35)]
        if target_p is not None:
            faint += seg_dashed(goal, target_p, 0.06, 0.10)
    elif kind == 'pincer':
        bow = 0.3 * float(np.linalg.norm(goal - here))
        if target_p is not None:
            # bow the hook away from the attacker, so it reads as coming round
            if float(_side(goal - here) @ (target_p - goal)) > 0.0:
                bow = -bow
        curve, last = seg_curve(here, goal, bow)
        solid += curve + seg_head(last, goal)
        if target_p is not None:
            faint += seg_dashed(goal, target_p, 0.06, 0.10)
    elif kind == 'post':
        solid += seg_diamond(goal)
        if far:
            faint += seg_dashed(here, goal, 0.08, 0.10)
    elif kind in ('bail', 'feint'):
        if far:
            faint += seg_dashed(here, goal)
            solid += seg_head(here, goal)
    elif kind == 'stage':
        if far:
            faint += seg_dashed(here, goal)
        faint += seg_circle(goal, 0.30, 16)
    elif kind in ('strike', 'decoy', 'gang', 'evade'):
        if far:
            solid += seg_line(here, goal) + seg_head(here, goal, 0.28)
        if kind in ('strike', 'decoy'):
            faint += seg_dashed(goal, vip, 0.08, 0.12)
        elif kind == 'gang' and target_p is not None:
            faint += seg_dashed(goal, target_p, 0.06, 0.10)
    else:
        if far:
            faint += seg_dashed(here, goal)
    return solid, faint


def intent_colour(team, kind):
    if team == DEFENSE:
        return C_DEF
    return {'decoy': C_DECOY, 'feint': C_FEINT}.get(kind, C_ATT)


class GuardViz:
    def __init__(self, node, trail=40, bodies=True):
        """``bodies``: draw a body sphere for each drone. True for the
        offline player (nothing else draws them); guard_show passes False,
        because the real drones are already in the picture."""
        self.node = node
        self.ok = Marker is not None
        if self.ok:
            self.pub = node.create_publisher(MarkerArray, TOPIC, 10)
        self.trails = {}
        self.trail = trail
        self.bodies = bodies
        self._bursts = []          # [ticks_left, centre, colour]
        self._seen = set()         # (ns, id) published last time
        self._tick = 0

    def _m(self, ns, mid, mtype, stamp, life=1.0):
        m = Marker()
        m.header.frame_id = FRAME
        m.header.stamp = stamp
        m.ns, m.id, m.type, m.action = ns, mid, mtype, Marker.ADD
        m.pose.orientation.w = 1.0
        m.lifetime = Duration(sec=int(life), nanosec=int((life % 1.0) * 1e9))
        return m

    def _segs(self, ns, mid, segs, rgba, width, stamp):
        m = self._m(ns, mid, Marker.LINE_LIST, stamp)
        m.scale.x = width
        m.color = _c(rgba)
        m.points = [_pt(p) for s in segs for p in s]
        return m

    def publish(self, t, cfg, rules, vip, agents, labels, result=None, title='',
                meters=None, intents=None, plans=None, corrected=(), events=(),
                banner=''):
        if not self.ok:
            return
        try:
            self._publish(t, cfg, rules, vip, agents, labels, result, title,
                          meters or {}, intents or {}, plans or {}, set(corrected),
                          events or (), banner)
        except Exception as e:                        # noqa: BLE001
            self.node.get_logger().warn(f'guard viz: {e!r}', throttle_duration_sec=5.0)

    def clear(self):
        """Forget trails and bursts (a new match)."""
        self.trails = {}
        self._bursts = []

    def _publish(self, t, cfg, rules, vip, agents, labels, result, title, meters,
                 intents, plans, corrected, events, banner):
        stamp = self.node.get_clock().now().to_msg()
        self._tick += 1
        vip = np.asarray(vip, float)
        out = []
        won = getattr(result, 'winner', '') if result is not None else ''
        # -- the room: floor outline and ceiling outline
        poly = safety.ARENA_POLYGON
        if poly is not None:
            for k, z in enumerate((0.0, cfg.ceiling)):
                m = self._m('room', k, Marker.LINE_STRIP, stamp)
                m.scale.x = 0.03
                m.color = _c(C_ROOM if k == 0 else _a(C_ROOM, 0.35))
                m.points = [_pt((x, y, z)) for x, y in list(poly) + [poly[0]]]
                out.append(m)
        # -- the VIP: the objective, its strike circle, its keep-out
        vcol = C_VIP if not won else (C_SECURE if won == DEFENSE else C_LOST)
        m = self._m('vip', 0, Marker.SPHERE, stamp)
        m.pose.position = _pt(vip)
        m.scale.x = m.scale.y = m.scale.z = 0.30
        m.color = _c(vcol)
        out.append(m)
        out.append(self._segs('vip', 1, seg_circle(vip, rules.strike_radius, 48, True),
                              _a(C_ATT, 0.55), 0.025, stamp))
        out.append(self._segs('vip', 2, seg_circle(vip, cfg.d_vip, 32),
                              _a(C_VIP, 0.25), 0.012, stamp))
        if won:
            pulse = 0.45 + 0.35 * abs(np.sin(self._tick * 0.15))
            out.append(self._segs('vip', 3, seg_circle(vip, pulse, 32), vcol, 0.05, stamp))
            m = self._m('vip', 4, Marker.TEXT_VIEW_FACING, stamp)
            m.pose.position = _pt(vip + [0.0, 0.0, 1.0])
            m.scale.z = 0.45
            m.color = _c(vcol)
            m.text = banner or ('VIP SECURE' if won == DEFENSE else 'VIP COMPROMISED')
            out.append(m)

        # -- the attack's plan: lanes as axes of advance
        plan = plans.get(ATTACK, {}) or {}
        if plan.get('lanes') and not won:
            r_out = float(plan.get('r_stage', rules.strike_radius + 2.0))
            for j, (b, dz) in enumerate(plan['lanes']):
                u = np.array([np.cos(b), np.sin(b), 0.0])
                outer = vip + u * r_out + [0.0, 0.0, dz]
                inner = vip + u * rules.strike_radius + [0.0, 0.0, dz]
                if plan.get('phase') == 'commit':
                    segs = seg_line(outer, inner) + seg_head(outer, inner, 0.35)
                    out.append(self._segs('lanes', j, segs, _a(C_ATT, 0.35), 0.04, stamp))
                else:
                    out.append(self._segs('lanes', j, seg_dashed(outer, inner, 0.25, 0.20),
                                          _a(C_ATT, 0.25), 0.02, stamp))

        # -- every drone: halo, (body), trail, label, intent
        for k, (n, a) in enumerate(sorted(agents.items())):
            team_col = C_ATT if a.team == ATTACK else C_DEF
            col = team_col if a.active else C_OUT
            p = np.asarray(a.p, float)
            out.append(self._segs('halo', k, seg_circle(p, 0.17, 16), col, 0.03, stamp))
            if self.bodies:
                m = self._m('drone', k, Marker.SPHERE, stamp)
                m.pose.position = _pt(p)
                m.scale.x = m.scale.y = m.scale.z = 0.16
                m.color = _c(col)
                out.append(m)
            if not a.active:
                out.append(self._segs('out', k, seg_cross(p), C_OUT, 0.03, stamp))
            if a.active and n in corrected:
                m = self._m('keepout', k, Marker.SPHERE, stamp, life=0.3)
                m.pose.position = _pt(p)
                m.scale.x = m.scale.y = cfg.d_cc
                m.scale.z = cfg.d_cc * cfg.cc_z_ratio
                m.color = _c(_a(col, 0.10))
                out.append(m)
            tr = self.trails.setdefault(n, deque(maxlen=self.trail))
            tr.append(p.copy())
            if len(tr) > 1:
                m = self._m('trail', k, Marker.LINE_STRIP, stamp)
                m.scale.x = 0.015
                m.color = _c(_a(col, 0.30))
                m.points = [_pt(q) for q in tr]
                out.append(m)
            m = self._m('label', k, Marker.TEXT_VIEW_FACING, stamp)
            m.pose.position = _pt(p + [0.0, 0.0, 0.32])
            m.scale.z = 0.22
            m.color = _c(col if a.active else C_OUT)
            it = intents.get(n) if a.active else None
            if a.status == RETIRING or not a.active:
                what = a.outcome.upper()
            else:
                what = (it.kind if it is not None else labels.get(n, '')).upper()
            mt = meters.get(n, {}) if a.active else {}
            gauge = ''.join(f' {q[0]}{int(100 * v)}%' for q, v in sorted(mt.items())
                            if v > 0.005)
            m.text = f'{n} {what}{gauge}'.strip()
            out.append(m)
            if it is not None and not won:
                tgt = agents.get(it.target)
                tp = np.asarray(tgt.p, float) if tgt is not None and tgt.active else None
                solid, faint = intent_symbol(it.kind, p, it.goal, tp, vip)
                icol = intent_colour(a.team, it.kind)
                if solid:
                    w = 0.045 if it.kind in ('strike', 'decoy') else 0.03
                    out.append(self._segs('intent', k, solid, icol, w, stamp))
                if faint:
                    out.append(self._segs('intent_aux', k, faint, _a(icol, 0.55),
                                          0.018, stamp))

        # -- events: a ring bursts where a drone is downed, at the VIP on a strike
        for e in events:
            who = agents.get(getattr(e, 'who', ''))
            if e.kind == 'strike':
                self._bursts.append([20, vip.copy(), C_LOST])
            elif who is not None:
                col = C_ATT if who.team == ATTACK else C_DEF
                self._bursts.append([20, np.asarray(who.p, float).copy(), col])
        live = []
        for j, b in enumerate(self._bursts):
            left, c, col = b
            r = 0.2 + (20 - left) * 0.06
            out.append(self._segs('burst', j, seg_circle(c, r, 24),
                                  _a(col, 0.9 * left / 20), 0.05, stamp))
            b[0] -= 1
            if b[0] > 0:
                live.append(b)
        self._bursts = live

        # -- the scoreboard, above the room
        m = self._m('score', 0, Marker.TEXT_VIEW_FACING, stamp)
        m.pose.position = _pt([cfg.room_center[0], cfg.room_center[1], cfg.ceiling + 2.0])
        m.scale.z = 0.45
        m.color = _c(C_TEXT if not won else vcol)
        line = f'{title} | t {t:.1f}s'
        if plan.get('phase') and not won:
            ph = {'stage': 'STAGING', 'commit': 'COMMITTED'}.get(plan['phase'],
                                                                 plan['phase'].upper())
            if plan.get('decoy'):
                ph += f' behind decoy {plan["decoy"]}'
            line += f' | attack {ph}'
        if result is not None:
            line += f' | strikes {result.strikes} downs {result.downs}'
            if result.winner:
                line += f' | {result.winner.upper()} WINS: {result.reason}'
        m.text = line
        out.append(m)

        # whatever was drawn last time and not this time goes now, not when
        # its lifetime runs out (an intent that changed must not linger)
        now = {(x.ns, x.id) for x in out}
        for ns, mid in self._seen - now:
            d = self._m(ns, mid, Marker.LINE_LIST, stamp)
            d.action = Marker.DELETE
            out.append(d)
        self._seen = now
        self.pub.publish(MarkerArray(markers=out))
