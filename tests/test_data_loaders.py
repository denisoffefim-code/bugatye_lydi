import importlib
import unittest


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
