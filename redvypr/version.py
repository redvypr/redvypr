""" Utility to have the version in redvypr available
"""
import pkg_resources
import os

# Get the version of redvypr
_version_file = pkg_resources.resource_filename('redvypr','VERSION')
# This is a workaround to read the VERSION file in a pyinstaller environment in linux (redvypr exectuable and redvypr directory cannot life together)
if(os.path.exists(_version_file)):
    pass
else:
    _version_file = 'VERSION'
with open(_version_file) as _version_f:
   version = _version_f.read().strip()

_version_f.close()
