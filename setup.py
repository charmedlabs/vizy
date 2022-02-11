#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

from setuptools import setup
import os


about = {}
with open(os.path.join("src/vizy", "about.py"), encoding="utf-8") as fp:
    exec(fp.read(), about)

#depencencies
#kritter
#wiringpi

setup(
    name=about['__title__'],
    version=about['__version__'],
    author=about['__author__'],
    author_email=about['__email__'], 
    license=about['__license__'],
    package_dir={"": "src"},
    packages=["vizy"],
    package_data = {"": ['*.jpg'], "vizy": ["media/*", "login/*"]},
    zip_safe=False    
    )