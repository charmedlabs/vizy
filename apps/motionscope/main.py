import os
import math
from threading import Thread, RLock
import kritter
import cv2
import numpy as np
import time
import json
import collections
from dash_devices import Services, callback_context
from dash_devices.dependencies import Input, Output, State
import dash_core_components as dcc
import dash_bootstrap_components as dbc
import dash_html_components as html
import plotly.graph_objs as go
from vizy import Vizy
from centroidtracker import CentroidTracker

"""
todo:

figure out color scheme and whether to use card for tabs

vizyvisor nav -- include info button, navbar style in app.info (including no navbar)
Draw shape -- play, record, pause in capture instead of displaying message
One video mode for camera
get rid of make_divisible, calc_video_resolution, MAX_AREA.  Push that into Kvideo as default sizing logic.  Also fix max_width for KvideoComponent while we're at it, and tab controls
to reflect the max_width (instead of 640). 
Turn off camera streaming when processing, playing, analyzing.  
Create consts file for values that are rarely used

Thumbnail image for motionscope and birdfeeder
Constant bitrate for encoder


testing:
test null case (no motion)
test short vid < BG_CNT_FINAL frames
transitions -- load file while processing, move to capture while processing (then back again)

documentation:
data:
0 pts
1 index
2 x centroid
3 y centroid
4 rect-x
5 rect-y
6 rect-width
7 rect-height

"""

MAX_RECORDING_DURATION = 10 # seconds
PADDING = 10
UPDATE_RATE = 10 # updates/second
PLAY_RATE = 30 # frames/second
WIDTH = 736
APP_DIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(APP_DIR, "media")
GRAPHS = 6
HIGHLIGHT_TIMEOUT = 0.25
GRAPH_UPDATE_TIMEOUT = 0.15


class DataUpdate:
    def __init__(self, data):
        self.data = data
        self.data_update_callback_func = None

    # cmem allows the retention of call information to prevent infinite loops,
    # feed forward call information, etc.
    def data_update(self, changed, cmem=None):
        return []

    def call_data_update_callback(self, changed, cmem=None):
        if self.data_update_callback_func:
            return self.data_update_callback_func(changed, cmem)

    def data_update_callback(self, func):
        self.data_update_callback_func = func


class Tab(DataUpdate):
    def __init__(self, name, kapp, data):
        super().__init__(data)
        self.name = name
        self.kapp = kapp

    def frame(self):
        return None

    def focus(self, state):
        return []


class Camera(Tab):

    def __init__(self, kapp, data, camera, video):

        super().__init__("Camera", kapp, data)
        self.kapp = kapp
        self.stream = camera.stream()
        style = {"label_width": 3, "control_width": 6}

        modes = ["640x480x10bpp (cropped)", "768x432x10bpp", "1280x720x10bpp"]
        self.data[self.name]["mode"] = camera.mode
        self.mode = kritter.Kdropdown(name='Camera mode', options=modes, value=camera.mode, style=style)

        self.data[self.name]["brightness"] = camera.brightness
        self.brightness = kritter.Kslider(name="Brightness", value=camera.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style=style)

        self.data[self.name]["framerate"] = camera.framerate
        self.framerate = kritter.Kslider(name="Framerate", value=camera.framerate, mxs=(camera.min_framerate, camera.max_framerate, 1), format=lambda val : f'{val} fps', style=style)

        self.data[self.name]["autoshutter"] = camera.autoshutter
        self.autoshutter = kritter.Kcheckbox(name='Auto-shutter', value=camera.autoshutter, style=style)

        self.data[self.name]["shutter"] = camera.shutter_speed
        self.shutter = kritter.Kslider(name="Shutter-speed", value=camera.shutter_speed, mxs=(.0001, 1/camera.framerate, .0001), format=lambda val: f'{val:.4f}s', style=style)
        shutter_cont = dbc.Collapse(self.shutter, id=kapp.new_id(), is_open=not camera.autoshutter, style=style)

        self.data[self.name]["awb"] = camera.awb
        self.awb = kritter.Kcheckbox(name='Auto-white-balance', value=camera.awb, style=style)

        self.data[self.name]["red_gain"] = camera.awb_red
        self.red_gain = kritter.Kslider(name="Red gain", value=camera.awb_red, mxs=(0.05, 2.0, 0.01), style=style)

        self.data[self.name]["blue_gain"] = camera.awb_blue
        self.blue_gain = kritter.Kslider(name="Blue gain", value=camera.awb_blue, mxs=(0.05, 2.0, 0.01), style=style)

        awb_gains = dbc.Collapse([self.red_gain, self.blue_gain], id=kapp.new_id(), is_open=not camera.awb)   

        self.settings_map = {"mode": self.mode, "brightness": self.brightness, "framerate": self.framerate, "autoshutter": self.autoshutter, "shutter": self.shutter, "awb": self.awb, "red_gain": self.red_gain, "blue_gain": self.blue_gain}

        @self.mode.callback()
        def func(value):
            self.data[self.name]["mode"] = value
            camera.mode = value
            return video.out_width(WIDTH) + self.framerate.out_value(camera.framerate) + self.framerate.out_min(camera.min_framerate) + self.framerate.out_max(camera.max_framerate)

        @self.brightness.callback()
        def func(value):
            self.data[self.name]["brightness"] = value
            camera.brightness = value

        @self.framerate.callback()
        def func(value):
            self.data[self.name]["framerate"] = value
            camera.framerate = value
            return self.shutter.out_value(camera.shutter_speed) + self.shutter.out_max(1/camera.framerate)

        @self.autoshutter.callback()
        def func(value):
            self.data[self.name]["autoshutter"] = value
            camera.autoshutter = value
            return Output(shutter_cont.id, 'is_open', not value)

        @self.shutter.callback()
        def func(value):
            self.data[self.name]["shutter"] = value
            camera.shutter_speed = value    

        @self.awb.callback()
        def func(value):
            self.data[self.name]["awb"] = value
            camera.awb = value
            return Output(awb_gains.id, 'is_open', not value)

        @self.red_gain.callback()
        def func(value):
            self.data[self.name]["red_gain"] = value
            camera.awb_red = value

        @self.blue_gain.callback()
        def func(value):
            self.data[self.name]["blue_gain"] = value
            camera.awb_blue = value
         
        self.layout = dbc.Collapse([self.mode, self.brightness, self.framerate, self.autoshutter, shutter_cont, self.awb, awb_gains], id=kapp.new_id(), is_open=True)

    def settings_update(self, settings):
        # Copy settings because setting framerate (for example) sets shutter.
        settings = settings.copy() 
        for k, s in self.settings_map.items():
            try: 
                # Individually set each setting.  This will make sure they are 
                # set in order, which is important (e.g. shutter needs to be set last.)
                self.kapp.push_mods(s.out_value(settings[k]))
            except:
                pass
        return []

    def data_update(self, changed, cmem=None):
        mods = []
        if self.name in changed:
            mods += self.settings_update(self.data[self.name])
        return mods
    
    def frame(self):
        return self.stream.frame()[0]



