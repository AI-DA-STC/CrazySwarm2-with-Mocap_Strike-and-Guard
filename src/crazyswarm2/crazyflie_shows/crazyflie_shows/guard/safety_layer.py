"""The safety layer: every command passes through here, and it has the last word.

One least-squares projection per tick, solved by AirStack's Dykstra solver
(``crazyflie_shows.cbf.solve_safe_commands``, ported verbatim). What is ours
is the constraint set handed to it, built in the solver's own
``PairwiseConstraints`` shape -- the extension point its docstring names:

* **Aircraft pairs** -- a first-order (velocity) CBF on an ELLIPSOIDAL keep-out,
  wider vertically than across, because a drone in another's downwash loses
  thrust:  h = (dx^2 + dy^2)/a^2 + dz^2/c^2 - 1 >= 0, and requiring
  h_dot + alpha h >= 0 gives  2 W^2 (p_i - p_j) . (v_i - v_j) + alpha h >= 0
  with W^2 = diag(1/a^2, 1/a^2, 1/c^2): linear in the velocities, exactly the
  form AirStack's builder produces for a sphere (W = I/r). Each pair gets
  its own (a, c): Crazyflie-Crazyflie, or Crazyflie-VIP.
* **The VIP** (a hand-flown DJI, a person, or a fixed point) is a FIXED row at
  its measured velocity: the solver never corrects it, so the Crazyflies
  absorb the whole evasion -- AirStack's treatment of an RC-flown intruder.
* **Retiring drones** (tagged or struck, being landed) are fixed rows too,
  descending at the land speed.
* **Walls, floor and ceiling** are constraints against PHANTOM fixed rows at
  zero velocity:  n . v_i + alpha_wall * clearance >= 0, with n the inward
  normal. The solver only knows pairs; a pair with a motionless phantom is a
  single-drone half-space, so the room joins the same projection instead of
  being clamped afterwards (a clamp after the CBF could undo it).

The CBF holds the SETPOINTS apart, not the aircraft: it runs on the commanded
reference the drones follow, which exists identically in the simulator and
on hardware. The aircraft trail it by up to TRACKING_MARGIN, which is why
``d_cc`` is the hard floor (``min_separation``) plus that margin; the
near-miss watchdog checks the aircraft themselves (``floor_ratio``).
"""

from dataclasses import dataclass

import numpy as np

from crazyflie_shows import escort, safety
from crazyflie_shows.cbf import PairwiseConstraints, solve_safe_commands


@dataclass
class SafetyResult:
    velocities: np.ndarray         # (n_movable, 3) safe commands
    corrected: np.ndarray          # (n_movable,) bool
    converged: bool
    emergency: bool
    residual: float
    n_pairs: int                   # aircraft pairs in play this tick
    n_walls: int                   # wall/floor/ceiling constraints this tick


def _pair_rows(P, axes, n_rows):
    """Ellipsoidal pair constraints over rows 0..n_rows-1 of P."""
    idx_i, idx_j = np.triu_indices(n_rows, k=1)
    d = P[idx_i] - P[idx_j]
    a = np.maximum(axes[idx_i, 0], axes[idx_j, 0])
    c = np.maximum(axes[idx_i, 1], axes[idx_j, 1])
    w2 = np.stack([1.0 / a ** 2, 1.0 / a ** 2, 1.0 / c ** 2], axis=1)
    h = np.einsum('md,md->m', d * w2, d) - 1.0
    return idx_i, idx_j, 2.0 * w2 * d, h


def filter_commands(cfg, P_move, V_nom, P_fixed=(), V_fixed=(), fixed_axes=(),
                    move_axes=None):
    """Safe velocities for the movable drones.

    ``P_move`` (n, 3), ``V_nom`` (n, 3): the commanded reference and the
    strategies' requests. ``P_fixed``/``V_fixed`` (k, 3): obstacles that will
    do what they do (the VIP, retiring drones), with ``fixed_axes`` (k, 2)
    their keep-out half-axes (across, vertical). ``move_axes`` defaults to the
    Crazyflie keep-out for every movable row.
    """
    P_move = np.asarray(P_move, float).reshape(-1, 3)
    V_nom = np.asarray(V_nom, float).reshape(-1, 3)
    n = len(P_move)
    P_fixed = np.asarray(P_fixed, float).reshape(-1, 3)
    V_fixed = np.asarray(V_fixed, float).reshape(-1, 3)
    k = len(P_fixed)
    cc = np.array([cfg.d_cc, cfg.d_cc * cfg.cc_z_ratio])
    axes = np.vstack([np.tile(cc, (n, 1)) if move_axes is None
                      else np.asarray(move_axes, float).reshape(-1, 2),
                      np.asarray(fixed_axes, float).reshape(-1, 2)])
    # The keep-out between two bodies is the LARGER of their two shapes, so
    # a Crazyflie-VIP pair uses the VIP's.
    P = np.vstack([P_move, P_fixed])
    idx_i, idx_j, grad, h = _pair_rows(P, axes, n + k)
    # Pairs of two fixed bodies can't be influenced; leave them out.
    keep = (idx_i < n) | (idx_j < n)
    idx_i, idx_j, grad, h = idx_i[keep], idx_j[keep], grad[keep], h[keep]
    bias = cfg.alpha * h

    # ---- walls / floor / ceiling: one phantom fixed row per constraint ----
    # Each held wall_margin INSIDE the clamp: the first-order CBF is exact in
    # continuous time, but integrated at 20 Hz, and at a polygon corner the
    # inward normal turns between ticks, so a setpoint can creep a couple of
    # cm past h = 0. The margin absorbs that and leaves backstop() to fire
    # only for a solver that failed (it counts every time it does).
    reach = cfg.v_max_safety / max(cfg.alpha_wall, 1e-6) + 0.5
    wm = cfg.wall_margin
    w_i, w_g, w_b, w_h = [], [], [], []
    for i in range(n):
        for g, c in _room_rows(cfg, P_move[i], wm, reach):
            w_i.append(i)
            w_g.append(g)
            w_b.append(cfg.alpha_wall * c)
            w_h.append(c)
        lo = P_move[i, 2] - cfg.floor - wm
        hi = cfg.ceiling - P_move[i, 2] - wm
        if lo < reach:
            w_i.append(i), w_g.append([0.0, 0.0, 1.0])
            w_b.append(cfg.alpha_wall * lo), w_h.append(lo)
        if hi < reach:
            w_i.append(i), w_g.append([0.0, 0.0, -1.0])
            w_b.append(cfg.alpha_wall * hi), w_h.append(hi)
    m = len(w_i)
    phantom = n + k + np.arange(m)

    commands = np.vstack([V_nom, V_fixed, np.zeros((m, 3))])
    fixed = np.zeros(n + k + m, bool)
    fixed[n:] = True
    cons = PairwiseConstraints(
        idx_i=np.concatenate([idx_i, np.asarray(w_i, int)]),
        idx_j=np.concatenate([idx_j, phantom]),
        gradient=np.vstack([grad, np.asarray(w_g, float).reshape(-1, 3)]),
        bias=np.concatenate([bias, np.asarray(w_b, float)]),
        barrier=np.concatenate([h, np.asarray(w_h, float)]),
    )
    res = solve_safe_commands(commands, cons, norm_cap=cfg.v_max_safety,
                              fixed=fixed)
    v = res.velocities[:n]
    return SafetyResult(velocities=v, corrected=res.corrected[:n],
                        converged=res.converged,
                        emergency=res.used_emergency_stop,
                        residual=res.residual,
                        n_pairs=int(np.count_nonzero(idx_j < n + k)),
                        n_walls=m)


