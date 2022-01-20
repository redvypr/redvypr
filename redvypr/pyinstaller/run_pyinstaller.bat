pyinstaller --noconfirm --add-data "../VERSION;." --add-data "../icon/*;." --clean -n redvypr --hidden-import cftime redvypr_run.py

# Windows 10 mkl_intel_thread.1.dll in anaconda/Library/bin has to be copied into the redvypr folder in dist
