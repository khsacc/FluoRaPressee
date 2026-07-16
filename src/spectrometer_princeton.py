import re
import time

import serial
from PyQt5.QtCore import QThread, pyqtSignal


class SpectrometerControllerPI:
    """Acton SpectraPro-2750 controller using its serial ASCII protocol."""

    def __init__(self, config=None, debug=False):
        self.debug = debug
        self.config = config

        self.is_initialized = False
        self.spec = None

        self.com_port = (self.config or {}).get("com_port", "COM3")

    def initialize(self):
        if self.debug:
            print("[DEBUG MODE] Spectrometer dummy mode forced.")
            self.is_initialized = False
            return False

        print("Spectrometer initialization...")
        try:
            self.spec = serial.Serial(self.com_port, 9600, timeout=1)

            # Keep the wavelength connection test in the form that is known
            # to work with this instrument.
            self.spec.write(b"? NM\r\n")
            response = self.spec.readline().decode("ascii").strip()
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

    def _send_command(self, command, timeout_s=5.0):
        """Send one command and return response lines after its ``ok`` reply."""
        if not self.spec:
            raise RuntimeError("Spectrometer serial port is not open")
        if "\r" in command or "\n" in command:
            raise ValueError("command must not contain CR or LF")

        wire_command = command.encode("ascii") + b"\r"
        self.spec.reset_input_buffer()
        self.spec.write(wire_command)
        self.spec.flush()

        deadline = time.monotonic() + timeout_s
        received = bytearray()

        while time.monotonic() < deadline:
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
            raise TimeoutError(
                "No completion response from spectrometer: "
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

    def _send_wavelength_command(self, command):
        """Use the original one-line exchange used by the working centre control."""
        if not self.is_initialized or not self.spec:
            return ""
        try:
            self.spec.write((command + "\r").encode("ascii"))
            return self.spec.readline().decode("ascii").strip()
        except Exception as e:
            print(f"Serial communication error: {e}")
            return ""

    def get_wavelength(self):
        if not self.is_initialized:
            return 694.0  # Dummy value (used when not initialized/connected)

        try:
            response = self._send_wavelength_command("? NM")
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

    def set_wavelength(self, wavelength_nm):
        if not self.is_initialized:
            print(f"(Dummy) Setting spectrometer wavelength to {wavelength_nm} nm...")
            time.sleep(1.5)
            return False

        print(f"Setting spectrometer wavelength to {wavelength_nm} nm...")
        try:
            # As with GRATING, the SP2750 returns "ok" only after movement
            # finishes.  _send_command accepts both a standalone "ok" and an
            # echoed "<command> ok" response from the actual instrument.
            self._send_command(f"{wavelength_nm:.3f} GOTO", timeout_s=30.0)
            return True
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

    def __init__(self, spec_ctrl, grating_index, wavelength):
        super().__init__()
        self.spec_ctrl = spec_ctrl
        self.grating_index = grating_index
        self.wavelength = wavelength
        self.success = None
        self.error_message = ""

    def run(self):
        if not self.spec_ctrl.is_initialized:
            # Preserve the existing dummy/debug-mode behaviour.
            self.spec_ctrl.set_grating(self.grating_index)
            self.spec_ctrl.set_wavelength(self.wavelength)
            self.success = True
        else:
            grating_ok = self.spec_ctrl.set_grating(self.grating_index)
            # Centre movement must still be attempted if grating verification
            # fails; this was the behaviour before the protocol change.
            wavelength_ok = self.spec_ctrl.set_wavelength(self.wavelength)
            self.success = grating_ok and wavelength_ok
            if not self.success:
                self.error_message = (
                    "The spectrometer did not confirm the requested grating "
                    "and centre-wavelength settings."
                )
        self.finished_signal.emit()
