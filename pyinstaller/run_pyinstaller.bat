:: One file version
::pyinstaller --onefile -i ../redvypr/icon/icon_v03.3.ico --workpath ./build_windows --distpath ./dist_windows --noconfirm --add-data "../redvypr/VERSION;." --add-data "../redvypr/icon/*;." --hidden-import cftime --hidden-import netCDF4.utils  --clean -n redvypr redvypr_run.py

:: Standard version
pyinstaller -i ../redvypr/icon/icon_v03.3.ico --workpath ./build --distpath ./dist --noconfirm --add-data "../redvypr/VERSION;." --add-data "../redvypr/icon/*;." --hidden-import cftime --hidden-import netCDF4.utils  --clean -n redvypr redvypr_run.py

:: Windows 10 mkl_intel_thread.1.dll in anaconda/Library/bin has to be copied into the redvypr folder in dist
