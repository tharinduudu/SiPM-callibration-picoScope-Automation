# Contributing

Changes are welcome when they keep the calibration traceable and safe.

1. Create a branch with a short descriptive name.
2. Keep detector-specific constants separate from general analysis changes.
3. Add or update tests for changed behavior.
4. Run `make check`.
5. Include a short description of the hardware and data used for validation.
6. State whether raw data, synthetic data, or both were tested.
7. Do not commit passwords, private keys, bulk raw waveform captures, or undocumented calibration constants.

For scientific-analysis changes, explain the physical reason, equations, selection changes, and expected effect on previous results. A plot that looks cleaner is not enough reason to change an estimator.
