""" Utility to have the version in redvypr available
"""
import os
import sys
import logging
from importlib import resources  # Modern replacement for pkg_resources

# Setup logging
logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.version')
logger.setLevel(logging.INFO)


def get_version():
    """
    Get the version of redvypr.
    Works for installed packages, development mode, and PyInstaller.
    """
    # 1. Primary Method: Use importlib.resources (Modern Python 3.9+)
    try:
        # This looks inside the 'redvypr' package for a file named 'VERSION'
        with resources.files('redvypr').joinpath('VERSION').open('r') as f:
            return f.read().strip()
    except (FileNotFoundError, ModuleNotFoundError, TypeError, AttributeError):
        # Fallback for older Python versions or specific PyInstaller edge cases
        logger.debug("importlib.resources failed, trying manual path resolution")

    # 2. Fallback: Manual path (PyInstaller / Local Dev)
    # PyInstaller sets sys._MEIPASS when running as a bundled executable
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))

    # Try different possible locations for the VERSION file
    possible_paths = [
        os.path.join(base_path, 'redvypr', 'VERSION'),  # Package structure
        os.path.join(base_path, 'VERSION')  # Flat structure/PyInstaller root
    ]

    for path in possible_paths:
        if os.path.exists(path):
            logger.debug(f'Opening version file at {path}')
            try:
                with open(path, 'r') as f:
                    return f.read().strip()
            except Exception as e:
                logger.debug(f"Could not read {path}: {e}")

    logger.warning('Could not locate VERSION file in any known location.')
    return "unknown"


# Define the version variable for other modules to import
version = get_version()

if __name__ == "__main__":
    print(f"redvypr version: {version}")


