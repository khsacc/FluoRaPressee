"""Versioned spectrometer-configuration storage and indexed discovery.

The JSON records are the canonical, portable configuration files.  SQLite is
only a compact catalog used to find the active record for each measurement
condition without scanning every historical JSON file.  This module has no Qt
dependency so the GUI and the future HTTP API can share exactly the same
selection and compatibility rules.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


CONFIGURATION_SCHEMA_VERSION = 1
CATALOG_SCHEMA_VERSION = 1


class ConfigurationError(Exception):
    """Base class for configuration-catalog failures."""


class ConfigurationValidationError(ConfigurationError):
    """A configuration record is incomplete or malformed."""


class ConfigurationCompatibilityError(ConfigurationError):
    """A configuration cannot be applied to the current hardware."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def default_configuration_root() -> Path:
    """Return a per-user, writable application-data directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "FluoraPressee" / "configurations"


def format_configuration_label(summary: dict[str, Any]) -> str:
    grating = summary.get("grating", summary.get("spectrometer", {}))
    roi = summary.get("roi", summary.get("detector", {}))
    roi_mode = roi.get("mode", roi.get("roi_mode"))
    roi_start = roi.get("start", roi.get("roi_start"))
    roi_end = roi.get("end", roi.get("roi_end"))
    center_nm = summary.get(
        "center_wavelength_nm", grating.get("target_center_wavelength_nm")
    )
    grooves = grating.get(
        "grooves_per_mm", grating.get("grating_grooves_per_mm")
    )
    if roi_mode == "1d_roi":
        roi_text = f"ROI {roi_start}–{roi_end}"
    elif roi_mode == "1d_full":
        roi_text = "Full ROI"
    else:
        roi_text = "2D"
    return (
        f"{grooves} g/mm | "
        f"{center_nm:.3f} nm | {roi_text}"
    )


class ConfigurationCatalog:
    """Persist immutable records and maintain one active version per slot."""

    def __init__(self, root: str | os.PathLike[str] | None = None):
        self.root = Path(root) if root is not None else default_configuration_root()
        self.records_root = self.root / "records"
        self.database_path = self.root / "catalog.sqlite3"
        self.records_root.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize_database(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS catalog_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS slots (
                    slot_id TEXT PRIMARY KEY,
                    signature TEXT NOT NULL UNIQUE,
                    spectrometer_serial TEXT,
                    camera_serial TEXT,
                    grating_index INTEGER NOT NULL,
                    grating_grooves_per_mm INTEGER NOT NULL,
                    center_position_pm INTEGER NOT NULL,
                    roi_mode TEXT NOT NULL,
                    roi_start INTEGER NOT NULL,
                    roi_end INTEGER NOT NULL,
                    active_configuration_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS configurations (
                    configuration_id TEXT PRIMARY KEY,
                    slot_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'archived')),
                    calibration_unit TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    sha256 TEXT NOT NULL,
                    last_used_at TEXT,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(slot_id) REFERENCES slots(slot_id)
                );

                CREATE INDEX IF NOT EXISTS idx_configurations_slot_created
                    ON configurations(slot_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_configurations_status_created
                    ON configurations(status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_slots_active_conditions
                    ON slots(grating_index, center_position_pm, roi_mode, roi_start, roi_end);
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO catalog_meta(key, value) VALUES('schema_version', ?)",
                (str(CATALOG_SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO catalog_meta(key, value) VALUES('revision', '0')"
            )

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="milliseconds")

    @staticmethod
    def _center_pm(value_nm: Any) -> int:
        try:
            return int(round(float(value_nm) * 1000.0))
        except (TypeError, ValueError) as exc:
            raise ConfigurationValidationError(
                "spectrometer.target_center_wavelength_nm must be numeric"
            ) from exc

    @classmethod
    def _validate_draft(cls, draft: dict[str, Any]) -> None:
        try:
            compatibility = draft["compatibility"]
            spectrometer = draft["spectrometer"]
            detector = draft["detector"]
            calibration = draft["calibration"]
            int(spectrometer["grating_index"])
            int(spectrometer["grating_grooves_per_mm"])
            cls._center_pm(spectrometer["target_center_wavelength_nm"])
            mode = detector["roi_mode"]
            roi_start = int(detector["roi_start"])
            roi_end = int(detector["roi_end"])
            coefficients = calibration["coefficients"]
            float(coefficients["c0"])
            float(coefficients["c1"])
            float(coefficients["c2"])
            unit = calibration["unit"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationValidationError(
                f"Incomplete configuration record: {exc}"
            ) from exc

        if mode not in {"1d_roi", "1d_full", "2d"}:
            raise ConfigurationValidationError(f"Unsupported ROI mode: {mode!r}")
        if roi_start < 0 or roi_end <= roi_start:
            raise ConfigurationValidationError("ROI must satisfy 0 <= start < end")
        if unit not in {"Wavelength", "Raman shift"}:
            raise ConfigurationValidationError(f"Unsupported calibration unit: {unit!r}")
        if unit == "Raman shift" and calibration.get("excitation_wavelength_nm") is None:
            raise ConfigurationValidationError(
                "Raman shift calibration requires excitation_wavelength_nm"
            )
        if not isinstance(compatibility, dict):
            raise ConfigurationValidationError("compatibility must be an object")

    @classmethod
    def _signature(cls, draft: dict[str, Any]) -> str:
        compatibility = draft["compatibility"]
        spectrometer = draft["spectrometer"]
        detector = draft["detector"]
        identity = {
            "spectrometer_serial_number": compatibility.get("spectrometer_serial_number"),
            "camera_serial_number": compatibility.get("camera_serial_number"),
            "grating_index": int(spectrometer["grating_index"]),
            "grating_grooves_per_mm": int(spectrometer["grating_grooves_per_mm"]),
            "center_position_pm": cls._center_pm(
                spectrometer["target_center_wavelength_nm"]
            ),
            "roi_mode": detector["roi_mode"],
            "roi_start": int(detector["roi_start"]),
            "roi_end": int(detector["roi_end"]),
        }
        return json.dumps(identity, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _record_bytes(record: dict[str, Any]) -> bytes:
        return (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    def register_configuration(self, draft: dict[str, Any]) -> dict[str, Any]:
        """Register a new immutable version and make it active for its slot."""
        self._validate_draft(draft)
        signature = self._signature(draft)
        created_at = self._now()
        configuration_id = self._new_id("cfg")
        final_path: Path | None = None

        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            slot_row = conn.execute(
                "SELECT * FROM slots WHERE signature = ?", (signature,)
            ).fetchone()
            slot_id = slot_row["slot_id"] if slot_row else self._new_id("slot")

            record = deepcopy(draft)
            record["schema_version"] = CONFIGURATION_SCHEMA_VERSION
            record["configuration_id"] = configuration_id
            record["slot_id"] = slot_id
            record["created_at"] = created_at

            relative_path = Path(
                "records",
                created_at[0:4],
                created_at[5:7],
                f"{configuration_id}.json",
            )
            final_path = self.root / relative_path
            final_path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._record_bytes(record)
            digest = hashlib.sha256(payload).hexdigest()
            temporary_path = final_path.with_suffix(".json.tmp")

            try:
                temporary_path.write_bytes(payload)
                os.replace(temporary_path, final_path)

                spectrometer = record["spectrometer"]
                detector = record["detector"]
                compatibility = record["compatibility"]
                center_pm = self._center_pm(
                    spectrometer["target_center_wavelength_nm"]
                )

                if slot_row is None:
                    conn.execute(
                        """
                        INSERT INTO slots(
                            slot_id, signature, spectrometer_serial, camera_serial,
                            grating_index, grating_grooves_per_mm, center_position_pm,
                            roi_mode, roi_start, roi_end, active_configuration_id,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                        """,
                        (
                            slot_id,
                            signature,
                            compatibility.get("spectrometer_serial_number"),
                            compatibility.get("camera_serial_number"),
                            int(spectrometer["grating_index"]),
                            int(spectrometer["grating_grooves_per_mm"]),
                            center_pm,
                            detector["roi_mode"],
                            int(detector["roi_start"]),
                            int(detector["roi_end"]),
                            created_at,
                            created_at,
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE configurations SET status = 'archived' "
                        "WHERE configuration_id = ?",
                        (slot_row["active_configuration_id"],),
                    )

                conn.execute(
                    """
                    INSERT INTO configurations(
                        configuration_id, slot_id, created_at, status,
                        calibration_unit, relative_path, sha256
                    ) VALUES (?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (
                        configuration_id,
                        slot_id,
                        created_at,
                        record["calibration"]["unit"],
                        relative_path.as_posix(),
                        digest,
                    ),
                )
                conn.execute(
                    "UPDATE slots SET active_configuration_id = ?, updated_at = ? "
                    "WHERE slot_id = ?",
                    (configuration_id, created_at, slot_id),
                )
                self._increment_revision(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                if final_path.exists():
                    final_path.unlink()
                raise

        return record

    @staticmethod
    def _increment_revision(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT value FROM catalog_meta WHERE key = 'revision'"
        ).fetchone()
        revision = int(row["value"]) + 1
        conn.execute(
            "UPDATE catalog_meta SET value = ? WHERE key = 'revision'",
            (str(revision),),
        )
        return revision

    def catalog_revision(self) -> int:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT value FROM catalog_meta WHERE key = 'revision'"
            ).fetchone()
        return int(row["value"])

    def get_configuration(self, configuration_id: str) -> dict[str, Any]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT relative_path, sha256 FROM configurations "
                "WHERE configuration_id = ?",
                (configuration_id,),
            ).fetchone()
        if row is None:
            raise ConfigurationError(f"Unknown configuration: {configuration_id}")
        path = self.root / row["relative_path"]
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ConfigurationError(
                f"Configuration file is unavailable: {configuration_id}"
            ) from exc
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise ConfigurationError(
                f"Configuration file failed its integrity check: {configuration_id}"
            )
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(
                f"Configuration file is invalid JSON: {configuration_id}"
            ) from exc

    def _summary_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        summary = {
            "slot_id": row["slot_id"],
            "configuration_id": row["configuration_id"],
            "active_configuration_id": row["active_configuration_id"],
            "active": row["configuration_id"] == row["active_configuration_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "grating": {
                "index": row["grating_index"],
                "grooves_per_mm": row["grating_grooves_per_mm"],
            },
            "center_wavelength_nm": row["center_position_pm"] / 1000.0,
            "roi": {
                "mode": row["roi_mode"],
                "start": row["roi_start"],
                "end": row["roi_end"],
            },
            "calibration": {
                "available": True,
                "unit": row["calibration_unit"],
            },
            "compatibility": {
                "spectrometer_serial_number": row["spectrometer_serial"],
                "camera_serial_number": row["camera_serial"],
            },
        }
        summary["display_label"] = format_configuration_label(summary)
        return summary

    @staticmethod
    def compatibility_reasons(
        configuration: dict[str, Any], hardware_context: dict[str, Any]
    ) -> list[str]:
        compatibility = configuration.get("compatibility", {})
        reasons: list[str] = []
        for key, label in (
            ("spectrometer_serial_number", "Spectrometer serial number"),
            ("camera_serial_number", "Camera serial number"),
        ):
            expected = compatibility.get(key)
            current = hardware_context.get(key)
            if expected and current != expected:
                reasons.append(f"{label} does not match")

        spectrometer = configuration.get("spectrometer", {})
        grating = configuration.get("grating") or spectrometer.get("grating")
        if grating is None:
            grating = {
                "index": spectrometer.get(
                    "grating_index", configuration.get("grating_index")
                ),
                "grooves_per_mm": spectrometer.get(
                    "grating_grooves_per_mm",
                    configuration.get("grating_grooves_per_mm"),
                ),
            }
        available_gratings = hardware_context.get("gratings", [])
        if available_gratings:
            match = next(
                (
                    item for item in available_gratings
                    if int(item.get("index", -1)) == int(grating.get("index", -2))
                ),
                None,
            )
            if match is None:
                reasons.append("Grating slot is not available")
            elif int(match.get("grooves", -1)) != int(grating.get("grooves_per_mm", -2)):
                reasons.append("Grating type does not match the configured slot")

        roi = configuration.get("roi") or configuration.get("detector", {})
        detector_height = hardware_context.get("detector_height")
        if detector_height is not None:
            if int(roi.get("roi_start", roi.get("start", 0))) < 0:
                reasons.append("ROI start is outside the detector")
            if int(roi.get("roi_end", roi.get("end", 0))) > int(detector_height):
                reasons.append("ROI end is outside the detector")
        return reasons

    def assert_compatible(
        self, configuration: dict[str, Any], hardware_context: dict[str, Any]
    ) -> None:
        reasons = self.compatibility_reasons(configuration, hardware_context)
        if reasons:
            raise ConfigurationCompatibilityError(reasons)

    def list_selectable(
        self,
        hardware_context: dict[str, Any],
        *,
        active_only: bool = True,
        include_incompatible: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return lightweight structured rows suitable for GUI/API selection."""
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        conditions = []
        parameters: list[Any] = []
        if active_only:
            conditions.append("c.configuration_id = s.active_configuration_id")
        if not include_incompatible:
            for column, context_key in (
                ("s.spectrometer_serial", "spectrometer_serial_number"),
                ("s.camera_serial", "camera_serial_number"),
            ):
                current = hardware_context.get(context_key)
                if current:
                    conditions.append(f"({column} IS NULL OR {column} = ?)")
                    parameters.append(current)
                else:
                    conditions.append(f"{column} IS NULL")

            gratings = hardware_context.get("gratings", [])
            if gratings:
                grating_clauses = []
                for grating in gratings:
                    grating_clauses.append(
                        "(s.grating_index = ? AND s.grating_grooves_per_mm = ?)"
                    )
                    parameters.extend(
                        [int(grating["index"]), int(grating["grooves"])]
                    )
                conditions.append("(" + " OR ".join(grating_clauses) + ")")

            detector_height = hardware_context.get("detector_height")
            if detector_height is not None:
                conditions.append("s.roi_start >= 0 AND s.roi_end <= ?")
                parameters.append(int(detector_height))

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        select_from = f"""
            SELECT
                c.configuration_id, c.slot_id, c.created_at, c.calibration_unit,
                s.active_configuration_id, s.updated_at,
                s.spectrometer_serial, s.camera_serial,
                s.grating_index, s.grating_grooves_per_mm,
                s.center_position_pm, s.roi_mode, s.roi_start, s.roi_end
            FROM configurations c
            JOIN slots s ON s.slot_id = c.slot_id
            {where}
        """
        with self._connection() as conn:
            conn.execute("BEGIN")
            revision = int(
                conn.execute(
                    "SELECT value FROM catalog_meta WHERE key = 'revision'"
                ).fetchone()["value"]
            )
            total = conn.execute(
                f"SELECT COUNT(*) AS count FROM ({select_from})",
                parameters,
            ).fetchone()["count"]
            rows = conn.execute(
                select_from + " ORDER BY c.created_at DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()

        compatible_items: list[dict[str, Any]] = []
        for row in rows:
            summary = self._summary_from_row(row)
            reasons = self.compatibility_reasons(summary, hardware_context)
            summary["compatible"] = not reasons
            summary["incompatibility_reasons"] = reasons
            if include_incompatible or not reasons:
                compatible_items.append(summary)

        return {
            "catalog_revision": revision,
            "items": compatible_items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def resolve_slots(
        self, slot_ids: list[str], hardware_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Resolve stable slot references to exact active record IDs."""
        resolved_ids = []
        with self._connection() as conn:
            conn.execute("BEGIN")
            revision = int(
                conn.execute(
                    "SELECT value FROM catalog_meta WHERE key = 'revision'"
                ).fetchone()["value"]
            )
            for slot_id in slot_ids:
                row = conn.execute(
                    "SELECT active_configuration_id FROM slots WHERE slot_id = ?",
                    (slot_id,),
                ).fetchone()
                if row is None or row["active_configuration_id"] is None:
                    raise ConfigurationError(f"No active configuration for slot: {slot_id}")
                resolved_ids.append(
                    (slot_id, row["active_configuration_id"])
                )

        resolved = []
        for slot_id, configuration_id in resolved_ids:
            record = self.get_configuration(configuration_id)
            self.assert_compatible(record, hardware_context)
            resolved.append(
                {"slot_id": slot_id, "configuration_id": configuration_id}
            )
        return {"catalog_revision": revision, "resolved": resolved}

    def mark_used(self, configuration_id: str) -> None:
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE configurations SET last_used_at = ?, use_count = use_count + 1 "
                "WHERE configuration_id = ?",
                (self._now(), configuration_id),
            )
            if cursor.rowcount == 0:
                raise ConfigurationError(f"Unknown configuration: {configuration_id}")
