#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

import numpy as np 
import cv2 
from motion import Motion
from kritter import Range
    
# This class does reasonably well with symmetrical(ish) objects as they 
# move against the background.  If you wanted to track the motion of a 
# trebuchet (for example) you'd want to use other visual clues (hue? structure?) 
# to extract the motion of the munition only as it's being fired and gaining speed.
class SimpleMotion(Motion):

    def __init__(self):
    	# Range maps one range to another range -- in this case from 1 to 100 
        # which is user-friendly compared to 1*3 to 50*3, which makes sense for our threshold code.  
        self.threshold_range = Range((1, 100), (1*3, 50*3), outval=20*3) 

    def extract(self, frame_split, bg_split):
        diff = np.zeros(frame_split[0].shape, dtype="uint16")

        # Compute absolute difference with background frame
        for i in range(3):
            diff += cv2.absdiff(bg_split[i], frame_split[i])

        # Threshold motion
        motion = diff>self.threshold_range.outval
        motion = motion.astype("uint8")            

        # Clean up
        motion = cv2.erode(motion, None, iterations=4)
        motion = cv2.dilate(motion, None, iterations=4) 

        return motion

    @property
    def threshold(self):
        return self.threshold_range.inval 

    @threshold.setter
    def threshold(self, _threshold):
        self.threshold_range.inval = _threshold