class Capture(Tab):

    def __init__(self, kapp, data, camera):

        super().__init__("Capture", kapp, data)
        self.ratio = 0.1
        self.update_timer = 0
        self.curr_frame = None
        self.prev_mods = []
        self.camera = camera
        self.data["recording"] = None
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
        self.stop_button = kritter.Kbutton(name=[kapp.icon("stop"), "Stop"], disabled=True)
        self.step_backward = kritter.Kbutton(name=kapp.icon("step-backward", padding=0), disabled=True)
        self.step_forward = kritter.Kbutton(name=kapp.icon("step-forward", padding=0), disabled=True)
        self.more_c = kritter.Kbutton(name=kapp.icon("plus", padding=0))

        self.record.append(self.play)
        self.record.append(self.stop_button)
        self.record.append(self.step_backward)
        self.record.append(self.step_forward)
        #self.record.append(self.more_c)

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
        self.layout = dbc.Collapse([self.playback_c, self.status, self.record, more_controls], id=kapp.new_id(), is_open=False)

        @self.more_c.callback()
        def func():
            self.more = not self.more
            return self.more_c.out_name(kapp.icon("minus", padding=0) if self.more else kapp.icon("plus", padding=0)) + [Output(more_controls.id, "is_open", self.more)]

        @self.record.callback()
        def func():
            self.data['recording'] = self.camera.record(duration=self.duration, start_shift=self.start_shift)
            self.new_recording = True
            self.playing = False
            self.paused = False
            return self.update()

        @self.play.callback()
        def func():
            if self.playing:
                self.paused = not self.paused
            self.playing = True
            return self.update()

        self.stop_button.callback()(self.stop)

        @self.step_backward.callback()
        def func():
            self.playing = True  
            self.paused = True 
            self.data["recording"].seek(self.curr_frame[2]-1)
            frame = self.data["recording"].frame()
            return self.playback_c.out_value(frame[1])

        @self.step_forward.callback()
        def func():
            self.playing = True  
            self.paused = True 
            frame = self.data["recording"].frame()
            if frame is not None:
                return self.playback_c.out_value(frame[1])


        @self.playback_c.callback()
        def func(t):
            # Check for client dragging slider when we're stopped, in which case, 
            # go into paused state.
            if not self.playing and not self.data["recording"].recording() and callback_context.client and t!=0:
                self.playing = True 
                self.paused = True

            if self.playing:
                # Only seek if client actually dragged slider, not when we set it ourselves.
                if callback_context.client:
                    t = self.data["recording"].time_seek(t) # Update time to actual value.
                if self.paused:
                    self.curr_frame = self.data["recording"].frame()
                    time.sleep(1/UPDATE_RATE)

            return self.playback_c.out_text(f"{t:.3f}s")

    def stop(self):
        self.playing = False
        self.paused = False
        if self.data["recording"]:
            self.data["recording"].stop()
            self.data["recording"].seek(0)
        return self.update()

    def play_name(self):
        return [self.kapp.icon("pause"), "Pause"] if self.playing and not self.paused else [self.kapp.icon("play"), "Play"]

    def update(self, cmem=None):
        mods = []
        if self.data["recording"]:
            t = self.data["recording"].time() 
            tlen = self.data["recording"].time_len()
            mods += self.play.out_name(self.play_name()) 
            if self.playing:
                if self.paused:
                    mods += self.step_backward.out_disabled(self.curr_frame[2]==0) + self.step_forward.out_disabled(self.curr_frame[2]==self.data["recording"].len()-1) + self.status.out_value("Paused")
                else: 
                    mods += self.playback_c.out_disabled(False) + self.step_backward.out_disabled(True) + self.step_forward.out_disabled(True) + self.playback_c.out_value(t) + self.status.out_value("Playing...") 
                mods += self.record.out_disabled(True) + self.stop_button.out_disabled(False) + self.play.out_disabled(False) + self.playback_c.out_max(tlen) 
            elif self.data["recording"].recording()>0:
                mods += self.playback_c.out_disabled(True) + self.record.out_disabled(True) + self.stop_button.out_disabled(False) + self.play.out_disabled(True) + self.step_backward.out_disabled(True) + self.step_forward.out_disabled(True) + self.playback_c.out_max(self.duration) + self.status.out_value("Recording...") + self.playback_c.out_value(tlen)
            else: # Stopped
                mods += self.playback_c.out_disabled(False) + self.playback_c.out_max(tlen) + self.playback_c.out_value(0) + self.record.out_disabled(False) + self.stop_button.out_disabled(True) + self.step_backward.out_disabled(True) + self.step_forward.out_disabled(False) + self.play.out_disabled(False) + self.status.out_value("Stopped") + ["stop_marker"]

        # Find new mods with respect to the previous mods
        diff_mods = [m for m in mods if not m in self.prev_mods]
        # Save current mods
        self.prev_mods = mods 
        # Stop marker allows us to see the stop event by detecting it in diff_mods.
        if "stop_marker" in diff_mods:
            diff_mods.remove("stop_marker")
            if self.new_recording:
                self.new_recording = False # This prevents a loaded video (from Load) from triggering recording_update
                self.data['recording'] = self.data["recording"]
                if cmem is None:
                    self.kapp.push_mods(diff_mods)
                    diff_mods = self.call_data_update_callback("recording", 1) 
        # Only send new mods
        return diff_mods    

    def data_update(self, changed, cmem=None):
        mods = []
        if "recording" in changed and cmem is None:
            self.playing = False
            self.paused = False
            mods += self.update(1)
        return mods

    def frame(self):
        update = False

        if self.playing:
            if not self.paused:
                self.curr_frame = self.data['recording'].frame()
                if self.curr_frame is None:
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

        if self.playing and self.curr_frame is not None: # play recording
            return self.curr_frame[0], 1/PLAY_RATE
        else: # stream live
            frame = self.stream.frame()
            if frame:
                return frame[0]

    def focus(self, state):
        return self.stop()


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

