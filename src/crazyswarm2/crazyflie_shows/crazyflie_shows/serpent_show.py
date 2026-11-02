#!/usr/bin/env python3
"""Fly the serpent show: a fast, three-dimensional one-minute chase for cf1-cf5.

All geometry, timing and verification live in :mod:`serpent` (pure, checked
offline by ``plan_serpent``). Flying goes through the constellation show's
loop unchanged (:func:`constellation_show.run`): mocap and placement checks,
the supervisor go/no-go, the upload, beat-locked phases, light cues and the
staged abort.

    ros2 launch crazyflie launch.py backend:=sim
    ros2 run crazyflie_shows serpent_show --ros-args -p use_sim_time:=true

    # hardware: stack up, scan every address, preflight GUI, plan_serpent, THEN
    ros2 run crazyflie_shows serpent_show --ros-args -p dry_run:=true   # rehearsal
    ros2 run crazyflie_shows serpent_show

Parameters are the constellation show's (dry_run, lights, check_placement,
placement_tol, bpm, scale, arena_radius, ceiling, use_sim_time).
"""

import sys

from crazyflie_shows import constellation_show, serpent


def main():
    return constellation_show.run('serpent_show', serpent.SerpentConfig,
                                  serpent.build_plan, serpent.report_extras)


if __name__ == '__main__':
    sys.exit(main())
