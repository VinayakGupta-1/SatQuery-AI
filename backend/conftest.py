"""Makes the ``app`` package importable however pytest is invoked.

Without this, ``pytest`` only works when launched as ``python -m pytest`` from
the ``backend`` directory, because that is the one invocation that happens to
put the backend directory on ``sys.path``.

It also makes the suite hermetic. This file is imported before any test module
and therefore before ``app.config.settings``, which is the only point at which
the environment can still be controlled:

* ``backend/.env`` is never read. It typically holds a developer's real API
  key, and a test run that picks it up both stops testing the defaults and
  sends every pipeline test's query to a hosted model.
* Hosted-model credentials and provider choices exported in the shell are
  dropped for the same reason. Tests that need them set them explicitly.
* Automatic imagery fetching is off, so a request without files can never
  reach Planetary Computer or the geocoder. Acquisition tests turn it on and
  replace the network functions themselves.
* Storage points at a throwaway directory. Importing ``app.main`` builds the
  app, and building it purges old task files from the storage root -- which,
  left at its default, is the developer's real one.
"""

import os
import sys
import tempfile

BACKEND_ROOT = os.path.dirname(os.path.abspath(__file__))

if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

os.environ["SATQUERY_LOAD_DOTENV"] = "0"
for _name in list(os.environ):
    if _name.startswith(("SATQUERY_AGENT_", "SATQUERY_VQA_", "SATQUERY_FETCH_", "SATQUERY_GEOCODER_")):
        del os.environ[_name]
os.environ["SATQUERY_FETCH_ENABLED"] = "0"
os.environ["SATQUERY_STORAGE_ROOT"] = tempfile.mkdtemp(prefix="satquery-tests-")
