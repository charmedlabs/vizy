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


NOISE_FLOOR = 30*3
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
STATE_FULL = 1  
STATE_FINISHING = 2 
MINIMUM_DATA = 3
SHUTTER_SPEED = 0.001
FRAME_QUEUE_LENGTH = 4
STATE_QUEUE_LENGTH = 5 
BIN_FINISH = 0.9
MAX_RESIDUAL = 100
MIN_SPAN = BINS/2

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
        self.camera.brightness = self.config['brightness']
        self.stream = self.camera.stream() #(False)
        #self.stream.load("/home/pi/vizy/etc/motionscope/car3/video.raw")
        self.pointing_right = True 

        self.sensitivity_range = kritter.Range((1, 100), (200, 25), inval=self.config['sensitivity']) 
        self.bin_threshold = self.sensitivity_range.outval

        style = {"label_width": 2, "control_width": 4}
        self.video = kritter.Kvideo(width=self.camera.resolution[0], overlay=True)
        self.media_queue = MediaDisplayQueue(MEDIA_DIR, CAMERA_WIDTH, CAMERA_WIDTH) 
        self.settings_button = kritter.Kbutton(name=[kritter.Kritter.icon("gear"), "Settings..."], service=None)
        self.brightness = kritter.Kslider(name="Brightness", value=self.config['brightness'], mxs=(0, 100, 1), format=lambda val: f'{val}%', grid=False, style=style)
        self.settings_button.append(self.brightness)
        self.gcloud = kritter.Gcloud(self.kapp.etcdir)
        self.gphoto_interface = self.gcloud.get_interface("KstoreMedia")
        self.store_media = kritter.SaveMediaQueue(path=MEDIA_DIR)
        if self.config['gphoto_upload']:
            self.store_media.store_media = self.gphoto_interface 
        self.calib_text = kritter.KtextBox(name="Speed", style={"control_width": 3}, grid=False, service=None)
        self.calib_button = kritter.Kbutton(name=[self.kapp.icon("calculator"), "Calibrate"], service=None)
        self.calib_dialog = kritter.Kdialog(title=[self.kapp.icon("calculator"), "Calibrate speed"], left_footer=self.calib_button, layout=[self.calib_text])
        
        dstyle = {"label_width": 5, "control_width": 5}
        self.sensitivity = kritter.Kslider(name="Sensitivity", value=self.config['sensitivity'], mxs=(1, 100, 1), format=lambda val: f'{int(val)}%', style=dstyle)
        self.kph = kritter.Kcheckbox(name="Kilometers per hour", value=self.config['kph'], style=dstyle)        
        self.left = kritter.Kcheckbox(name="Camera pointing left", value=self.config['left_pointing'], style=dstyle)
        self.upload = kritter.Kcheckbox(name="Upload to Google Photos", value=self.config['gphoto_upload'], disabled=self.gphoto_interface is None, style=dstyle)
        dlayout = [self.sensitivity, self.kph, self.left, self.upload]
        self.settings = kritter.Kdialog(title=[kritter.Kritter.icon("gear"), "Settings"], layout=dlayout)

        self.graph_layout = dict(title="Data points", 
            yaxis=dict(zeroline=False, title="Horizontal movement"),
            xaxis=dict(zeroline=False, title='Time (seconds)'),
            showlegend=False,
            width=CAMERA_WIDTH, 
            height=int(CAMERA_WIDTH*3/4), 
        )

        self.graph = dcc.Graph(style={"display": "none"}, id=self.kapp.new_id())
        self.kapp.layout = html.Div([self.video, self.media_queue.layout, self.settings_button, self.graph, self.calib_dialog, self.settings], style={"padding": "15px"})

        self.kapp.push_mods(self.media_queue.out_images())
        
        @self.brightness.callback()
        def func(value):
            self.config['brightness'] = value
            self.camera.brightness = value
            self.config.save()

        @self.settings_button.callback()
        def func():
            return self.settings.out_open(True)

        @self.sensitivity.callback()
        def func(value):
            self.config['sensitivity'] = value
            self.sensitivity_range.inval = value
            print(self.bin_threshold)
            self.bin_threshold = self.sensitivity_range.outval
            print(value, self.bin_threshold)
            self.config.save()
            
        @self.kph.callback()
        def func(value):
            self.config['kph'] = value  
            self.config.save()

        @self.left.callback()
        def func(value):
            self.config['left_pointing'] = value  
            self.config.save()

        @self.upload.callback()
        def func(value):
            self.config['gphoto_upload'] = value  
            self.store_media.store_media = self.gphoto_interface if value else None
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
        print("end")
        data_y, data_time = data

        # Valid vehicles need to span a minimum width of the image 
        span = max(data_y) - min(data_y)
        if span<MIN_SPAN:
            print("minimum span", span)
            return 

        # deal with minimum data and left motion that looks like it's going right and right motion that looks like it's going left
        if len(data_y)<MINIMUM_DATA or (left and data_y[0]-data_y[-1]<0) or (not left and data_y[0]-data_y[-1]>0):
            return None

        # Take all of the data and fit to a line.  This will give us the most likely speed given noise, 
        # that is, erroneous data is drown out by valid data. 
        A = np.vstack([data_time, np.ones(len(data_time))]).T
        result = np.linalg.lstsq(A, data_y, rcond=None)
        m, b = result[0]
        residual = result[1][0]/len(data_time)

        # The data is a line (ideally).  If it's not a line the residual will be larger.  
        # We reject line fits that exceed a threshold.
        if residual>MAX_RESIDUAL:
            print("residual exceeded", residual)
            return 
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

        # If we end up with 0 speed after we've rounded everything, that's probably not a valid vehicle.
        if round(speed)==0:
            return     

        filename_ = kritter.time_stamped_file("jpg")
        filename = os.path.join(MEDIA_DIR, filename_)
        metadata = {"speed": speed, "speed_raw": speed_raw, "left_moving": left, "left_pointing": self.config["left_pointing"], "timestamp": self._timestamp(), "data": [list(data_time), list(data_y)], "width": pic.shape[1], "height": pic.shape[0]}
        # write image without speed overlay
        cv2.imwrite(filename+"_", pic) 
        # Overlay speed and write image with speed
        pic = self._overlay_speed(pic, speed)
        cv2.imwrite(filename, pic) 
        kritter.save_metadata(filename, metadata)
        # Update media queue
        self.kapp.push_mods(self.media_queue.out_images())
        # Render graph
        figure = go.Figure(data=[go.Scatter(x=data_time, y=data_y, mode='lines+markers'), go.Scatter(x=[data_time[0], data_time[-1]], y=[m*data_time[0]+b, m*data_time[-1]+b])], layout=self.graph_layout)
        self.kapp.push_mods([Output(self.graph.id, "style", {"display": "block"}), Output(self.graph.id, "figure", figure)])
        
        return speed

    def motion(self):
        if len(self.motion_queue)<STATE_QUEUE_LENGTH:
            return True 
        mot = 0
        for i in self.motion_queue:
            if i:
                mot += 1
        return mot>len(self.motion_queue)//2

    def finish_right(self):
        if not self.right_pic is None:
            speed = self.handle_end(self.right_data, self.right_pic, False)
            if speed: 
                self.speed_disp = speed, time.time()
            print("self.right_state NONE")
        else:
            print("self.right_state NONE (not motion, no pic)")
        self.right_state = STATE_NONE

    def finish_left(self):
        if not self.left_pic is None:
            speed = self.handle_end(self.left_data, self.left_pic, True)
            if speed: 
                self.speed_disp = speed, time.time()
            print("self.left_state NONE")
        else:
            print("self.left_state NONE (not motion, no pic)")
        self.left_state = STATE_NONE

    # Frame grabbing thread
    def grab(self):  
        self.speed_disp = None
        frame0 = None
        cols = None
        last_timestamp = None
        frame_queue = []
        t0 = time.time()
        hist_cols = np.arange(0, BINS, dtype='uint')
        right_time = left_time = 0
        self.left_state = self.right_state = STATE_NONE
        self.left_pic = self.right_pic = None
        self.motion_queue = []

        while time.time()-t0<3:
            self.stream.frame()
        self.camera.awb = False

        while self.run_grab:
            mods = []
            left_pointing = self.config['left_pointing']
            # Get frame
            frame_orig = self.stream.frame()

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
                    # If we see motion of col_thresh[0], start recording data in to self.right_data (right-moving object data).
                    # Stop recording when we see motion on col_thresh[BINS-1]
                    # If we see motion of col_thresh[BINS-1], start recording data in to self.left_data (left-moving object data).
                    # Stop recording when we see motion on col_thresh[0]
                    self.motion_queue = self.motion_queue[0:STATE_QUEUE_LENGTH-1]           
                    if len(col_thresh): 
                        leftmost = col_thresh[0]
                        rightmost = col_thresh[-1]                            
                        left_col = leftmost==0
                        right_col = rightmost==BINS-1 
                        self.motion_queue.insert(0, True)
                        motion = self.motion()
                            
                        if self.right_state==STATE_NONE:
                            if left_col and self.left_state==STATE_NONE:
                                print("self.right_state FULL")
                                self.right_state = STATE_FULL    
                                self.motion_queue = []
                                self.right_data = [np.array([]), np.array([])]
                                right_time = time.time()
                                self.right_pic = None
                        elif self.right_state==STATE_FULL:
                            if right_col:
                                print("self.right_state FINISHING")
                                if left_pointing:
                                    self.right_pic = frame_queue[0][0]
                                self.right_state = STATE_FINISHING 
                        if not left_pointing and self.right_state and left_col:         
                            print("take right pic")                                  
                            self.right_pic = frame_orig[0]

                        if self.left_state==STATE_NONE:
                            if right_col and self.right_state==STATE_NONE:
                                print("self.left_state FULL")
                                self.left_state = STATE_FULL    
                                self.motion_queue = []
                                self.left_data = [np.array([]), np.array([])]
                                left_time = time.time()
                                self.left_pic = None
                        elif self.left_state==STATE_FULL:
                            if left_col:
                                print("self.left_state FINISHING")
                                if not left_pointing:
                                    self.left_pic = frame_queue[0][0]
                                self.left_state = STATE_FINISHING 
                        if left_pointing and self.left_state and right_col:         
                            print("take left pic")                                  
                            self.left_pic = frame_orig[0]


                        if self.left_state:
                            print("left", self.left_state, col_thresh[0], col_thresh[-1])
                            if self.left_state==STATE_FULL:
                                # Add column data
                                self.left_data[0] = np.append(self.left_data[0], col_thresh[0])
                                # Add timestamp data
                                self.left_data[1] = np.append(self.left_data[1], frame_orig[1])
                        if self.right_state:
                            print("right", self.right_state, col_thresh[0], col_thresh[-1])
                            if self.right_state==STATE_FULL:
                                # Add column data
                                self.right_data[0] = np.append(self.right_data[0], col_thresh[-1])
                                # Add timestamp data
                                self.right_data[1] = np.append(self.right_data[1], frame_orig[1])
                    else:
                        self.motion_queue.insert(0, False)

                    if self.right_state and not self.motion():
                        print("right no motion")
                        self.finish_right()
                    elif self.right_state and time.time()-right_time>DATA_TIMEOUT:
                        self.right_state = STATE_NONE
                        print("right timeout")

                    if self.left_state and not self.motion():
                        print("left no motion")
                        self.finish_left()
                    elif self.left_state and time.time()-left_time>DATA_TIMEOUT:
                        self.left_state = STATE_NONE
                        print("left timeout")

                except Exception as e:
                    print("***", e)
                 
                if self.speed_disp is None:
                    self.video.push_frame(frame_orig) # np.dstack(frame0)
                else: # overlay speed ontop of video 
                    speed_frame = self._overlay_speed(frame_orig[0], self.speed_disp[0])
                    self.video.push_frame(speed_frame)
                    if time.time()-self.speed_disp[1]>SPEED_DISPLAY_TIMEOUT:
                        self.speed_disp = None 
                        
            frame0 = frame
            frame_queue.insert(0, frame_orig)
            frame_queue = frame_queue[0:FRAME_QUEUE_LENGTH]
            self.kapp.push_mods(mods)
            
if __name__ == "__main__":
    Video()
