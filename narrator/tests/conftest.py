import os
import sys
from pathlib import Path

# Make the narrator package importable when running `pytest` from narrator/.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Ensure the shipped policy is what we test (no env overrides leaking in).
for var in ("NTFY_SERVER", "NTFY_TOPIC", "NTFY_TOKEN", "ARGUS_SITE",
            "PROMETHEUS_URL", "PEER_NARRATOR_URL", "WATCHDOG_DEADLINE_SECONDS",
            "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENROUTER_BASE_URL", "LLM_ENABLED"):
    os.environ.pop(var, None)

import pytest  # noqa: E402

from narrator import config as configmod  # noqa: E402


CONFIG_PATH = ROOT / "config" / "narrator.yml"


@pytest.fixture
def cfg():
    return configmod.load(str(CONFIG_PATH))
