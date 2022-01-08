import os
from threading import Thread, RLock
import kritter
import cv2
import numpy as np
import time
import json
from dash_devices import Services, callback_context
from dash_devices.dependencies import Input, Output
import dash_core_components as dcc
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy
from math import sqrt 
from centroidtracker import CentroidTracker

"""
todo:
make self.tabs and self.tab_ids instead of having tuples for self.tabs

make a base class for tabs, put camera and stream in it, focus has pass implementation

vizyvisor nav
figure out color scheme and whether to use card for tabs
get rid of make_divisible, calc_video_resolution, MAX_AREA.  Push that into Kvideo as default sizing logic.  Also fix max-width for KvideoComponent while we're at it.

Create consts file for values that are rarely used

testing:
test null case (no motion)
test short vid < BG_CNT_FINAL frames
transitions -- load file while processing, move to capture while processing (then back again)
"""

MAX_AREA = 640*480
MAX_RECORDING_DURATION = 5 # seconds
UPDATE_RATE = 10 # updates/second
PLAY_RATE = 30 # frames/second
WIDTH = 736
APP_DIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(APP_DIR, "media")

def make_divisible(val, d):
    # find closest integer that's divisible by d
    mod = val%d
    if mod < d/2:
        val -= mod
    else:
        val += d-mod
    return val 

def calc_video_resolution(width, height):
    if width*height>MAX_AREA:
        ar = width/height 
        height = int(sqrt(MAX_AREA/ar))
        height = make_divisible(height, 16)
        width = int(height * ar) 
        width = make_divisible(width, 16) 
        return width, height 
    else:
        return width, height

class Tab:
    def __init__(self, name, kapp, data):
        self.name = name
        self.kapp = kapp
        self.data = data 
        self.data_update_callback_func = None

    def frame(self):
        return None

    def focus(self, state):
        pass

    def data_update(self, changed):
        pass

    def call_data_update_callback(self, changed):
        if self.data_update_callback_func:
            return self.data_update_callback_func(changed)

    def data_update_callback(self, func):
        self.data_update_callback_func = func


class Camera(Tab):

    def __init__(self, kapp, data, camera, video):

        super().__init__("Camera", kapp, data)
        self.stream = camera.stream()
        style = {"label_width": 3, "control_width": 6}
        modes = ["640x480x10bpp (cropped)", "768x432x10bpp", "1280x720x10bpp"]
        mode = kritter.Kdropdown(name='Camera mode', options=modes, value=camera.mode, style=style)
        brightness = kritter.Kslider(name="Brightness", value=camera.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style=style)
        framerate = kritter.Kslider(name="Framerate", value=camera.framerate, mxs=(camera.min_framerate, camera.max_framerate, 1), format=lambda val : f'{val} fps', style=style)
        autoshutter = kritter.Kcheckbox(name='Auto-shutter', value=camera.autoshutter, style=style)
        shutter = kritter.Kslider(name="Shutter-speed", value=camera.shutter_speed, mxs=(.0001, 1/camera.framerate, .0001), format=lambda val: f'{val:.4f}s', style=style)
        shutter_cont = dbc.Collapse(shutter, id=kapp.new_id(), is_open=not camera.autoshutter, style=style)
        awb = kritter.Kcheckbox(name='Auto-white-balance', value=camera.awb, style=style)
        red_gain = kritter.Kslider(name="Red gain", value=camera.awb_red, mxs=(0.05, 2.0, 0.01), style=style)
        blue_gain = kritter.Kslider(name="Blue gain", value=camera.awb_red, mxs=(0.05, 2.0, 0.01), style=style)
        awb_gains = dbc.Collapse([red_gain, blue_gain], id=kapp.new_id(), is_open=not camera.awb)            

        @brightness.callback()
        def func(value):
            camera.brightness = value

        @framerate.callback()
        def func(value):
            camera.framerate = value
            return shutter.out_value(camera.shutter_speed) + shutter.out_max(1/camera.framerate)

        @mode.callback()
        def func(value):
            camera.mode = value
            width, height = calc_video_resolution(camera.resolution[0], camera.resolution[1])
            return video.out_width(width) + video.out_height(height) + framerate.out_value(camera.framerate) + framerate.out_min(camera.min_framerate) + framerate.out_max(camera.max_framerate)

        @autoshutter.callback()
        def func(value):
            camera.autoshutter = value
            return Output(shutter_cont.id, 'is_open', not value)

        @shutter.callback()
        def func(value):
            camera.shutter_speed = value    

        @awb.callback()
        def func(value):
            camera.awb = value
            return Output(awb_gains.id, 'is_open', not value)

        @red_gain.callback()
        def func(value):
            camera.awb_red = value

        @blue_gain.callback()
        def func(value):
            camera.awb_blue = value
         
        self.layout = dbc.Collapse([mode, brightness, framerate, autoshutter, shutter_cont, awb, awb_gains], id=kapp.new_id(), is_open=True)

    def frame(self):
        return self.stream.frame()[0]



