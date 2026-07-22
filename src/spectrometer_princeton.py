import re
import threading
import time

import serial
from PyQt5.QtCore import QThread, pyqtSignal

from src.instrument_status import device_snapshot, item, safe_item, unavailable_device


class MoveCancelled(Exception):
    """Raised by _send_command when a cancellable command was interrupted via MONO-STOP."""


class SpectrometerControllerPI:
    """Acton SpectraPro-2750 controller using its serial ASCII protocol."""

    # Tolerates "1200g/mm", "1200 g/mm", and a leading "*" marking the
    # currently-selected slot (exact real-hardware format unconfirmed; see
    # work/work_PI_grating.md Step A).
    _GRATING_LINE_RE = re.compile(r"(\d+)\s*\*?\s*(\d+)\s*g\s*/\s*mm", re.IGNORECASE)

    def __init__(self, config=None, debug=False):
        self.debug = debug
        self.config = config or {}

        self.is_initialized = False
        self.spec = None

        self.com_port = self.config.get("com_port", "COM3")

        # RLock is deliberately shared by live status reads and motion commands.
        # A status refresh can therefore never interleave bytes with an in-flight
        # GOTO/GRATING command, while nested helpers may safely call _send_command().
        self._hw_lock = threading.RLock()
        self._cancel_event = threading.Event()
        self.last_move_cancelled = False

        # Hardware values are cached as they are read or successfully changed.
        # get_cached_hardware_metadata() only reads these fields and never touches
        # the serial port, matching SpectrometerControllerAndor's API contract.
        self._device_identity = {"model": None, "serial_number": None}
        self._gratings = []
        self._current_grating = 1
        self._current_wavelength_nm = 694.0

    def initialize(self):
        if self.debug:
            print("[DEBUG MODE] Spectrometer dummy mode forced.")
            self._ensure_debug_cache()
            self.is_initialized = False
            return False

        print("Spectrometer initialization...")
        try:
            self.spec = serial.Serial(self.com_port, 9600, timeout=1)

            response = " ".join(self._send_command("?NM", timeout_s=3.0))
            if response:
                try:
                    self._current_wavelength_nm = self._parse_wavelength(response)
                except ValueError:
                    # Preserve the old connection criterion: any non-empty ?NM
                    # response is enough to consider the controller connected.
                    pass
                print(
                    f"Connected to SP2750 on {self.com_port}. "
                    f"(Response: {response})"
                )
                self.is_initialized = True
                return True

            print("Failed to get a wavelength response from SP2750.")
            self._close_serial()
            return False

        except serial.SerialException as e:
            print(
                f"[Warning] Failed to open {self.com_port}. "
                f"Running in dummy mode. Error: {e}"
            )
        except Exception as e:
            print(f"An error occurred during initialization: {e}")

        self._close_serial()
        self.is_initialized = False
        return False

    def _send_command(self, command, timeout_s=5.0, cancellable=False):
        """Serialize one complete RS-232 request/response transaction."""
        with self._hw_lock:
            return self._send_command_locked(command, timeout_s, cancellable)

    def _send_command_locked(self, command, timeout_s=5.0, cancellable=False):
        """Send one command and return response lines after its ``ok`` reply.

        If ``cancellable`` and a cancellation was requested (see
        ``request_cancel_move``) while waiting, ``MONO-STOP`` is sent and
        ``MoveCancelled`` is raised instead of returning normally.
        """
        if not self.spec:
            raise RuntimeError("Spectrometer serial port is not open")
        if "\r" in command or "\n" in command:
            raise ValueError("command must not contain CR or LF")

        if cancellable:
            self._cancel_event.clear()

        wire_command = command.encode("ascii") + b"\r"
        self.spec.reset_input_buffer()
        self.spec.write(wire_command)
        self.spec.flush()

        deadline = time.monotonic() + timeout_s
        stop_sent = False
        received = bytearray()

        while time.monotonic() < deadline:
            if cancellable and not stop_sent and self._cancel_event.is_set():
                print(f"Cancelling in-flight command: command={command!r}")
                self.spec.write(b"MONO-STOP\r")
                self.spec.flush()
                stop_sent = True
                # Bound the remaining wait instead of riding out the
                # original (possibly 30s) timeout for the abort ack.
                deadline = min(deadline, time.monotonic() + 5.0)

            size = max(self.spec.in_waiting, 1)
            chunk = self.spec.read(size)
            if not chunk:
                continue

            received.extend(chunk)
            normalized = bytes(received).replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            # Depending on the firmware/echo setting, completion may be sent
            # either as its own line ("ok\r\n") or after the echoed command
            # on the same line ("2 GRATING ok\r\n").
            if re.search(rb"(?:^|\s)ok\s*$", normalized, flags=re.IGNORECASE):
                break
        else:
            if not stop_sent:
                raise TimeoutError(
                    "No completion response from spectrometer: "
                    f"command={command!r}, received={bytes(received)!r}"
                )

        if stop_sent:
            print(
                "Command cancelled by user request: "
                f"command={command!r}, received={bytes(received)!r}"
            )
            raise MoveCancelled(f"Cancelled: {command!r}")

        print(
            "Spectrometer command completed: "
            f"command={command!r}, received={bytes(received)!r}"
        )

        text = received.decode("ascii", errors="replace")
        lines = []
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            # Remove an attached or standalone completion marker before
            # filtering the command echo and returning response content.
            line = re.sub(r"(?:^|\s)ok\s*$", "", line, flags=re.IGNORECASE).strip()
            if line:
                lines.append(line)

        # The RS-232 interface may echo the command before the response.
        return [
            line
            for line in lines
            if line != command
        ]

    def request_cancel_move(self):
        """Request that the in-flight cancellable command (see set_wavelength) abort."""
        self._cancel_event.set()

    def get_wavelength(self):
        if self.debug:
            self._ensure_debug_cache()
            return self._current_wavelength_nm
        if not self.is_initialized:
            return self._current_wavelength_nm  # Dummy/cached value when disconnected

        try:
            return self._read_wavelength()
        except Exception as e:
            print(f"Failed to read spectrometer wavelength: {e}")
        return self._current_wavelength_nm

    @staticmethod
    def _parse_wavelength(response):
        match = re.search(r"[-+]?\d*\.\d+|\d+", str(response))
        if not match:
            raise ValueError(f"Invalid ?NM response: {response!r}")
        return float(match.group())

    def _read_wavelength(self):
        """Read and cache the centre wavelength, raising on invalid replies."""
        response = " ".join(self._send_command("?NM", timeout_s=3.0))
        wavelength = self._parse_wavelength(response)
        self._current_wavelength_nm = wavelength
        return wavelength

    def get_grating(self):
        if self.debug:
            self._ensure_debug_cache()
            return self._current_grating
        if not self.is_initialized:
            return self._current_grating  # Dummy/cached value when disconnected

        try:
            return self._read_grating()
        except Exception as e:
            print(f"Failed to read spectrometer grating: {e}")
        return self._current_grating

    def _read_grating(self):
        """Read the grating number, raising if the response cannot be parsed."""
        response = self._send_command("?GRATING", timeout_s=5.0)
        match = re.search(r"\d+", " ".join(response))
        if not match:
            raise RuntimeError(f"Invalid ?GRATING response: {response!r}")
        grating = int(match.group())
        self._current_grating = grating
        return grating

    def get_device_identity(self):
        """Return {"model": str|None, "serial_number": str|None} for hardware_identity
        cross-checking (see ConfigMixin.check_and_record_hardware_identity()).

        Uses the SP2750's "MODEL" / "SERIAL" RS-232 commands (confirmed against the
        SpectraPro-series command set, shared with the older Acton controllers).
        """
        if self.debug:
            # Fabricated so --debug mode can exercise the identity check without hardware.
            self._ensure_debug_cache()
            return dict(self._device_identity)
        if not self.is_initialized:
            return {"model": None, "serial_number": None}

        with self._hw_lock:
            model = None
            try:
                model = self._read_identity_field("MODEL", "model")
            except Exception as e:
                print(f"Failed to read spectrometer model: {e}")

            serial = None
            try:
                serial = self._read_identity_field("SERIAL", "serial_number")
            except Exception as e:
                print(f"Failed to read spectrometer serial number: {e}")

        return {"model": model, "serial_number": serial}

    def _read_identity_field(self, command, cache_key):
        value = " ".join(self._send_command(command, timeout_s=3.0)).strip()
        if not value:
            raise RuntimeError(f"Empty {command} response")
        self._device_identity[cache_key] = value
        return value

    def get_status_snapshot(self):
        """Return a complete read-only spectrograph status snapshot.

        Unlike get_cached_hardware_metadata(), this method queries the instrument.
        The whole snapshot is serialized under _hw_lock so its commands cannot race
        a wavelength or grating move.
        """
        if self.debug:
            with self._hw_lock:
                self._ensure_debug_cache()
                return self._debug_status_snapshot()
        if not self.is_initialized or self.spec is None:
            return unavailable_device(
                "princeton_acton", "Spectrograph is not connected."
            )

        with self._hw_lock:
            return device_snapshot(
                "princeton_acton",
                {
                    "Spectrograph identification": [
                        safe_item(
                            "model", "Model",
                            lambda: self._read_identity_field("MODEL", "model"),
                        ),
                        safe_item(
                            "serial_number", "Serial number",
                            lambda: self._read_identity_field("SERIAL", "serial_number"),
                        ),
                        item("com_port", "COM port", self.com_port),
                    ],
                    "Current position": [
                        safe_item(
                            "centre_wavelength", "Centre wavelength",
                            self._read_wavelength, "nm",
                        ),
                        safe_item("grating", "Current grating", self._read_grating),
                    ],
                    "Installed gratings": self._status_grating_rows(),
                    "Optical geometry": [
                        item(
                            "optical_geometry", "Optical geometry",
                            state="unsupported",
                            error="The Acton serial protocol does not expose optical geometry.",
                        )
                    ],
                    "Accessories": [
                        item(
                            "accessories", "Accessories",
                            state="unsupported",
                            error="Accessory status is not implemented for this controller.",
                        )
                    ],
                },
            )

    def get_gratings(self):
        """Query all grating slots via ?GRATINGS.

        Returns a list of {"index": int, "grooves": int} dicts sorted by
        index, or [] if not connected or the response could not be parsed.
        The exact real-hardware response format is unconfirmed (see
        work/work_PI_grating.md Step A); parsing is defensive and simply
        yields no results rather than raising if it doesn't match.
        """
        if self.debug:
            self._ensure_debug_cache()
            return [dict(grating) for grating in self._gratings]
        if not self.is_initialized:
            return []
        try:
            return self._read_gratings()
        except Exception as e:
            print(f"Failed to read grating list: {e}")
            return []

    def _read_gratings(self):
        response = self._send_command("?GRATINGS", timeout_s=5.0)
        gratings = self._parse_gratings_response(response)
        if gratings:
            self._gratings = [dict(grating) for grating in gratings]
        return [dict(grating) for grating in gratings]

    @classmethod
    def _parse_gratings_response(cls, lines):
        gratings = []
        for line in lines:
            match = cls._GRATING_LINE_RE.search(line)
            if match:
                gratings.append({"index": int(match.group(1)), "grooves": int(match.group(2))})
        gratings.sort(key=lambda g: g["index"])
        return gratings

    def set_wavelength(self, wavelength_nm):
        if not self.is_initialized:
            print(f"(Dummy) Setting spectrometer wavelength to {wavelength_nm} nm...")
            self._current_wavelength_nm = float(wavelength_nm)
            time.sleep(1.5)
            return False

        print(f"Setting spectrometer wavelength to {wavelength_nm} nm...")
        self.last_move_cancelled = False
        try:
            # As with GRATING, the SP2750 returns "ok" only after movement
            # finishes.  _send_command accepts both a standalone "ok" and an
            # echoed "<command> ok" response from the actual instrument.
            with self._hw_lock:
                self._send_command(f"{wavelength_nm:.3f} GOTO", timeout_s=30.0, cancellable=True)
                try:
                    self._read_wavelength()
                except Exception as e:
                    # GOTO completed successfully; retain the requested value if
                    # the optional readback failed, as the Andor backend does.
                    print(f"Warning: failed to read back centre wavelength: {e}")
                    self._current_wavelength_nm = float(wavelength_nm)
            return True
        except MoveCancelled:
            print(f"Wavelength move to {wavelength_nm} nm was cancelled by user request.")
            self.last_move_cancelled = True
            return False
        except Exception as e:
            print(f"Failed to set spectrometer wavelength: {e}")
            return False

    def set_grating(self, grating_index):
        if not 1 <= grating_index <= 9:
            raise ValueError("grating_index must be between 1 and 9")

        if not self.is_initialized:
            print(f"(Dummy) Changing grating to index {grating_index}...")
            self._current_grating = int(grating_index)
            time.sleep(2.0)
            return False

        print(f"Changing grating to index {grating_index}...")
        try:
            # The parameter precedes GRATING; TURRET selects calibration data
            # and does not move a grating into the optical path.
            with self._hw_lock:
                self._send_command(f"{grating_index} GRATING", timeout_s=30.0)
                actual_grating = self._read_grating()
            if actual_grating != grating_index:
                print(
                    "Failed to verify grating change: "
                    f"requested={grating_index}, actual={actual_grating}"
                )
                return False
            return True
        except Exception as e:
            print(f"Failed to set spectrometer grating: {e}")
            return False

    def get_cached_hardware_metadata(self):
        """Return spectrograph metadata without issuing serial commands."""
        with self._hw_lock:
            if self.debug:
                self._ensure_debug_cache()
            selected = next(
                (
                    dict(grating)
                    for grating in self._gratings
                    if grating.get("index") == self._current_grating
                ),
                {},
            )
            limits = selected.pop("wavelength_limits_nm", None)
            return {
                "serial_number": self._device_identity.get("serial_number"),
                "grating": {
                    "index": self._current_grating,
                    "grooves_per_mm": selected.get("grooves"),
                    "blaze": selected.get("blaze"),
                },
                "center_wavelength_nm": self._current_wavelength_nm,
                "wavelength_limits_nm": limits,
            }

    def _status_grating_rows(self):
        try:
            gratings = self._read_gratings()
        except Exception as exc:
            return [item("grating_count", "Grating count", state="error", error=exc)]

        rows = [item("grating_count", "Grating count", len(gratings))]
        for grating in gratings:
            index = grating.get("index")
            value = {"lines_per_mm": grating.get("grooves")}
            if grating.get("blaze") is not None:
                value["blaze"] = grating["blaze"]
            limits = grating.get("wavelength_limits_nm")
            if limits is not None:
                value.update({
                    "wavelength_min_nm": limits.get("min"),
                    "wavelength_max_nm": limits.get("max"),
                })
            rows.append(item(f"grating_{index}", f"Grating {index}", value))
        return rows

    def _ensure_debug_cache(self):
        self._device_identity.update({
            "model": "SP-2750 [DEBUG]",
            "serial_number": "DEBUG-SP2750-0000000",
        })
        if not self._gratings:
            configured = self.config.get("grating") or [
                {"index": 1, "grooves": 600},
                {"index": 2, "grooves": 1200},
                {"index": 3, "grooves": 1800},
            ]
            self._gratings = [dict(grating) for grating in configured]

    def _debug_status_snapshot(self):
        selected = next(
            (g for g in self._gratings if g.get("index") == self._current_grating),
            {},
        )
        rows = [item("grating_count", "Grating count", len(self._gratings))]
        rows.extend(
            item(
                f"grating_{grating.get('index')}",
                f"Grating {grating.get('index')}",
                {"lines_per_mm": grating.get("grooves")},
            )
            for grating in self._gratings
        )
        return device_snapshot(
            "princeton_acton_debug",
            {
                "Spectrograph identification": [
                    item("model", "Model", self._device_identity["model"]),
                    item(
                        "serial_number", "Serial number",
                        self._device_identity["serial_number"],
                    ),
                    item("com_port", "COM port", self.com_port),
                ],
                "Current position": [
                    item(
                        "centre_wavelength", "Centre wavelength",
                        self._current_wavelength_nm, "nm",
                    ),
                    item("grating", "Current grating", self._current_grating),
                    item(
                        "grooves", "Grooves",
                        selected.get("grooves"), "g/mm",
                    ),
                ],
                "Installed gratings": rows,
                "Optical geometry": [
                    item(
                        "optical_geometry", "Optical geometry",
                        state="unsupported",
                        error="The Acton serial protocol does not expose optical geometry.",
                    )
                ],
                "Accessories": [
                    item(
                        "accessories", "Accessories",
                        state="unsupported",
                        error="Accessory status is not implemented for this controller.",
                    )
                ],
            },
        )

    def _close_serial(self):
        with self._hw_lock:
            if self.spec:
                try:
                    self.spec.close()
                except Exception:
                    pass
                finally:
                    self.spec = None

    def close(self):
        self._close_serial()
        self.is_initialized = False


