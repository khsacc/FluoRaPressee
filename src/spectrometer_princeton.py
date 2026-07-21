import re
import threading
import time

import serial
from PyQt5.QtCore import QThread, pyqtSignal


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
        self.config = config

        self.is_initialized = False
        self.spec = None

        self.com_port = (self.config or {}).get("com_port", "COM3")

        self._cancel_event = threading.Event()
        self.last_move_cancelled = False

    def initialize(self):
        if self.debug:
            print("[DEBUG MODE] Spectrometer dummy mode forced.")
            self.is_initialized = False
            return False

        print("Spectrometer initialization...")
        try:
            self.spec = serial.Serial(self.com_port, 9600, timeout=1)

            response = " ".join(self._send_command("?NM", timeout_s=3.0))
            if response:
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
        if not self.is_initialized:
            return 694.0  # Dummy value (used when not initialized/connected)

        try:
            response = " ".join(self._send_command("?NM", timeout_s=3.0))
            match = re.search(r"[-+]?\d*\.\d+|\d+", response)
            if match:
                return float(match.group())
        except Exception as e:
            print(f"Failed to read spectrometer wavelength: {e}")
        return 694.0

    def get_grating(self):
        if not self.is_initialized:
            return 1  # Dummy value (used when not initialized/connected)

        try:
            return self._read_grating()
        except Exception as e:
            print(f"Failed to read spectrometer grating: {e}")
        return 1

    def _read_grating(self):
        """Read the grating number, raising if the response cannot be parsed."""
        response = self._send_command("?GRATING", timeout_s=5.0)
        match = re.search(r"\d+", " ".join(response))
        if not match:
            raise RuntimeError(f"Invalid ?GRATING response: {response!r}")
        return int(match.group())

    def get_device_identity(self):
        """Return {"model": str|None, "serial_number": str|None} for hardware_identity
        cross-checking (see ConfigMixin.check_and_record_hardware_identity()).

        Uses the SP2750's "MODEL" / "SERIAL" RS-232 commands (confirmed against the
        SpectraPro-series command set, shared with the older Acton controllers).
        """
        if self.debug:
            # Fabricated so --debug mode can exercise the identity check without hardware.
            return {"model": "SP-2750 [DEBUG]", "serial_number": "DEBUG-SP2750-0000000"}
        if not self.is_initialized:
            return {"model": None, "serial_number": None}

        model = None
        try:
            model = " ".join(self._send_command("MODEL", timeout_s=3.0)).strip() or None
        except Exception as e:
            print(f"Failed to read spectrometer model: {e}")

        serial = None
        try:
            serial = " ".join(self._send_command("SERIAL", timeout_s=3.0)).strip() or None
        except Exception as e:
            print(f"Failed to read spectrometer serial number: {e}")

        return {"model": model, "serial_number": serial}

    def get_gratings(self):
        """Query all grating slots via ?GRATINGS.

        Returns a list of {"index": int, "grooves": int} dicts sorted by
        index, or [] if not connected or the response could not be parsed.
        The exact real-hardware response format is unconfirmed (see
        work/work_PI_grating.md Step A); parsing is defensive and simply
        yields no results rather than raising if it doesn't match.
        """
        if not self.is_initialized:
            return []
        try:
            response = self._send_command("?GRATINGS", timeout_s=5.0)
            return self._parse_gratings_response(response)
        except Exception as e:
            print(f"Failed to read grating list: {e}")
            return []

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
            time.sleep(1.5)
            return False

        print(f"Setting spectrometer wavelength to {wavelength_nm} nm...")
        self.last_move_cancelled = False
        try:
            # As with GRATING, the SP2750 returns "ok" only after movement
            # finishes.  _send_command accepts both a standalone "ok" and an
            # echoed "<command> ok" response from the actual instrument.
            self._send_command(f"{wavelength_nm:.3f} GOTO", timeout_s=30.0, cancellable=True)
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
            time.sleep(2.0)
            return False

        print(f"Changing grating to index {grating_index}...")
        try:
            # The parameter precedes GRATING; TURRET selects calibration data
            # and does not move a grating into the optical path.
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

    def _close_serial(self):
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
