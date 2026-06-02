"""Allow `python -m agent ...` as an alias for the `smkit` CLI."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
