# Troubleshooting

## Application Does Not Open

Run it from a terminal to see the error:

```bash
./app/launch.sh
```

For `No module named tkinter`:

```bash
sudo apt-get install python3-tk
```

For a display error, run it in the logged-in desktop session rather than a headless SSH shell. The command-line runner can operate without Tkinter.

## PicoScope Is Not Found

```bash
source .venv/bin/activate
python automation/pico_capture.py --probe --driver auto --range-mv 200 --probe-attenuation 10
```

Check USB visibility, PicoSDK system libraries, user permissions, and whether another program owns the scope. Close the PicoScope graphical application before acquisition.

## SSH Preflight Fails

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 cosmic@DETECTOR_IP hostname
```

If this asks for a password, install an SSH key. If the hostname is unexpected, stop and identify the detector. If the host key changed, investigate before deleting the known-host entry.

## Another Run Owns The Lock

First check whether a runner is active:

```bash
pgrep -af calibration_runner.py
```

Do not remove `/tmp/glowcost_calibration_app.lock` to defeat a real run. The operating-system lock is released when the owning process exits; a leftover empty file is harmless.

## Reference Event Count Is Too Low

- Verify C and D are connected to the reference tiles.
- Inspect pulse polarity and physical amplitude.
- Verify 1x/10x attenuation settings.
- Confirm both reference tiles overlap geometrically.
- Check the coincidence interval against measured pulse timing.
- Lower thresholds only after viewing baseline noise and real reference pulses.
- Check that the scope trigger is not waiting for a polarity that never occurs.

## No Photoelectron Peaks Are Found

- Confirm the SiPM is light blocked for the dark-pulse measurement.
- Increase event count without changing trigger conditions.
- Check that trigger bias has not removed the first p.e. population.
- Inspect raw histograms on linear and logarithmic y scales.
- Confirm the scope and amplifier are not clipping.
- Check the integration/search gate against pulse timing.
- Confirm the overvoltage is high enough to resolve gain but still safe.
- Do not reduce peak distance merely to force more peaks; shoulders can be counted incorrectly.

## First Peak Is Smaller Than The Second

This can be physical or instrumental. Possible causes include optical cross-talk, more than one photon in the triggering light population, self-trigger selection that suppresses small pulses, afterpulsing, merged pedestal/1 p.e. populations, or an incorrect peak assignment. Peak positions can still be useful, but the trigger and population model must be documented.

## Vbr Fit Is Rejected

The fit requires three quality-passing bias points. Open every `point_summary.json` and spectrum. Add bias points only where the p.e. sequence is physically resolved. A wider scan cannot rescue saturation, channel swaps, changing temperature, or inconsistent acquisition settings.

## Saturated Waveforms

Overflowed events are rejected, but analog-amplifier saturation can occur without PicoScope overflow. Look for a flat top or a height-area relation that stops being linear. Reduce overvoltage or analog gain, or increase scope range if only the scope is clipping. Never use clipped peaks for Vbr.

## Reported Bias Does Not Match The Meter

The reported value is calculated from calibration equations. Check:

1. MAX1932 code and high-side transfer function;
2. DAC code, channel, and low-side transfer function;
3. effective-bias sign (`high - low`);
4. channel wiring;
5. whether another process changed the DAC;
6. meter reference point and input loading.

Recalibrate before continuing. Do not add an unexplained correction offset to make one point agree.

## Temperature Compensation Is Still Running

```bash
ssh cosmic@DETECTOR_IP "pgrep -af '[b]iasAdj.py'"
```

The live runner attempts to stop this process. If a differently named compensation service exists, add an explicit controlled stop mechanism rather than relying on the current process-name match.

## Run Stopped Before Plots Were Made

Raw point directories remain. Read `manifest.json` and `run.log`, then run the appropriate analysis manually or rerun only the summary command. Do not mark a partial run complete. Preserve the original manifest and document any offline recovery.
