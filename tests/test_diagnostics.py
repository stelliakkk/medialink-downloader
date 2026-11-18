import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from medialink.diagnostics import configure_diagnostics, unexpected_error


class DiagnosticsTests(unittest.TestCase):
    def test_local_log_contains_safe_code_locations_but_no_exception_payload(self):
        logger = logging.Logger("isolated-diagnostics", logging.ERROR)
        with TemporaryDirectory() as directory, patch("medialink.diagnostics.LOGGER", logger):
            try:
                configure_diagnostics(Path(directory))
                try:
                    raise ValueError("SESSDATA=secret https://example.invalid/?signed=secret")
                except ValueError as error:
                    message = unexpected_error(error, "下载")
                for handler in logger.handlers:
                    handler.flush()
                content = (Path(directory) / "diagnostics.log").read_text("utf-8")
                self.assertRegex(message, r"ML-[A-F0-9]{10}")
                self.assertIn("ValueError", content)
                self.assertIn("test_local_log_contains_safe_code_locations", content)
                self.assertNotIn("secret", content + message)
                self.assertNotIn(str(Path.cwd()), content)
            finally:
                for handler in logger.handlers:
                    handler.close()
