#!/bin/sh
# Use the system Python, which has PyGObject + GTK4 + libadwaita.
cd "$(dirname "$0")" && exec /usr/bin/python3 -m stocks "$@"