def merge_data(map, add):
    for i, d in add.items():
        if i in map:
            map[i] = np.vstack((map[i], d))
        else:
            map[i] = np.array([d])


class FuncTimer:
    def __init__(self, timeout):
        self.active = False
        self.timeout = timeout

    def start(self, func):
        self.t0 = time.time()
        self.func = func
        self.active = True

    def update(self, *argv):
        if not self.active:
            return False
        t = time.time()
        if t-self.t0>self.timeout:
            self.fire()
            return True
        else:
            return False

    def fire(self, *argv):
        self.active = False
        self.func(*argv)

    def cancel(self):
        self.active = False

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

        self.data[self.name]["motion_threshold"] = self.motion_threshold.inval
        self.motion_threshold_c = kritter.Kslider(name="Motion threshold", value=self.motion_threshold.inval, mxs=(1, 100, 1), format=lambda val: f'{val:.0f}%', style=style)

        more_controls = dbc.Collapse([self.motion_threshold_c], id=kapp.new_id(), is_open=False)
        self.layout = dbc.Collapse([self.playback_c, self.process_button, more_controls], id=kapp.new_id(), is_open=False)

        @self.more_c.callback()
        def func():
            self.more = not self.more
            return self.more_c.out_name(kapp.icon("minus", padding=0) if self.more else kapp.icon("plus", padding=0)) + [Output(more_controls.id, "is_open", self.more)]

        @self.motion_threshold_c.callback()
        def func(val):
            self.data[self.name]["motion_threshold"] = val
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
        if state:
            self.stream.stop()
            if self.state!=FINISHED: # Only process if we haven't processed this video first (not finished)
                return self.set_state(PROCESSING)


OBJECTS = 1
POINTS = 2
LINES = 4
ARROWS = 8 

