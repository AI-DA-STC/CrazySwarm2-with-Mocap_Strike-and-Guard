from __future__ import annotations

import math

import numpy as np
from rclpy.node import Node
from rclpy.time import Time
from rosgraph_msgs.msg import Clock

from ..sim_data_types import Action, State


class Backend:
    """Backend that uses newton-euler rigid-body dynamics implemented in numpy."""

    def __init__(self, node: Node, names: list[str], states: list[State]):
        self.node = node
        self.names = names
        self.clock_publisher = node.create_publisher(Clock, 'clock', 10)
        self.t = 0
        self.dt = 0.0005
        #: Publish /clock every Nth physics step (here: 500 Hz, 2 ms resolution).
        #: Publishing all 2000 steps/s flooded every sim-time node with clock
        #: messages and made rclpy publishing a large share of each step; the
        #: physics and the controllers still run at every step.
        self.clock_every = 4
        self._k = 0

        self.uavs = []
        for state in states:
            uav = Quadrotor(state)
            self.uavs.append(uav)

    def time(self) -> float:
        return self.t

    def step(self, states_desired: list[State], actions: list[Action]) -> list[State]:
        # advance the time
        self.t += self.dt

        next_states = []

        for uav, action in zip(self.uavs, actions):
            uav.step(action, self.dt)
            next_states.append(uav.state)

        # print(states_desired, actions, next_states)
        # publish the current clock (every clock_every steps)
        self._k += 1
        if self._k % self.clock_every == 0:
            clock_message = Clock()
            clock_message.clock = Time(seconds=self.time()).to_msg()
            self.clock_publisher.publish(clock_message)

        return next_states

    def shutdown(self):
        pass


class Quadrotor:
    """Basic rigid body quadrotor model (no drag)."""

    def __init__(self, state):
        # parameters (Crazyflie 2.0 quadrotor)
        self.mass = 0.034  # kg
        # self.J = np.array([
        # 	[16.56,0.83,0.71],
        # 	[0.83,16.66,1.8],
        # 	[0.72,1.8,29.26]
        # 	]) * 1e-6  # kg m^2
        self.J = np.array([16.571710e-6, 16.655602e-6, 29.261652e-6])

        # Note: we assume here that our control is forces
        arm_length = 0.046  # m
        arm = 0.707106781 * arm_length
        t2t = 0.006  # thrust-to-torque ratio
        self.B0 = np.array([
            [1, 1, 1, 1],
            [-arm, -arm, arm, arm],
            [-arm, arm, arm, -arm],
            [-t2t, t2t, -t2t, t2t]
            ])
        self.g = 9.81  # not signed

        if self.J.shape == (3, 3):
            self.inv_J = np.linalg.pinv(self.J)  # full matrix -> pseudo inverse
        else:
            self.inv_J = 1 / self.J  # diagonal matrix -> division

        self.state = state

    def step(self, action, dt, f_a=None):
        """One physics step -- the same equations as before, in plain floats.

        The numpy/rowan version spent its time in per-call overhead on
        3-vectors (np.cross alone was a third of the simulator's time); this
        computes the identical quantities (checked to 1e-12 against it) about
        an order of magnitude faster, which is what limited the simulator to
        ~0.06x real time with 7 drones.
        """
        # RPM -> force: polyfit from IMRCLab/crazyflie-system-id, grams -> N
        p0, p1, p2 = 2.55077341e-08, -4.92422570e-05, -1.51910248e-01
        f = []
        for rpm in action.rpm:
            rpm = float(rpm)
            g = (p0 * rpm + p1) * rpm + p2
            f.append(max(g * 9.81 / 1000.0, 0.0))
        B = self.B0
        e0 = f[0] + f[1] + f[2] + f[3]
        e1 = B[1, 0] * f[0] + B[1, 1] * f[1] + B[1, 2] * f[2] + B[1, 3] * f[3]
        e2 = B[2, 0] * f[0] + B[2, 1] * f[1] + B[2, 2] * f[2] + B[2, 3] * f[3]
        e3 = B[3, 0] * f[0] + B[3, 1] * f[1] + B[3, 2] * f[2] + B[3, 3] * f[3]

        st = self.state
        px, py, pz = (float(v) for v in st.pos)
        vx, vy, vz = (float(v) for v in st.vel)
        qw, qx, qy, qz = (float(v) for v in st.quat)
        wx, wy, wz = (float(v) for v in st.omega)

        def rot(x, y, z):
            # q v q*, for a unit q: t = 2 (q_v x v); v' = v + w t + q_v x t
            tx = 2.0 * (qy * z - qz * y)
            ty = 2.0 * (qz * x - qx * z)
            tz = 2.0 * (qx * y - qy * x)
            return (x + qw * tx + (qy * tz - qz * ty),
                    y + qw * ty + (qz * tx - qx * tz),
                    z + qw * tz + (qx * ty - qy * tx))

        # dot{p} = v ; m dot{v} = m g + R f_u + f_a
        fx, fy, fz = rot(0.0, 0.0, e0)
        if f_a is not None:
            fx, fy, fz = fx + f_a[0], fy + f_a[1], fz + f_a[2]
        m = self.mass
        pos_next = (px + vx * dt, py + vy * dt, pz + vz * dt)
        vel_next = (vx + (fx / m) * dt, vy + (fy / m) * dt,
                    vz + (-self.g + fz / m) * dt)

        # q_next = normalize(exp(0.5 * omega_global * dt) * q)  (rowan.calculus.integrate)
        gx, gy, gz = rot(wx, wy, wz)
        hx, hy, hz = 0.5 * gx * dt, 0.5 * gy * dt, 0.5 * gz * dt
        n = math.sqrt(hx * hx + hy * hy + hz * hz)
        aw = math.cos(n)
        if n <= 1e-8:                       # rowan: np.isclose(norm, 0)
            ax = ay = az = 0.0
        else:
            s = math.sin(n) / n
            ax, ay, az = hx * s, hy * s, hz * s
        nw = aw * qw - ax * qx - ay * qy - az * qz
        nx = aw * qx + ax * qw + ay * qz - az * qy
        ny = aw * qy - ax * qz + ay * qw + az * qx
        nz = aw * qz + ax * qy - ay * qx + az * qw
        nn = math.sqrt(nw * nw + nx * nx + ny * ny + nz * nz)
        q_next = (nw / nn, nx / nn, ny / nn, nz / nn)

        # J dot{w} = J w x w + tau_u   (J diagonal)
        J0, J1, J2 = (float(v) for v in self.J)
        iJ0, iJ1, iJ2 = (float(v) for v in self.inv_J)
        jx, jy, jz = J0 * wx, J1 * wy, J2 * wz
        cx = jy * wz - jz * wy
        cy = jz * wx - jx * wz
        cz = jx * wy - jy * wx
        omega_next = (wx + iJ0 * (cx + e1) * dt, wy + iJ1 * (cy + e2) * dt,
                      wz + iJ2 * (cz + e3) * dt)

        st.pos = np.array(pos_next)
        st.vel = np.array(vel_next)
        st.quat = np.array(q_next)
        st.omega = np.array(omega_next)

        # if we fall below the ground, set velocities to 0
        if st.pos[2] < 0:
            st.pos[2] = 0
            st.vel = [0, 0, 0]
            st.omega = [0, 0, 0]
