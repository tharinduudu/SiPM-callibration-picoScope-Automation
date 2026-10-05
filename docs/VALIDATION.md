# Validation Record

## Software Checks

The repository contains:

- configuration-boundary tests for all three workflows;
- a process/logging test;
- Python bytecode compilation for `app/`, `automation/`, and `pi/`;
- a synthetic end-to-end run for breakdown voltage, dark pulses, and zero-event efficiency.

Run all checks with:

```bash
make check
```

## Synthetic Vbr Recovery

During development, synthetic p.e. spectra were generated with known breakdown voltages near 50.5 V. Representative recovered results were:

| Signal | Metric | Recovered Vbr (V) |
|---|---|---:|
| SiPM 1 | Peak height | 50.561 ± 0.080 |
| SiPM 1 | Pulse area | 50.488 ± 0.095 |
| SiPM 2 | Peak height | 50.500 ± 0.107 |
| SiPM 2 | Pulse area | 50.541 ± 0.095 |

These values validate that synthetic generation, point analysis, weighted fitting, plotting, and result serialization work together. They do not measure a real SiPM and should never be quoted as hardware calibration.

## Hardware Acceptance Checklist

A detector installation is accepted only after the following are recorded:

- [ ] Scope model/serial number and PicoSDK driver identified.
- [ ] All physical probe attenuations match software.
- [ ] Scope range and trigger verified on visible waveforms.
- [ ] Channel map checked by moving or pulsing one input at a time.
- [ ] MAX1932 transfer function measured and residuals inspected.
- [ ] DAC transfer function measured for every used channel.
- [ ] Calculated effective biases checked with an independent meter.
- [ ] HV-off action verified physically.
- [ ] Temperature sensor reading compared with an independent thermometer.
- [ ] One short Vbr scan repeated without moving cables.
- [ ] Height- and area-derived Vbr values compared.
- [ ] One zero-event voltage point repeated to assess drift.
- [ ] Saturation/overflow fraction checked.
- [ ] Final hardware state confirmed after Stop and after a forced acquisition error.

## Reproducibility Criteria

For a repeated scan, compare rather than merely overlay:

- fitted Vbr difference and combined uncertainty;
- p.e. spacing at common bias points;
- baseline noise and peak resolution;
- accepted-event and overflow fractions;
- temperature and elapsed time;
- repeated zero-event efficiency intervals;
- upward versus downward scan points.

A disagreement should remain visible in the record. Do not average repeated runs until the reason for a systematic change has been investigated.

## Known Gaps

- No independent high-voltage readback is integrated.
- The self-trigger capture does not provide absolute dead-time-corrected DCR.
- Hardware-in-the-loop tests are manual.
- The geometry acceptance is not reconstructed event by event.
- The present zero-event boundary uses a supplied p.e. charge-gap calibration; uncertainty in that calibration is not yet jointly propagated into efficiency.
- Temperature gradients between BME280 and SiPM are not measured by this software.

These are analysis limits, not reasons to hide the measurement. They define the next validation work.
