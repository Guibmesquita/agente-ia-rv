#!/bin/bash
set -e

pip install -r requirements.txt --quiet --disable-pip-version-check 2>/dev/null || true

echo "Post-merge setup complete."