class Capture(Tab):

    def __init__(self, kapp, data, camera):

        super().__init__("Capture", kapp, data)
        self.ratio = 0.1
        self.update_timer = 0
        self.pts_timer = 0
        self.prev_mods = []
        self.camera = camera
        self.recording = None
        self.new_recording = False
        self.playing = False
        self.paused = False
        self.stream = self.camera.stream()
        self.duration = MAX_RECORDING_DURATION
        self.start_shift = 0
        self.trigger_sensitivity = 50
        self.more = False

        style = {"label_width": 3, "control_width": 6}
        self.status = kritter.Ktext(value="Press Record to begin.")
        self.playback_c = kritter.Kslider(value=0, mxs=(0, 1, .001), updatetext=False, updaterate=0, disabled=True, style={"control_width": 8})

        self.record = kritter.Kbutton(name=[kapp.icon("circle"), "Record"])
        self.play = kritter.Kbutton(name=self.play_name(), disabled=True)
        self.stop = kritter.Kbutton(name=[kapp.icon("stop"), "Stop"], disabled=True)
        self.step_backward = kritter.Kbutton(name=kapp.icon("step-backward", padding=0), disabled=True)
        self.step_forward = kritter.Kbutton(name=kapp.icon("step-forward", padding=0), disabled=True)
        self.more_c = kritter.Kbutton(name="More...")

        self.record.append(self.play)
        self.record.append(self.stop)
        self.record.append(self.step_backward)
        self.record.append(self.step_forward)
        self.record.append(self.more_c)

        self.save = kritter.Kbutton(name=[kapp.icon("save"), "Save"])
        self.load = kritter.KdropdownMenu(name="Load")
        self.delete = kritter.KdropdownMenu(name="Delete")
        self.save.append(self.load)
        self.save.append(self.delete)

        self.start_shift_c = kritter.Kslider(name="Start-shift", value=self.start_shift, mxs=(-5.0, 5, .01), format=lambda val: f'{val:.2f}s', style=style)
        self.duration_c = kritter.Kslider(name="Duration", value=self.duration, mxs=(0, MAX_RECORDING_DURATION, .01), format=lambda val: f'{val:.2f}s', style=style)
        self.trigger_modes = ["button press", "auto-trigger", "auto-trigger, auto-analyze"]
        self.trigger_mode = self.trigger_modes[0]
        self.trigger_modes_c = kritter.Kdropdown(name='Trigger mode', options=self.trigger_modes, value=self.trigger_mode, style=style)
        self.trigger_sensitivity_c = kritter.Kslider(name="Trigger sensitivitiy", value=self.trigger_sensitivity, mxs=(1, 100, 1), style=style)

        more_controls = dbc.Collapse([self.save, self.start_shift_c, self.duration_c, self.trigger_modes_c, self.trigger_sensitivity_c], id=kapp.new_id(), is_open=self.more)
        self.layout = dbc.Collapse([self.status, self.playback_c, self.record, more_controls], id=kapp.new_id(), is_open=False)

        @self.more_c.callback()
        def func():
            self.more = not self.more
            return self.more_c.out_name("Less..." if self.more else "More...") + [Output(more_controls.id, "is_open", self.more)]

        @self.record.callback()
        def func():
            self.recording = self.camera.record(duration=self.duration, start_shift=self.start_shift)
            self.new_recording = True
            self.playing = False
            self.paused = False
            return self.update()

        @self.play.callback()
        def func():
            if self.playing:
                self.paused = not self.paused
            self.playing = True
            self.pts_timer = time.time()
            return self.update()

        @self.stop.callback()
        def func():
            self.playing = False
            self.paused = False
            self.recording.stop()
            self.recording.seek(0)
            return self.update()

        @self.step_backward.callback()
        def func():
            self.playing = True  
            self.paused = True 
            self.recording.seek(self._frame[2]-1)
            frame = self.recording.frame()
            return self.playback_c.out_value(frame[1])

        @self.step_forward.callback()
        def func():
            self.playing = True  
            self.paused = True 
            frame = self.recording.frame()
            if frame is not None:
                return self.playback_c.out_value(frame[1])


        @self.playback_c.callback()
        def func(t):
            # Check for client dragging slider when we're stopped, in which case, 
            # go into paused state.
            if not self.playing and not self.recording.recording() and callback_context.client and t!=0:
                self.playing = True 
                self.paused = True

            if self.playing:
                # Only seek if client actually dragged slider, not when we set it ourselves.
                if callback_context.client:
                    t = self.recording.time_seek(t) # Update time to actual value.
                if self.paused:
                    self._frame = self.recording.frame()
                    time.sleep(1/UPDATE_RATE)

            return self.playback_c.out_text(f"{t:.3f}s")
    def play_name(self):
        return [self.kapp.icon("pause"), "Pause"] if self.playing and not self.paused else [self.kapp.icon("play"), "Play"]

    def update(self):
        mods = []
        if self.recording:
            t = self.recording.time() 
            tlen = self.recording.time_len()
            mods += self.play.out_name(self.play_name()) 
            if self.playing:
                if self.paused:
                    mods += self.step_backward.out_disabled(self._frame[2]==0) + self.step_forward.out_disabled(self._frame[2]==self.recording.len()-1) + self.status.out_value("Paused")
                else: 
                    mods += self.playback_c.out_disabled(False) + self.step_backward.out_disabled(True) + self.step_forward.out_disabled(True) + self.playback_c.out_value(t) + self.status.out_value("Playing...") 
                mods += self.record.out_disabled(True) + self.stop.out_disabled(False) + self.play.out_disabled(False) + self.playback_c.out_max(tlen) 
            elif self.recording.recording()>0:
                mods += self.playback_c.out_disabled(True) + self.record.out_disabled(True) + self.stop.out_disabled(False) + self.play.out_disabled(True) + self.step_backward.out_disabled(True) + self.step_forward.out_disabled(True) + self.playback_c.out_max(self.duration) + self.status.out_value("Recording...") + self.playback_c.out_value(tlen)
            else: # Stopped
                mods += self.playback_c.out_disabled(False) + self.playback_c.out_max(tlen) + self.playback_c.out_value(0) + self.record.out_disabled(False) + self.stop.out_disabled(True) + self.step_backward.out_disabled(True) + self.step_forward.out_disabled(False) + self.play.out_disabled(False) + self.status.out_value("Stopped") + ["stop_marker"]

        # Find new mods with respect to the previous mods
        diff_mods = [m for m in mods if not m in self.prev_mods]
        # Save current mods
        self.prev_mods = mods 
        # Stop marker allows us to see the stop event by detecting it in diff_mods.
        if "stop_marker" in diff_mods:
            diff_mods.remove("stop_marker")
            if self.new_recording:
                self.new_recording = False # This prevents a loaded video (from Load) from triggering recording_changed
                self.data['recording'] = self.recording
                diff_mods += self.call_data_update_callback("recording") 
        # Only send new mods
        return diff_mods    

    def data_update(self, changed):
        if "recording" in changed:
            self.playing = False
            self.paused = False
            self.recording = self.data['recording']

    def frame(self):
        update = False

        if self.playing:
            if not self.paused:
                self._frame = self.data['recording'].frame()
                if self._frame is None:
                    self.playing = False
                    self.paused = False
                    self.data['recording'].seek(0)
                    update = True

        t = time.time()
        if update or t-self.update_timer>1/UPDATE_RATE:
            self.update_timer = t
            mods = self.update()
            if mods:
                self.kapp.push_mods(mods)

        if self.playing and self._frame is not None: # play recording
            self.pts_timer += 1/PLAY_RATE
            sleep = self.pts_timer - time.time()
            if sleep>0:
                time.sleep(sleep)
            return self._frame[0]
        else: # stream live
            frame = self.stream.frame()[0]
            return frame



