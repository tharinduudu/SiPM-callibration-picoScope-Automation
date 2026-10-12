# Changelog

## 0.2.0 - 2026-10-12

- Added an enforced review, dry-run, hardware-check, and live-run sequence.
- Added a click-to-open help page beside every input, with plain-language selection advice and conceptual diagrams.
- Changed fixed hardware choices to dropdown controls for scope range, attenuation, detector channel, and scope channel.
- Split reusable Tkinter components and help content out of the main application file.
- Added frontend and backend development guides and help-content coverage tests.
- Updated the operator guide and interface screenshot.
- Added explicit, separately gated low- and high-overvoltage characterization modes.
- Added a reproducible lower-overvoltage zero-event scan with automatic scope ranges and 3 V restoration.

## 0.1.0 - 2026-10-05

- Added the gLOWCOST SiPM calibration desktop application.
- Added synthetic and hardware PicoScope acquisition for self-triggered and four-channel reference-triggered waveforms.
- Added robust baseline, pulse-height, pulse-area, p.e. peak, and weighted Vbr analysis.
- Added dark-corrected particle-triggered zero-event efficiency analysis.
- Added MAX1932 and low-side DAC bias planning with ramping, locks, logs, and HV-off cleanup.
- Added unit tests and complete synthetic workflow tests.
- Added installation, operation, scientific-method, hardware, safety, data-format, troubleshooting, development, and validation documentation.
- Added hover help for calibration fields and actions, including units and hardware effects.
