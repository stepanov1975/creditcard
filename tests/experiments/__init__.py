import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
__path__.append(str(_PROJECT_ROOT / "experiments"))