PAUSED = 0
PROCESSING = 1
FINISHED = 2
BG_AVG_RATIO = 0.1
BG_CNT_FINAL = 10 
MIN_RANGE = 30

class Range:

    def __init__(self, in_range, out_range, inval=None, outval=None):
        if inval is None and outval is None:
            raise RuntimeError("at least one value (inval or outval) needs to be specified")    
        self.in_range = in_range
        self.out_range = out_range
        self._inval = self._outval = None
        if inval is not None:
            self._inval = inval
        if outval is not None:
            self._outval = outval

    @property
    def outval(self):
        if self._outval is None:
            self._outval = self.out_range[0] + (self._inval-self.in_range[0])/(self.in_range[1]-self.in_range[0])*(self.out_range[1]-self.out_range[0])

        return self._outval
    
    @outval.setter
    def outval(self, outval):
        self._outval = outval
        self._inval = None

    @property
    def inval(self):
        if self._inval is None:
            self._inval = self.in_range[0] + (self._outval-self.out_range[0])/(self.out_range[1]-self.out_range[0])*(self.in_range[1]-self.in_range[0])
        return self._inval
    
    @inval.setter
    def inval(self, inval):
        self._inval = inval  
        self._outval = None

class Process(Tab):

    def __init__(self, kapp, data, camera):

        super().__init__("Process", kapp, data)
        self.lock = RLock() # for sychronizing self.state
        self.update_timer = 0
        self.camera = camera
        self.stream = camera.stream()
        self.data['recording'] = None
        self.state = PAUSED
        self.more = False
        self.motion_threshold = Range((1, 100), (1*3, 50*3), outval=20*3)

        style = {"label_width": 3, "control_width": 6}
        self.playback_c = kritter.Kslider(value=0, mxs=(0, 1, .001), updatetext=False, updaterate=0, style={"control_width": 8})
        self.process_button = kritter.Kbutton(name=[kapp.icon("refresh"), "Process"], spinner=True)
        self.cancel = kritter.Kbutton(name=[kapp.icon("close"), "Cancel"], disabled=True)
        self.more_c = kritter.Kbutton(name=kapp.icon("plus", padding=0))
        self.process_button.append(self.cancel)
        self.process_button.append(self.more_c)

        self.motion_threshold_c = kritter.Kslider(name="Motion threshold", value=self.motion_threshold.inval, mxs=(1, 100, 1), format=lambda val: f'{val:.0f}%', style=style)

        more_controls = dbc.Collapse([self.motion_threshold_c], id=kapp.new_id(), is_open=False)
        self.layout = dbc.Collapse([self.playback_c, self.process_button, more_controls], id=kapp.new_id(), is_open=False)

        @self.more_c.callback()
        def func():
            self.more = not self.more
            return self.more_c.out_name(kapp.icon("minus", padding=0) if self.more else kapp.icon("plus", padding=0)) + [Output(more_controls.id, "is_open", self.more)]

        @self.motion_threshold_c.callback()
        def func(val):
            self.motion_threshold.inval = val

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

    def data_update(self, changed):
        with self.lock:
            if "obj_data" in changed:
                self.obj_data = self.data['obj_data']
                return self.set_state(FINISHED)
            if "recording" in changed:
                self.calc_bg()
                return self.set_state(PROCESSING)

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
        diff = np.zeros(frame_split[0].shape, dtype="uint16")

        # Compute absolute difference with background frame
        for i in range(3):
            diff += cv2.absdiff(self.bg_split[i], frame_split[i])

        # Threshold motion
        mthresh = diff>self.motion_threshold.outval
        mthresh = mthresh.astype("uint8")            

        # Clean up
        mthresh = cv2.erode(mthresh, None, iterations=4)
        mthresh = cv2.dilate(mthresh, None, iterations=4) 

        # Create composite frame
        mthreshb = mthresh.astype("bool")
        mthresh3 = np.repeat(mthreshb[:, :, np.newaxis], 3, axis=2)
        frame = np.where(mthresh3, frame, frame/4) 

        # Perform connected components
        retval, labels, stats, centroids = cv2.connectedComponentsWithStats(mthresh)
        rects = stats[1:, 0:4]
        crects = np.concatenate((centroids[1:], rects), axis=1)
        colors = np.empty((0,3), int) 

        # Extract average color of each object so we can more accurately track 
        # each object from frame to frame.
        for r in rects:
            rect_pixels = frame[r[1]:r[1]+r[3], r[0]:r[0]+r[2], :]
            rect_mask = mthreshb[r[1]:r[1]+r[3], r[0]:r[0]+r[2]]
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

    def set_state(self, state):
        with self.lock:
            if state==PROCESSING:
                self.obj_data = self.data['obj_data'] = {}
                self.data['recording'].seek(0)
                self.tracker = CentroidTracker(maxDisappeared=15, maxDistance=200, maxDistanceAdd=50)
                mods = self.process_button.out_spinner_disp(True) + self.cancel.out_disabled(False) + self.playback_c.out_max(self.data['recording'].time_len()) + self.playback_c.out_disabled(True)
                mods += self.call_data_update_callback("obj_data")
            elif state==PAUSED:
                self.curr_frame = self.data['recording'].frame()
                mods = self.process_button.out_spinner_disp(False) + self.cancel.out_disabled(True) + self.playback_c.out_disabled(False)
            elif state==FINISHED:
                self.prune() # Clean up self.obj_data
                mods = self.process_button.out_spinner_disp(False) + self.cancel.out_disabled(True) + self.playback_c.out_disabled(False) + self.playback_c.out_value(0)
                self.data['recording'].time_seek(0)
                self.curr_frame = self.data['recording'].frame()
                mods += self.call_data_update_callback("obj_data")
            self.state = state
            return mods  

    def update(self):
        t = self.data['recording'].time()
        mods = self.playback_c.out_value(t) 
        return mods  

    def frame(self):
        with self.lock:
            if self.state==PROCESSING:
                self.curr_frame = self.data['recording'].frame()
                if self.curr_frame is None:
                    self.kapp.push_mods(self.set_state(FINISHED))

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
        if state:
            if self.state!=FINISHED: # Only process if we haven't processed this video first (not finished)
                self.kapp.push_mods(self.set_state(PROCESSING))