def _room_rows(cfg, p, wm, reach):
    """(gradient, h) for every room boundary near ``p``.

    ONE row per polygon EDGE within reach, each the distance to that edge's
    segment. A single row for the nearest edge (the first version) let a
    drone sliding along one wall run straight through the next at a convex
    corner -- the nearest edge was the one it was sliding along, so nothing
    constrained the other direction (test_walls_hold_a_drone_inside_the_room).
    Segment distance, not the edge's infinite line, so that at the step's
    REFLEX corner the constraint is the distance to the corner point and the
    room is not trimmed.
    """
    rows = []
    poly = safety.ARENA_POLYGON
    xy = np.asarray(p, float)[:2]
    off = safety.TRACKING_MARGIN + wm
    inside = poly is not None and float(safety.edge_clearance(xy)) > 0.0
    if inside:
        a = poly
        b = np.roll(poly, -1, axis=0)
        ab = b - a
        t = np.clip(((xy - a) * ab).sum(1) / (ab * ab).sum(1), 0.0, 1.0)
        c = a + t[:, None] * ab
        d = np.linalg.norm(xy - c, axis=1)
        for k in np.flatnonzero(d - off < reach):
            g = (xy - c[k]) / max(d[k], 1e-9)       # away from the edge: inward
            rows.append(([g[0], g[1], 0.0], float(d[k] - off)))
    else:
        # the circle room, or a point already outside the polygon: the signed
        # clearance and its inward normal (escort's helpers)
        h = float(escort.room_clearance(cfg, p)) - wm
        if h < reach:
            nrm = escort.room_inward(cfg, p)
            rows.append(([nrm[0], nrm[1], 0.0], h))
    # an explicitly tighter circle (cfg.arena_radius) applies on top
    if inside and cfg.arena_radius < safety.ARENA_RADIUS_PLAN - 1e-9:
        r = xy - np.asarray(cfg.room_center, float)
        rn = float(np.linalg.norm(r))
        h = cfg.arena_radius - rn - wm
        if h < reach:
            u = -r / max(rn, 1e-9)
            rows.append(([u[0], u[1], 0.0], h))
    return rows


def keep_out(cfg, kind):
    """(across, vertical) half-axes of a body's keep-out: 'cf' or 'vip'."""
    if kind == 'vip':
        return np.array([cfg.d_vip, cfg.d_vip * cfg.vip_z_ratio])
    return np.array([cfg.d_cc, cfg.d_cc * cfg.cc_z_ratio])


def floor_ratio(cfg, p, q):
    """How far outside the HARD floor ellipsoid two aircraft are: 1 = on it."""
    d = np.asarray(p, float) - np.asarray(q, float)
    return float(np.sqrt((d[0] ** 2 + d[1] ** 2) / cfg.min_separation ** 2
                         + d[2] ** 2 / cfg.min_separation_z ** 2))


def separation_ratio(cfg, p, q, kind='cf'):
    """How far outside the keep-out ``q`` is from ``p``: 1 = on its surface."""
    a, c = keep_out(cfg, kind)
    d = np.asarray(p, float) - np.asarray(q, float)
    return float(np.sqrt((d[0] ** 2 + d[1] ** 2) / a ** 2 + d[2] ** 2 / c ** 2))


def backstop(cfg, sp):
    """Last line after integration: the room and the band, as a clamp.

    The CBF should already have kept the setpoint inside; this exists for a
    solver that did not converge. Returns (setpoint, clamped?).
    """
    sp = np.asarray(sp, float).copy()
    xy, hit = escort.clamp_to_room(cfg, sp[:2])
    sp[:2] = xy
    z = float(np.clip(sp[2], cfg.floor, cfg.ceiling))
    hit = hit or z != sp[2]
    sp[2] = z
    return sp, hit
