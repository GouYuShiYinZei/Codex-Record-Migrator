from __future__ import annotations

import sys

from .app import run
from .cli import main as cli_main


def main() -> int:
    if len(sys.argv) > 1:
        return cli_main(sys.argv[1:])
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