class Analyze(Tab):

    def __init__(self, kapp, data, camera):

        super().__init__("Analyze", kapp, data)
        self.camera = camera
        self.stream = camera.stream()

        style = {"label_width": 2, "control_width": 6}
        self.spacing_c = kritter.Kslider(name="Spacing", mxs=(1, 10, 1), style=style)
        self.crop_c = kritter.Kslider(name="Crop", range=True, value=[0, 10], mxs=(0, 10, 1), style=style)

        self.layout = dbc.Collapse([self.spacing_c, self.crop_c], id=self.kapp.new_id())

        @self.spacing_c.callback()
        def func(val):
            self.spacing = val
            self.render()

        @self.crop_c.callback()
        def func(val):
            self.curr_first_index, self.curr_last_index = val
            self.render()

    def find_bounds(self):
        # Find when time begins (min_pts)
        # Find first frame (min_index)
        # Find last frame (max_index)
        max_points = []
        ptss = []
        indexes = []
        for i, data in self.data['obj_data'].items():
            max_points.append(len(data))
            ptss = np.append(ptss, data[:, 0])  
            indexes = np.append(indexes, data[:, 1])
        indexes = indexes.astype(int)
        self.pts0 = min(ptss) 
        self.time_lut = dict(zip(list(indexes), list(ptss))) 
        self.max_points = max(max_points)
        self.first_index = self.curr_first_index = min(indexes)
        self.last_index = self.curr_last_index = max(indexes)
        # Periods can be greater than actual frame period because of dropped frames.
        # Finding the minimum period of all frames is overkill, but gets us what we want.   
        self.frame_period = np.min(ptss[1:]-ptss[:-1]) 

    def calc_points(self):
        self.points = {}
        for k, data in self.data['obj_data'].items():

            # find part of data that's >= curr_first_index
            for i, d in enumerate(data):
                if d[1]>=self.curr_first_index:
                    break
            self.points[k] = np.array([d])
            d0 = d

            # Create rest of list that <= curr_last_index and is spaced correctly
            for d in data[i+1:]:
                if d[1]>self.curr_last_index:
                    break
                if d[0]-d0[0]>=self.frame_period*(self.spacing-0.5):
                    self.points[k] = np.vstack((self.points[k], d))
                    d0 = d

    def composite(self):
        # Start with background frame
        frame = self.data['bg'].copy()
        for k, data in self.points.items():
            for v in data:
                #  0    1    2    3    4    5    6    7    8    9    10    11    12    13    14    15     
                #  pts  ind  x    y    xr   yr   w    h    xv   yv   mv    av    xa    ya    ma    aa 
                #  480 640 3
                # grab frame associated with this vector
                self.data['recording'].seek(int(v[1]))
                framev = self.data['recording'].frame()
                framev = framev[0]
                # copy frame into frame
                frame[int(v[5]):int(v[5]+v[7]), int(v[4]):int(v[4]+v[6]), :] = framev[int(v[5]):int(v[5]+v[7]), int(v[4]):int(v[4]+v[6]), :]

        self.curr_frame = frame

    def render(self):
        self.calc_points()
        self.composite()

    def data_update(self, changed):
        if "obj_data" in changed and self.data['obj_data']:
            self.spacing = 1
            self.find_bounds()
            self.crop_c.set_format(lambda val : f'{self.time_lut[val[0]]:.3f}s → {self.time_lut[val[1]]:.3f}s')
            self.render()
            return self.spacing_c.out_max(self.max_points//8) + self.spacing_c.out_value(self.spacing) + self.crop_c.out_min(self.first_index) + self.crop_c.out_max(self.last_index) + self.crop_c.out_value((self.first_index, self.last_index))

    def frame(self):
        time.sleep(1/PLAY_RATE)
        return self.curr_frame

    def focus(self, state):
        pass

            

class MotionScope:

    def __init__(self):
        if not os.path.isdir(MEDIA_DIR):
            os.system(f"mkdir -p {MEDIA_DIR}")
        self.data = {}
        self.kapp = Vizy()

        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.camera.mode = "768x432x10bpp"
        width, height = calc_video_resolution(*self.camera.resolution)

        self.video = kritter.Kvideo(width=width, height=height)

        style = {"label_width": 3, "control_width": 6}
        self.camera_tab = Camera(self.kapp, self.data, self.camera, self.video)
        self.capture_tab = Capture(self.kapp, self.data, self.camera)
        self.process_tab = Process(self.kapp, self.data, self.camera)
        self.analyze_tab = Analyze(self.kapp, self.data, self.camera)
        self.tabs = [(self.camera_tab, self.kapp.new_id()),  (self.capture_tab, self.kapp.new_id()), (self.process_tab, self.kapp.new_id()), (self.analyze_tab, self.kapp.new_id())]
        self.tab = self.camera_tab

        self.file_options = [dbc.DropdownMenuItem("Save", disabled=True), dbc.DropdownMenuItem("Load")]
        self.file_menu = kritter.KdropdownMenu(name="File", options=self.file_options, nav=True)

        nav_items = [dbc.NavItem(dbc.NavLink(p[0].name, active=i==0, id=p[1], disabled=p[0].name=="Process" or p[0].name=="Analyze")) for i, p in enumerate(self.tabs)]
        nav_items.append(self.file_menu.control)
        nav_items.append(dbc.NavItem(dbc.NavLink(self.kapp.icon("info-circle"))))
        nav = dbc.Nav(nav_items, pills=True, navbar=True)
        navbar = dbc.Navbar(html.Div([html.Img(src="/media/vizy_eye.png", height="25px", style={"margin": "0 5px 10px 0"}), dbc.NavbarBrand("MotionScope"), nav]), color="dark", dark=True, expand=True, style={"max-width": WIDTH})

        self.save_progress_dialog = kritter.KprogressDialog(title="Saving...", shared=True)
        self.load_progress_dialog = kritter.KprogressDialog(title="Loading...", shared=True)

        self.kapp.layout = [html.Div([navbar, self.video, dbc.Card([t[0].layout for t in self.tabs], style={"max-width": f"{width-10}px", "margin": "5px"})], style={"margin": "15px"}), self.save_progress_dialog, self.load_progress_dialog]

        @self.file_menu.callback()
        def func(val):
            self.run_progress = True
            if val==0:
                Thread(target=self.save_load_progress, args=(self.save_progress_dialog, )).start()
                self.data['recording'].save(os.path.join(MEDIA_DIR, "out.raw"))
            elif val==1:
                self.data['recording'] = self.camera.stream(False)
                Thread(target=self.save_load_progress, args=(self.load_progress_dialog, )).start()
                self.data['recording'].load(os.path.join(MEDIA_DIR, "out.raw"))
            self.run_progress = False

        for t in self.tabs:
            func = self.get_tab_func(t)
            self.kapp.callback_shared(None, [Input(t[1], "n_clicks")])(func)
        
        @self.capture_tab.data_update_callback
        def func(changed):
            if "recording" in changed:
                self.recording_changed(self.capture_tab)

        @self.process_tab.data_update_callback
        def func(changed):
            if "obj_data" in changed:
                return self.obj_data_changed(self.process_tab)

        # Run main gui thread.
        self.run_thread = True
        Thread(target=self.thread).start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self.run_thread = False

    def get_tab_func(self, tab):
        mods = [Output(t[0].layout.id, "is_open", t is tab) for t in self.tabs] + [Output(t[1], "active", t is tab) for t in self.tabs]
        def func(val):
            self.tab.focus(False)
            self.tab = tab[0]
            self.tab.focus(True)
            return mods 
        return func

    def data_update(self, changed, tab):
        mods = []
        for t, _ in self.tabs:
            if not t is tab: # Don't call data_update on the originating tab.
                m = t.data_update(changed)
                if m:
                    mods += m 
        self.kapp.push_mods(mods)            

    def recording_changed(self, tab):
        self.data_update("recording", tab)
        if self.data['recording'].len()>BG_CNT_FINAL: 
            process_tab = self.find_tab("Process") 
            self.file_options[0].disabled = False
            return self.file_menu.out_options(self.file_options) + [Output(process_tab[1], "disabled", False)]

    def obj_data_changed(self, tab):
        self.data_update("obj_data", tab)
        analyze_tab = self.find_tab("Analyze") 
        if self.data['obj_data']:
            f = self.get_tab_func(analyze_tab)
            return [Output(analyze_tab[1], "disabled", False)] + f(None)
        else: 
            return [Output(analyze_tab[1], "disabled", True)]

    def find_tab(self, name):
        for t in self.tabs:
            if t[0].name==name:
                return t 
        raise RuntimeError()

    def save_load_progress(self, dialog):
        self.kapp.push_mods(dialog.out_progress(0) + dialog.out_open(True)) 

        # Update progress while file is being saved/loaded.
        while self.run_progress:
            progress = self.data['recording'].progress()
            self.kapp.push_mods(dialog.out_progress(progress*.9))
            time.sleep(1/UPDATE_RATE)

        # Save/load rest of data.
        filename = os.path.join(MEDIA_DIR, "out.json")
        # Save
        if dialog is self.save_progress_dialog: 
            with open(filename, 'w') as f:
                data = {"obj_data": self.data["obj_data"]}
                json.dump(data, f, cls=kritter.JSONEncodeFromNumpy) 
        # Load        
        else: 
            # Inform tabs that we have a recording.
            self.kapp.push_mods(self.recording_changed(None))
            try:
                with open(filename) as f:
                    data = json.load(f, cls=kritter.JSONDecodeToNumpy)
                self.data["obj_data"] = data['obj_data']
            except Exception as e:
                print(f"Error loading: {e}")
            else:
                # Inform tabs that we have object data.
                self.obj_data_changed(None)

        #self.kapp.push_mods(dialog.out_progress(100))     
        self.kapp.push_mods(dialog.out_open(False))

    def thread(self):
        while self.run_thread:
            # Get frame
            frame = self.tab.frame()
            # Send frame
            self.video.push_frame(frame)


if __name__ == "__main__":
    ms = MotionScope()