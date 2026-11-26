# 1. Setup

Once per laptop, about 30 minutes, mostly downloads. Ubuntu 22.04 with ROS 2 Humble (the
demo laptop) or Ubuntu 24.04 with ROS 2 Jazzy.

> **Using conda?** Run `conda deactivate` in every terminal for this project. ROS 2 needs
> the system Python.

## Step 1: install ROS 2

Paste this whole block. It picks the ROS version for your Ubuntu.

```bash
source /etc/os-release
case "$VERSION_ID" in
  22.04) export ROS_DISTRO=humble ;;
  24.04) export ROS_DISTRO=jazzy  ;;
  *) echo "Unsupported Ubuntu $VERSION_ID"; return 2>/dev/null || exit 2 ;;
esac

sudo apt update && sudo apt install -y software-properties-common curl
sudo add-apt-repository universe -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu $UBUNTU_CODENAME main" \
  | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
sudo apt update
sudo apt install -y ros-${ROS_DISTRO}-desktop ros-dev-tools

echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> ~/.bashrc
source /opt/ros/${ROS_DISTRO}/setup.bash
```

## Step 2: get the code and build it

```bash
git clone https://github.com/AI-DA-STC/CrazySwarm2-with-Mocap_Strike-and-Guard.git ~/strike-and-guard
cd ~/strike-and-guard
./scripts/setup.sh
sudo apt install -y python3-scipy
```

`setup.sh` installs the dependencies and builds everything. It needs internet (the first
build downloads OptiTrack's NatNet SDK; the Motive network has none). It must end with a
line starting `OK: motion_capture_tracking from .../install/...`; if it prints `ERROR`,
fix that first ([troubleshooting](troubleshooting.md)).

> **Never** `apt install ros-<distro>-motion-capture-tracking`. This repo carries its own
> fixed copy of that camera driver; the apt one silently receives nothing here.

## Step 3: let your user talk to the radio (real drones only)

```bash
sudo groupadd plugdev 2>/dev/null; sudo usermod -aG plugdev $USER
cat <<'EOF' | sudo tee /etc/udev/rules.d/99-bitcraze.rules > /dev/null
SUBSYSTEM=="usb", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="7777", MODE="0664", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="1915", ATTRS{idProduct}=="0101", MODE="0664", GROUP="plugdev"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="5740", MODE="0664", GROUP="plugdev"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then log out and back in.

## Step 4: build the simulator (simulator only)

The simulator runs the real drone firmware on your laptop:

```bash
./scripts/setup_sim_firmware.sh
source ~/.bashrc
cd ~ && python3 -c "import cffirmware; print('cffirmware OK')"
```

## Step 5: open a terminal the right way

Every terminal for this project starts with these lines (put the last one in
`~/.bashrc` if you like):

```bash
cd ~/strike-and-guard
source /opt/ros/$ROS_DISTRO/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=42      # any number 1-100 nobody else in the lab uses
```

The lab network is shared: without your own `ROS_DOMAIN_ID`, your laptop hears other
people's drone commands, and they hear yours. Check:

```bash
ros2 pkg prefix motion_capture_tracking   # must print a path inside ~/strike-and-guard/install
```

Next: [the flight-day routine](02-flight-day.md), then pick a demo: [escort](escort/run.md), [STL game](stl/run.md) or [guard](guard/run.md).

---

**Later:** after editing `src/`, run `./scripts/build.sh` (or one package:
`./scripts/build.sh crazyflie_shows`), then `source install/setup.bash` again. Low memory:
`LOW_MEM=1 ./scripts/build.sh`.
