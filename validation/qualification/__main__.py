"""Run the Model Qualification Harness as a module: `py -3 -m validation.qualification`."""

from __future__ import annotations

import sys

from validation.qualification.cli import main


if __name__ == "__main__":
    sys.exit(main())
