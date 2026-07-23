---
name: add-pressure-scale
description: Use when adding a new pressure calibration scale (or a new sensor material/line) to FluoraPressée's PressureCalculator — e.g. "add the XYZ 2024 ruby scale", "add a new temperature-correction scale for zircon", "add support for a new pressure sensor". Covers what must change in src/core/pressureCalc.py, what does NOT need to change (UI, API, file I/O are all data-driven), the temperature-mode gotchas, the required README_ja.md citation-list update, and how to verify without an automated test suite.
---

# Adding a pressure scale to PressureCalculator

`src/core/pressureCalc.py` (`PressureCalculator`) is the **single source of truth**. Everything else that
touches pressure calculation — `src/ui/pressureCalc_ui.py` (the calculator dialog), `src/ui/ui_mixins/api_mixin.py`
+ `src/api/schemas.py`/`server.py` (the HTTP API), and `src/core/file_io.py` (saving results) — reads the
`SENSORS` / `PRESSURE_SCALES` / `TEMPERATURE_SCALES` dicts generically (combo boxes populated from the
dicts; API `sensor`/`pressure_scale`/`scale` fields are plain `str` passed straight through). **In the
common case, the only code file to edit is `src/core/pressureCalc.py`** — but the change isn't done until
`README_ja.md`'s scale list is updated too (step 4 below), since that's the only place citations live.
Don't touch the UI or API layers unless you're doing something the checklist below calls out explicitly.

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
`sm_srb4o7_rashchenko_2015_lam12`). Add it to `PressureCalculator.PRESSURE_SCALES[sensor]`:

```python
"ruby_newauthor_2025": {"label": "Newauthor et al. 2025", "temperature_mode": "none"},
```

**Ordering — ruby pressure scales only**: `PRESSURE_SCALES["ruby"]` (and the mirrored 圧力シフト list
under ルビー in `README_ja.md`, step 4) is kept sorted **newest first** by publication year. Insert
your new key at the position matching its year — don't just append to the end. This convention
currently applies only to ruby's pressure-shift (`PRESSURE_SCALES`) entries; other sensors' dicts and
ruby's own 温度シフト/`TEMPERATURE_SCALES` list are not required to follow it unless asked.

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

**Gotcha**: the two range keys are named differently depending on where they live —
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

### 4. Document it in README_ja.md (required, not optional)

`PRESSURE_SCALES`/`TEMPERATURE_SCALES` in code have no citation info — `README_ja.md`'s
**### 圧力計算画面（「Open pressure calculator」ボタンをクリックして開く）** section (currently around
line 42) is the only place in the repo that records *which paper* each scale key implements, and it is
the actively-maintained doc (the note at the top of `README.md` says it "is updated more frequently";
`README.md`'s own feature list is HTML-commented out and not rendered, so don't bother mirroring
changes there). Treat updating this section as part of the change, not an afterthought.

Match the existing structure exactly:
- Top-level split: `蛍光スケール` (fluorescence) vs `Raman スケール`, each a bullet list of sensors.
- Under each sensor bullet (e.g. `ルビー（Cr³⁺:Al₂O₃）`), two sub-lists where applicable: `圧力シフト`
  (pressure scales) and `温度シフト` (temperature scales) — this mirrors `PRESSURE_SCALES[sensor]` vs
  `TEMPERATURE_SCALES[sensor]` respectively. A brand-new sensor needs a new top-level sensor bullet
  under the right fluorescence/Raman group (matching `SENSORS[sensor]["kind"]`).
- Each citation line format: `Author et al., <i>Journal</i> (year) [DOI: xxx](https://doi.org/xxx)`
  (or `[calibrated using the ... scale]` qualifiers where the original list uses them, e.g. the
  Sm²⁺:SrB₄O₇ entries). Temperature-shift lines additionally prefix the valid range, e.g.
  `0 - 600 K, Ragan et al., ...` — keep that prefix in sync with the `valid_range`/`valid_temp_range`
  tuple you set in step 1.
- Use the actual DOI, not a placeholder — look it up rather than guessing.

### 5. What you do NOT need to touch

- `src/ui/pressureCalc_ui.py` — combo boxes, mandatory-T banner, T0-fixed banner, and range warnings are
  all driven by the dicts/static methods above. No edits needed unless you're changing dialog *layout*.
- `src/ui/ui_mixins/api_mixin.py`, `src/api/schemas.py`, `src/api/server.py` — `sensor`/`pressure_scale`/
  `temperature_correction.scale` are plain `str` fields (see `schemas.py` `PressureRequest`), passed
  straight to `PressureCalculator.calculate()`. A new key works over the API the moment it's in
  `pressureCalc.py`, no schema change needed.
- `src/core/file_io.py` — `save_fitting_results`/etc. take a generic `pressure_info` dict (`pressure`,
  `pressure_err`, `scale`, `sensor`, `lam0`) built from whatever the UI/API already resolved; nothing
  sensor-specific.
- `docs-site/docs/api/acquire-pressure.md` — intentionally doesn't enumerate individual scale keys,
  just points at `src/core/pressureCalc.py`.
- `README.md` — its scale-related bullet lives inside a `<!-- ## ✨ Features ... -->` HTML comment and
  isn't rendered; it's stale and not the maintained doc (see step 4).

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
   `docs-site/docs/api/acquire-pressure.md`) — but this only re-exercises the same
   `PressureCalculator.calculate()` call, so step 4 is the one that actually matters.
6. Confirm `README_ja.md`'s scale list was updated (step 4 of Case A, which Case B inherits) and that
   its citation format matches the surrounding entries.
