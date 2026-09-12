import math
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path


_CALIBRATION_DLL = "PrincetonInstruments.Calibration.dll"
_DEFAULT_LIGHTFIELD_DIR = Path(
    os.environ.get("ProgramFiles", r"C:\Program Files")
) / "Princeton Instruments" / "LightField"
_runtime_cache = {}


def _normalise_model(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower()).removeprefix("model")


def _model_family(model, available_families):
    """Map a controller model string to a family supplied by the DLL XML."""
    normalised = _normalise_model(model)
    families = {_normalise_model(name): name for name in available_families}

    for key, original in sorted(families.items(), key=lambda item: -len(item[0])):
        if key and key in normalised:
            return original

    # SpectraPro model names commonly contain the focal length (SP-2-750i),
    # while the DLL groups them under the series name (sp2700).
    aliases = (
        (r"(?:spectrapro|sp)2?150", "sp2150"),
        (r"(?:spectrapro|sp)2?300", "sp2300"),
        (r"(?:spectrapro|sp)2?500", "sp2500"),
        (r"(?:spectrapro|sp)2?(?:700|750)", "sp2700"),
        (r"isoplane.*320|sct320", "SCT320"),
        (r"isoplane.*160|iso160", "ISO160"),
    )
    for pattern, family in aliases:
        if re.search(pattern, normalised) and _normalise_model(family) in families:
            return families[_normalise_model(family)]
    return None


def starting_parameters(model, xml_text):
    """Return optical starting parameters for *model* from DLL configuration XML."""
    root = ET.fromstring(str(xml_text).strip())
    family = _model_family(model, [child.tag for child in root])
    if family is None:
        raise ValueError(f"No calibration model is available for {model!r}")
    node = next(child for child in root if child.tag == family)
    params = node.find("startingParams")
    if params is None:
        raise ValueError(f"Calibration model {family!r} has no starting parameters")
    return {
        name: float(params.attrib[name])
        for name in ("gamma", "focus", "delta", "eta")
    }


def _resolve_dll_path(lightfield_path=None):
    candidate = Path(lightfield_path) if lightfield_path else _DEFAULT_LIGHTFIELD_DIR
    if candidate.is_dir() or candidate.suffix.lower() != ".dll":
        candidate /= _CALIBRATION_DLL
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _load_runtime(lightfield_path=None):
    dll_path = str(_resolve_dll_path(lightfield_path).resolve())
    if dll_path in _runtime_cache:
        return _runtime_cache[dll_path]

    from pythonnet import load

    load("netfx")
    import clr

    clr.AddReference(dll_path)
    from PIActon.Calibrate import MonoCalibrate
    from PIActon.PICore import SpectralCal
    from System import Array, Boolean

    runtime = MonoCalibrate, SpectralCal, Array, Boolean
    _runtime_cache[dll_path] = runtime
    return runtime


def build_seed_axis(
    model,
    number_pixels,
    pixel_width_um,
    grooves_per_mm,
    center_wavelength_nm,
    *,
    lightfield_path=None,
):
    """Calculate PI's approximate detector wavelength axis.

    Model geometry is read at runtime from the calibration DLL's embedded XML;
    no per-instrument optical constants are maintained here.
    """
    number_pixels = int(number_pixels)
    pixel_width_um = float(pixel_width_um)
    grooves_per_mm = float(grooves_per_mm)
    center_wavelength_nm = float(center_wavelength_nm)
    if number_pixels < 2 or pixel_width_um <= 0 or grooves_per_mm <= 0:
        raise ValueError("Invalid detector or grating parameters")

    MonoCalibrate, SpectralCal, Array, Boolean = _load_runtime(lightfield_path)
    flags = Array[Boolean]([False] * number_pixels)
    calibrator = MonoCalibrate(str(model), number_pixels, pixel_width_um, flags)
    params = starting_parameters(model, calibrator.LoadConfigParams())
    calibrator.ApplyDefaultParamaters(
        params["focus"], params["gamma"], params["delta"], params["eta"]
    )
    calibrator.GratingDensity = grooves_per_mm
    calibrator.CenterWave = center_wavelength_nm
    grating_angle = float(calibrator.GratingAngleCalc())

    evaluator = SpectralCal()
    gamma = math.radians(params["gamma"])
    detector_angle = math.radians(params["delta"])
    groove_spacing_nm = 1_000_000.0 / grooves_per_mm
    pixel_width_mm = pixel_width_um / 1000.0
    detector_center = number_pixels / 2.0 - 1.0
    axis = [
        float(
            evaluator.dispersedWave(
                gamma,
                groove_spacing_nm,
                1.0,
                center_wavelength_nm,
                detector_angle,
                params["focus"],
                pixel_width_mm,
                pixel - detector_center,
                grating_angle,
                False,
            )
        )
        for pixel in range(number_pixels)
    ]
    if not all(math.isfinite(value) for value in axis):
        raise ValueError("Calibration DLL returned non-finite wavelengths")
    if not (all(a < b for a, b in zip(axis, axis[1:])) or
            all(a > b for a, b in zip(axis, axis[1:]))):
        raise ValueError("Calibration DLL returned a non-monotonic wavelength axis")
    return axis
