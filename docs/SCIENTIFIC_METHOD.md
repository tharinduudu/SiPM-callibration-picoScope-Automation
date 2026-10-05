# Scientific Method

## 1. What Is Being Calibrated

The readout sees the voltage pulse after the SiPM and analog amplifier. A fired SiPM microcell contributes approximately one elementary avalanche response. If several microcells fire together, the pulse-height or pulse-charge distribution can contain regularly spaced photoelectron peaks.

The calibration has two separate questions:

1. **What is the SiPM breakdown voltage?** Measure p.e. peak spacing at several bias voltages and extrapolate the spacing to zero.
2. **Where should the assembled detector operate?** Measure the particle-detection efficiency of the complete tile-fiber-SiPM-readout chain versus overvoltage and examine its plateau together with noise and saturation.

Equal answers to the first question do not guarantee equal answers to the second.

## 2. Waveform Baseline And Noise

For each waveform, the pre-pulse samples are used to estimate the baseline. A normal mean can be pulled by an early pulse, so the code begins with robust statistics:

\[
m=\operatorname{median}(x_i), \qquad
\sigma_{\mathrm{MAD}}=1.4826\operatorname{median}(|x_i-m|).
\]

The factor 1.4826 makes the median absolute deviation comparable to the standard deviation for Gaussian noise. Samples farther than four robust standard deviations from the median are removed. The mean and sample standard deviation of the remaining values become the baseline and baseline-noise estimates.

The baseline is subtracted event by event. This matters because a fixed offset would broaden p.e. peaks and bias pulse area.

## 3. Pulse Height And Pulse Area

The prompt peak is searched for only inside the configured timing gate. The largest sample is refined with a parabola through that sample and its two neighbors. This gives a sub-sample estimate without smoothing the waveform itself.

An event is accepted for spectrum construction only when:

- the scope did not report overflow;
- the peak is inside the search gate;
- its height exceeds the larger of five baseline-noise standard deviations and 5 mV.

Pulse area is calculated numerically:

\[
Q_V=\int_{t_1}^{t_2}[V(t)-V_{\mathrm{baseline}}]dt,
\]

using `numpy.trapezoid`. In peak-aligned mode, the integration window moves with the measured pulse time. The result is stored in mV ns. It is a voltage-time area, not electric charge in coulombs unless the full input impedance and analog transfer function are included.

Height is sensitive to pulse shape and bandwidth. Area is often more stable when pulse widths vary, but is more sensitive to the selected gate and residual baseline. Both are retained as cross-checks.

## 4. Constructing The Photoelectron Spectrum

The accepted event values are trimmed only for choosing a useful display and fit range, using the 0.2 and 99.8 percentiles. Histogram width is chosen by the Freedman-Diaconis rule:

\[
h=2\,\frac{IQR}{n^{1/3}},
\]

with the number of bins limited to 50-220 to avoid unusably coarse or noisy plots.

The raw histogram remains visible. A copy of its bin counts is smoothed with `scipy.ndimage.gaussian_filter1d` to locate broad maxima. `scipy.signal.find_peaks` requires:

- a prominence of at least four events or 1.8% of the largest smoothed bin;
- a minimum separation corresponding to approximately 12 mV for height.

Smoothing is used to generate starting candidates. Final peak positions do not come from the smoothed curve.

Each candidate is fitted in its local unsmoothed histogram region with a Gaussian plus a linear background:

\[
f(x)=A\exp\left[-\frac{(x-\mu)^2}{2\sigma^2}\right]+c+d(x-\mu).
\]

`scipy.optimize.curve_fit` returns the center \(\mu\), width, and covariance. The center uncertainty comes from the covariance matrix.

## 5. Selecting A Consistent Peak Sequence

Not every local maximum is a p.e. peak. The algorithm tests candidate combinations against an equally spaced sequence:

\[
x_k=x_0+k\Delta,
\]

where \(k\) is an integer p.e. index and \(\Delta\) is the p.e. spacing. Candidate sequences are scored by their weighted line fit, number of peaks, spacing range, and resolution. This prevents a shoulder or split structure within one p.e. population from automatically becoming an extra p.e. peak.

The numerical result must still be inspected. Optical cross-talk, afterpulsing, trigger bias, amplifier distortion, merged populations, and clipping can produce convincing but wrong patterns.

The present quality conditions are:

- at least two selected peaks;
- spacing at least 12 mV for a two-peak height result;
- peak resolution at least 1.5 where it can be evaluated;
- for three or more selected peaks, sequence linearity \(R^2\ge0.995\).

## 6. Breakdown Voltage From Gain

