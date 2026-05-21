# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Sagar Sarkale

"""Allow running the server with `python -m opentrace.server`."""

from opentrace.server.app import run_server

if __name__ == "__main__":
    run_server()
