#!/usr/bin/env bash
set -euo pipefail

exec "$(git -C "$(dirname "$0")/../../.." rev-parse --show-toplevel)/poc/port_tariff_agent/run.sh"
