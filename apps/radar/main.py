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
import datetime
import kritter
import cv2
import numpy as np
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy, MediaDisplayQueue
from kritter.ktextvisor import KtextVisor, KtextVisorTable, Image
import time
from PIL import Image, ImageDraw, ImageFont

NOISE_FLOOR = 25*3
BINS = 100
BIN_THRESHOLD = 25
DATA_TIMEOUT = 20 # seconds
SPEED_DISPLAY_TIMEOUT = 3 # seconds
CAMERA_WIDTH = 768
BASEDIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(BASEDIR, "media")
CONFIG_FILE = "radar.json"
DEFAULT_CALIBRATION = 0.33 # MPH*seconds/bins
KM_PER_MILE = 1.60934
FONT_SIZE = 60 
FONT_COLOR = (0, 255, 0)
STATE_NONE = 0
STATE_OCCLUDED = 1
STATE_FULL = 2  

DEFAULT_CONFIG = {
    "brightness": 50,
    "detection_sensitivity": 75,
    "kph": False, 
    "gphoto_upload": False,
    "left_pointing": False, 
    "left_calibration": None, # left moving, MPH
    "right_calibration": None # right moving, MPH
}

class Video: 
    def __init__(self):
        # Create Kritter server.
        self.kapp = Vizy()
        config_filename = os.path.join(self.kapp.etcdir, CONFIG_FILE)      
        self.config = kritter.ConfigFile(config_filename, DEFAULT_CONFIG)               
        self.font = ImageFont.truetype(os.path.join(BASEDIR, "font.ttf"), FONT_SIZE)        
        if not os.path.isdir(MEDIA_DIR):
            os.makedirs(MEDIA_DIR)
        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream(False)
        self.stream.load("/home/pi/vizy/etc/motionscope/car1/video.raw")
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
        
    def _timestamp(self):
        return datetime.datetime.now().strftime("%D %H:%M:%S")

    def handle_end(self, data, pic, left):
        if len(data[0]):
            # Take all of the data and fit to a line.  This will give us the most likely speed given noise, 
            # that is, erroneous data is drown out by valid data. 
            A = np.vstack([data[1], np.ones(len(data[1]))]).T
            speed, _ = np.linalg.lstsq(A, data[0], rcond=None)[0]
            speed = abs(speed)
            # Choose calibration based on direction of travel
            if left:
                calibration = self.config["left_calibration"] or self.config["right_calibration"] or DEFAULT_CALIBRATION
            else: # moving right
                calibration = self.config["right_calibration"] or self.config["left_calibration"] or DEFAULT_CALIBRATION
            speed *= calibration
            if self.config["kph"]:
                speed *= KM_PER_MILE
                
            filename_ = kritter.time_stamped_file("jpg")
            filename = os.path.join(MEDIA_DIR, filename_)
            data = {"speed": speed, "left_moving": left, "left_pointing": self.config["left_pointing"], "timestamp": self._timestamp(), "width": pic.shape[1], "height": pic.shape[0]}
            cv2.imwrite(filename+"_", pic) # write image without speed overlay
            img = Image.fromarray(pic, "RGB")
            drw = ImageDraw.Draw(img)
            drw.text((0, 0), f'{round(speed)} {"kph" if self.config["kph"] else "mph"}', fill=FONT_COLOR, font=self.font)
            pic = np.asarray(img)
            cv2.imwrite(filename, pic) # write image with speed overlay
            kritter.save_metadata(filename, data)
            self.kapp.push_mods(self.media_queue.out_images())
            return speed

    # Frame grabbing thread
    def grab(self):  
        speed_disp = None
        frame0 = None
        cols = None
        left_state = right_state = STATE_NONE
        left_pic = right_pic = None
        hist_cols = np.arange(0, BINS, dtype='uint')
        last_timestamp = None
        while self.run_grab:
            mods = []
            # Get frame
            frame_orig = self.stream.frame()
            if frame_orig is None:
                self.stream.seek(0)
                frame0 = None
                # left_state, left_pic is motion to left
                # right_state, right_pic is motion to right
                left_state = right_state = STATE_NONE
                left_pic = right_pic = None
                speed_disp = None
                continue

            timestamp = self._timestamp()
            if timestamp!=last_timestamp:
                self.video.overlay.draw_clear()
                self.video.overlay.draw_text(0, frame_orig[0].shape[0]-1, timestamp, fillcolor="black", font=dict(family="sans-serif", size=12, color="white"), xanchor="left", yanchor="bottom")
                mods += self.video.overlay.out_draw()
                last_timestamp = timestamp

            
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
                # Try to get rid of noise by thresholding
                th = diff>NOISE_FLOOR
                # Take the thresholded pixels and associate with column values
                th = cols[th]
                # Create a "histogram of motion".  We're essentially taking the image and dividing it into BINS 
                # number of columns.
                hist = np.histogram(th, BINS, (0, diff.shape[1]-1))
                # Further threshold the columns to eliminate columns that don't have "significant data".
                col_thresh = hist_cols[hist[0]>BIN_THRESHOLD]
                # The rest of the code will look at the first (leftmost) column of motion (col_thresh[0]) and the 
                # last (rightmost) column of motion (col_threshj[1]).  
                # If we see motion of col_thresh[0], start recording data in to right_data (right-moving object data).
                # Stop recording when we see motion on col_thresh[BINS-1]
                # If we see motion of col_thresh[BINS-1], start recording data in to left_data (left-moving object data).
                # Stop recording when we see motion on col_thresh[0]
                if len(col_thresh):
                    if col_thresh[-1]==BINS-1:
                        if right_state==STATE_FULL:
                            if right_pic is None:
                                right_pic = frame_prev[0].copy()
                            speed = self.handle_end(right_data, right_pic, False)
                            if speed: 
                                speed_disp = speed, time.time()
                            right_state = left_state = STATE_NONE
                            left_pic = right_pic = None
                        elif left_state==STATE_NONE:
                            left_state = STATE_FULL 
                            left_data = [np.array([]), np.array([])]

                    if col_thresh[0]==0:
                        if left_state==STATE_FULL:
                            if left_pic is None:
                                left_pic = frame_prev[0].copy()
                            speed = self.handle_end(left_data, left_pic, True)
                            if speed:
                                speed = speed
                                speed_disp = speed, time.time()
                            left_state = right_state = STATE_NONE
                            left_pic = right_pic = None
                        elif right_state==STATE_NONE:
                            right_state = STATE_OCCLUDED
                            right_data = [np.array([]), np.array([])]
                    elif right_state==STATE_OCCLUDED:
                        right_state = STATE_FULL
                        right_pic = frame_prev[0].copy()

                    if left_state:
                        # Add column data
                        left_data[0] = np.append(left_data[0], col_thresh[0])
                        # Add timestamp data
                        left_data[1] = np.append(left_data[1], frame_orig[1])
                        t = left_data[1][-1] -left_data[1][0]
                        if t>DATA_TIMEOUT:
                            left_state = STATE_NONE
                    if right_state:
                        # Add column data
                        right_data[0] = np.append(right_data[0], col_thresh[-1])
                        # Add timestamp data
                        right_data[1] = np.append(right_data[1], frame_orig[1])
                        t = right_data[1][-1] -right_data[1][0]
                        if t>DATA_TIMEOUT:
                            right_data = STATE_NONE
                        
                if speed_disp is None:
                    self.video.push_frame(frame_orig)
                else: # overlay speed ontop of video 
                    img = Image.fromarray(frame_orig[0], "RGB")
                    drw = ImageDraw.Draw(img)
                    drw.text((0, 0), f'{round(speed_disp[0])} {"kph" if self.config["kph"] else "mph"}', fill=FONT_COLOR, font=self.font)
                    speed_frame = np.asarray(img)
                    self.video.push_frame(speed_frame)
                    if time.time()-speed_disp[1]>SPEED_DISPLAY_TIMEOUT:
                        speed_disp = None 
                        
            frame0 = frame.copy()
            frame_prev = frame_orig
            self.kapp.push_mods(mods)
            
if __name__ == "__main__":
    Video()
