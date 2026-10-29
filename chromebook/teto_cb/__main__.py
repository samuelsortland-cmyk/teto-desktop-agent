import os
import sys

# Teto for Chromebook reuses Teto's brain and tab tools from the main package.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from teto_cb.app import main  # noqa: E402

main()
