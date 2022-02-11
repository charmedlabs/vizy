#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

class DataUpdate:
    def __init__(self, data):
        self.data = data
        self.data_update_callback_func = None

    # cmem allows the retention of call information to prevent infinite loops,
    # feed forward call information, etc.
    def data_update(self, changed, cmem=None):
        return []

    def call_data_update_callback(self, changed, cmem=None):
        if self.data_update_callback_func:
            return self.data_update_callback_func(changed, cmem)

    def data_update_callback(self, func):
        self.data_update_callback_func = func
