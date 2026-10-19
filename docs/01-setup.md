# 1. Setup

You do this once per laptop. It takes about 30 minutes, mostly downloads.

**Supported:** Ubuntu 22.04 with ROS 2 Humble (what the demo laptop runs), or
Ubuntu 24.04 with ROS 2 Jazzy.

> **Using conda?** Run `conda deactivate` first, in every terminal you use for this
> project. ROS 2 needs the system Python, and conda breaks it in confusing ways.

## Step 1: install ROS 2

Copy and paste this whole block. It picks the right ROS version for your Ubuntu.

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
git clone https://github.com/AI-DA-STC/CrazySwarm2-with-Mocap_Escort-Demo.git ~/escort-demo
cd ~/escort-demo
./scripts/setup.sh
sudo apt install -y python3-scipy
```

`setup.sh` installs the dependencies and builds everything. It must finish with a line
starting `OK: motion_capture_tracking from .../install/...`. If it prints `ERROR`,
fix that first (see [troubleshooting](05-troubleshooting.md)).

> **Never** `apt install ros-<distro>-motion-capture-tracking`. This repo carries its
> own fixed copy of that camera driver. The apt version silently receives no camera
> data on this network.

## Step 3: let your user talk to the radio (real drones only)

Skip this if you only want the simulator.

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

The simulator runs the real drone firmware on your laptop. Build it once:

```bash
./scripts/setup_sim_firmware.sh
source ~/.bashrc
cd ~ && python3 -c "import cffirmware; print('cffirmware OK')"
```

## Step 5: open a terminal the right way

Every terminal you use for this project needs these lines first. Add the last one to
`~/.bashrc` if you like.

```bash
cd ~/escort-demo
source /opt/ros/$ROS_DISTRO/setup.bash
source install/setup.bash
export ROS_DOMAIN_ID=42      # any number 1-100 nobody else in the lab uses
```

**Why `ROS_DOMAIN_ID`:** the lab network is shared. Without your own number, your
laptop hears other people's drone commands, and they hear yours.

Check it worked:

```bash
ros2 pkg prefix motion_capture_tracking   # must print a path inside ~/escort-demo/install
```

Next: [run the demo](02-run-the-demo.md).

---

**Later:** after editing anything in `src/`, rebuild with `./scripts/build.sh` (or just
one package, e.g. `./scripts/build.sh crazyflie_shows`) and re-run
`source install/setup.bash`. On a low-memory machine use `LOW_MEM=1 ./scripts/build.sh`.
