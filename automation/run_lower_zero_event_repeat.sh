#!/usr/bin/env bash
set -euo pipefail

# Lower-overvoltage continuation of the four-tile zero-event scan.
# The reference tiles stay at 3.0 V while the two GSU tiles are scanned.

EVENTS_PER_POINT="${EVENTS_PER_POINT:-30}"
SETTLE_SECONDS="${SETTLE_SECONDS:-30}"
POINTS=(0.35 0.50 0.75 1.00 1.15 1.25 1.35 1.50 1.75 2.00 2.25 2.50 2.75 3.00)
REFERENCE_OVER_V="2.5"
ROOT="${ROOT:-/home/muon/brDownVstudy/experiments/$(date +%Y-%m-%d_%H%M%S)_lower_zero_event_repeat}"
TOOLS="/home/muon/brDownVstudy/automation"
PI="cosmic@10.51.100.224"
PI_SETTER="/home/cosmic/set_four_channel_efficiency_scan_bias.py"

mkdir -p "$ROOT"
printf '%s\n' "${POINTS[*]}" >"$ROOT/scan_points.txt"
printf '%s\n' "$EVENTS_PER_POINT" >"$ROOT/events_per_point.txt"
printf '%s\n' \
  "reference_overvoltage_V=$REFERENCE_OVER_V" \
  "scope_AB_probe_attenuation=10" \
  "scope_CD_input_range_mV=10000" \
  "scope_CD_probe_attenuation=1" \
  "reference_threshold_C_mV=700" \
  "reference_threshold_D_mV=700" \
  "reference_coincidence_ns=30" \
  "sample_interval_ns=2" \
  "pre_trigger_ns=800" \
  "post_trigger_ns=400" \
  "signal_gate_relative_ns=-20,200" \
  "dark_gate_ns=-520,-300" \
  "fixed_DUT_times_ns=A:8,B:12" \
  >"$ROOT/fixed_conditions.txt"
printf 'starting\n' >"$ROOT/status.txt"
printf '%s\n' "$ROOT" >"/home/muon/brDownVstudy/experiments/latest_lower_zero_event_repeat.txt"

set_biases() {
  local dut_overvoltage="$1"
  ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
    "python3 $PI_SETTER --dut-overvoltage $dut_overvoltage --reference-overvoltage $REFERENCE_OVER_V --allow-low-overvoltage --confirm SET_FOUR_SCAN_BIASES"
}

# Leaving the apparatus at its normal operating point is part of the run.
restore_operating_point() {
  set_biases 3.0 >"$ROOT/restore_all_channels_3p0V.json" \
    2>"$ROOT/restore_all_channels_3p0V.err" || true
}
trap restore_operating_point EXIT

# Small pulses need a smaller input range; larger pulses need clipping headroom.
scope_range_for() {
  awk -v v="$1" 'BEGIN {
    if (v >= 1.0) print 500;
    else if (v >= 0.5) print 200;
    else print 100;
  }'
}

total="${#POINTS[@]}"
minimum_reference_events="$((EVENTS_PER_POINT * 4 / 5))"
for index in "${!POINTS[@]}"; do
  overvoltage="${POINTS[$index]}"
  step="$((index + 1))"
  tag="$(printf '%s' "$overvoltage" | tr '.' 'p')V"
  point_root="$(printf '%s/step_%02d_vov_%s' "$ROOT" "$step" "$tag")"
  mkdir -p "$point_root"
  printf 'acquiring step %d/%d at %s V overvoltage\n' \
    "$step" "$total" "$overvoltage" >"$ROOT/status.txt"

  set_biases "$overvoltage" >"$point_root/bias_set.json"
  sleep "$SETTLE_SECONDS"

  ab_range_mv="$(scope_range_for "$overvoltage")"
  printf '%s\n' "$ab_range_mv" >"$point_root/scope_AB_input_range_mV.txt"
  sipm1_gap="$(awk -v v="$overvoltage" 'BEGIN {printf "%.6f", 1558.8*v/3.0}')"
  sipm2_gap="$(awk -v v="$overvoltage" 'BEGIN {printf "%.6f", 1600.3*v/3.0}')"
  sipm1_height="$(awk -v v="$overvoltage" 'BEGIN {printf "%.6f", 29.8*v/3.0}')"
  sipm2_height="$(awk -v v="$overvoltage" 'BEGIN {printf "%.6f", 30.2*v/3.0}')"

  python3 "$TOOLS/pico_scintillator_capture.py" \
    --output "$point_root/raw" \
    --events "$EVENTS_PER_POINT" \
    --driver ps3000a \
    --enabled-channels A,B,C,D \
    --channel-ranges-mv "A=$ab_range_mv,B=$ab_range_mv,C=10000,D=10000" \
    --channel-attenuations A=10,B=10,C=1,D=1 \
    --sample-interval-ns 2 \
    --pre-trigger-ns 800 \
    --post-trigger-ns 400 \
    --trigger-channel C \
    --trigger-mv 700 \
    --coincidence-channel D \
    --coincidence-trigger-mv 700 \
    --auto-trigger-ms 120000 \
    >"$point_root/capture.log" 2>&1

  ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" \
    'python3 /home/cosmic/vbr_bias_control.py environment' \
    >"$point_root/post_environment.json"

  python3 "$TOOLS/analyze_scintillator_zero.py" \
    --run-dir "$point_root/raw" \
    --output "$point_root/analysis" \
    --reference-channels C,D \
    --reference-thresholds-mv C=700,D=700 \
    --reference-coincidence-ns 30 \
    --minimum-reference-events "$minimum_reference_events" \
    --minimum-clear-pulses 10 \
    --expected-dut-times-ns A=8,B=12 \
    --dut "A:SiPM_1:${sipm1_gap}:${sipm1_height}" \
    --dut "B:SiPM_2:${sipm2_gap}:${sipm2_height}" \
    >"$point_root/analysis.log" 2>&1
done

trap - EXIT
restore_operating_point
printf 'complete\n' >"$ROOT/status.txt"
