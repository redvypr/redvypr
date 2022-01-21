import pkg_resources
import os

# Get the logo pixmap of redvypr
logo_file = pkg_resources.resource_filename('redvypr','icon/redvypr_logo_v02.png')
# This is a workaround to read the VERSION file in a pyinstaller environment in linux (redvypr exectuable and redvypr directory cannot life together)
if(os.path.exists(logo_file)):
    pass
else:
    logo_file = 'redvypr_logo_v02.png'
    
# Get the logo pixmap of redvypr
icon_file = pkg_resources.resource_filename('redvypr','icon/icon_v02.png')
# This is a workaround to read the VERSION file in a pyinstaller environment in linux (redvypr exectuable and redvypr directory cannot life together)
if(os.path.exists(icon_file)):
    pass
else:
    icon_file = 'icon_v02.png'