#!/bin/sh
# Run the add-on tests in background Blender. BLENDER env var overrides the path.
BLENDER="${BLENDER:-blender}"
exec "$BLENDER" -b --factory-startup --python "$(dirname "$0")/../addon/tests/run.py"
