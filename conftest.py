"""conftest.py — make sure `import byou` works in pytest.

Pytest doesn't add the project root to sys.path by default when run
from a sub-directory.  This conftest lives at the project root
(by being in tests/ its parent) and fixes that.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path so `import byou` works in all test files
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
