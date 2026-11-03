"""Guard: N defenders against M attackers, with pluggable strategies.

The successor experiment to the escort (which stays, unchanged, as the
flown-for-guests demo). Four layers, each replaceable without the others:

``policies``      what each team WANTS to do: a velocity per drone. Any
                  number of strategies, registered by name and chosen per run
                  (``defense:=shell attack:=coordinated``); a strategy can
                  live in any importable module (``policy_module:=...``).
``safety_layer``  what the drones are ALLOWED to do: AirStack's CBF solver
                  (``crazyflie_shows.cbf``, ported verbatim) over every pair
                  of aircraft, the DJI included, plus the room and the
                  altitude band. It has the last word on every command.
``rules``         who won: strikes on the VIP, tags that down an attacker,
                  the clock.
``engine``        one tick of all three, pure Python. ``plan_guard`` runs it
                  offline over many seeds; ``guard_show`` runs it on drones.

Nothing here imports ROS. Design notes: docs/details/guard-design-notes.md.
"""
