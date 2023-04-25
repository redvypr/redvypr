from setuptools import setup, find_packages
import os

ROOT_DIR='redvypr'
with open(os.path.join(ROOT_DIR, 'VERSION')) as version_file:
    version = version_file.read().strip()

# read the contents of your README file
#this_directory = os.path.abspath(os.path.dirname(__file__))
#with open(os.path.join(this_directory, 'README.md'), encoding='utf-8') as f:
#    long_description = f.read()    

setup(name='redvypr',
      version=version,
      description='redvypr: REaltime Data Viewer and PRocessor (in PYthon)',
      long_description='redvypr: REaltime Data Viewer and PRocessor (in PYthon). Python based software to read, process, fuse, distribute, save and visualize data from various sensors.',
      long_description_content_type="text/x-rst",
      url='https://github.com/redvypr/redvypr',
      author='Peter Holtermann',
      author_email='peter.holtermann@io-warnemuende.de',
      license='GPLv03',
      #packages=['redvypr'],
      packages=find_packages(),
      scripts = [],
      entry_points={ 'console_scripts': ['redvypr=redvypr:redvypr_main']},
      package_data = {'':['VERSION','icon/*','utils/csv2dict/*.yaml']},
      install_requires=[ 'pyaml', 'pyqtgraph','netCDF4', 'pyqtconsole', 'pyserial','qtawesome'],
      classifiers=[
        'Development Status :: 4 - Beta',
        'Topic :: Scientific/Engineering',          
        'Intended Audience :: Science/Research',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',  
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3 :: Only',
      ],
      python_requires='>=3.5',
      zip_safe=False)
