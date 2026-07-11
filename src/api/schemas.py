from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CalibrationRequest(BaseModel):
    c0: float
    c1: float
    c2: float
    unit: Literal["Wavelength", "Raman shift"]
    laser_wavelength_nm: float | None = None
    label: str = "api"

    @model_validator(mode="after")
    def _require_laser_wavelength_for_raman(self):
        if self.unit == "Raman shift" and self.laser_wavelength_nm is None:
            raise ValueError('laser_wavelength_nm is required when unit="Raman shift"')
        return self


class CalibrationResponse(BaseModel):
    applied: bool
    unit: str
    c0: float
    c1: float
    c2: float
    label: str


class DarkOptions(BaseModel):
    mode: Literal["none", "reuse_loaded", "provided"] = "none"
    data: list[float] | None = None
    ignore_mismatch: bool = False

    @model_validator(mode="after")
    def _require_data_for_provided(self):
        if self.mode == "provided" and self.data is None:
            raise ValueError('dark.data is required when dark.mode="provided"')
        return self


class AcquireRequest(BaseModel):
    exposure_time_s: float | None = None
    accumulations: int = 1
    dark: DarkOptions = Field(default_factory=DarkOptions)


class FitRange(BaseModel):
    start: float
    end: float


class AcquireFitRequest(AcquireRequest):
    fit_function: Literal["Pseudo Voigt", "Moffat", "Gauss", "Lorentz"]
    fit_peak_count: int = Field(default=2, ge=1, le=5)
    peak_sort_order: Literal["x_desc", "x_asc", "intensity_desc", "intensity_asc"] = "x_desc"
    fit_range: FitRange | None = None


class TemperatureCorrection(BaseModel):
    enabled: bool
    scale: str
    current_t: float
    t0: float
    zero_pressure_peak_at_t0: float


class AcquirePressureRequest(AcquireFitRequest):
    sensor: str
    pressure_scale: str
    zero_pressure_peak: float
    pressure_peak_index: int = Field(default=1, ge=1, le=5)
    temperature_correction: TemperatureCorrection | None = None

    @model_validator(mode="after")
    def _pressure_peak_must_exist_in_fit(self):
        if self.pressure_peak_index > self.fit_peak_count:
            raise ValueError("pressure_peak_index must be less than or equal to fit_peak_count")
        return self


# ----------------------------------------------------------------------
# Response models. x/y_raw/y are left as untyped `list` (rather than
# list[float]) because a 2D (image-mode) acquisition returns a nested
# list[list[float]] for y_raw/y and None for x.
# ----------------------------------------------------------------------

class AcquireResponse(BaseModel):
    x: list | None = None
    y_raw: list
    y: list
    mode: Literal["1d", "2d"]
    exposure_time_s: float
    accumulations: int
    detector_temperature_c: float | None = None
    timestamp: str
    background_mismatch_warning: bool | None = None


class FitResult(BaseModel):
    success: bool
    x_fit: list | None = None
    y_fit: list | None = None
    fit: dict | None = None


class AcquireFitResponse(AcquireResponse):
    fit: FitResult


class AcquirePressureResponse(AcquireFitResponse):
    pressure_gpa: float | None = None
    pressure_err_gpa: float | None = None
    zero_pressure_peak_at_current_t: float | None = None
    temperature_warning: str | None = None


class StatusResponse(BaseModel):
    busy: bool
    camera_connected: bool
    exposure_time_s: float
    calibration: dict
    roi: dict
    background: dict
