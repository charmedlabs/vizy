#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

from kritter import Kritter
from dataupdate import DataUpdate

class Tab(DataUpdate):
    def __init__(self, name, data, kapp=None):
        super().__init__(data)
        self.name = name
        self.kapp = kapp if kapp else Kritter.kapp
        self.focused = False

    def frame(self):
        return None

    def focus(self, state):
        self.focused = state
        return []

    def reset(self):
        return []