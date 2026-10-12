# Frontend Guide

## Purpose

The desktop interface is a guided laboratory control, not only a form. It is written with Python's standard Tkinter library so it runs on the Ubuntu acquisition computer without a browser or a large application framework.

The interface has three measurement tabs:

- **Zero-event efficiency** measures the complete scintillator, fiber, SiPM, amplifier, and analysis response using two reference tiles.
- **Dark-count spectra** records self-triggered SiPM pulses at selected overvoltages.
- **Breakdown-voltage search** records p.e. spectra at absolute bias voltages and fits p.e. spacing against bias.

## Required Student Workflow

The strip above the tabs shows six steps. Green means complete, blue is the next available step, and gray is locked.

1. **Choose method**: select the correct tab.
2. **Set values**: complete values must pass backend validation.
3. **Review plan**: the operator reads a compact run summary and accepts it.
4. **Dry run**: the same configuration runs with synthetic waveforms and no hardware access.
5. **Check hardware**: the operator verifies detector identity, cables, probe attenuation, scope ranges, and measured bias.
6. **Live run**: typed confirmation is required before voltage is changed.

The review and dry-run records contain a signature of the complete selected configuration. Editing one value produces a new signature and locks the later steps. This is intentional: a dry run of one setup cannot authorize a different live setup.

## Source Layout

### `calibration_app.py`

Owns the main window and operator state. Its sections are:

- window construction and visual styles;
- reusable field and section builders;
- method-specific forms;
- conversion between widgets and JSON configuration;
- required-step state and plan review;
- runner process start, stop, and message handling;
- result image and run-log display.

Scientific fitting and detector bias calculations do not belong in this file.

### `ui_components.py`

Contains interface pieces that do not know about a calibration method:

- `ScrolledFrame` for forms on a small monitor;
- `ToolTip` for a short hover reminder;
- `show_help()` for the click-to-open help page;
- `_draw_diagram()` for simple conceptual sketches.

### `help_content.py`

Contains the operator explanation for each setting. A `HelpTopic` has:

- `title`;
- `summary`, shown under **What this controls**;
- `why`, shown under **Why it matters**;
- `choose`, shown under **How to choose it**;
- `units`;
- a diagram type.

Repeated fields such as scope channel, detector channel, range, attenuation, and SiPM name use contextual fallback pages. `test_help_content.py` checks that all fixed fields have complete help.

## Adding A New Input

1. Add a conservative default to `calibration_defaults.json`.
2. Add the field in the appropriate `_build_*_tab()` method.
3. Add a full `HelpTopic` in `help_content.py`.
4. Load it in `_load_into_fields()` and write it in `_config_from_fields()`.
5. Validate it in `calibration_core.py` before any hardware access.
6. Pass it explicitly through `calibration_runner.py`.
7. Add a unit test and update the relevant operator/scientific documentation.

Use a `Combobox` for a fixed set such as scope ranges, probe attenuation, detector channels, or scope inputs. Use a text entry only when the value is truly free-form or numeric.

## Help Writing Style

Explain the physical idea first. State how a wrong value changes the measurement. End with a practical way to choose the value from measured data or the checked setup. Do not hide a safety condition only in help text; enforce it in backend validation too.

## Running The Interface During Development

```bash
./app/launch.sh
```

Check the window at the smallest supported size as well as full screen. Verify that every input has a visible `?` button, long text does not cover controls, and the required-step strip changes after review, dry run, and hardware confirmation.

Run all non-hardware checks before committing:

```bash
make check
```
