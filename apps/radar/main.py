#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

from threading import Thread
import kritter
import cv2
import numpy as np
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy, Perspective
from kritter.ktextvisor import KtextVisor, KtextVisorTable, Image
import time

NOISE_FLOOR = 25*3
BINS = 100
COLUMN_THRESHOLD = 25
STATE_NONE = 0 
STATE_DET = 1  
STATE_TIMEOUT = 5 

class Video: 
    def __init__(self):
        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream(False)
        self.stream.load("/home/pi/vizy/etc/motionscope/car4/video.raw")

        # Create Kritter server.
        kapp = Vizy()
        style = {"label_width": 3, "control_width": 6}

        # Create video component and histogram enable.
        self.video = kritter.Kvideo(width=self.camera.resolution[0], overlay=True)
        # Add video component and controls to layout.
        kapp.layout = html.Div([self.video], style={"padding": "15px"})

        # Run camera grab thread.
        self.run_grab = True
        Thread(target=self.grab).start()

        # Run Kritter server, which blocks.
        kapp.run()
        self.run_grab = False


    # Frame grabbing thread
    def grab(self):        
        frame0 = None
        cols = None
        hist_cols = None
        state = STATE_NONE
        while self.run_grab:
            # Get frame
            frame = self.stream.frame()
            if frame is None:
                self.stream.seek(0)
                frame0 = None
                state = STATE_NONE
                continue
            frame = frame[0]
            if cols is None:
                r = np.arange(0, frame.shape[1], dtype='uint')
                cols = np.atleast_2d(r).repeat(repeats=frame.shape[0], axis=0)
            frame = cv2.split(frame)
            if frame0:
                diff = 0
                # Take diffence of all 3 color channels
                for i in range(3):
                    diff += cv2.absdiff(frame[i], frame0[i])
                # Send frame
                #diff = np.clip(diff, 0, 255)
                th = diff>NOISE_FLOOR
                #print(th.sum())
                th = cols[th]
                hist = np.histogram(th, BINS, (0, diff.shape[1]-1))
                if hist_cols is None:
                    hist_cols = np.arange(0, BINS, dtype='uint') 
                col_thresh = hist_cols[hist[0]>COLUMN_THRESHOLD]
                if len(col_thresh):
                    print(col_thresh[0], col_thresh[-1])
                    if state==STATE_NONE:
                        state = STATE_DET
                        print("Detect!")
                    state_timer = 0
                else: 
                    if state==STATE_DET:
                        state_timer += 1 
                        if state_timer==STATE_TIMEOUT:
                            print("None!")
                            state = STATE_NONE 
                #avg = np.average(th)
                #print(avg)
                diff = np.where(diff>NOISE_FLOOR, 255, 0)
                diff = diff.astype('uint8')
                self.video.push_frame(diff)
            #time.sleep(0.2)
            frame0 = frame.copy()

if __name__ == "__main__":
    Video()
