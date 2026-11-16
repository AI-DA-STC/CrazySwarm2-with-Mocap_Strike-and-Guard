#!/usr/bin/env python3
"""Move the console's 3D camera with a scripted mouse drag over Chrome's DevTools port.

    cdp_drag.py dx dy [wheel] [reload]

dx, dy: the drag in CSS px (the left button orbits; BTN=right pans). wheel: +N px
zooms out, -N in (100 px a notch). reload: reload the page first, bypassing the
cache, which also resets the view. The port is $CDP_PORT (9333). Needs the
`websockets` module (python3-websockets).
"""

import asyncio
import json
import os
import sys
import urllib.request

import websockets

BTN = os.environ.get('BTN', 'left')
BTNS = 2 if BTN == 'right' else 1
PORT = os.environ.get('CDP_PORT', '9333')


async def main(dx, dy, wheel, reload):
    tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json'))
    page = next(t for t in tabs if t['type'] == 'page' and 'mission' in t['url'])
    async with websockets.connect(page['webSocketDebuggerUrl'], max_size=None) as ws:
        n = 0

        async def call(method, **params):
            nonlocal n
            n += 1
            await ws.send(json.dumps({'id': n, 'method': method, 'params': params}))
            while True:
                r = json.loads(await ws.recv())
                if r.get('id') == n:
                    return r

        if reload:
            await call('Page.reload', ignoreCache=True)
            await asyncio.sleep(6)
        x0, y0 = 600, 520
        mouse = 'Input.dispatchMouseEvent'
        await call(mouse, type='mouseMoved', x=x0, y=y0)
        await call(mouse, type='mousePressed', x=x0, y=y0, button=BTN, clickCount=1, buttons=BTNS)
        steps = 30
        for i in range(1, steps + 1):
            await call(mouse, type='mouseMoved', x=x0 + dx * i / steps, y=y0 + dy * i / steps,
                       button=BTN, buttons=BTNS)
            await asyncio.sleep(0.02)
        await call(mouse, type='mouseReleased', x=x0 + dx, y=y0 + dy, button=BTN, clickCount=1,
                   buttons=0)
        for _ in range(int(abs(wheel) // 100)):
            await call(mouse, type='mouseWheel', x=x0, y=y0, deltaX=0,
                       deltaY=100 if wheel > 0 else -100)
            await asyncio.sleep(0.05)
        await call(mouse, type='mouseMoved', x=1300, y=900)    # park the pointer off the scene


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    asyncio.run(main(float(a[0]), float(a[1]), float(a[2]) if len(a) > 2 else 0, len(a) > 3))
