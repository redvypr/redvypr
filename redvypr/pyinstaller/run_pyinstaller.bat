:: One file version
pyinstaller --onefile -i ../icon/icon_v03.2.ico --workpath ./build_windows --distpath ./dist_windows --noconfirm --add-data "../VERSION;." --add-data "../icon/*;." --hidden-import cftime --hidden-import netCDF4.utils  --clean -n redvypr redvypr_run.py

:: Windows 10 mkl_intel_thread.1.dll in anaconda/Library/bin has to be copied into the redvypr folder in dist
