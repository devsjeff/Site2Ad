"""`python -m app` starts the API server (same as `python -m app.cli serve`; extra options such as --port 9000 are passed on)."""

import sys

from .cli import main

if __name__ == "__main__":
    main(["serve", *sys.argv[1:]])
