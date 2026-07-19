---
name: add-pressure-scale
description: Use when adding a new pressure calibration scale (or a new sensor material/line) to FluoraPressée's PressureCalculator — e.g. "add the XYZ 2024 ruby scale", "add a new temperature-correction scale for zircon", "add support for a new pressure sensor". Covers what must change in src/pressureCalc.py, what does NOT need to change (UI, API, file I/O are all data-driven), the temperature-mode gotchas, and how to verify without an automated test suite.
---

# Adding a pressure scale to PressureCalculator

`src/pressureCalc.py` (`PressureCalculator`) is the **single source of truth**. Everything else that
touches pressure calculation — `src/pressureCalc_ui.py` (the calculator dialog), `src/ui_mixins/api_mixin.py`
+ `src/api/schemas.py`/`server.py` (the HTTP API), and `src/file_io.py` (saving results) — reads the
`SENSORS` / `PRESSURE_SCALES` / `TEMPERATURE_SCALES` dicts generically (combo boxes populated from the
dicts; API `sensor`/`pressure_scale`/`scale` fields are plain `str` passed straight through). **In the
common case, adding a scale means editing only `src/pressureCalc.py`.** Don't touch the UI or API layers
unless you're doing something the checklist below calls out explicitly.

There is no test suite in this repo (see root `CLAUDE.md`) — verification is manual, via `--debug` mode.

## Decide which of the two cases you're in

