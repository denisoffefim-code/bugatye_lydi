import importlib
import unittest
from unittest.mock import patch


class DataLoaderModuleImportTests(unittest.TestCase):
    def test_load_remote_imports_as_package_module(self) -> None:
        module = importlib.import_module("data_loaders.load_remote")

        self.assertEqual(
            module.normalize_sources(["stations", "tttr", "stations"]),
            ("stations", "tttr"),
        )

    def test_main_imports_as_package_module(self) -> None:
        module = importlib.import_module("data_loaders.main")

        self.assertTrue(callable(module.create_app))

    def test_open_meteo_backfill_cli_parses_skip_outbox(self) -> None:
        module = importlib.import_module("data_loaders.load_open_meteo_backfill")

        with patch(
            "sys.argv",
            [
                "load_open_meteo_backfill.py",
                "--start-date",
                "2021-03-01",
                "--end-date",
                "2021-03-31",
                "--skip-outbox",
            ],
        ):
            args = module.parse_args()

        self.assertTrue(args.skip_outbox)
