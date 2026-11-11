"""The serpent show: a one-minute, fast, three-dimensional chase for five drones.

Built for the big arena (arena.yaml ``polygon:``), and sized from it at plan
time, so it shrinks itself to fit a smaller room instead of hard-coding one.

    ros2 run crazyflie_shows plan_serpent        # verify offline, no ROS
    ros2 run crazyflie_shows serpent_show        # fly it (same checks first)

The script (about 60 s on the wall clock):

1. **takeoff / settle** over each drone's own mark.
2. **queue up**: the drones fly into a line along the serpent's loop, nose to
   tail, ~1.4 m apart.
3. **serpent**: one lap of a big closed loop at up to ~1.9 m/s. Every drone
   follows the SAME 3D path, a fixed arc behind the one in front, so the
   formation reads as one snake chasing its head round the room. The loop
   rolls over two hills (1.3 -> 3.1 m) per lap, so the snake also climbs and
   dives as it goes.
4. **scythe**: the line pivots into a tilted spoke from the centre outwards,
   rising from 1.2 m at the hub to 3.6 m at the tip, and sweeps one full turn
   round the room like a radar arm.
5. **home / land** on the marks.

Why it is safe to fly fast, in the same terms as the other shows:

* **Plan-view separation is the enforced invariant** (``>= PLAN_SEPARATION``
  at every sample), so no drone ever passes over another and downwash never
  stacks. In the serpent the spacing is an arc of a convex-ish loop, in the
  scythe a radial gap; both are constant through the figure.
* **The figures stay ``margin`` (0.6 m) clear of the arena polygon**, on top
  of the tracking margin check_show already applies, because a fast drone
  overshoots a corner by more than a slow one.
* **The composition rule** (figures return every drone to its own start) holds
  because both figures are exactly one turn.
* Speeds and accelerations are checked on the FITTED trajectories that will
  be uploaded, not on the ideal paths, against safety.MAX_SPEED / MAX_ACCEL.
"""

from dataclasses import dataclass, field
from math import cos, pi, sin

import numpy as np

from crazyflie_shows import choreography, constellation, figures, safety
from crazyflie_shows.choreography import Figure, Phase, Plan

LIGHT = constellation.LIGHT
wrgb = constellation.wrgb


@dataclass
class SerpentConfig(choreography.ShowConfig):
    """Tunables. Rig fields (takeoff, landing, floor...) come from ShowConfig."""

    #: The beat grid every phase boundary sits on (as in the constellation).
    bpm: float = 120.0
    phase_margin: float = 0.25

    #: Clearance every FIGURE keeps from the arena polygon (or the circle),
    #: on top of safety.TRACKING_MARGIN. Speed costs overshoot at the edges.
    margin: float = 0.60

    #: Serpent loop: plan-view radius is sized to the room; this squares it
    #: off towards the corners, r(th) = R (1 - squareness cos 4 th).
    squareness: float = 0.07
    #: Arc spacing between consecutive drones along the loop, metres.
    spacing: float = 1.40
    #: Heights: centre and amplitude of the hills, and hills per lap.
    serpent_z: float = 2.20
    serpent_amp: float = 0.90
    serpent_hills: int = 2
    dur_serpent: float = 21.0

    #: Scythe: hub radius, radial gap between drones, hub and per-drone rise.
    scythe_hub: float = 0.25
    scythe_gap: float = 0.95
    scythe_z0: float = 1.20
    scythe_rise: float = 0.60
    dur_scythe: float = 18.0

    #: Figures ease in and out over this fraction of their length.
    ramp: float = 0.25

    #: Faster transits than the constellation (0.45): peak is ~1.9x this.
    trans_avg_speed: float = 0.95
    trans_min_duration: float = 2.0
    takeoff_height: float = 1.00
    home_height: float = 1.00
    settle_duration: float = 1.0

    pieces: dict = field(default_factory=lambda: {'serpent': 14, 'scythe': 10})


