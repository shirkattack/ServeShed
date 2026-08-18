from __future__ import annotations

import importlib
import pkgutil
import unittest

import serveshed


class ImportTests(unittest.TestCase):
    def test_every_serveshed_module_imports(self) -> None:
        modules = sorted(
            module.name for module in pkgutil.walk_packages(serveshed.__path__, prefix="serveshed.")
        )
        self.assertTrue(modules)
        for module in modules:
            with self.subTest(module=module):
                importlib.import_module(module)


if __name__ == "__main__":
    unittest.main()
