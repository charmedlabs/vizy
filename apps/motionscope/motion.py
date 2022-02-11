#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#


class Motion:

    # Extract motion from split BGR input frame (frame_split) 
    # and split BGR background frame (bg_split) 
    def extract(self, frame_split, bg_split):
        pass

    # Threshold property, varies between 1 and 100
    @property
    def threshold(self):
        return self._threshold 

    @threshold.setter
    def threshold(self, _threshold):
        self._threshold = _threshold