# =========================================================================
# Geometry
# =========================================================================

def show_centre(margin):
    """Where the room has the most space: the point furthest from the arena's
    edge (the polygon's inscribed-circle centre), and that clearance.

    Without a polygon this is ARENA_CENTRE and ARENA_RADIUS_TESTED.
    """
    if safety.ARENA_POLYGON is None:
        return np.asarray(safety.ARENA_CENTRE, float), safety.ARENA_RADIUS_TESTED
    P = safety.ARENA_POLYGON
    lo, hi = P.min(axis=0), P.max(axis=0)
    best = None
    for step in (0.25, 0.05):
        if best is None:
            xs, ys = np.arange(lo[0], hi[0], step), np.arange(lo[1], hi[1], step)
        else:
            c = best[1]
            xs = np.arange(c[0] - 0.3, c[0] + 0.3, step)
            ys = np.arange(c[1] - 0.3, c[1] + 0.3, step)
        g = np.array([(x, y) for x in xs for y in ys])
        clr = safety.edge_clearance(g)
        i = int(np.argmax(clr))
        best = (float(clr[i]), g[i])
    return best[1], best[0]


def loop_xy(c, R, sq, th):
    """Plan-view point of the serpent loop at angle ``th`` (rad)."""
    r = R * (1.0 - sq * np.cos(4.0 * th))
    return c[0] + r * np.cos(th), c[1] + r * np.sin(th)


def loop_z(cfg, th):
    return cfg.serpent_z + cfg.serpent_amp * np.sin(cfg.serpent_hills * th)


def fit_loop_radius(c, clearance, cfg):
    """Largest loop radius whose whole curve keeps ``cfg.margin`` +
    TRACKING_MARGIN from the arena edge."""
    need = cfg.margin + safety.TRACKING_MARGIN
    th = np.linspace(0, 2 * pi, 720, endpoint=False)
    R = clearance
    while R > 1.0:
        x, y = loop_xy(c, R, cfg.squareness, th)
        if float(safety.edge_clearance(np.c_[x, y]).min()) >= need:
            return R
        R -= 0.02
    raise ValueError('the arena is too small for the serpent loop')


def serpent_path(c, R, cfg, th0, duration):
    """One drone's lap: starts at loop angle ``th0`` and goes once round."""
    def fn(t):
        th = th0 + 2 * pi * figures.ease_ramped(t, duration, cfg.ramp)
        x, y = loop_xy(c, R, cfg.squareness, th)
        return (float(x), float(y), float(loop_z(cfg, th)), 0.0)
    return fn


def scythe_slot(c, k, heading, cfg):
    r = cfg.scythe_hub + k * cfg.scythe_gap
    return np.array([c[0] + r * cos(heading), c[1] + r * sin(heading),
                     cfg.scythe_z0 + k * cfg.scythe_rise])


def scythe_path(c, k, heading0, cfg, duration):
    r = cfg.scythe_hub + k * cfg.scythe_gap
    z = cfg.scythe_z0 + k * cfg.scythe_rise
    return figures.polar_path(
        c, lambda t: r,
        lambda t: heading0 + 2 * pi * figures.ease_ramped(t, duration, cfg.ramp),
        lambda t: z)


# =========================================================================
# The plan
# =========================================================================

