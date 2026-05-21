# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Entry point: python -m opentrace.daemon"""

import logging

from opentrace.daemon.config import DaemonConfig
from opentrace.daemon.main import Daemon


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    config = DaemonConfig()
    daemon = Daemon(config)
    daemon.run()


if __name__ == "__main__":
    main()
