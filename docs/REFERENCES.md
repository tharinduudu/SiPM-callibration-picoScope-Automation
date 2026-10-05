# Primary References

## SiPM Operation And Characterization

1. A. Ghassemi, K. Kobayashi, and K. Sato, [A technical guide to silicon photomultipliers (MPPC), Section 4: characterization measurements](https://hub.hamamatsu.com/us/en/technical-notes/mppc-sipms/a-technical-guide-to-silicon-photomutlipliers-MPPC-Section-4.html), Hamamatsu Photonics. This describes gain proportionality to overvoltage, Vbr from the gain-versus-bias x-intercept, and the zero/pedestal-event method used for PDE measurements.

2. Hamamatsu Photonics, [MPPC technical guide, complete PDF](https://www.hamamatsu.com/content/dam/hamamatsu-photonics/sites/documents/99_SALES_LIBRARY/ssd/mppc_kapd9005e.pdf). This is the consolidated device-physics and characterization guide used during development.

3. V. Chmill, E. Garutti, R. Klanner, M. Nitschke, and J. Schwandt, [Study of the breakdown voltage of SiPMs](https://arxiv.org/abs/1605.01692), *Nuclear Instruments and Methods in Physics Research A* **845** (2017) 56-59, DOI: [10.1016/j.nima.2016.04.047](https://doi.org/10.1016/j.nima.2016.04.047). The work compares breakdown-voltage definitions, obtains gain from p.e. pulse-area spacing, fits gain versus bias, and uses the zero-event fraction for relative photodetection behavior.

4. S. Gundacker and A. Heering, [The silicon photomultiplier: fundamentals and applications of a modern solid-state photon detector](https://cds.cern.ch/record/2738368/files/Gundacker_2020_Phys._Med._Biol._65_17TR01.pdf), *Physics in Medicine & Biology* **65** (2020) 17TR01. This review discusses SiPM gain, PDE, correlated noise, saturation, and Poisson zero-count methods.

## PicoScope Automation

5. Pico Technology, [PicoSDK](https://www.picotech.com/library/our-oscilloscope-software-development-kit-sdk). The system drivers provide direct control of PicoScope acquisition hardware.

6. Pico Technology, [Python and PicoSDK getting started](https://www.picotech.com/library/knowledge-bases/oscilloscopes/pypicosdk-get-started). This distinguishes the PicoSDK system drivers from Python wrappers and gives installation guidance.

## How These References Relate To This Repository

The Vbr workflow follows the established gain-extrapolation principle, using amplified pulse-height and voltage-time-area spacing as gain proxies. The zero-event workflow adapts the established pedestal/zero-count probability method to a reference-particle measurement of the complete scintillator channel.

That adaptation should be named carefully. Without a calibrated photon source and incident-photon measurement, the result is **full-chain particle-detection efficiency under the stated reference selection**, not an absolute SiPM PDE measurement.
