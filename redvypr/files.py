import pkg_resources
import os
import sys
import logging

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('files')
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

# Get the logo pixmap of redvypr
# Until v 0.3.11
#logo_file = pkg_resources.resource_filename('redvypr','icon/redvypr_logo_v02.png')
# Desert Horned Viper
logo_file = pkg_resources.resource_filename('redvypr','icon/logo_v03.1.svg')
# This is a workaround to read the VERSION file in a pyinstaller environment in linux (redvypr exectuable and redvypr directory cannot life together)
if(os.path.exists(logo_file)):
    pass
else:
    logo_file = resource_path('redvypr_logo_v02.svg')
    if (os.path.exists(logo_file)):
        pass
    else:  # pyinstaller windows10
        logger.warning('Could not load logo file {}'.format(logo_file))
    
# Desert Horned Viper
icon_file = pkg_resources.resource_filename('redvypr','icon/icon_v03.1.svg')
# This is a workaround to read the VERSION file in a pyinstaller environment in linux (redvypr exectuable and redvypr directory cannot life together)
if(os.path.exists(icon_file)):
    pass
else:
    icon_file = resource_path('icon_v03.1.svg')
    if (os.path.exists(icon_file)):
        pass
    else:  # pyinstaller windows10
        logger.warning('Could not load icon file {}'.format(icon_file))



