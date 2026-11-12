from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import launcher


class WindowedLauncherTest(unittest.TestCase):
    def test_missing_standard_streams_write_to_application_log(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict(os.environ, {"BOOK_AGENT_HOME": directory}),
                patch.object(sys, "stdout", None),
                patch.object(sys, "stderr", None),
            ):
                launcher._prepare_stdio()
                stream = sys.stdout
                self.assertIs(stream, sys.stderr)
                print("backend startup diagnostic")
                stream.close()
            self.assertIn(
                "backend startup diagnostic",
                (Path(directory) / "backend.log").read_text("utf-8"),
            )

    def test_existing_standard_streams_are_preserved(self):
        stdout, stderr = sys.stdout, sys.stderr
        launcher._prepare_stdio()
        self.assertIs(sys.stdout, stdout)
        self.assertIs(sys.stderr, stderr)
