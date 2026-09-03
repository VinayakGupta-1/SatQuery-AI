"""Makes the ``app`` package importable however pytest is invoked.

Without this, ``pytest`` only works when launched as ``python -m pytest`` from
the ``backend`` directory, because that is the one invocation that happens to
put the backend directory on ``sys.path``.
"""

import os
import sys

BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))

if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)
