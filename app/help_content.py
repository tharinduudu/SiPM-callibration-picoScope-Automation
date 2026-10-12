#!/usr/bin/env python3
"""Plain-language help shown beside every calibration setting.

Keeping this text outside the window-building code makes it possible for a
student or detector operator to improve an explanation without touching the
hardware or acquisition logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HelpTopic:
    """One help page for an input in the desktop application."""

    title: str
    summary: str
    why: str
    choose: str
    units: str = ""
    diagram: str = "generic"


def _topic(
    title: str,
    summary: str,
    why: str,
    choose: str,
    units: str = "",
    diagram: str = "generic",
) -> HelpTopic:
    return HelpTopic(title, summary, why, choose, units, diagram)


# Each key matches a field registered by calibration_app.py.
HELP_TOPICS: dict[str, HelpTopic] = {
    "common.pi": _topic(
        "Detector Pi",
        "The SSH address of the Raspberry Pi that sets the detector bias.",
        "A live run sends MAX1932 and low-side DAC commands to this computer. A wrong address can control the wrong detector.",
        "Use the verified user and IP address printed in the detector logbook, for example cosmic@10.51.100.224.",
        diagram="connection",
    ),
    "common.tools": _topic(
        "Analysis scripts",
        "The folder containing the PicoScope capture and analysis programs.",
        "The runner calls these programs for every scan point and stores their output with the run.",
        "Keep the default unless the automation folder was installed elsewhere. Relative paths are measured from the app folder.",
        diagram="files",
    ),
    "common.output": _topic(
        "Run output folder",
        "The parent folder where each calibration run receives its own time-stamped directory.",
        "Raw waveforms, settings, logs, tables, and plots need to remain together for the result to be reproducible.",
        "Choose a disk with enough free space. A large waveform scan can use several gigabytes.",
        diagram="files",
    ),
    "common.final": _topic(
        "Hardware state after a run",
        "Selects what the runner asks the detector to do when a run finishes or is stopped.",
        "Leaving an unintended bias on the SiPMs after a failed or unattended scan is avoidable risk.",
        "Use hv_off while commissioning. Use restore_3v only when a checked detector must immediately return to its operating point.",
        diagram="safety",
    ),
    "common.stop_temp": _topic(
        "Pause temperature compensation",
        "Stops biasAdj.py while calibration deliberately changes the low-side DAC.",
        "If temperature compensation changes the DAC during a scan, the requested bias point is no longer known.",
        "Leave this enabled for calibration. Restart compensation only after the detector has returned to normal operation.",
        diagram="control",
    ),
    "zero.points": _topic(
        "DUT overvoltage points",
        "The voltages above breakdown applied to regular-tile SiPMs 1 and 2.",
        "Efficiency is measured at each point so the rising region and stable operating region can be compared.",
        "Enter comma-separated values. Begin conservatively and include repeated points only when checking reproducibility or drift.",
        "V above breakdown",
        "overvoltage",
    ),
    "zero.reference_vov": _topic(
        "Reference-tile overvoltage",
        "The fixed overvoltage used by the two 9 x 9 cm reference-tile SiPMs.",
        "The reference tiles define which particle tracks are tested. Their response should not change while the DUT channels are scanned.",
        "Use a previously checked operating point that gives reliable reference pulses without saturation.",
        "V above breakdown",
        "overvoltage",
    ),
    "zero.events": _topic(
        "Events at each point",
        "The number of four-channel waveforms requested at every overvoltage.",
        "More accepted tracks reduce counting uncertainty, but they increase run time and disk use.",
        "Use a short run for setup. Use enough events for the final uncertainty required by the study.",
        "waveforms",
        "statistics",
    ),
    "zero.settle": _topic(
        "Settling time",
        "The wait after changing bias and before recording waveforms.",
        "The bias network and SiPM response need time to reach the new condition. Recording immediately can mix two operating points.",
        "Keep the validated value for comparable runs. Increase it if measured voltage or response is still drifting.",
        "seconds",
        "settling",
    ),
    "zero.minimum_refs": _topic(
        "Minimum accepted tracks",
        "The smallest number of valid C-D coincidences allowed for reporting an efficiency point.",
        "A point with too few selected particles has a large and potentially misleading uncertainty.",
        "Set it below events at each point, but high enough for the required binomial uncertainty.",
        "accepted tracks",
        "statistics",
    ),
    "zero.threshold_c": _topic(
        "Top reference threshold",
        "The minimum probe-corrected pulse height accepted from the top 9 x 9 cm reference tile on scope C.",
        "It rejects baseline noise while keeping real reference-particle pulses. The physical scope threshold is adjusted for probe attenuation.",
        "Choose it from the reference-tile pulse-height spectrum, above noise and below the particle population.",
        "mV at the probe tip",
        "threshold",
    ),
    "zero.threshold_d": _topic(
        "Bottom reference threshold",
        "The minimum probe-corrected pulse height accepted from the bottom 9 x 9 cm reference tile on scope D.",
        "Both reference tiles must respond to define a track through the test region.",
        "Choose it independently from the bottom reference-tile spectrum; do not copy C without checking D.",
        "mV at the probe tip",
        "threshold",
    ),
    "zero.coincidence": _topic(
        "Reference coincidence window",
        "The largest allowed time difference between the C and D reference pulses.",
        "A narrow window suppresses unrelated pulses. A window that is too narrow rejects real particles because of timing spread.",
        "Measure the C-D timing-difference distribution and cover its prompt peak with a small margin.",
        "ns",
        "coincidence",
    ),
    "zero.sample": _topic(
        "Sampling interval",
        "The requested time between adjacent voltage samples in each waveform.",
        "Smaller intervals describe fast pulse shapes better but produce larger files and may reduce available record length.",
        "Use a value that gives several samples across the fastest pulse edge. The actual interval is saved in metadata.",
        "ns per sample",
        "sampling",
    ),
    "zero.pre": _topic(
        "Pre-trigger record",
        "The waveform time saved before the PicoScope trigger.",
        "It must contain a quiet baseline and the complete dark window used for noise correction.",
        "Make it longer than the distance to the dark-window start, with extra baseline on both sides.",
        "ns",
        "gates",
    ),
    "zero.post": _topic(
        "Post-trigger record",
        "The waveform time saved after the trigger.",
        "It must contain the reference pulse, DUT pulse, and the full signal-integration window.",
        "Inspect real waveforms and include the complete pulse tail without recording unnecessary empty time.",
        "ns",
        "gates",
    ),
    "zero.auto": _topic(
        "Scope auto-trigger timeout",
        "The longest time the scope waits for a hardware trigger before returning a capture.",
        "It prevents a disconnected or quiet reference channel from blocking the program forever.",
        "Keep it longer than the expected wait for a real reference coincidence. Auto-triggered captures are still checked by analysis.",
        "ms",
        "trigger_wait",
    ),
    "zero.dark_start": _topic(
        "Dark window start",
        "The beginning of the off-time charge window before the selected particle pulse.",
        "This equal-width control window estimates random dark and electronic pulses that can imitate a DUT response.",
        "Place it in a quiet pre-trigger region, away from the signal and waveform boundary.",
        "ns relative to trigger",
        "gates",
    ),
    "zero.dark_stop": _topic(
        "Dark window stop",
        "The end of the off-time charge window.",
        "The dark and signal windows must have equal width so their zero-event probabilities can be compared fairly.",
        "Keep dark stop minus dark start equal to signal stop minus signal start.",
        "ns relative to trigger",
        "gates",
    ),
    "zero.signal_start": _topic(
        "Signal window start",
        "The beginning of DUT charge integration relative to the reference-track time.",
        "Starting too late loses the pulse rise; starting too early adds unnecessary baseline noise.",
        "Align it from accumulated real waveforms so it begins just before the earliest DUT pulse.",
        "ns relative to track",
        "gates",
    ),
    "zero.signal_stop": _topic(
        "Signal window stop",
        "The end of DUT charge integration relative to the reference-track time.",
        "Stopping too early loses pulse charge. Stopping too late adds noise and increases accidental pulses.",
        "Include the useful pulse tail and keep the width equal to the dark window.",
        "ns relative to track",
        "gates",
    ),
    "zero.s1_charge": _topic(
        "SiPM 1 area-gap slope",
        "The measured increase of one-photoelectron pulse area per volt of overvoltage for SiPM 1.",
        "It converts the requested overvoltage into the half-photoelectron boundary used to identify zero events.",
        "Use the fitted slope from this SiPM's accepted p.e.-spacing calibration, not a datasheet estimate.",
        "mV ns per V",
        "pe_spacing",
    ),
    "zero.s2_charge": _topic(
        "SiPM 2 area-gap slope",
        "The measured increase of one-photoelectron pulse area per volt of overvoltage for SiPM 2.",
        "Each SiPM and readout channel can have a different conversion, so the zero boundary is channel-specific.",
        "Use the accepted p.e.-spacing fit for SiPM 2 and record the calibration source with the run.",
        "mV ns per V",
        "pe_spacing",
    ),
    "zero.s1_height": _topic(
        "SiPM 1 height-gap slope",
        "The measured increase of one-photoelectron pulse height per volt for SiPM 1.",
        "This provides a waveform-quality check and helps identify clipping or a changed analog gain.",
        "Use the slope from the same probe, amplifier path, and scope scaling as the efficiency run.",
        "mV per V",
        "pe_spacing",
    ),
    "zero.s2_height": _topic(
        "SiPM 2 height-gap slope",
        "The measured increase of one-photoelectron pulse height per volt for SiPM 2.",
        "A disagreement with the area result can reveal saturation, timing, or pulse-shape problems.",
        "Use SiPM 2's own accepted pulse-height calibration.",
        "mV per V",
        "pe_spacing",
    ),
    "dark.points": _topic(
        "Dark-scan overvoltages",
        "The overvoltages at which each selected SiPM is recorded without a particle trigger.",
        "Dark-noise level, crosstalk, and visible p.e. spacing all change with overvoltage.",
        "Use comma-separated points spanning the intended operating region without exceeding the approved limit.",
        "V above breakdown",
        "overvoltage",
    ),
    "dark.reference_vov": _topic(
        "Other-channel overvoltage",
        "The overvoltage held on the two detector channels not being studied.",
        "A defined state prevents unused channels from being left at an unknown bias during the scan.",
        "Use a checked operating point, or use a dedicated configuration with unused channels off when appropriate.",
        "V above breakdown",
        "overvoltage",
    ),
    "dark.events": _topic(
        "Dark events per SiPM",
        "The number of self-triggered waveforms recorded from each SiPM at every point.",
        "Resolving photoelectron peaks and comparing distributions needs more events than a quick hardware check.",
        "Start with a few hundred for setup; use thousands for a final spectrum.",
        "waveforms",
        "statistics",
    ),
    "dark.settle": _topic(
        "Dark-scan settling time",
        "The wait between applying an overvoltage and recording dark pulses.",
        "It separates the new point from voltage settling and short thermal transients.",
        "Use the same validated delay at every point.",
        "seconds",
        "settling",
    ),
    "dark.trigger": _topic(
        "Dark-pulse trigger",
        "The probe-corrected pulse height required for the scope to save a dark event.",
        "A high value removes small avalanches; a low value can trigger on baseline noise. It changes which population is recorded.",
        "Set it below the first p.e. population but above electronic noise, then keep it fixed across the scan.",
        "mV at the probe tip",
        "threshold",
    ),
    "dark.range": _topic(
        "Dark-scan scope range",
        "The PicoScope full-scale input range before probe correction.",
        "Too small clips pulses. Too large wastes ADC resolution and makes nearby p.e. peaks harder to separate.",
        "Choose the smallest supported range that contains essentially all waveforms without overflow.",
        "mV at scope input",
        "scope_range",
    ),
    "dark.atten": _topic(
        "Dark-scan probe attenuation",
        "The physical voltage division of the connected scope probe.",
        "The software multiplies scope voltage by this number. A wrong value scales triggers, pulse heights, and areas incorrectly.",
        "Enter 10 for a fixed 10:1 probe. Enter 1 only for a verified direct or 1x path.",
        "ratio",
        "attenuation",
    ),
    "dark.sample": _topic("Dark waveform sampling", "Time between waveform samples.", "It sets pulse-shape resolution and file size.", "Keep the same value when comparing spectra.", "ns per sample", "sampling"),
    "dark.pre": _topic("Dark pre-trigger record", "Waveform time saved before the pulse trigger.", "It supplies the event-by-event baseline and noise estimate.", "Include enough quiet samples for a stable baseline.", "ns", "gates"),
    "dark.post": _topic("Dark post-trigger record", "Waveform time saved after the pulse trigger.", "It must include the full prompt pulse and decay tail used in pulse area.", "Inspect accumulated traces and include the full useful tail.", "ns", "gates"),
    "dark.auto": _topic("Dark auto-trigger timeout", "Maximum wait for a self-triggered pulse.", "It prevents a quiet or disconnected channel from blocking the run indefinitely.", "Keep it long enough for the expected pulse rate.", "ms", "trigger_wait"),
    "vbr.points": _topic(
        "Absolute bias points",
        "The physical SiPM bias voltages used to measure p.e. spacing.",
        "The gain-like peak spacing is fitted against bias; its zero-spacing intercept estimates breakdown voltage.",
        "Use several unsaturated points above breakdown with visible p.e. peaks. Do not force poor points into the fit.",
        "V",
        "vbr_fit",
    ),
    "vbr.minimum": _topic("Allowed minimum bias", "Software lower bound for requested absolute bias.", "It catches typing errors before hardware is changed.", "Set it to the approved lower edge of this detector's scan.", "V", "safety"),
    "vbr.maximum": _topic("Allowed maximum bias", "Software upper bound for requested absolute bias.", "It is a safety boundary, not a target.", "Keep it below the readout and SiPM limits, with margin for uncertainty.", "V", "safety"),
    "vbr.events": _topic("Vbr events per SiPM", "Self-triggered waveforms recorded at each absolute bias.", "Enough events are needed to resolve repeated p.e. peaks and estimate their spacing.", "Use a short setup run first, then a larger sample after ranges and triggers are fixed.", "waveforms", "statistics"),
    "vbr.settle": _topic("Vbr settling time", "Wait after setting each absolute bias.", "It avoids measuring while the bias is still changing.", "Use one validated delay for every fit point.", "seconds", "settling"),
    "vbr.trigger": _topic("Vbr self-trigger", "Probe-corrected pulse height required to save an event.", "Changing it between points changes the selected pulse population and can bias the spectra.", "Place it above baseline noise and below the first p.e. population; keep it fixed.", "mV at probe tip", "threshold"),
    "vbr.range": _topic("Vbr scope range", "PicoScope full-scale range before probe correction.", "The range must avoid clipping while preserving ADC resolution for peak separation.", "Use the same unsaturated range throughout the fit whenever possible.", "mV at scope input", "scope_range"),
    "vbr.atten": _topic("Vbr probe attenuation", "Physical voltage division of the probe.", "It scales all reported pulse heights and areas and therefore the fitted slope.", "Enter the marking on the actual connected probe and verify any switch position.", "ratio", "attenuation"),
    "vbr.sample": _topic("Vbr waveform sampling", "Time between adjacent waveform samples.", "It controls pulse-height timing resolution and numerical area integration.", "Use the same interval at every bias point.", "ns per sample", "sampling"),
    "vbr.pre": _topic("Vbr pre-trigger record", "Quiet waveform recorded before each self-trigger.", "It is used to estimate and subtract the event baseline.", "Include enough uncontaminated samples for a stable baseline.", "ns", "gates"),
    "vbr.post": _topic("Vbr post-trigger record", "Waveform recorded after the pulse trigger.", "It must contain the prompt maximum and full area-integration region.", "Inspect real traces and include the pulse tail without unnecessary empty time.", "ns", "gates"),
    "vbr.auto": _topic("Vbr auto-trigger timeout", "Maximum wait for one self-triggered waveform.", "It prevents a quiet channel from freezing the scan.", "Keep it long compared with the expected interval between accepted dark pulses.", "ms", "trigger_wait"),
}


def field_help(key: str) -> HelpTopic:
    """Return explicit help or a complete help page for repeated channel fields."""

    if key in HELP_TOPICS:
        return HELP_TOPICS[key]
    if ".range_" in key:
        return _topic("Channel scope range", "Full-scale input range for this PicoScope channel.", "It must contain the waveform without clipping while preserving ADC resolution.", "Use the smallest supported range that contains the accumulated traces.", "mV at scope input", "scope_range")
    if ".atten_" in key:
        return _topic("Channel probe attenuation", "Physical attenuation of the probe on this scope channel.", "It scales saved voltages and the physical trigger threshold.", "Enter 10 for a 10:1 probe or 1 only for a verified direct/1x connection.", "ratio", "attenuation")
    if ".name_" in key:
        return _topic("SiPM name", "The identifier written into folders, tables, plots, and manifests.", "A stable name keeps results attached to the same physical SiPM after channels are swapped.", "Use the label physically marked on the SiPM, not only its temporary channel.", diagram="identity")
    if ".detector_" in key:
        return _topic("Detector channel", "The PCB channel whose bias controls this SiPM.", "A wrong channel changes another SiPM and invalidates the requested voltage.", "Trace the cable and verify the mapping before checking the hardware box.", "channel 0 to 7", "connection")
    if ".scope_" in key:
        return _topic("Scope channel", "The PicoScope input carrying this SiPM waveform.", "Analysis must associate each waveform with the bias applied to the same physical SiPM.", "Use A, B, C, or D after tracing the connected probe.", "scope input", "connection")
    return _topic("Setting", "This value is saved with the calibration run.", "Recorded settings are needed to reproduce and interpret the result.", "Use the checked value from the current laboratory setup.")


def help_keys() -> set[str]:
    """Expose explicit keys for a small documentation completeness test."""

    return set(HELP_TOPICS)
