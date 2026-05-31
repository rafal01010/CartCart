#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

"${SCRIPT_DIR}/start-backend.sh"
"${SCRIPT_DIR}/start-frontend.sh"

echo "CartCart local app started."