The p.e. spacing is proportional to SiPM gain. Over a suitable operating interval, gain is approximately proportional to overvoltage:

\[
\Delta(V)=mV+b=m(V-V_{br}).
\]

Therefore,

\[
V_{br}=-\frac{b}{m}.
\]

The software uses weighted linear least squares with the p.e.-spacing uncertainties. It applies a small uncertainty floor to avoid one unrealistically precise point dominating the fit. If reduced chi-square is above one, the parameter covariance is expanded by that factor. The uncertainty in \(V_{br}\) includes slope-intercept covariance:

\[
\sigma^2_{V_{br}}=
\left(\frac{b}{m^2}\right)^2\sigma_m^2+
\left(-\frac{1}{m}\right)^2\sigma_b^2+
2\left(\frac{b}{m^2}\right)\left(-\frac{1}{m}\right)\operatorname{Cov}(m,b).
\]

Only quality-passing points enter the fit. At least three are required. The plotted intercept is an extrapolation; it is not the sharp turn-on point of an I-V curve.

## 7. Reference-Particle Selection

In the default geometry, the top and bottom 9 x 9 cm tiles define a reference track. Their pulses must each cross its threshold and occur within the coincidence window. Overflowed reference events are rejected.

This selection does not reconstruct an exact trajectory. Misalignment, finite tile thickness, scattering, and particles entering at an angle create a geometrical acceptance. The reference tiles should overlap and bracket both devices under test, and the geometry should be documented.

## 8. Zero-Event Efficiency

For each accepted reference event, the program integrates the DUT waveform in two equal 220 ns windows:

- a signal window aligned to the reference pulse;
- an earlier dark window where no reference-correlated scintillation pulse is expected.

The zero boundary is placed at half of the measured 1 p.e. charge spacing above the pedestal. Let

\[
P_0^{\mathrm{sig}}=\frac{N_{0,\mathrm{sig}}}{N}, \qquad
P_0^{\mathrm{dark}}=\frac{N_{0,\mathrm{dark}}}{N}.
\]

The signal window can contain scintillation response plus accidental dark/electronic pulses. Under the independent-noise assumption,

\[
P_0^{\mathrm{sig}}=P_0^{\mathrm{scint}}P_0^{\mathrm{dark}}.
\]

Therefore the noise-corrected full-chain detection efficiency is

\[
\boxed{\epsilon=1-\frac{P_0^{\mathrm{sig}}}{P_0^{\mathrm{dark}}}}.
\]

Example: for 1000 reference tracks, suppose 70 signal windows and 900 dark windows are below the zero boundary:

\[
P_0^{\mathrm{sig}}=0.070, \quad P_0^{\mathrm{dark}}=0.900,
\]

\[
\epsilon=1-\frac{0.070}{0.900}=0.9222\approx92.2\%.
\]

Without the dark correction the apparent efficiency would be 93.0%, because accidental pulses hide some real zero events.

An equivalent zero-count light occupancy is also reported:

\[
\mu=-\ln(P_0^{\mathrm{scint}}).
\]

This is a Poisson-equivalent detected-photoelectron occupancy. It should not be called absolute PDE unless the number and spectrum of photons incident on the SiPM are independently known.

## 9. Efficiency Uncertainty

The code treats the signal and dark zero counts as binomial observations. For each one it samples a Jeffreys posterior:

\[
P_0\sim\operatorname{Beta}(N_0+1/2, N-N_0+1/2).
\]

It draws 200,000 signal/dark pairs, evaluates the efficiency equation, and reports posterior quantiles. This behaves better near zero or one than a symmetric normal approximation.

## 10. Choosing The Operating Point

Plot efficiency, dark activity, p.e. separation, saturation fraction, and repeated-point consistency versus overvoltage. A reasonable operating point is the lowest overvoltage inside a statistically stable efficiency plateau that still has:

- sufficient efficiency for both channels;
- resolvable and stable signals;
- acceptable accidental/noise contribution;
- no amplifier or scope saturation;
- margin for temperature and bias uncertainty.

Do not choose the largest measured pulse merely because it is large. Increasing overvoltage also increases dark counts, optical cross-talk, afterpulsing, power, and saturation risk.

## 11. Assumptions To Test

- Signal-window and dark-window random noise have the same probability.
- Noise is independent of a real scintillation pulse.
- The reference selection is stable with overvoltage and time.
- The measured p.e. gap used for the zero boundary belongs to the same electronics configuration.
- Temperature does not drift enough to move gain appreciably during one point.
- The analog chain remains linear for the pulse population used.

Repeated points and saved raw waveforms exist to test these assumptions rather than conceal their failure.
