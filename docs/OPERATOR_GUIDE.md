# Operator Guide

## Channel Map Used By The Default Zero-Event Setup

| PicoScope | Detector PCB | Physical channel | Role |
|---|---:|---|---|
| A | CH2 | gLOWCOST regular tile 1 | Device under test 1 |
| B | CH3 | gLOWCOST regular tile 2 | Device under test 2 |
| C | CH0 | Top 9 x 9 cm reference tile | Reference trigger |
| D | CH1 | Bottom 9 x 9 cm reference tile | Reference coincidence |

This is a saved default, not an automatic wiring measurement. Edit the configuration whenever cables or SiPMs are moved.

## Before Every Run

1. Record the date, detector identity, SiPM identifiers, tile identifiers, wrapping, fiber arrangement, and physical order of the stack.
2. Confirm that the two reference tiles overlap each other and bracket both regular tiles.
3. Confirm scope A-D connections and probe attenuation.
4. Measure or verify the high-side voltage independently.
5. Confirm the BME280 temperature is plausible.
6. Confirm that another scan or temperature-compensation process is not changing the bias.
7. Check available disk space. Raw waveform CSV files are intentionally verbose.
8. Run a dry test after changing configuration.

## Starting The Application

```bash
./app/launch.sh
```

The left side selects a workflow and contains editable settings. The right side reports the current phase, command output, plots, and run directory. Save a configuration before a long run so the intended settings are preserved outside the generated run folder as well.

## Dry Run

Dry run is the default. It creates synthetic waveforms, runs the same analysis programs, generates plots, and exercises the run manifest. It does not open the scope, use SSH, stop temperature compensation, or set bias.

Use dry run to check:

- configuration validation;
- output location and write permission;
- plot generation;
- approximate runtime and disk organization;
- changes made to analysis or UI code.

## Live Run

1. Select the workflow.
2. Review every visible setting.
3. Select live operation.
4. Type `RUN_LIVE_HARDWARE` in the confirmation field.
5. Start the run.
6. Observe the first bias plan and scope preflight.
7. Inspect the first raw waveforms before leaving a long scan unattended.

Only one run can own `/tmp/glowcost_calibration_app.lock`. This prevents two copies of the application from controlling the same local setup at once.

## Breakdown-Voltage Search

Use this workflow with light-blocked SiPMs when photoelectron peaks are visible in dark-pulse spectra.

- Supply at least three bias points within the calibrated hardware range.
- Use enough events to resolve several p.e. peaks. Ten thousand is a reasonable starting point, not a universal requirement.
- Keep scope range, probe attenuation, trigger, integration gate, temperature, and cabling unchanged across the scan.
- Avoid points with amplifier or ADC clipping.
- Inspect both height and area spectra. A numerical fit is not sufficient if the assigned peak sequence is visibly wrong.

The result is an avalanche breakdown-voltage estimate. It is followed by an operating-point study; it is not itself the final operating voltage.

## Dark-Pulse Scan

This workflow records self-triggered pulses at selected overvoltages and runs the same p.e. analysis per point. It is useful for comparing pulse spectra and dark activity under controlled acquisition settings.

The capture rate shown by this workflow is affected by block-acquisition overhead and trigger dead time. Do not publish it as absolute dark-count rate without a live-time measurement.

## Particle-Triggered Zero-Event Scan

The two 9 x 9 cm reference tiles select particles passing through the reference overlap. The program then asks whether each regular tile produced charge in an equal, time-aligned signal window.

- References C and D must both exceed their thresholds within the configured coincidence interval.
- The signal and dark windows must have equal duration.
- The zero boundary is half of the measured 1 p.e. charge spacing above the pedestal.
- The off-time window estimates how often a dark or electronic pulse would make a zero event look detected.
- Repeat voltage points on the return path expose drift and hysteresis.

Use the lowest overvoltage on a stable efficiency plateau that also gives acceptable noise, cross-talk, saturation margin, and temperature behavior.

## Stop And Emergency Off

**Stop** terminates the active acquisition and then attempts the configured final hardware action. The default is all-channel HV off.

Use **Emergency HV off** when a waveform, measured voltage, current, temperature, or sound is unexpected. After any software failure, verify the physical high-side voltage. Software cleanup is a protection layer, not an independent interlock.

## After A Run

1. Open `manifest.json` and confirm `completed`, each point status, and `final_hardware_state`.
2. Check `run.log` for failed commands.
3. Inspect overflow counts and representative waveforms.
4. Inspect every accepted and rejected p.e. point.
5. Compare upward and downward repeated zero-event points.
6. Record any cable movement or manual intervention in the lab notebook.
7. Copy the complete run directory to backed-up laboratory storage.