class SpectrometerMoveThread(QThread):
    finished_signal = pyqtSignal()
    # Emitted just before each phase starts ("grating" then "wavelength"), so the
    # GUI can only allow cancellation during the wavelength move (MONO-STOP has no
    # documented effect on a GRATING turret change).
    phase_signal = pyqtSignal(str)

    def __init__(self, spec_ctrl, grating_index, wavelength):
        super().__init__()
        self.spec_ctrl = spec_ctrl
        self.grating_index = grating_index
        self.wavelength = wavelength
        self.success = None
        self.error_message = ""
        self.cancelled = False

    def request_cancel(self):
        if hasattr(self.spec_ctrl, "request_cancel_move"):
            self.spec_ctrl.request_cancel_move()

    def run(self):
        if not self.spec_ctrl.is_initialized:
            # Preserve the existing dummy/debug-mode behaviour.
            self.phase_signal.emit("grating")
            self.spec_ctrl.set_grating(self.grating_index)
            self.phase_signal.emit("wavelength")
            self.spec_ctrl.set_wavelength(self.wavelength)
            self.success = True
        else:
            self.phase_signal.emit("grating")
            grating_ok = self.spec_ctrl.set_grating(self.grating_index)
            # Centre movement must still be attempted if grating verification
            # fails; this was the behaviour before the protocol change.
            self.phase_signal.emit("wavelength")
            wavelength_ok = self.spec_ctrl.set_wavelength(self.wavelength)
            self.cancelled = getattr(self.spec_ctrl, "last_move_cancelled", False)
            self.success = grating_ok and wavelength_ok
            if not self.success and not self.cancelled:
                self.error_message = (
                    "The spectrometer did not confirm the requested grating "
                    "and centre-wavelength settings."
                )
        self.finished_signal.emit()
