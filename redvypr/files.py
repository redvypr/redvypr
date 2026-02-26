import os
import sys
import logging
from importlib import resources

# Setup logging
logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.files')
logger.setLevel(logging.INFO)


def get_resource_path(package, resource_name, subfolder=None):
    """
    Modern replacement for resource_filename.
    Handles installed packages, dev mode, and PyInstaller.
    """
    try:
        # 1. Try modern importlib.resources (Python 3.9+)
        traversable = resources.files(package)
        if subfolder:
            traversable = traversable.joinpath(subfolder)

        target_file = traversable.joinpath(resource_name)

        # Check if it exists within the package
        if target_file.exists():
            # as_file() ensures we have a real system path (extracts if necessary)
            with resources.as_file(target_file) as path:
                return str(path)

    except (FileNotFoundError, ModuleNotFoundError, TypeError, AttributeError):
        pass

    # 2. Fallback for PyInstaller / Manual bundling
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))

    # Check common locations:
    # - inside the subfolder in the bundle
    # - or flat in the root (how some PyInstaller setups handle it)
    search_paths = [
        os.path.join(base_path, package, subfolder or "", resource_name),
        os.path.join(base_path, subfolder or "", resource_name),
        os.path.join(base_path, resource_name)
    ]

    for path in search_paths:
        if os.path.exists(path):
            return path

    logger.warning(f'Could not load resource: {resource_name}')
    return ""


# --- Usage ---

# 1. Get the Logo
logo_file = get_resource_path('redvypr', 'logo_v03.1.svg', subfolder='icon')

# 2. Get the Icon
icon_file = get_resource_path('redvypr', 'icon_v03.3.svg', subfolder='icon')
