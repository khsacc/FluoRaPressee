from concurrent.futures import TimeoutError as FutureTimeoutError

import numpy as np
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException

from src.api.schemas import (
    AcquireFitRequest,
    AcquireFitResponse,
    AcquirePressureRequest,
    AcquirePressureResponse,
    AcquireRequest,
    AcquireResponse,
    CalibrationRequest,
    CalibrationResponse,
    StatusResponse,
)
from src.ui_mixins.api_mixin import BackgroundMismatchError


def _to_list(arr):
    return arr.tolist() if arr is not None else None


def _jsonify(obj):
    """Recursively convert numpy arrays/scalars to plain Python types.

    DataAnalyzer.fit_spectrum() and PressureCalculator.calculate() return
    numpy.float64 scalars (from curve_fit/formulas) and, for double-peak fits,
    numpy.ndarray curves (y_fit1/y_fit2) - none of which Pydantic/FastAPI's
    JSON encoder can serialize directly.
    """
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {k: _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify(v) for v in obj]
    return obj


def create_app(gui_window, gui_bridge) -> FastAPI:
    """Build the FastAPI app exposing ApiMixin's methods over HTTP.

    All routes here run as plain (non-async) functions so Starlette executes
    them in its worker threadpool, never on the GUI thread or the asyncio
    event loop thread - this is required both because GuiBridge.call() refuses
    to be invoked from the GUI thread, and because an async handler would
    block uvicorn's single event loop for the whole duration of a blocking
    acquisition, stalling every other concurrent request.
    """
    app = FastAPI(title="FluoraPressée API")

    def verify_api_key(x_api_key: str | None = Header(default=None)):
        # Reads gui_window._api_key live on every request (rather than
        # closing over a value captured at server-start time) so that
        # ApiMixin.regenerate_api_key() invalidates the old key immediately,
        # without needing to restart this server.
        # Use Header(default=None) rather than a required Header(...) so a
        # missing header and a wrong one both resolve to the same 401 here,
        # instead of FastAPI's default 422 for a missing required header.
        if x_api_key is None or x_api_key != gui_window._api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")

    router = APIRouter(dependencies=[Depends(verify_api_key)])

    def _run_acquire(req: AcquireRequest) -> dict:
        try:
            return gui_window.api_acquire(
                exposure_s=req.exposure_time_s,
                accumulations=req.accumulations,
                dark_mode=req.dark.mode,
                dark_data=req.dark.data,
                ignore_mismatch=req.dark.ignore_mismatch,
            )
        except RuntimeError as e:
            if str(e) == "acquisition busy":
                raise HTTPException(status_code=409, detail=str(e))
            raise HTTPException(status_code=500, detail=str(e))
        except BackgroundMismatchError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FutureTimeoutError:
            raise HTTPException(status_code=504, detail="Acquisition timed out")

    def _acquire_response_payload(result: dict) -> dict:
        payload = {
            "x": _to_list(result["x"]),
            "y_raw": _to_list(result["y_raw"]),
            "y": _to_list(result["y"]),
            "mode": result["mode"],
            "exposure_time_s": result["exposure_time_s"],
            "accumulations": result["accumulations"],
            "detector_temperature_c": result["detector_temperature_c"],
            "timestamp": result["timestamp"],
        }
        if "background_mismatch_warning" in result:
            payload["background_mismatch_warning"] = result["background_mismatch_warning"]
        return payload

    def _fit_payload(req: AcquireFitRequest, result: dict) -> dict:
        if result["mode"] != "1d":
            raise HTTPException(
                status_code=400,
                detail="Fitting is not supported for 2D (image) acquisitions; "
                       "switch the GUI to a 1D mode before using /acquire/fit or /acquire/pressure.",
            )
        fit_start, fit_end = (req.fit_range.start, req.fit_range.end) if req.fit_range else (None, None)
        fit_result = gui_window.api_fit(
            result["x"], result["y"], req.fit_function, fit_start=fit_start, fit_end=fit_end
        )
        return {
            "success": fit_result["success"],
            "x_fit": _to_list(fit_result["x_fit"]),
            "y_fit": _to_list(fit_result["y_fit"]),
            "fit": _jsonify(fit_result["fit"]),
        }

    @router.get("/status", response_model=StatusResponse)
    def get_status():
        return gui_bridge.call(gui_window.api_get_status)

    @router.post("/calibration", response_model=CalibrationResponse)
    def post_calibration(req: CalibrationRequest):
        return gui_bridge.call(lambda: gui_window.api_apply_calibration(
            req.c0, req.c1, req.c2, req.unit,
            laser_wavelength_nm=req.laser_wavelength_nm, label=req.label,
        ))

    @router.post("/acquire", response_model=AcquireResponse)
    def post_acquire(req: AcquireRequest):
        result = _run_acquire(req)
        return _acquire_response_payload(result)

    @router.post("/acquire/fit", response_model=AcquireFitResponse)
    def post_acquire_fit(req: AcquireFitRequest):
        result = _run_acquire(req)
        payload = _acquire_response_payload(result)
        payload["fit"] = _fit_payload(req, result)
        return payload

    @router.post("/acquire/pressure", response_model=AcquirePressureResponse)
    def post_acquire_pressure(req: AcquirePressureRequest):
        result = _run_acquire(req)
        payload = _acquire_response_payload(result)
        fit_payload = _fit_payload(req, result)
        payload["fit"] = fit_payload

        fit_res = fit_payload["fit"]
        if not fit_payload["success"] or fit_res is None:
            payload["pressure_gpa"] = None
            payload["pressure_err_gpa"] = None
            payload["temperature_warning"] = None
            return payload

        is_double = fit_res.get("is_double", False)
        peak = fit_res["Peak1"] if is_double else fit_res["Peak"]
        peak_err = fit_res["Peak1_Err"] if is_double else fit_res["Peak_Err"]

        temperature_correction = (
            req.temperature_correction.model_dump() if req.temperature_correction else None
        )
        pressure_result = gui_window.api_pressure(
            peak, peak_err, req.sensor, req.pressure_scale, req.zero_pressure_peak,
            temperature_correction=temperature_correction,
        )
        payload["pressure_gpa"] = _jsonify(pressure_result["pressure"])
        payload["pressure_err_gpa"] = _jsonify(pressure_result["pressure_err"])
        payload["temperature_warning"] = pressure_result["temperature_warning"]
        return payload

    app.include_router(router)
    return app
