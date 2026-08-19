#!/bin/bash
# FiBand - start the dashboard.
# Starts the Flask server FROM THE TERMINAL so it inherits Bluetooth permission.
# Double-click or: bash start.command
cd "$(dirname "$0")" || exit 1
echo "FiBand -> http://127.0.0.1:8080"
echo "(Ctrl+C to stop)"
.venv/bin/python app.py
