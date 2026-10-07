"""Import this first in every test module.

Points swimform at a throwaway config directory and removes any Gemini key
from the environment, so a test run can never read your real settings, write
into your real overlays folder, or spend your quota by accident.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HOME = tempfile.mkdtemp(prefix="swimform-test-")
os.environ["SWIMFORM_HOME"] = HOME
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("SWIMFORM_GEMINI_BASE", None)
atexit.register(shutil.rmtree, HOME, ignore_errors=True)
