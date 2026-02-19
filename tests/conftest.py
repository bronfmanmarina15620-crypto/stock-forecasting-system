"""Ensure project root is on sys.path for test imports."""
import sys
import os

# Add project root so `import determinism` works without triggering
# the root __init__.py's relative imports.
_root = os.path.dirname(os.path.dirname(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)
