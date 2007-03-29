######################################################################
##
## Copyright (C) 2006,  Varun Hiremath <varunhiremath@gmail.com>
##
## Filename:      setup.py
## Author:        Varun Hiremath <varunhiremath@gmail.com>
## Description:   Installation script
## License:       GPL
######################################################################

import os, sys
from distutils.core import setup

PROGRAM_NAME = "flickrfs"
PROGRAM_VERSION = "1.3.9"
PROGRAM_URL = "http://manishrjain.googlepages.com/flickrfs"

setup(name='%s' % (PROGRAM_NAME).lower(),
      version='%s' % (PROGRAM_VERSION),
      description="virtual filesystem for flickr online photosharing service",
      author="Manish Rai Jain",
      license='GPL-2',
      url="%s" % (PROGRAM_URL),
      author_email=" <manishrjain@gmail.com>",
      packages = ['flickrfs'])