- **Case A — new scale for an existing sensor** (e.g. a new ruby calibration, a new zircon temperature
  correction). Most requests are this. Go to [Case A](#case-a-new-scale-for-an-existing-sensor).
- **Case B — new sensor material or line entirely** (e.g. a new fluorescence/Raman probe not in
  `SENSORS`). Do the `SENSORS` step in [Case B](#case-b-new-sensor) first, then everything in Case A
  applies to it.

## Case A: new scale for an existing sensor

### 1. Pick a key and add the `PRESSURE_SCALES` entry

Key convention: `<sensor>_<firstauthor>_<year>[_variant]` (e.g. `ruby_shen_2020`,
`sm_srb4o7_rashchenko_2018_lam2`). Add it to `PressureCalculator.PRESSURE_SCALES[sensor]`:

```python
"ruby_newauthor_2025": {"label": "Newauthor et al. 2025", "temperature_mode": "none"},
```

`temperature_mode` is the key decision:

- **`"none"`** (the common case): the formula only needs `peak` and a zero-pressure reference
  (`wavelength0`/`wavenumber0`). Temperature effects, if the paper reports them, go in a *separate*
  `TEMPERATURE_SCALES` entry (step 3) that the user can independently toggle on/off in the UI — it
  corrects what the "zero-pressure peak" is before it ever reaches the pressure formula.
- **`"embedded_pt"`**: the pressure formula itself is `P(peak, T)` — the literature scale's
  coefficients are polynomials in `T`, so temperature is not an optional correction, it's baked into
  the formula. Only use this when the paper's own P(x) equation takes T as an argument (see
  `cubic_bn_datchi_2004` / `diamond_13c_mysen_yamashita_2010` for real examples). Setting this:
  - forces "Temperature Correction: On" and makes the T field mandatory in the UI
    (`pressureCalc_ui.py::on_p_scale_changed` reads this via `pressure_scale_requires_temperature`)
  - skips the `TEMPERATURE_SCALES`-based zero-peak correction entirely (`calculate()` uses
    `zero_peak_at_t0` directly instead of running it through `get_corrected_zero_peak`)
  - needs `"valid_temp_range": (lo, hi)` if the formula has a stated validity range (shown as a
    red warning in the UI when out of range)
  - optionally `"reports_zero_peak_at_current_t": True` if your formula can also derive what the
    zero-pressure peak would be at the current T (only set this if you actually return that value —
    see step 2)
  - optionally `"fixed_t0": 298.15` + `"fixed_t0_note": "..."` if the scale defines its reference
    temperature as fixed rather than user-adjustable (locks/greys out the T0 spinbox in the UI via
    `resolve_t0`/`_apply_t0_constraint`)

/ **Gotcha**: the two range keys are named differently depending on where they live —
`PRESSURE_SCALES[...]["valid_temp_range"]` for an `embedded_pt` pressure scale, vs.
`TEMPERATURE_SCALES[...]["valid_range"]` for a temperature-correction scale. Mixing these names up
silently disables the range warning (`get_temp_valid_range` just returns `(None, None)`).

### 2. Implement the formula

Both formula methods live in `pressureCalc.py` and are dispatched by `SENSORS[sensor]["kind"]`:

- `kind == "fluorescence"` → add a branch inside `_calculate_fluorescence`, under `if sensor == "...":`,
  matching `if p_scale == "your_new_key":`. Signature only has
  `wavelength, wavelength0, wavelength_err` — **no `current_t`/`t0`/`wavelength0_at_t0`**.
- `kind == "raman"` → same, but inside `_calculate_raman`, which *does* additionally get
  `wavenumber0_at_t0, current_t, t0` (needed for `embedded_pt` raman formulas).

  > **Asymmetry gotcha**: if you need `embedded_pt` for a **fluorescence** sensor, `_calculate_fluorescence`
  > doesn't currently receive `current_t`/`t0`/`wavelength0_at_t0` at all — no existing fluorescence
  > scale needs them. You'll have to extend its signature *and* the call site in `calculate()` (mirror
  > what's already done for `_calculate_raman`) before you can write the formula. Don't skip this — it's
  > silent (you'd otherwise get a `NameError`/`KeyError` or just be unable to reference T at all).

  Return a 3-tuple: `(pressure, pressure_err, zero_peak_override)`. `zero_peak_override` is normally
  `None` — only return a real value if `reports_zero_peak_at_current_t` is set (step 1).

  For error propagation (`pressure_err`), do standard partial-derivative propagation from the peak
  position error and any literature-reported coefficient errors (pass `0` for coefficients whose error
  isn't published — see existing branches for the pattern). Two reusable helpers exist for common
  functional forms — check whether your formula matches one before writing bespoke derivative code:
  - `_calc_mao_type(peak, zero_peak, peak_err, A, B, A_err, B_err)` — Mao-type `P = (A/B)((peak/zero)^B - 1)`
  - `_calc_kunk_type(...)` — Kunc et al. (2003) form, `P = A·r·(1+B·r)` with `r=(peak-zero)/zero`

  `calculate()` already wraps the whole dispatch in try/except (`ZeroDivisionError`/`ValueError`/
  `KeyError`/generic) and prints + returns `PressureCalculationResult(None, None, None)` on failure —
  you don't need your own error handling inside the formula branch, just let exceptions propagate.

### 3. (Optional) Add a temperature-correction scale

Only needed if the paper (or a different paper) publishes how the *zero-pressure* peak position shifts
with temperature, and `temperature_mode` is `"none"`. Add to
`PressureCalculator.TEMPERATURE_SCALES[sensor]`:

```python
"ruby_newauthor_2025": {"label": "Newauthor et al. 2025", "valid_range": (100, 700)},
```

then implement it in `get_corrected_zero_peak()`, under `if sensor == "...": if t_scale == "...":`,
returning the corrected zero-pressure peak at `current_t` given `zero_peak_at_t0` at `t0`. Note this
dict is independent of `PRESSURE_SCALES` — any pressure scale with `temperature_mode == "none"` for
that sensor can be combined with any temperature scale for that sensor; they're not paired 1:1.

### 4. What you do NOT need to touch

- `src/pressureCalc_ui.py` — combo boxes, mandatory-T banner, T0-fixed banner, and range warnings are
  all driven by the dicts/static methods above. No edits needed unless you're changing dialog *layout*.
- `src/ui_mixins/api_mixin.py`, `src/api/schemas.py`, `src/api/server.py` — `sensor`/`pressure_scale`/
  `temperature_correction.scale` are plain `str` fields (see `schemas.py` `PressureRequest`), passed
  straight to `PressureCalculator.calculate()`. A new key works over the API the moment it's in
  `pressureCalc.py`, no schema change needed.
- `src/file_io.py` — `save_fitting_results`/etc. take a generic `pressure_info` dict (`pressure`,
  `pressure_err`, `scale`, `sensor`, `lam0`) built from whatever the UI/API already resolved; nothing
  sensor-specific.

## Case B: new sensor

Add to `PressureCalculator.SENSORS` first:

```python
"my_new_sensor": {
    "label": "My New Sensor",
    "kind": "fluorescence",   # or "raman" — controls dispatch in calculate()
    "unit": "nm",             # or "cm-1" — controls which SpectrometerGUI mode offers it
    "initial_value": 700.0,   # sensible default zero-pressure peak position, shown when first selected
},
```

Then add its `PRESSURE_SCALES[...]` (and optionally `TEMPERATURE_SCALES[...]`) entries and formula
branches exactly as in Case A — the new sensor key just needs its own `if sensor == "my_new_sensor":`
block in `_calculate_fluorescence`/`_calculate_raman` (and `get_corrected_zero_peak` if applicable).

Optional: if the sensor's characteristic spectrum has a well-known peak multiplicity (like ruby's R1/R2
doublet), add a case to `_apply_recommended_fit_peak_count` in `pressureCalc_ui.py` (currently: ruby→2,
sm_srb4o7→1, else unchanged) so selecting the sensor nudges the fit-peak-count spinner. Not required —
without it the user's current peak-count setting is left alone.

## Verify (no automated tests — this is the acceptance check)

1. `python main.py --debug` (synthetic double-peak spectrum, no hardware needed).
2. Enable peak fitting (the Pressure Calculator refuses to open otherwise), then open it.
3. Select your sensor / new pressure scale in the combo boxes:
   - label text renders correctly
   - for `embedded_pt`: temperature correction is forced on, the "mandatory" warning shows, T0 is
     greyed out and shows your `fixed_t0_note` if you set one
   - for a new `TEMPERATURE_SCALES` entry: toggle "Temperature Correction: On", pick it from the T-scale
     combo, confirm the out-of-range warning triggers outside your `valid_range`
4. Plug in the zero-pressure peak and a test peak position taken from a worked example in the source
   paper; confirm the displayed `P` (and, where the paper states one, its uncertainty) matches within
   rounding. This is the real correctness check — the UI wiring alone doesn't validate the physics.
5. If you touched a sensor that's also reachable via the HTTP API, optionally sanity-check
   `POST /acquire/pressure` with `"sensor"`/`"pressure_scale"` set to your new keys (see
   `manuals/API.md`) — but this only re-exercises the same `PressureCalculator.calculate()` call, so
   step 4 is the one that actually matters.

## Optional: docs

- `manuals/API.md` intentionally does *not* enumerate individual scale keys (it just says "see
  `SENSORS`/`PRESSURE_SCALES` in `src/pressureCalc.py`") — no edit needed there for a new key.
- `README.md`'s feature bullet ("Pressure calculation based on Ruby fluorescence shift (supports
  Piermarini, Mao, and Shen scales)") is already stale relative to `pressureCalc.py` (missing
  Dorogokupets/Holzapfel, and the non-ruby sensors entirely). Not this skill's job to fix, but if you're
  touching that bullet's sensor anyway, consider updating it.
