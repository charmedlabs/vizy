#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

import cv2
from threading import Thread
from vizy import Vizy
import kritter
import time

class EdgeDetector:

    def __init__(self):
        self.threshold1 = 100
        self.threshold2 = 200
        camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = camera.stream()
        kapp = Vizy()

        self.video = kritter.Kvideo(width=camera.resolution[0])
        threshold1_slider = kritter.Kslider(name="threshold1", value=self.threshold1, mxs=(0, 255, 1))
        threshold1_slider.t0 = 0
        threshold2_slider = kritter.Kslider(name="threshold2", value=self.threshold2, mxs=(0, 255, 1))
        threshold2_slider.t0 = 0
        kapp.layout = [self.video, threshold1_slider, threshold2_slider]

        @threshold1_slider.callback()
        def func(val):
            self.threshold1 = val
            if self.threshold1>self.threshold2 and time.time()-threshold2_slider.t0>1:
                threshold1_slider.t0 = time.time()
                self.threshold2 = self.threshold1
                return threshold2_slider.out_value(self.threshold1)

        @threshold2_slider.callback()
        def func(val):
            self.threshold2 = val 
            if self.threshold2<self.threshold1 and time.time()-threshold1_slider.t0>1:
                threshold2_slider.t0 = time.time()
                self.threshold1 = self.threshold2
                return threshold1_slider.out_value(self.threshold2)

        self.run_loop = True
        thread = Thread(target=self.loop)
        thread.start()

        # Run Kritter server, which blocks.
        kapp.run()
        self.run_loop = False

    # Main processing thread
    def loop(self):
        while self.run_loop:
            # Get frame
            frame = self.stream.frame()[0]
            # Convert to grayscale
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # Create edge image
            edges = cv2.Canny(gray, self.threshold1, self.threshold2)
            # Display
            self.video.push_frame(edges)


if __name__ == '__main__':
    ed = EdgeDetector()