def build_plan(names, initial_positions, cfg=None):
    """Build and verify the serpent show. Pure; raises ValueError if unsafe."""
    cfg = cfg or SerpentConfig()
    starts = [np.asarray(p, float) for p in initial_positions]
    n = len(starts)
    if n != 5:
        raise ValueError(f'the serpent is choreographed for 5 drones, got {n}')

    # the marks must be inside the arena (the chalk lines are not geometry)
    clr = safety.edge_clearance(np.array([s[:2] for s in starts]))
    bad = [(nm, c) for nm, c in zip(names, clr) if c < safety.TRACKING_MARGIN]
    if bad:
        raise ValueError(
            'these drones are parked outside the tracked volume: '
            + ', '.join(f'{nm} {c:+.2f} m from its edge' for nm, c in bad)
            + ' -- move the drone, then re-sync initial_position')

    c, room = show_centre(cfg.margin)
    R = fit_loop_radius(c, room, cfg)
    tip = cfg.scythe_hub + (n - 1) * cfg.scythe_gap
    if tip > room - cfg.margin - safety.TRACKING_MARGIN:
        raise ValueError(
            f'scythe tip {tip:.2f} m does not fit: {room:.2f} m of room at the '
            f'centre less the {cfg.margin:.2f} m margin')
    dth = cfg.spacing / R                        # arc gap -> angle gap

    phases, pos = [], [p.copy() for p in starts]

    def add(name, kind, duration, ends, lights=None, **kw):
        if kind != 'figure':
            duration = constellation._on_beat(cfg, duration)
        slot = constellation._slot(cfg, duration)
        phases.append(Phase(name, kind, duration, [p.copy() for p in pos],
                            [np.asarray(e, float) for e in ends],
                            lights=lights, slot=slot, **kw))
        for j in range(n):
            pos[j] = np.asarray(ends[j], float)

    def leg_time(src, dst):
        longest = max(float(np.linalg.norm(np.asarray(d) - np.asarray(s)))
                      for s, d in zip(src, dst))
        return max(cfg.trans_min_duration, longest / cfg.trans_avg_speed)

    home = [np.array([s[0], s[1], cfg.home_height]) for s in starts]

    # ------------------------------------------------ takeoff
    hover = [np.array([s[0], s[1], cfg.takeoff_height]) for s in starts]
    add('takeoff', 'takeoff', cfg.takeoff_duration, hover, goals=hover,
        lights=LIGHT['deep_blue'],
        note=f'all drones to {cfg.takeoff_height:.2f} m over their own start')
    add('settle', 'goto', cfg.settle_duration, hover, goals=hover,
        note='hold while the Kalman filter settles')

    # ------------------------------------------------ queue up on the loop
    # Where the snake's head starts is free: pick the one whose queue is
    # quickest (and safe) to reach from the marks.
    def queue(th_head):
        return [np.array([*loop_xy(c, R, cfg.squareness, th_head - k * dth),
                          loop_z(cfg, th_head - k * dth)]) for k in range(n)]

    best = None
    for th_head in np.radians(np.arange(0.0, 360.0, 7.5)):
        res = safety.assign_makespan(hover, queue(th_head), safety.PLAN_SEPARATION,
                                     safety.PLAN_SEPARATION,
                                     prefer_sep_xy=constellation.COMFORT_SEP)
        if res is None:
            continue
        key = (0 if res['sep_xy'] >= constellation.COMFORT_SEP else 1,
               round(res['longest'], 2))
        if best is None or key < best[0]:
            best = (key, th_head, res)
    if best is None:
        raise ValueError('queue up: no head position and assignment keeps every '
                         f'pair >= {safety.PLAN_SEPARATION:.2f} m in plan view')
    _, th_head, res = best
    q = res['targets']
    # rank[j]: drone j's place in the line (0 = head)
    slots = queue(th_head)
    rank = [int(np.argmin([np.linalg.norm(q[j] - s) for s in slots])) for j in range(n)]
    snake_lights = [wrgb(w=0x7F) if rank[j] == 0 else
                    wrgb(r=0x20 + 0x30 * rank[j], b=0xE0 - 0x20 * rank[j])
                    for j in range(n)]
    add('queue up', 'goto', leg_time(pos, q), q, goals=q, lights=LIGHT['indigo'],
        note=f'nose to tail on the loop, {cfg.spacing:.1f} m apart; '
             f'plan-view sep {res["sep_xy"]:.2f} m')

    fig_specs = []

    def figure_phase(name, paths, dur, note, lights):
        fig_specs.append((name, paths, dur))
        add(name, 'figure', dur, [p.copy() for p in pos], figure=name,
            note=note, lights=lights)

    dur_s = constellation._on_beat(cfg, cfg.dur_serpent)
    figure_phase('serpent',
                 [serpent_path(c, R, cfg, th_head - rank[j] * dth, dur_s)
                  for j in range(n)],
                 dur_s, 'one lap of the room, nose to tail, over two hills',
                 snake_lights)

    # ------------------------------------------------ morph into the scythe
    # Choose the spoke's heading (and who goes where) so that this morph AND
    # the flight home afterwards are both safe in plan view.
    def home_clears(limit):
        return lambda targets: (
            safety.pairs_transit_min(targets, home, 3) >= limit
            and safety.pairs_transit_min(targets, home, 2) >= limit)

    # comfortable on the way home too if any heading allows it, else the budget
    best = None
    for limit in (constellation.COMFORT_SEP, safety.PLAN_SEPARATION):
        for h in np.radians(np.arange(0.0, 360.0, 5.0)):
            spoke = [scythe_slot(c, k, h, cfg) for k in range(n)]
            r2 = safety.assign_makespan(pos, spoke, safety.PLAN_SEPARATION,
                                        safety.PLAN_SEPARATION, home_clears(limit),
                                        prefer_sep_xy=constellation.COMFORT_SEP)
            if r2 is None:
                continue
            key = (0 if r2['sep_xy'] >= constellation.COMFORT_SEP else 1,
                   round(r2['longest'], 2))
            if best is None or key < best[0]:
                best = (key, h, r2)
        if best is not None:
            break
    if best is None:
        raise ValueError('morph to the scythe: no heading keeps the morph and the '
                         'flight home clear in plan view')
    _, h0, r2 = best
    spoke = r2['targets']
    k_of = [int(np.argmin([np.linalg.norm(spoke[j] - scythe_slot(c, k, h0, cfg))
                           for k in range(n)])) for j in range(n)]
    add('form the scythe', 'goto', leg_time(pos, spoke), spoke, goals=spoke,
        lights=LIGHT['amber'],
        note=f'a tilted spoke, hub {cfg.scythe_z0:.1f} m -> tip '
             f'{cfg.scythe_z0 + (n - 1) * cfg.scythe_rise:.1f} m; '
             f'plan-view sep {r2["sep_xy"]:.2f} m')
    dur_c = constellation._on_beat(cfg, cfg.dur_scythe)
    figure_phase('scythe',
                 [scythe_path(c, k_of[j], h0, cfg, dur_c) for j in range(n)],
                 dur_c, 'the spoke sweeps one full turn round the room',
                 [LIGHT['cyan'] if k_of[j] % 2 else LIGHT['white'] for j in range(n)])

    # ------------------------------------------------ home and land
    add('return home', 'goto', leg_time(pos, home), home, goals=home,
        lights=LIGHT['deep_blue'], note="back over each drone's own start mark")
    ground = [np.array([s[0], s[1], cfg.land_height]) for s in starts]
    add('land', 'land', cfg.land_duration, ground, goals=ground,
        lights=LIGHT['red'], note='red: the rig convention for "a script has the drones"')

    # ------------------------------------------------ fit the figures
    offsets, total_pieces = figures.pack_offsets(
        [cfg.pieces[name] for name, _, _ in fig_specs])
    figs = {}
    for (name, paths, dur), off, tid in zip(fig_specs, offsets,
                                            range(1, len(fig_specs) + 1)):
        trajs = [figures.fit_trajectory(p, dur, n_pieces=cfg.pieces[name])
                 for p in paths]
        figs[name] = Figure(name, tid, off, trajs, paths, dur)
    for ph in phases:
        if ph.kind == 'figure':
            ph.figure = figs[ph.figure]

    plan = Plan(list(names), starts, np.asarray(c, float),
                [float(np.degrees(th_head - rank[j] * dth)) % 360 for j in range(n)],
                list(figs.values()), phases, res['sep_xy'])

    # ------------------------------------------------ verify
    bounds, t = [], 0.0
    for ph in phases:
        bounds.append((ph.name, t, t + ph.duration))
        t += ph.duration
    plan.report = safety.check_show(
        plan.sample, plan.duration, n,
        radius=cfg.arena_radius, ceiling=cfg.ceiling, center=c,
        floor=cfg.floor, floor_window=(bounds[0][2], bounds[-1][1]),
        phase_bounds=bounds)

    samples, times = plan.report['samples'], plan.report['times']
    sep_xy, k, a, b = safety.sample_min_sep(samples[:, :, :2])
    if sep_xy < safety.PLAN_SEPARATION:
        raise ValueError(
            f'show check failed:\n  - plan-view separation {sep_xy:.2f} m < '
            f'{safety.PLAN_SEPARATION:.2f} m - drones {a} and {b} at '
            f'{times[k]:.1f}s: a drone would pass over another')
    # the figures' own edge margin, on the FITTED trajectories
    fig_clear = []
    for name, t0, t1 in bounds:
        if name in figs:
            m = (times >= t0) & (times <= t1)
            fig_clear.append(float(safety.edge_clearance(samples[:, m, :2]).min()))
    need = cfg.margin + safety.TRACKING_MARGIN - 0.05   # 5 cm of fit slack
    if min(fig_clear) < need:
        raise ValueError(
            f'show check failed:\n  - a figure comes {min(fig_clear):.2f} m from '
            f'the arena edge; the serpent keeps {need:.2f} m')
    fit_err = max(figures.fit_error(tr, p) for f in figs.values()
                  for tr, p in zip(f.trajs, f.paths))
    dw, dk, da, db = safety.downwash_clearance(samples)

    plan.report.update(
        pieces=total_pieces, config=cfg,
        min_sep_xy=sep_xy, min_sep_xy_pair=(a, b), min_sep_xy_time=float(times[k]),
        downwash=dw, downwash_pair=(da, db), downwash_time=float(times[dk]),
        wall=sum(ph.slot for ph in phases), beat=60.0 / cfg.bpm,
        loop_radius=R, room=room, scythe_tip=tip, figure_edge_clearance=min(fig_clear),
        fit_error=fit_err, heading=float(np.degrees(h0)))
    return plan


