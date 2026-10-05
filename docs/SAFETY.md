# Safety and Failure Recovery

This software changes SiPM high voltage and controls an oscilloscope. Review the detector schematic, instrument ratings, and local laboratory procedure before live use.

## Protections Implemented In Software

- Dry run is the default mode.
- Live mode requires the exact confirmation `RUN_LIVE_HARDWARE`.
- Voltage, overvoltage, event-count, gate, range, attenuation, and timing bounds are validated before the run object is created.
- One non-blocking local file lock prevents simultaneous runs from the same acquisition computer.
- Pi-side bias operations have their own file lock.
- The Pi scripts limit MAX1932 operation to the measured linear code region.
- DAC movement is ramped after changing the shared high side.
- Stop requests terminate the active child process and enter finalization.
- The default final hardware state is HV off.
- Commands, calculated bias plans, configuration, and completion state are logged.

## What Software Cannot Guarantee

- It cannot verify the physical voltage without an independent readback.
- It cannot detect a wrongly connected SiPM or scope cable.
- It cannot know the physical 1x/10x probe switch position.
- It cannot protect hardware if the Pi, network, operating system, MAX1932 binary, DAC script, relay, or power supply fails in an unsafe state.
- It cannot distinguish detector saturation from scope saturation without waveform inspection and range checks.
- It cannot guarantee that killing `biasAdj.py` stops every possible process that controls bias.

## Probe Attenuation

The scope driver measures voltage at the PicoScope input. The acquisition code multiplies by the configured probe attenuation before saving waveforms. A physical 10:1 probe entered as 1x produces amplitudes ten times too small and can select an inappropriate input range. A physical 1x probe entered as 10x produces amplitudes ten times too large in saved data. Check both the connector marking and any probe switch.

## Before Live Operation

- Confirm the correct detector by hostname and visual inspection.
- Confirm MAX1932 and DAC calibration constants.
- Confirm the allowable bias of the installed SiPM.
- Confirm scope input limits with the selected probe attenuation.
- Confirm the readout amplifier cannot drive the scope beyond its input rating.
- Confirm temperature compensation and unrelated scans are stopped.
- Keep a meter connected during first commissioning where practical.
- Know how to remove detector power physically.

## Unexpected Waveform Or Voltage

1. Press **Emergency HV off**.
2. Stop the run.
3. Measure the actual high-side and low-side voltages.
4. If HV remains, remove power using the laboratory procedure.
5. Preserve `run.log`, `manifest.json`, and the most recent raw waveforms.
6. Do not resume by simply increasing the scope range or trigger. First identify whether the cause is probe attenuation, channel mapping, amplifier saturation, oscillation, a light leak, or a wrong bias model.

## Interrupted Network Connection

An SSH disconnect does not prove that voltage is off. The Pi command may have completed before the response was lost. Reconnect, run the Pi controller `status` action, then measure the voltage. Use the `off` action and verify physically.

## Temperature Compensation After A Scan

Automatic restart is disabled by default. If a scan finishes with HV off, decide whether the detector should return to normal operation before restarting compensation. Restarting compensation with stale Vbr/channel values can immediately apply a wrong bias.

## Data Safety

Do not run out of disk space during acquisition. A partially written waveform directory may still look like a valid point. The manifest and capture metadata must be checked before analysis is accepted.
