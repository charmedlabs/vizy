import numpy as np 
import cv2 
from motion import Motion
from kritter import Range
    

class SimpleMotion(Motion):

    def __init__(self):
    	# Range maps one range to another range -- in this case from 1 to 100 to 
    	# 1*3 to 50*3.  
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
