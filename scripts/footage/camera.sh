#!/bin/bash
# The docs camera: reload the mission window (its default view, cache bypassed), then orbit
# behind the attackers (-x,+y), raise it, pull back one step and pan so the airborne play
# (1-2 m up) sits in the middle of the frame. The scene has no camera API, so this drives
# its orbit control with mouse drags over Chrome's DevTools port.
D=$(dirname "$0")
python3 -I "$D/cdp_drag.py" 195 0 0 reload \
  && python3 -I "$D/cdp_drag.py" 0 30 200 \
  && BTN=right python3 -I "$D/cdp_drag.py" 0 -30