class Graphs():

    def __init__(self, kapp, data, spacing_map, settings_map, lock, video, num_graphs, style):
        self.kapp = kapp
        self.data = data
        self.spacing_map = spacing_map
        self.settings_map = settings_map
        self.name = "Analyze"
        self.lock = lock
        self.video = video
        self.num_graphs = num_graphs
        self.calib_pixels = None
        self.highlight_timer = FuncTimer(HIGHLIGHT_TIMEOUT)
        self.unhighlight_timer = FuncTimer(HIGHLIGHT_TIMEOUT)
        self.highlight_data = None
        self.highlight_lock = RLock()

        # Each map member: (abbreviation, units/meter)
        self.units_map = {"pixels": ("px", 1), "meters": ("m", 1), "centimeters": ("cm", 100), "feet": ("ft", 3.28084), "inches": ("in", 39.3701)}
        self.units_list = [u for u, v in self.units_map.items()]
        self.graph_descs = {"x, y position": ("x position", "y position", ("{}", "{}"), self.xy_pos), "x, y velocity": ("x velocity", "y velocity", ("{}/s", "{}/s"), self.xy_vel), "x, y acceleration": ("x acceleration", "y acceleration", ("{}/s^2", "{}/s^2"), self.xy_accel), "velocity magnitude, direction": ("velocity magnitude", "velocity direction", ("{}/s", "deg"), self.md_vel),  "acceleration magnitude, direction": ("accel magnitude", "accel direction", ("{}/s^2", "deg"), self.md_accel)}

        self.units = "pixels"
        self.data[self.name]['units'] = self.units

        self.num_units = 1
        self.data[self.name]["num_units"] = self.num_units
        self.units_info = self.units_map[self.units]
        self.units_per_pixel = 1 

        self.options = [k for k, v in self.graph_descs.items()]
        self.selections = self.options[0:self.num_graphs//2]
        for i in range(self.num_graphs//2):
            self.data[self.name][f"graph{i}"] = i

        style_dropdown = style.copy()
        style_dropdown["control_width"] = 5 
        self.units_c = kritter.Kdropdown(name='Distance units', options=self.units_list, value=self.units_list[0], style=style_dropdown)

        self.show_options_map = {"objects": OBJECTS, "objects, points": OBJECTS+POINTS, "objects, points, lines": OBJECTS+POINTS+LINES, "objects, points, lines, arrows": OBJECTS+POINTS+LINES+ARROWS}
        show_options_list = [k for k, v in self.show_options_map.items()]
        self.show_options = self.show_options_map[show_options_list[0]]
        self.show_options_c = kritter.Kdropdown(name='Show', options=show_options_list, value=show_options_list[0], style=style_dropdown)

        self.calib = kritter.Ktext(name="Calibration", style=style)
        self.calib_ppu = dbc.Col(id=self.kapp.new_id(), width="auto", style={"padding": "5px"})
        self.calib_input = dbc.Input(value=self.num_units, id=self.kapp.new_id(), type='number', style={"width": 75})
        self.calib_units = dbc.Col(id=self.kapp.new_id(), width="auto", style={"padding": "5px"})
        self.calib.set_layout(None, [self.calib.label, self.calib_ppu, dbc.Col(self.calib_input, width="auto", style={"padding": "0px"}), self.calib_units])
        self.calib_button = kritter.Kbutton(name=[kapp.icon("calculator"), "Calibrate..."])
        self.calib.append(self.calib_button)
        self.calib_collapse = dbc.Collapse(self.calib, is_open=False, id=self.kapp.new_id())

        # Controls layout
        self.controls_layout = [self.show_options_c, self.units_c, self.calib_collapse]
        
        # Graphs layout
        self.graphs = []
        self.menus = []
        self.layout = []

        for i in range(0, self.num_graphs, 2):
            g0 = dcc.Graph(id=self.kapp.new_id(), clear_on_unhover=True, config={'displayModeBar': False})
            g1 = dcc.Graph(id=self.kapp.new_id(), clear_on_unhover=True, config={'displayModeBar': False})
            self.kapp.callback(None, [Input(g0.id, "hoverData")])(self.get_highlight_func(i))
            self.kapp.callback(None, [Input(g1.id, "hoverData")])(self.get_highlight_func(i+1))
            self.graphs.extend((g0, g1))
            menu = kritter.KdropdownMenu(options=self.items())
            self.menus.append(menu)
            self.layout.append(dbc.Row(dbc.Col(menu))) 
            self.layout.append(dbc.Row([dbc.Col(g0), dbc.Col(g1)]))
            menu.callback()(self.get_menu_func(i//2))
        self.layout = html.Div(html.Div(self.layout, style={"margin": "5px", "float": "left"}), id=self.kapp.new_id(), style={'display': 'none'})

        def set_pixels(val):
            self.calib_pixels = val
            return self.update_units()

        self.settings_map.update({f"graph{i}": self.get_menu_func(i) for i in range(self.num_graphs//2)})
        self.settings_map.update({"show_options": self.show_options_c.out_value, "units": self.units_c.out_value, "num_units": lambda val: [Output(self.calib_input.id, "value", val)], "calib_pixels": set_pixels})

        self.video.callback_hover()(self.get_highlight_func(self.num_graphs))

        @self.video.callback_draw()
        def func(val):
            try:
                for k, v in val.items():
                    x = v[0]['x1'] - v[0]['x0']
                    y = v[0]['y1'] - v[0]['y0']
                    length = (x**2 + y**2)**0.5
                    break  
            except: # in case we get unknown callbacks
                return            
            self.video.draw_user(None)
            self.calib_pixels = length
            self.data[self.name]["calib_pixels"] = length
            #  pixels/num_units units / num_units * units/meter = pixels/meter   
            #  1/pixel/meter = meter/pixel
            return self.update_units()

        @self.units_c.callback()
        def func(val):
            units_old_per_meter = self.units_info[1]
            self.units = val
            self.data[self.name]["units"] = val
            self.units_info = self.units_map[val]
            if self.calib_pixels:
                # pixels/num_units units_old * units_old/meter / units_new/meter = pixels/num_units units_new
                self.calib_pixels *= units_old_per_meter/self.units_info[1]
            return self.update_units() 

        @self.show_options_c.callback()
        def func(val):
            self.show_options = self.show_options_map[val]
            self.data[self.name]["show_options"] = val
            return self.out_draw()

        @self.calib_button.callback()
        def func():
            self.video.draw_user("line", line=dict(color="rgba(0, 255, 0, 0.80)"))
            self.video.draw_graph_data(None)
            self.video.draw_clear()
            self.video.draw_text(self.video.source_width/2, self.video.source_height/2, "Point and drag to draw a calibration line.")
            return self.video.out_draw_overlay()

        @self.kapp.callback_shared(None, [Input(self.calib_input.id, "value")])
        def func(num_units):
            if num_units:
                self.num_units = num_units
                self.data[self.name]["num_units"] = num_units
                return self.update_units()


    def unhighlight(self):
        self.kapp.push_mods(self.out_draw())

    def highlight(self):
        with self.highlight_lock:
            keys = list(self.spacing_map.keys())
            index, data = self.highlight_data
            for k, v in data.items():
                # curveNumber is the nth curve, which doesn't necessarily correspond
                # to the key value in spacing_map.
                mods = self.out_draw((index, keys[v[0]['curveNumber']], v[0]['pointIndex']))
                self.kapp.push_mods(mods)
                return

    def update_units(self):
        if self.units=="pixels":
            self.units_per_pixel = 1
            mods = []
        elif self.num_units and self.calib_pixels:
            self.units_per_pixel = self.num_units/self.calib_pixels  
            mods = [Output(self.calib_ppu.id, "children", f"{self.calib_pixels:.2f} pixels per")]  
        else:
            self.units_per_pixel = 1 
            mods = [Output(self.calib_ppu.id, "children", f"? pixels per")]
        return mods + [Output(self.calib_units.id, "children", f"{self.units}.")] + [Output(self.calib_collapse.id, "is_open", self.units!="pixels")] + self.out_draw()

    def draw_arrow(self, p0, p1, color):
        D0 = 9 # back feather
        D1 = 7 # width
        D2 = 12 # back feather tip
        dx = p1[0]-p0[0]
        dy = p1[1]-p0[1]
        h = (dx*dx + dy*dy)**0.5
        ca = dx/h
        sa = dy/h
        tx = p1[0] - ca*D2
        ty = p1[1] - sa*D2
        points = [(p1[0], p1[1]), (tx - sa*D1, ty + ca*D1), (p1[0] - ca*D0, p1[1] - sa*D0), (tx + sa*D1, ty - ca*D1)]
        self.video.draw_shape(points, fillcolor=color, line={"color": "black", "width": 1})

    def items(self):
        return [dbc.DropdownMenuItem(i, disabled=i in self.selections) for i in self.options]

    def get_highlight_func(self, index):
        def func(data):
            with self.highlight_lock:
                if data:
                    self.highlight_data = index, data
                    self.highlight_timer.start(self.highlight)
                    self.unhighlight_timer.cancel()
                else:
                    self.unhighlight_timer.start(self.unhighlight)
                    self.highlight_timer.cancel()
        return func

    def get_menu_func(self, index):
        def func(val):
            self.selections[index] = self.options[val]
            self.data[self.name][f"graph{index}"] = val
            mods = []
            for menu in self.menus:
                mods += menu.out_options(self.items())
            return mods + self.out_draw()
        return func

    def figure(self, title, units, data, annotations):
        layout = dict(title=title, 
            yaxis=dict(zeroline=False, title=f"{title} ({units})"),
            xaxis=dict(zeroline=False, title='time (seconds)'),
            annotations=annotations,
            showlegend=False,
            hovermode='closest',
            width=300, 
            height=200, 
            #xpad=20,
            margin=dict(l=50, b=30, t=25, r=5))
        return dict(data=data, layout=layout)

    def differentiate(self, x, y):
        x_ = x[:-1] 
        xdiff = x[1:] - x_
        y_ = (y[1:]-y[:-1])/xdiff
        return x_, y_

    def scatter(self, x, y, k, units):
        return go.Scatter(x=x, y=y, hovertemplate='(%{x:.3f}s, %{y:.3f}'+units+')', line=dict(color=kritter.get_rgb_color(int(k), html=True)), mode='lines+markers', name='')        

    def add_highlight(self, highlight, k, trace, annotations, domain, range_):
        if highlight and highlight[1]==k:
            # Velocity and acceleration domains are smaller than position.
            # If index is out of range, just exit.
            try:            
                x = domain[highlight[2]]
                y = range_[highlight[2]]
            except:
                return
            text = trace['hovertemplate'].replace('%', '').format(x=x, y=y)

            if x<(domain[-1]+domain[0])/2:
                ax = 6
                xanchor = 'left'
            else:
                ax = -6
                xanchor = 'right'
            annotations.append(dict(x=x, y=y, xref="x", yref="y", text=text, font=dict(color="white"), borderpad=3, showarrow=True, ax=ax, ay=0, xanchor=xanchor, arrowcolor="black", bgcolor=trace['line']['color'], bordercolor="white"))            

    def xy_pos(self, i, units, highlight):
        data = []
        annotations = []
        height = self.data["bg"].shape[0]
        for k, d in self.spacing_map.items():
            domain = d[:, 0]
            if i==0: # x position 
                range_ = d[:, 2]*self.units_per_pixel 
            else: # y position
                # Camera coordinates start at top, so we need to adjust y axis accordingly.
                range_ = (height-1-d[:, 3])*self.units_per_pixel
            trace = self.scatter(domain, range_, k, units)
            data.append(trace)
            self.add_highlight(highlight, k, trace, annotations, domain, range_)
        return data, annotations

    def xy_vel(self, i, units, highlight):
        data = []
        annotations = []
        for k, d in self.spacing_map.items():
            if i==0: # x velocity
                domain, range_ = self.differentiate(d[:, 0], d[:, 2])
                range_ *= self.units_per_pixel
            else: # y velocity
                domain, range_ = self.differentiate(d[:, 0], d[:, 3])
                # Camera coordinates start at top and go down 
                # so we need to flip sign for y axis.                
                range_ *= -self.units_per_pixel
            trace = self.scatter(domain, range_, k, units)
            data.append(trace)
            self.add_highlight(highlight, k, trace, annotations, domain, range_)
        return data, annotations

    def xy_accel(self, i, units, highlight):
        data = []
        annotations = []
        for k, d in self.spacing_map.items():
            if i==0: # x accel
                domain, range_ = self.differentiate(d[:, 0], d[:, 2])
                domain, range_ = self.differentiate(domain, range_)
                range_ *= self.units_per_pixel
            else: # y accel
                domain, range_ = self.differentiate(d[:, 0], d[:, 3])
                domain, range_ = self.differentiate(domain, range_)
                # Camera coordinates start at top and go down 
                # so we need to flip sign for y axis.                
                range_ *= -self.units_per_pixel
            trace = self.scatter(domain, range_, k, units)
            data.append(trace)
            self.add_highlight(highlight, k, trace, annotations, domain, range_)
        return data, annotations

    def md_vel(self, i, units, highlight):
        data = []
        annotations = []
        for k, d in self.spacing_map.items():
            domain, range_x = self.differentiate(d[:, 0], d[:, 2])
            domain, range_y = self.differentiate(d[:, 0], d[:, 3])
            if i==0: # velocity magnitude
                range_ = (range_x*range_x + range_y*range_y)**0.5 # vector magnitude
                range_ *= self.units_per_pixel
            else: # velocity direction
                # Camera coordinates start at top and go down 
                # so we need to flip sign for y axis.                
                range_ = np.arctan2(-range_y, range_x)
                range_ *= 180/math.pi # radians to degrees
            trace = self.scatter(domain, range_, k, units)
            data.append(trace)
            self.add_highlight(highlight, k, trace, annotations, domain, range_)
        return data, annotations

    def md_accel(self, i, units, highlight):
        data = []
        annotations = []
        for k, d in self.spacing_map.items():
            domain, range_x = self.differentiate(d[:, 0], d[:, 2])
            domain, range_x = self.differentiate(domain, range_x)
            domain, range_y = self.differentiate(d[:, 0], d[:, 3])
            domain, range_y = self.differentiate(domain, range_y)
            if i==0: # acceleration magnitude
                range_ = (range_x*range_x + range_y*range_y)**0.5
                range_ *= self.units_per_pixel
            else: # velocity direction
                # Camera coordinates start at top and go down 
                # so we need to flip sign for y axis.                
                range_ = np.arctan2(-range_y, range_x)
                range_ *= 180/math.pi # radians to degrees
            trace = self.scatter(domain, range_, k, units)
            data.append(trace)
            self.add_highlight(highlight, k, trace, annotations, domain, range_)
        return data, annotations

    def out_draw_video(self, highlight):
        self.video.draw_clear()
        data =[]
        height = self.data["bg"].shape[0]
        units = self.units_info[0]
        if highlight and highlight[0]==self.num_graphs: # Don't highlight if we're hovering on this graph.
            highlight = None 
            self.video.overlay_annotations.clear()
        for i, d in self.spacing_map.items():
            color = kritter.get_rgb_color(int(i), html=True)
            x = d[:, 2]*self.units_per_pixel 
            y = (height-1-d[:, 3])*self.units_per_pixel
            customdata = np.column_stack((d[:, 0], x, y))
            hovertemplate = '%{customdata[0]:.3f}s (%{customdata[1]:.3f}'+units+', %{customdata[2]:.3f}'+units+')'
            obj_color = kritter.get_rgb_color(int(i), html=True)
            if self.show_options&POINTS:
                color = obj_color
                marker = dict(size=8, line=dict(width=1, color='black'))   
            else:
                color = "rgba(0,0,0,0)" 
                marker = dict(size=8)
            mode = "markers" if not self.show_options&LINES else "lines+markers"
            data.append(go.Scatter(x=d[:, 2], y=d[:, 3], 
                line=dict(color=color), mode=mode, name='', hovertemplate=hovertemplate, hoverlabel=dict(bgcolor=obj_color), customdata=customdata, marker=marker))
            if self.show_options&ARROWS:
                for i, d_ in enumerate(d):
                    if i<len(d)-1:
                        self.draw_arrow(d_[2:4], d[i+1][2:4], obj_color)
            if highlight and highlight[1]==i:
                text = hovertemplate.replace('%', '').format(customdata=customdata[highlight[2]])
                x = d[highlight[2], 2]
                y = d[highlight[2], 3]
                if x<self.video.source_width//2:
                    ax = 6
                    xanchor = 'left'
                else:
                    ax = -6
                    xanchor = 'right'
                self.video.overlay_annotations.append(dict(x=x, y=y, xref="x", yref="y", text=text, font=dict(color="white"), borderpad=3, showarrow=True, ax=ax, ay=0, xanchor=xanchor, arrowcolor="black", bgcolor=obj_color, bordercolor="white"))

        self.video.draw_graph_data(data)
        return self.video.out_draw_overlay() 

    def out_draw(self, highlight=None):
        with self.lock:
            mods = self.out_draw_video(highlight)
            for i, g in enumerate(self.selections):
                desc = self.graph_descs[g]
                for j in range(2):
                    title = desc[j]
                    units = desc[2][j].format(self.units_info[0])
                    # Don't highlight if we're hovering on this graph.
                    if highlight and highlight[0]==i*2+j: 
                        data, annotations = desc[3](j, units, None)
                    else:
                        data, annotations = desc[3](j, units, highlight)                        
                    figure = self.figure(title, units, data, annotations)
                    mods += [Output(self.graphs[i*2+j].id, "figure", figure)]
            return mods

    def out_disp(self, disp):
        if disp:
            mods = [Output(self.layout.id, "style", {'display': 'block'})]
        else:
            mods = [Output(self.layout.id, "style", {'display': 'none'})]
        return self.video.out_overlay_disp(disp) + mods

    def update(self):
        self.highlight_timer.update()
        self.unhighlight_timer.update()

class Analyze(Tab):

    def __init__(self, kapp, data, video, num_graphs):

        super().__init__("Analyze", kapp, data)
        self.lock = RLock()
        self.graph_update_timer = FuncTimer(GRAPH_UPDATE_TIMEOUT)
        self.data_spacing_map = {}
        style = {"label_width": 2, "control_width": 7, "max_width": 726}

        self.spacing_c = kritter.Kslider(name="Spacing", mxs=(1, 10, 1), updaterate=6, style=style)
        self.time_c = kritter.Kslider(name="Time", range=True, value=[0, 10], mxs=(0, 10, 1), updaterate=6, style=style)

        self.settings_map = {"spacing": self.spacing_c.out_value, "time": self.time_c.out_value}
        self.graphs = Graphs(self.kapp, self.data, self.data_spacing_map, self.settings_map, self.lock, video, num_graphs, style) 

        self.layout = dbc.Collapse([self.spacing_c, self.time_c] + self.graphs.controls_layout, id=self.kapp.new_id())

        @self.spacing_c.callback()
        def func(val):
            self.data[self.name]["spacing"] = val
            self.spacing = val
            self.render()

        @self.time_c.callback()
        def func(val):
            self.data[self.name]["time"] = val     
            self.curr_first_index, self.curr_last_index = val
            self.render()


    def precompute(self):
        # Keep in mind that self.data['obj_data'] may have multiple objects with
        # data point indexes that don't correspond perfectly with data point indexes
        # of sibling objects.
        max_points = []
        ptss = []
        indexes = []
        self.data_index_map = collections.defaultdict(dict)
        for k, data in self.data['obj_data'].items():
            max_points.append(len(data))
            ptss = np.append(ptss, data[:, 0])  
            indexes = np.append(indexes, data[:, 1]).astype(int)
            for d in data:
                self.data_index_map[int(d[1])][k] = d
        self.time_index_map = dict(zip(list(indexes), list(ptss))) 
        self.time_index_map = dict(sorted(self.time_index_map.items()))
        self.indexes = list(self.time_index_map.keys()) # sorted and no duplicates
        ptss = np.array(list(self.time_index_map.values())) # sorted and no duplicates
        self.curr_first_index = self.indexes[0]
        self.curr_last_index = self.indexes[-1]
        # Periods can be greater than actual frame period because of dropped frames.
        # Finding the minimum period of all frames is overkill, but gets us what we want.   
        self.frame_period = np.min(ptss[1:]-ptss[:-1]) 
        self.zero_index_map = dict(zip(self.indexes, [0]*len(self.indexes)))
        self.curr_render_index_map = self.zero_index_map.copy()
        self.max_points = max(max_points)

    def recompute(self):
        self.data_spacing_map.clear() 
        self.next_render_index_map = self.zero_index_map.copy()
        self.next_render_index_map[self.curr_first_index] = 1
        t0 = self.time_index_map[self.curr_first_index]
        merge_data(self.data_spacing_map, self.data_index_map[self.curr_first_index])
        for i, t in self.time_index_map.items():
            if i>self.curr_last_index:
                break
            if t-t0>=self.frame_period*(self.spacing-0.5):
                self.next_render_index_map[i] = 1
                merge_data(self.data_spacing_map, self.data_index_map[i])
                t0 = t

    def compose_frame(self, index, val):
        if val>0:
            self.data['recording'].seek(index)
            frame = self.data['recording'].frame()[0]
        else:
            frame = self.data['bg']
        dd = self.data_index_map[index]  
        for k, d in dd.items():
            self.pre_frame[int(d[5]):int(d[5]+d[7]), int(d[4]):int(d[4]+d[6]), :] = frame[int(d[5]):int(d[5]+d[7]), int(d[4]):int(d[4]+d[6]), :]

    def compose(self):
        next_values = list(self.next_render_index_map.values())
        diff = list(np.array(next_values) - np.array(list(self.curr_render_index_map.values())))
        for i, d in enumerate(diff):
            # If i in diff is -1 (erase) change diff's neighbors within distance n=3 to 
            # to 1's if next_value at same location is 1. (This is needed because objects overlap
            # between frames.)
            if d<0:
                for j in range(3):
                    if i>j and next_values[i-j-1]>0:
                        diff[i-j-1] = 1
                    if i<len(next_values)-j-1 and next_values[i+j+1]>0:
                        diff[i+j+1] = 1

        diff_map = dict(zip(self.indexes, diff))

        # Erase all objects first
        for i, v in diff_map.items():
            if v<0: 
                self.compose_frame(i, v)
        # Then add objects
        for i, v in diff_map.items():
            if v>0: 
                self.compose_frame(i, v)

        self.curr_render_index_map = self.next_render_index_map
        self.curr_frame = self.pre_frame.copy()

    def graph_update(self):
        self.kapp.push_mods(self.graphs.out_draw())

    def render(self):
        with self.lock:
            self.recompute()
            self.compose()
            self.graph_update_timer.start(self.graph_update)

    def data_update(self, changed, cmem=None):
        if self.name in changed:
            # Copy before we push any mods, because the mods will change the values
            # when the callbacks are called.
            settings = self.data[self.name].copy()

        if "obj_data" in changed and self.data['obj_data']:
            self.pre_frame = self.data['bg'].copy()
            self.spacing = 1
            self.precompute()
            self.time_c.set_format(lambda val : f'{self.time_index_map[val[0]]:.3f}s → {self.time_index_map[val[1]]:.3f}s')
            # Send mods off because they might conflict with mods self.name, and 
            # calling push_mods forces calling render() early. 
            self.kapp.push_mods(self.spacing_c.out_max(self.max_points//8) + self.spacing_c.out_value(self.spacing) + self.time_c.out_min(self.indexes[0]) + self.time_c.out_max(self.indexes[-1]) + self.time_c.out_value((self.curr_first_index, self.curr_last_index)))

        if self.name in changed:
            for k, s in self.settings_map.items():
                try:
                    # Push each mod individually because of they will affect each other
                    self.kapp.push_mods(s(settings[k]))
                except:
                    pass
        return []

    def frame(self):
        self.graphs.update()
        self.graph_update_timer.update()
        time.sleep(1/PLAY_RATE)
        return self.curr_frame

    def focus(self, state):
        if state:
            return self.graphs.out_disp(True)
        else:
            return self.graphs.out_disp(False)   


# Do a nested dictionary update
def deep_update(d1, d2):
    if all((isinstance(d, dict) for d in (d1, d2))):
        for k, v in d2.items():
            d1[k] = deep_update(d1.get(k), v)
        return d1
    return d2

class MotionScope:

    def __init__(self):
        if not os.path.isdir(MEDIA_DIR):
            os.system(f"mkdir -p {MEDIA_DIR}")
        self.data = collections.defaultdict(dict)
        self.kapp = Vizy()

        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.camera.mode = "768x432x10bpp"

        style = {"label_width": 3, "control_width": 6}
        # Set video width to dynamically scale with width of window or WIDTH, whichever
        # is less.  We subtract 2*PADDING because it's on both sides. 
        self.video = kritter.Kvideo(overlay=True, video_style={"width": f"min(calc(100vw - {2*PADDING}px), {WIDTH}px)"})

        self.camera_tab = Camera(self.kapp, self.data, self.camera, self.video)
        self.capture_tab = Capture(self.kapp, self.data, self.camera)
        self.process_tab = Process(self.kapp, self.data, self.camera)
        self.analyze_tab = Analyze(self.kapp, self.data, self.video, GRAPHS)
        self.tabs = [(self.camera_tab, self.kapp.new_id()),  (self.capture_tab, self.kapp.new_id()), (self.process_tab, self.kapp.new_id()), (self.analyze_tab, self.kapp.new_id())]
        self.tab = self.camera_tab

        self.file_options = [dbc.DropdownMenuItem("Save", disabled=True), dbc.DropdownMenuItem("Load")]
        self.file_menu = kritter.KdropdownMenu(name="File", options=self.file_options, nav=True)

        nav_items = [dbc.NavItem(dbc.NavLink(p[0].name, active=i==0, id=p[1], disabled=p[0].name=="Process" or p[0].name=="Analyze")) for i, p in enumerate(self.tabs)]
        nav_items.append(self.file_menu.control)
        nav = dbc.Nav(nav_items, pills=True, navbar=True)
        navbar = dbc.Navbar(nav, color="dark", dark=True, expand=True)

        self.save_progress_dialog = kritter.KprogressDialog(title="Saving...", shared=True)
        self.load_progress_dialog = kritter.KprogressDialog(title="Loading...", shared=True)

        controls_layout = html.Div([
            # Navbar stays fixed at top
            navbar, 
            # Everything else scrolls.
            html.Div([
                html.Div([
                    html.Div([self.video, 
                        dbc.Card([t[0].layout for t in self.tabs], 
                            style={"max-width": f"{WIDTH}px", "margin-top": "10px", "margin-bottom": "10px"}
                        )
                    ], style={"float": "left"}), 
                    html.Div(self.analyze_tab.graphs.layout)
                ], style={"padding": f"{PADDING}px"})
            # Next Div is scrollable, occupies all of available viewport.    
            ], style={"overflow": "overlay"})
        # Outermost Div is flexbox 
        ], style={"display": "flex", "height": "100%", "flex-direction": "column"})

        self.kapp.layout = [controls_layout, self.save_progress_dialog, self.load_progress_dialog]

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
        def func(changed, cmem):
            return self.data_update(changed, cmem)

        @self.process_tab.data_update_callback
        def func(changed, cmem):
            return self.data_update(changed, cmem)

        # Run main gui thread.
        self.run_thread = True
        Thread(target=self.thread).start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self.run_thread = False

    def get_tab_func(self, tab):
        def func(val):
            mods = [Output(t[0].layout.id, "is_open", t is tab) for t in self.tabs] + [Output(t[1], "active", t is tab) for t in self.tabs]
            res = self.tab.focus(False)
            if res:
                mods += res
            self.tab = tab[0]
            res = self.tab.focus(True)
            if res:
                mods += res
            return mods 
        return func

    def data_update(self, changed, cmem=None):
        mods = []
        for t, _ in self.tabs:
            mods += t.data_update(changed, cmem)
        if "recording" in changed:
            if self.data['recording'].len()>BG_CNT_FINAL: 
                process_tab = self.find_tab("Process") 
                self.file_options[0].disabled = False
                mods += self.file_menu.out_options(self.file_options) + [Output(process_tab[1], "disabled", False)]
        if "obj_data" in changed:
            analyze_tab = self.find_tab("Analyze") 
            if self.data['obj_data']:
                f = self.get_tab_func(analyze_tab)
                mods += [Output(analyze_tab[1], "disabled", False)] + f(None)
            else: 
                mods += [Output(analyze_tab[1], "disabled", True)]

        return mods           

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
            self.kapp.push_mods(dialog.out_progress(progress))
            time.sleep(1/UPDATE_RATE)

        mods = []
        # Save/load rest of data.
        filename = os.path.join(MEDIA_DIR, "out.json")
        # Save
        if dialog is self.save_progress_dialog: 
            with open(filename, 'w') as f:
                data = self.data.copy()
                # We don't need bg, and recording is already saved.
                del data['bg'], data['recording'] 
                json.dump(data, f, cls=kritter.JSONEncodeFromNumpy) 
        # Load        
        else: 
            # Inform tabs that we have a recording.
            mods += self.data_update("recording")
            try:
                with open(filename) as f:
                    data = json.load(f, cls=kritter.JSONDecodeToNumpy)
                deep_update(self.data, data)

                # Inform tabs that we have a list of changed
                changed = list(data.keys())
                mods += self.data_update(changed)
            except Exception as e:
                print(f"Error loading: {e}")

        #self.kapp.push_mods(dialog.out_progress(100))     
        self.kapp.push_mods(mods + dialog.out_open(False))

    def thread(self):

        while self.run_thread:
            # Get frame
            frame = self.tab.frame()
            # Send frame
            if isinstance(frame, tuple): 
                # Capture can send frameperiod with frame 
                # so it renders correctly
                self.video.push_frame(*frame)
            else:
                self.video.push_frame(frame)


if __name__ == "__main__":
    ms = MotionScope()