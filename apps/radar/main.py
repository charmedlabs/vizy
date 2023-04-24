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
import dash_core_components as dcc
import plotly.graph_objs as go


NOISE_FLOOR = 25*3
BINS = 100
DATA_TIMEOUT = 10 # seconds
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
MINIMUM_DATA = 5
SHUTTER_SPEED = 0.001
FRAME_QUEUE_LENGTH = 15

DEFAULT_CONFIG = {
    "brightness": 50,
    "sensitivity": 50,
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
        self.camera.autoshutter = False
        self.camera.shutter_speed = SHUTTER_SPEED
        self.stream = self.camera.stream() #(False)
        #self.stream.load("/home/pi/vizy/etc/motionscope/car3/video.raw")
        self.pointing_right = True 

        self.sensitivity_range = kritter.Range((1, 100), (200, 25), inval=self.config['sensitivity']) 
        self.bin_threshold = self.sensitivity_range.outval

        style = {"label_width": 2, "control_width": 4}
        self.video = kritter.Kvideo(width=self.camera.resolution[0], overlay=True)
        self.media_queue = MediaDisplayQueue(MEDIA_DIR, CAMERA_WIDTH, CAMERA_WIDTH) 
        self.brightness = kritter.Kslider(name="Brightness", value=self.camera.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style=style)
        self.sensitivity = kritter.Kslider(name="Sensitivity", value=self.config['sensitivity'], mxs=(1, 100, 1), format=lambda val: f'{int(val)}%', style=style)
        self.gcloud = kritter.Gcloud(self.kapp.etcdir)
        self.gphoto_interface = self.gcloud.get_interface("KstoreMedia")
        self.store_media = kritter.SaveMediaQueue(path=MEDIA_DIR)
        if self.config['gphoto_upload']:
            self.store_media.store_media = self.gphoto_interface 
        self.calib_text = kritter.KtextBox(name="Speed", style={"control_width": 3}, grid=False, service=None)
        self.calib_button = kritter.Kbutton(name=[self.kapp.icon("calculator"), "Calibrate"], service=None)
        self.calib_dialog = kritter.Kdialog(title=[self.kapp.icon("calculator"), "Calibrate speed"], left_footer=self.calib_button, layout=[self.calib_text])
        
        self.graph_layout = dict(title="Data points", 
            yaxis=dict(zeroline=False, title="Horizontal movement"),
            xaxis=dict(zeroline=False, title='Time (seconds)'),
            showlegend=False,
            width=CAMERA_WIDTH, 
            height=int(CAMERA_WIDTH*3/4), 
        )

        self.graph = dcc.Graph(style={"display": "none"}, id=self.kapp.new_id())
        self.kapp.layout = html.Div([self.video, self.media_queue.layout, self.brightness, self.sensitivity, self.graph, self.calib_dialog], style={"padding": "15px"})

        self.kapp.push_mods(self.media_queue.out_images())
        
        @self.brightness.callback()
        def func(value):
            self.config['brightness'] = value
            self.camera.brightness = value
            self.config.save()

        @self.sensitivity.callback()
        def func(value):
            self.config['sensitivity'] = value
            self.sensitivity_range.inval = value
            print(self.bin_threshold)
            self.bin_threshold = self.sensitivity_range.outval
            print(value, self.bin_threshold)
            self.config.save()

        @self.media_queue.dialog_image_callback()
        def func(src, srcpath):
            self.calib_info = srcpath, kritter.load_metadata(srcpath)
            return self.calib_dialog.out_open(True)
        
        @self.calib_button.callback(self.calib_text.state_value())
        def func(speed):
            try:
                speed = float(''.join(filter(str.isdigit, speed))) # convert to float, remove all non-numeric characters
                srcpath, data = self.calib_info
                calibration = speed/data['speed_raw']
                if data['left_moving']:
                    self.config['left_calibration'] = calibration
                    if self.config['right_calibration'] is None:
                        self.config['right_calibration'] = calibration
                else:
                    self.config['right_calibration'] = calibration
                    if self.config['left_calibration'] is None:
                        self.config['left_calibration'] = calibration
                self.config.save()    
                data['speed'] = speed
                kritter.save_metadata(srcpath, data)
                pic = cv2.imread(srcpath+"_")
                pic = self._overlay_speed(pic, speed)
                srcpath = kritter.update_time_stamped_file(srcpath)
                self.calib_info = srcpath, kritter.load_metadata(srcpath)
                cv2.imwrite(srcpath, pic)
                return self.media_queue.dialog_image.out_src(os.path.basename(srcpath)) + self.media_queue.out_images() + self.calib_dialog.out_open(False) + self.calib_text.out_value("")
            except Exception as e:
                print(e)
            
        # Run camera grab thread.
        self.run_grab = True
        Thread(target=self.grab).start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self.run_grab = False
        
    def _timestamp(self):
        return datetime.datetime.now().strftime("%D %H:%M:%S")

    def _overlay_speed(self, image, speed):
        image = Image.fromarray(image, "RGB")
        drawing = ImageDraw.Draw(image)
        drawing.text((0, 0), f'{round(speed)} {"kph" if self.config["kph"] else "mph"}', fill=FONT_COLOR, font=self.font)
        return np.asarray(image)
    
    def handle_end(self, data, pic, left):
        data_y, data_time = data
        # deal with minimum data and left motion that looks like it's going right and right motion that looks like it's going left
        if len(data_y)<MINIMUM_DATA or (left and data_y[0]-data_y[-1]<0) or (not left and data_y[0]-data_y[-1]>0):
            return None
        # Take all of the data and fit to a line.  This will give us the most likely speed given noise, 
        # that is, erroneous data is drown out by valid data. 
        A = np.vstack([data_time, np.ones(len(data_time))]).T
        result = np.linalg.lstsq(A, data_y, rcond=None)
        m, b = result[0]
        residual = result[1]
        print("residual", residual)
        speed_raw = abs(m)
        # Choose calibration based on direction of travel
        if left:
            calibration = self.config["left_calibration"] or self.config["right_calibration"] or DEFAULT_CALIBRATION
        else: # moving right
            calibration = self.config["right_calibration"] or self.config["left_calibration"] or DEFAULT_CALIBRATION
        speed = speed_raw*calibration
        if self.config["kph"]:
            speed *= KM_PER_MILE
            
        filename_ = kritter.time_stamped_file("jpg")
        filename = os.path.join(MEDIA_DIR, filename_)
        metadata = {"speed": speed, "speed_raw": speed_raw, "left_moving": left, "left_pointing": self.config["left_pointing"], "timestamp": self._timestamp(), "data": [list(data_time), list(data_y)], "width": pic.shape[1], "height": pic.shape[0]}
        cv2.imwrite(filename+"_", pic) # write image without speed overlay
        pic = self._overlay_speed(pic, speed)
        cv2.imwrite(filename, pic) # write image with speed overlay
        kritter.save_metadata(filename, metadata)
        self.kapp.push_mods(self.media_queue.out_images())
        figure = go.Figure(data=[go.Scatter(x=data_time, y=data_y, mode='lines+markers'), go.Scatter(x=[data_time[0], data_time[-1]], y=[m*data_time[0]+b, m*data_time[-1]+b])], layout=self.graph_layout)
        #self.graph = dcc.Graph(figure=figure)
        self.kapp.push_mods([Output(self.graph.id, "style", {"display": "block"}), Output(self.graph.id, "figure", figure)])
        return speed

    # Frame grabbing thread
    def grab(self):  
        speed_disp = None
        cols = None
        left_state = right_state = STATE_NONE
        left_pic = right_pic = None
        hist_cols = np.arange(0, BINS, dtype='uint')
        last_timestamp = None
        frame_queue = []
        while self.run_grab:
            mods = []
            # Get frame
            frame_orig = self.stream.frame()
            if 0: #frame_orig is None:
                self.stream.seek(0)
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
            if len(frame_queue)>=FRAME_QUEUE_LENGTH:
                frame0 = cv2.split(frame_queue[-1][0])
                try:
                    diff = 0
                    # Take diffence of all 3 color channels
                    for i in range(3):
                        diff += cv2.absdiff(frame[i], frame0[i])
                    # Detect motion by thresholding just above the noise of the image.
                    th = diff>NOISE_FLOOR
                    # Take the thresholded pixels and associate with column values
                    th = cols[th]
                    # Create a "histogram of motion".  We're essentially taking the image and dividing it into BINS 
                    # number of columns.
                    hist = np.histogram(th, BINS, (0, diff.shape[1]-1))
                    # Further threshold the columns to eliminate columns that don't have "significant data".
                    col_thresh = hist_cols[hist[0]>self.bin_threshold]
                    # The rest of the code will look at the first (leftmost) column of motion (col_thresh[0]) and the 
                    # last (rightmost) column of motion (col_threshj[-1]).  
                    # If we see motion of col_thresh[0], start recording data in to right_data (right-moving object data).
                    # Stop recording when we see motion on col_thresh[BINS-1]
                    # If we see motion of col_thresh[BINS-1], start recording data in to left_data (left-moving object data).
                    # Stop recording when we see motion on col_thresh[0]
                    if len(col_thresh):
                        if self.config['left_pointing']:
                            if col_thresh[-1]==BINS-1:
                                if right_state==STATE_FULL:
                                    if right_pic is None:
                                        right_pic = frame_queue[0][0].copy()
                                    speed = self.handle_end(right_data, right_pic, False)
                                    if speed: 
                                        speed_disp = speed, time.time()
                                    right_state = left_state = STATE_NONE
                                    left_pic = right_pic = None
                                elif left_state==STATE_NONE:
                                    left_state = STATE_OCCLUDED 
                                    left_data = [np.array([]), np.array([])]
                            elif left_state==STATE_OCCLUDED:
                                left_state = STATE_FULL
                                left_pic = frame_queue[0][0].copy()
    
                            if col_thresh[0]==0:
                                if left_state==STATE_FULL:
                                    if left_pic is None:
                                        left_pic = frame_queue[0][-1].copy()
                                    speed = self.handle_end(left_data, left_pic, True)
                                    if speed:
                                        speed_disp = speed, time.time()
                                    left_state = right_state = STATE_NONE
                                    left_pic = right_pic = None
                                elif right_state==STATE_NONE:
                                    right_state = STATE_FULL
                                    right_data = [np.array([]), np.array([])]
                        else: # right pointing
                            if col_thresh[-1]==BINS-1:
                                print("right col")
                                if right_state==STATE_FULL:
                                    if right_pic is None:
                                        right_pic = frame_queue[0][-1].copy()
                                    speed = self.handle_end(right_data, right_pic, False)
                                    if speed: 
                                        speed_disp = speed, time.time()
                                    right_state = left_state = STATE_NONE
                                    left_pic = right_pic = None
                                elif left_state==STATE_NONE:
                                    left_state = STATE_FULL 
                                    left_data = [np.array([]), np.array([])]
    
                            if col_thresh[0]==0:
                                print("left col")
                                if left_state==STATE_FULL:
                                    if left_pic is None:
                                        left_pic = frame_queue[0][0].copy()
                                    speed = self.handle_end(left_data, left_pic, True)
                                    if speed:
                                        speed_disp = speed, time.time()
                                    left_state = right_state = STATE_NONE
                                    left_pic = right_pic = None
                                elif right_state==STATE_NONE:
                                    right_state = STATE_OCCLUDED
                                    right_data = [np.array([]), np.array([])]
                            elif right_state==STATE_OCCLUDED:
                                right_state = STATE_FULL
                                right_pic = frame_queue[0][0].copy()
    
                        if left_state:
                            print("left", left_state)
                            # Add column data
                            left_data[0] = np.append(left_data[0], col_thresh[0])
                            # Add timestamp data
                            left_data[1] = np.append(left_data[1], frame_orig[1])
                            t = left_data[1][-1] - left_data[1][0]
                            if t>DATA_TIMEOUT:
                                left_state = STATE_NONE
                            
                        if right_state:
                            print("right", right_state)
                            # Add column data
                            right_data[0] = np.append(right_data[0], col_thresh[-1])
                            # Add timestamp data
                            right_data[1] = np.append(right_data[1], frame_orig[1])
                            t = right_data[1][-1] - right_data[1][0]
                            if t>DATA_TIMEOUT:
                                right_state = STATE_NONE
                except Exception as e:
                    print("***", e)
                    breakpoint()
                    
                if speed_disp is None:
                    self.video.push_frame(frame_orig)
                else: # overlay speed ontop of video 
                    speed_frame = self._overlay_speed(frame_orig[0], speed_disp[0])
                    self.video.push_frame(speed_frame)
                    if time.time()-speed_disp[1]>SPEED_DISPLAY_TIMEOUT:
                        speed_disp = None 
                        
            frame_queue.insert(0, frame_orig)
            frame_queue = frame_queue[0:FRAME_QUEUE_LENGTH]
            self.kapp.push_mods(mods)
            
if __name__ == "__main__":
    Video()