def report_extras(plan, cfg, names):
    """The serpent's own numbers, after plan_show's core report."""
    r = plan.report
    out = print
    a, b = r['min_sep_xy_pair']
    da, db = r['downwash_pair']
    out('\n  SERPENT')
    out(f'    room           {r["room"]:.2f} m clear around the show centre '
        f'({plan.center[0]:+.2f}, {plan.center[1]:+.2f})')
    out(f'    loop           radius {r["loop_radius"]:.2f} m, drones '
        f'{cfg.spacing:.1f} m apart, hills {cfg.serpent_z - cfg.serpent_amp:.1f} -> '
        f'{cfg.serpent_z + cfg.serpent_amp:.1f} m')
    out(f'    scythe         tip {r["scythe_tip"]:.2f} m out, '
        f'{cfg.scythe_z0:.1f} -> {cfg.scythe_z0 + 4 * cfg.scythe_rise:.1f} m up')
    out(f'    figure margin  {r["figure_edge_clearance"]:.2f} m from the arena '
        f'edge at the closest (keeps {cfg.margin + safety.TRACKING_MARGIN:.2f})')
    out(f'    plan-view sep  {r["min_sep_xy"]:5.2f} m  min {safety.PLAN_SEPARATION:.2f} m '
        f'({names[a]}/{names[b]} at t={r["min_sep_xy_time"]:.1f}s)  enforced')
    out(f'    downwash       {r["downwash"]:.2f} x  ({names[da]}/{names[db]} at '
        f't={r["downwash_time"]:.1f}s)')
    out(f'    fit error      {r["fit_error"] * 1000:.1f} mm worst, uploaded vs ideal path')
    out(f'    wall clock     {r["wall"]:.1f} s')
