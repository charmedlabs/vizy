#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

import os
from threading import Thread
import kritter
import cv2
import numpy as np
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy, MediaDisplayQueue
from kritter.ktextvisor import KtextVisor, KtextVisorTable, Image
import time

NOISE_FLOOR = 25*3
BINS = 100
COLUMN_THRESHOLD = 25
STATE_NONE = 0
STATE_OCCLUDED = 1
STATE_FULL = 2  
DATA_TIMEOUT = 20 
CAMERA_WIDTH = 768
BASEDIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(BASEDIR, "media")
CONFIG_FILE = "radar.json"

DEFAULT_CONFIG = {
    "brightness": 50,
    "detection_sensitivity": 75,
    "gphoto_upload": False,
}

class Video: 
    def __init__(self):
        # Create Kritter server.
        self.kapp = Vizy()
        config_filename = os.path.join(self.kapp.etcdir, CONFIG_FILE)      
        self.config = kritter.ConfigFile(config_filename, DEFAULT_CONFIG)               
        
        if not os.path.isdir(MEDIA_DIR):
            os.makedirs(MEDIA_DIR)
        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream(False)
        self.stream.load("/home/pi/vizy/etc/motionscope/car3/video.raw")
        self.pointing_right = True 
        
        style = {"label_width": 3, "control_width": 6}

        # Create video component and histogram enable.
        self.video = kritter.Kvideo(width=self.camera.resolution[0], overlay=True)
        self.media_queue = MediaDisplayQueue(MEDIA_DIR, CAMERA_WIDTH, CAMERA_WIDTH) 
        self.gcloud = kritter.Gcloud(self.kapp.etcdir)
        self.gphoto_interface = self.gcloud.get_interface("KstoreMedia")
        self.store_media = kritter.SaveMediaQueue(path=MEDIA_DIR)
        if self.config['gphoto_upload']:
            self.store_media.store_media = self.gphoto_interface 
        # Add video component and controls to layout.
        self.kapp.layout = html.Div([self.video, self.media_queue.layout], style={"padding": "15px"})

        # Run camera grab thread.
        self.run_grab = True
        Thread(target=self.grab).start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self.run_grab = False

    def handle_end(self, data, pic):
        if len(data[0]):
            A = np.vstack([data[1], np.ones(len(data[1]))]).T
            speed, _ = np.linalg.lstsq(A, data[0], rcond=None)[0]
            speed = abs(speed)
            print(speed)
            
            filename = os.path.join(MEDIA_DIR, kritter.time_stamped_file("jpg"))
            data = {"speed": speed, "width": pic.shape[1], "height": pic.shape[0]}
            cv2.imwrite(filename, pic)
            kritter.save_metadata(filename, data)
            self.kapp.push_mods(self.media_queue.out_images())

    # Frame grabbing thread
    def grab(self):        
        frame0 = None
        cols = None
        left_state = right_state = STATE_NONE
        left_pic = right_pic = None
        hist_cols = np.arange(0, BINS, dtype='uint') 
        while self.run_grab:
            # Get frame
            frame_orig = self.stream.frame()
            if frame_orig is None:
                self.stream.seek(0)
                frame0 = None
                left_state = right_state = STATE_NONE
                left_pic = right_pic = None
                continue
            
            frame = frame_orig[0]
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
                col_thresh = hist_cols[hist[0]>COLUMN_THRESHOLD]
                if len(col_thresh):
                    if col_thresh[-1]==BINS-1:
                        if right_state==STATE_FULL:
                            if right_pic is None:
                                right_pic = frame_prev[0].copy()
                            self.handle_end(right_data, right_pic)
                            right_state = left_state = STATE_NONE
                            left_pic = right_pic = None
                        elif left_state==STATE_NONE:
                            left_state = STATE_FULL 
                            left_data = [np.array([]), np.array([])]

                    if col_thresh[0]==0:
                        if left_state==STATE_FULL:
                            if left_pic is None:
                                left_pic = frame_prev[0].copy()
                            self.handle_end(left_data, left_pic)
                            left_state = right_state = STATE_NONE
                            left_pic = right_pic = None
                        elif right_state==STATE_NONE:
                            right_state = STATE_OCCLUDED
                            right_data = [np.array([]), np.array([])]
                    elif right_state==STATE_OCCLUDED:
                        right_state = STATE_FULL
                        right_pic = frame_prev[0].copy()

                    if left_state:
                        left_data[0] = np.append(left_data[0], col_thresh[0])
                        left_data[1] = np.append(left_data[1], frame_orig[1])
                        t = left_data[1][-1] -left_data[1][0]
                        if t>DATA_TIMEOUT:
                            left_state = STATE_NONE
                    if right_state:
                        right_data[0] = np.append(right_data[0], col_thresh[-1])
                        right_data[1] = np.append(right_data[1], frame_orig[1])
                        t = right_data[1][-1] -right_data[1][0]
                        if t>DATA_TIMEOUT:
                            right_data = STATE_NONE
                        

                #avg = np.average(th)
                #print(avg)
                #diff = np.where(diff>NOISE_FLOOR, 255, 0)
                #diff = diff.astype('uint8')
                self.video.push_frame(frame_orig)
            frame0 = frame.copy()
            frame_prev = frame_orig

if __name__ == "__main__":
    Video()
