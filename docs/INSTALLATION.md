# Installation and Instrument Setup

## 1. System Arrangement

The normal installation uses two computers:

- **Acquisition computer:** Ubuntu PC connected to the PicoScope by USB. The desktop application, acquisition scripts, and analysis run here.
- **Detector controller:** Raspberry Pi connected to the readout PCB. It controls the shared MAX1932 high-side voltage and the channel-specific 10-bit DAC low-side voltages.

The repository defaults use `cosmic@10.51.100.224` as the Pi host because that was the development detector. Change this in the application for the detector actually connected. An IP address is not a detector identity; confirm the hostname and channel wiring too.

## 2. Ubuntu Prerequisites

Install Git, Python, Tkinter, and virtual-environment support:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv python3-tk
```

Install the PicoSDK libraries supplied for the connected scope. The Python `picosdk` package is only a wrapper; the manufacturer library must also be installed and visible to the dynamic linker. Confirm the scope in the PicoScope application before debugging this project.

Clone and install:

```bash
git clone https://github.com/tharinduudu/SiPM-callibration-picoScope-Automation.git
cd SiPM-callibration-picoScope-Automation
chmod +x app/install_desktop.sh app/launch.sh
./app/install_desktop.sh
```

The installer creates `.venv`, installs `requirements.txt`, and creates a desktop launcher named **gLOWCOST Calibration**. It does not install or alter Pi-side bias software.

## 3. Test Without Hardware

```bash
make check
```

This compiles the Python files, runs configuration and process unit tests, and performs synthetic versions of all three workflows. Synthetic success proves software plumbing and analysis execution. It does not prove the PicoScope, probes, SSH connection, PCB, or bias calibration.

## 4. Configure SSH

Use a key so that a long scan does not stop at a password prompt:

```bash
ssh-keygen -t ed25519
ssh-copy-id cosmic@DETECTOR_IP
ssh -o BatchMode=yes cosmic@DETECTOR_IP hostname
```

The final command must return without asking for a password. Confirm that the hostname is the intended detector.

## 5. Install Pi-Side Files

Copy only after reviewing [PI_BIAS_CONTROL.md](PI_BIAS_CONTROL.md):

```bash
scp pi/vbr_bias_control.py cosmic@DETECTOR_IP:/home/cosmic/
scp pi/set_dual_operating_point.py cosmic@DETECTOR_IP:/home/cosmic/
scp pi/set_four_channel_efficiency_scan_bias.py cosmic@DETECTOR_IP:/home/cosmic/
```

Required existing detector files are:

```text
/home/cosmic/dac.py
/home/cosmic/mppcInterface/firmware/libraries/max1932/main
```

The four-channel setter imports the other Pi scripts from the same directory. Do not run it until the `DEVICES` table and transfer-function constants have been checked against measured values for this exact readout.

## 6. Check The Scope

Activate the environment and probe the driver:

```bash
source .venv/bin/activate
python automation/pico_capture.py \
  --probe --driver ps3000a --range-mv 200 --probe-attenuation 10
```

Use `--driver auto` if the family is unknown. Supported Python wrappers are `ps2000a`, `ps3000a`, `ps4000a`, and `ps5000a`.

## 7. First Live Commissioning

1. Measure the actual high-side voltage with a suitable high-impedance meter.
2. Set each DAC to a known code and measure its low-side voltage.
3. Confirm that effective SiPM bias is `Vhigh - Vlow`.
4. Check the physical channel-to-SiPM map.
5. Check every PicoScope probe attenuation switch and the software setting.
6. Start with one point, low event count, conservative range, and **HV off** as the final state.
7. Watch the first waveforms for clipping, wrong polarity, oscillation, or unexpected baseline movement.
8. Increase event count only after that short run is understood.

## 8. Updating

From a clean checkout:

```bash
git pull --ff-only
./app/install_desktop.sh
make check
```

Keep local hardware values in a saved local configuration or a detector-specific branch. Do not silently replace the documented calibration constants for all detectors.
