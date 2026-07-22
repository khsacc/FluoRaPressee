# Versioned configuration catalog

## Scope

This implementation replaces arbitrary calibration/configuration JSON save/load dialogs with a
versioned application-managed catalog. HTTP routes are intentionally out of scope. The public,
Qt-independent `ConfigurationCatalog` methods are the integration boundary for those routes later.

A configuration contains:

- spectrometer/camera compatibility identity;
- grating index and grooves/mm;
- nominal target and observed centre wavelength;
- ROI mode/start/end and detector dimensions;
- wavelength/Raman display context;
- polynomial calibration and its unit/excitation wavelength.

Exposure, accumulation, sample/material, dark, fit, and pressure settings are not configuration
identity or payload fields.

## Identity and versions

A stable slot is selected by the canonical signature:

```
(spectrometer identity, camera identity, grating index/type,
 target centre rounded to 0.001 nm, ROI mode/start/end)
```

Instrument identity uses a serial number when one was recorded. If a backend cannot report a
serial number, the configured/detected model is the required fallback. A missing current serial
does not silently bypass a saved serial check, and model-only records are accepted only for the same
model. Model names are also checked when both sides provide them.

Each Save and Apply creates an immutable `configuration_id`. If its signature already exists, the
new record becomes that slot's active record and the previous one becomes archived. The `slot_id`
does not change, allowing an Experiment Scheduler to save a condition reference and resolve it to
the latest active record when validating a run. `resolve_slots()` returns exact record IDs and the
catalog revision so a run can freeze them before execution.

## Persistence and query performance

Canonical pretty-printed JSON records live below the user's application-data directory:

```
FluoraPressee/configurations/records/YYYY/MM/cfg_<uuid>.json
```

`catalog.sqlite3` stores only indexed discovery/version metadata plus file hashes. Normal listing
does not load record JSON. Queries default to active and hardware-compatible rows and are paginated;
history requires an explicit request. Every write increments a catalog revision. SQLite uses WAL and
a separate short-lived connection for each call so GUI and future API worker threads can share it.
Catalog schema upgrades are automatic; schema v2 adds indexed model identity and rebuilds v1 slot
signatures from their canonical active records.

## GUI workflow

- Calibration `Save and apply` registers a new record automatically; there is no filename prompt.
- The existing Load Configuration button opens `ConfigurationBrowserDialog`.
- Active, compatible records are shown by default; compatible history is opt-in.
- A selected record restores ROI/display/excitation and moves the grating/centre. Calibration is
  applied only after the move succeeds. A cancelled or failed move clears pending configuration.
- Manual grating/centre movement invalidates the active configuration and returns the axis to pixels.

The previous free-form calibration JSON format is intentionally not imported during this
development-phase breaking change. Existing files are left untouched on disk, but the GUI only
loads records registered in the versioned catalog.

## Future API boundary (not routed yet)

The following methods are intentionally transport-neutral:

- `list_selectable(hardware_context, active_only=True, limit=..., offset=...)`
- `get_configuration(configuration_id)`
- `assert_compatible(configuration, hardware_context)`
- `resolve_slots(slot_ids, hardware_context)`
- `mark_used(configuration_id)`

An HTTP layer should serialize these structured summaries rather than scrape GUI labels or duplicate
compatibility rules. Configuration apply/move remains a GUI-thread/instrument-gate operation and will
need a separate bridge when API work resumes.
