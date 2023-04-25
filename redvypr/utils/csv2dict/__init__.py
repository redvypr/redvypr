from .csv2dict import *
import pkg_resources

# Get the version
version_file = pkg_resources.resource_filename('csv2dict','VERSION')

with open(version_file) as version_f:
   __version__ = version_f.read().strip()

