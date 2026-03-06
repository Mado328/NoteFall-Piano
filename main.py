"""
Grand Piano — entry point.

All application logic lives in :class:`piano.app.Application`.
This file is intentionally minimal.
"""

import sys
from piano.app import Application


def main() -> None:
    app = Application()
    app.run()
    sys.exit(0)


if __name__ == "__main__":
    main()
