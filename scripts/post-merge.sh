#!/bin/bash
set -e

pip install -r requirements.txt --quiet --disable-pip-version-check 2>/dev/null || true

echo "Running anti-capture structure guard suite..."
pytest tests/test_structure_guard.py -q

echo "Post-merge setup complete."
