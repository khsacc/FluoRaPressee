import csv
import os
import tempfile
import unittest

from src.core.file_io import DataFileIO

try:
    from src.api.schemas import AcquireFitRequest
except (ImportError, ModuleNotFoundError):
    AcquireFitRequest = None


def fit_result():
    return {
        "R2": 0.999,
        "peaks": [{
            "position": 694.3,
            "position_err": 0.01,
            "width": 1.2,
            "width_err": 0.03,
        }],
        "baseline": {
            "requested": "Auto Polynomial",
            "selected": "Linear",
            "coefficients": [10.0, 2.0],
            "coefficient_errors": [0.1, 0.2],
        },
    }


class BaselineIoApiTests(unittest.TestCase):
    def test_api_baseline_defaults_to_constant(self):
        if AcquireFitRequest is None:
            self.skipTest("Pydantic API dependencies are not installed")
        request = AcquireFitRequest(fit_function="Gauss")
        self.assertEqual(request.baseline_model, "constant")

    def test_api_accepts_auto_polynomial(self):
        if AcquireFitRequest is None:
            self.skipTest("Pydantic API dependencies are not installed")
        request = AcquireFitRequest(
            fit_function="Pseudo Voigt", baseline_model="auto_polynomial"
        )
        self.assertEqual(request.baseline_model, "auto_polynomial")

    def test_individual_fitting_result_saves_baseline_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "fit.csv")
            DataFileIO().save_fitting_results(path, fit_result(), "Gauss")
            with open(path, newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))

        header, values = rows
        mapped = dict(zip(header, values))
        self.assertEqual(mapped["Baseline_Requested"], "Auto Polynomial")
        self.assertEqual(mapped["Baseline_Selected"], "Linear")
        self.assertEqual(mapped["Baseline_b0"], "10.000000")
        self.assertEqual(mapped["Baseline_b1"], "2.000000")
        self.assertEqual(mapped["Baseline_b2"], "nan")

    def test_sequential_summary_columns_align_with_baseline_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "summary.csv")
            io = DataFileIO()
            io.create_fitting_seq_summary(
                path,
                "Gauss",
                690.0,
                700.0,
                1,
                "nm",
                False,
                baseline_model="Auto Polynomial",
            )
            io.append_fitting_seq_row(
                path, "spectrum.txt", "2026-07-21T12:00:00", fit_result(), 1
            )
            with open(path, encoding="utf-8") as handle:
                lines = [line.strip() for line in handle if not line.startswith("#")]

        header = next(csv.reader([lines[0]]))
        values = next(csv.reader([lines[1]]))
        self.assertEqual(len(header), len(values))
        mapped = dict(zip(header, values))
        self.assertEqual(mapped["Baseline Selected"], "Linear")
        self.assertEqual(mapped["Baseline b0"], "10.000000")
        self.assertEqual(mapped["Baseline b2"], "nan")


if __name__ == "__main__":
    unittest.main()
