""" Utility to have the version in redvypr available
"""
import pkg_resources
import os
import sys
import logging

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.version')
logger.setLevel(logging.INFO)

#https://stackoverflow.com/questions/7674790/bundling-data-files-with-pyinstaller-onefile/13790741#13790741
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# Get the version of redvypr
_version_file = pkg_resources.resource_filename('redvypr','VERSION')

# This is a workaround to read the VERSION file in a pyinstaller environment in linux (redvypr exectuable and redvypr directory cannot life together)
if(os.path.exists(_version_file)):
    pass
else:
    _version_file = resource_path('VERSION')
    if (os.path.exists(_version_file)):
        pass
    else: # pyinstaller windows10
        logger.warning('Could not load version file {}'.format(_version_file))

logger.debug('Opening version file {}'.format(_version_file))
with open(_version_file) as _version_f:
   version = _version_f.read().strip()

_version_f.close()
