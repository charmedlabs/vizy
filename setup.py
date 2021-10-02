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