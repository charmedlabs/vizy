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
import time
import cv2 
from threading import RLock
from tab import Tab
import kritter
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
from dash_devices import callback_context
from centroidtracker import CentroidTracker
from motionscope_consts import UPDATE_RATE, BG_AVG_RATIO, BG_CNT_FINAL, MIN_RANGE
from simplemotion import SimpleMotion

PAUSED = 0
PROCESSING = 1
FINISHED = 2

class Process(Tab):

    def __init__(self, kapp, data, camera, perspective):

        super().__init__("Process", kapp, data)
        self.lock = RLock() # for sychronizing self.state
        self.update_timer = 0
        self.camera = camera
        self.perspective = perspective
        self.stream = camera.stream()
        self.data['recording'] = None
        self.motion = SimpleMotion()
        self.state = PAUSED
        self.more = False

        style = {"label_width": 3, "control_width": 6}
        self.playback_c = kritter.Kslider(value=0, mxs=(0, 1, .001), updatetext=False, updaterate=0, style={"control_width": 8})
        self.process_button = kritter.Kbutton(name=[kapp.icon("refresh"), "Process"], spinner=True)
        self.cancel = kritter.Kbutton(name=[kapp.icon("close"), "Cancel"], disabled=True)
        self.more_c = kritter.Kbutton(name=kapp.icon("plus", padding=0))
        self.process_button.append(self.cancel)
        self.process_button.append(self.more_c)

        self.data[self.name]["motion_threshold"] = self.motion.threshold
        self.motion_threshold_c = kritter.Kslider(name="Motion threshold", value=self.motion.threshold, mxs=(1, 100, 1), format=lambda val: f'{val:.0f}%', style=style)

        more_controls = dbc.Collapse([self.motion_threshold_c], id=kapp.new_id(), is_open=False)
        self.layout = dbc.Collapse([self.playback_c, self.process_button, more_controls], id=kapp.new_id(), is_open=False)

        @self.more_c.callback()
        def func():
            self.more = not self.more
            return self.more_c.out_name(kapp.icon("minus", padding=0) if self.more else kapp.icon("plus", padding=0)) + [Output(more_controls.id, "is_open", self.more)]

        @self.motion_threshold_c.callback()
        def func(val):
            self.data[self.name]["motion_threshold"] = val
            self.motion.threshold = val

        @self.process_button.callback()
        def func():
            return self.set_state(PROCESSING) 

        @self.cancel.callback()
        def func():
            return self.set_state(PAUSED)

        @self.playback_c.callback()
        def func(t):
            if callback_context.client:
                t = self.data['recording'].time_seek(t)
                self.curr_frame = self.data['recording'].frame()
                time.sleep(1/UPDATE_RATE)
            return self.playback_c.out_text(f"{t:.3f}s")            

    def data_update(self, changed, cmem=None):
        with self.lock:
            mods = []
            if "obj_data" in changed and cmem is None:
                self.obj_data = self.data['obj_data']
                mods += self.set_state(FINISHED, 1)
            if "recording" in changed:
                # If we're loading, calculate bg immediately. 
                if cmem is None:
                    self.calc_bg()
                # ...otherwise defer it until we are processing so we don't 
                # block UI.  
                else:
                    self.bg_split = None                    
                mods += self.set_state(PROCESSING, 1)
            if self.name in changed:
                try:
                    mods += self.motion_threshold_c.out_value(self.data[self.name]['motion_threshold'])
                except:
                    pass
            return mods 

    def record(self, tinfo, pts, index):
        for i, v in tinfo.items():
            v = v[0:6]
            v = np.insert(v, 0, pts)
            v = np.insert(v, 1, index)
            if i in self.obj_data:
                self.obj_data[i] = np.vstack((self.obj_data[i], v))
            else:
                self.obj_data[i] = np.array([v])

    def calc_bg(self):
        self.data['recording'].seek(0)
        for i in range(BG_CNT_FINAL):
            frame = self.data['recording'].frame()[0]
            if i==0:
                self.bg = frame
            else:
                self.bg = self.bg*(1-BG_AVG_RATIO) + frame*BG_AVG_RATIO
                self.bg = self.bg.astype("uint8")    
        self.data['recording'].seek(0)
        # We only use split version of bg
        self.bg_split = cv2.split(self.bg)
        self.data['bg'] = self.bg

    def prune(self):
        # Delete objects that don't move "much" (set by MIN_RANGE)
        # Go through data find x and y range, if both ranges are less than 
        # threshold then delete.
        for i, data in self.obj_data.copy().items():
            x_range = np.max(data[:, 2]) - np.min(data[:, 2])
            y_range = np.max(data[:, 3]) - np.min(data[:, 3])
            if x_range<MIN_RANGE and y_range<MIN_RANGE:
                del self.obj_data[i]


    def process(self, frame):
        index = frame[2]
        pts = frame[1]
        frame = frame[0]
        frame_split  = cv2.split(frame)

        motion = self.motion.extract(frame_split, self.bg_split)

        # Create composite frame
        motionb = motion.astype("bool")
        motion3 = np.repeat(motionb[:, :, np.newaxis], 3, axis=2)
        frame = np.where(motion3, frame, frame/4) 

        # Perform connected components
        retval, labels, stats, centroids = cv2.connectedComponentsWithStats(motion)
        rects = stats[1:, 0:4]
        crects = np.concatenate((centroids[1:], rects), axis=1)
        colors = np.empty((0,3), int) 

        # Extract average hue of each object so we can more accurately track 
        # each object from frame to frame.
        for r in rects:
            rect_pixels = frame[r[1]:r[1]+r[3], r[0]:r[0]+r[2], :]
            rect_mask = motionb[r[1]:r[1]+r[3], r[0]:r[0]+r[2]]
            rect_pixels = rect_pixels[rect_mask]
            avg_pixel = np.array([np.average(rect_pixels[:, 0]), np.average(rect_pixels[:, 1]), np.average(rect_pixels[:, 2])])
            colors = np.vstack((colors, avg_pixel))

        # Send rectangles to tracker so we can track objects.
        tinfo = self.tracker.update(crects, colors) 

        # Add crosshair to detected objects
        for i, t in tinfo.items():
            cx = int(round(t[0]))
            cy = int(round(t[1]))
            w = int(t[4])
            h = int(t[5])
            cv2.line(frame, (cx-w, cy), (cx+w, cy), thickness=1, color=(255, 255, 255))
            cv2.line(frame, (cx, cy-h), (cx, cy+h), thickness=1, color=(255, 255, 255))

        # Record data if we're processing
        if self.state==PROCESSING:
            self.record(tinfo, pts, index)

        return frame

    def set_state(self, state, cmem=None):
        with self.lock:
            if state==PROCESSING:
                self.obj_data = self.data['obj_data'] = {}
                self.data['recording'].seek(0)
                self.tracker = CentroidTracker(maxDisappeared=15, maxDistance=200, maxDistanceAdd=50)
                mods = self.process_button.out_spinner_disp(True) + self.cancel.out_disabled(False) + self.playback_c.out_max(self.data['recording'].time_len()) + self.playback_c.out_disabled(True) + self.playback_c.out_value(0)
                if cmem is None:
                    mods += self.call_data_update_callback("obj_data", 1)
            elif state==PAUSED:
                self.curr_frame = self.data['recording'].frame()
                mods = self.process_button.out_spinner_disp(False) + self.cancel.out_disabled(True) + self.playback_c.out_disabled(False)
            elif state==FINISHED:
                self.prune() # Clean up self.obj_data
                mods = self.process_button.out_spinner_disp(False) + self.cancel.out_disabled(True) + self.playback_c.out_disabled(False) + self.playback_c.out_value(0)
                self.data['recording'].time_seek(0)
                self.curr_frame = self.data['recording'].frame()
                if cmem is None:
                    mods += self.call_data_update_callback("obj_data", 1)
            self.state = state
            return mods  

    def update(self):
        t = self.data['recording'].time()
        mods = self.playback_c.out_value(t) 
        return mods  

    def frame(self):
        with self.lock:
            if self.bg_split is None:
                self.calc_bg()

            if self.state==PROCESSING:
                self.curr_frame = self.data['recording'].frame()
                if self.curr_frame is None:
                    self.kapp.push_mods(self.set_state(FINISHED))
                else:
                    t = time.time()
                    if t-self.update_timer>1/UPDATE_RATE:
                        self.update_timer = t
                        mods = self.update()
                        if mods:
                            self.kapp.push_mods(mods)

            if self.curr_frame is None:
                return None

            frame = self.process(self.curr_frame)

            return frame

    def focus(self, state):
        mods = []
        if state:
            mods += self.perspective.out_disp(False)
            self.stream.stop()
            if self.state!=FINISHED: # Only process if we haven't processed this video first (not finished)
                mods += self.set_state(PROCESSING)
        return mods

