import os
from threading import Thread, RLock
import kritter
import cv2
import numpy as np
import time
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

class Camera:

    def __init__(self, kapp, camera, video, style):

        self.name = "Camera"
        self.stream = camera.stream()
        modes = ["640x480x10bpp (cropped)", "768x432x10bpp", "1280x720x10bpp"]
        mode = kritter.Kdropdown(name='Camera mode', options=modes, value=camera.mode, style=style)
        brightness = kritter.Kslider(name="Brightness", value=camera.brightness, mxs=(0, 100, 1), format=lambda val: '{}%'.format(val), style=style)
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

    def focus(self, state):
        print(self.name, state)


class Capture:

    def __init__(self, kapp, camera, style):

        self.name = "Capture"
        self.ratio = 0.1
        self.update_timer = 0
        self.pts_timer = 0
        self.prev_mods = []
        self.camera = camera
        self.recording = None
        self.playing = False
        self.paused = False
        self.stream = self.camera.stream()
        self.kapp = kapp
        self.duration = MAX_RECORDING_DURATION
        self.start_shift = 0
        self.trigger_sensitivity = 50
        self.more = False
        self.recording_ready_callback_func = None 

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

    def recording_ready_callback(self, func):
        self.recording_ready_callback_func = func 

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
            if self.recording_ready_callback_func:
                 diff_mods += self.recording_ready_callback_func()
        # Only send new mods
        return diff_mods    

    def frame(self):
        update = False

        if self.playing:
            if not self.paused:
                self._frame = self.recording.frame()
                if self._frame is None:
                    self.playing = False
                    self.paused = False
                    self.recording.seek(0)
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

    def focus(self, state):
        print(self.name, state)


CALC_BG = 0
PAUSED = 1
PROCESSING = 2
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

class Process:

    def __init__(self, kapp, camera):

        self.name = "Process"
        self.lock = RLock() # for sychronizing self.state
        self.processing_ready_callback_func = None
        self.kapp = kapp
        self.update_timer = 0
        self.camera = camera
        self.stream = camera.stream()
        self.recording = None
        self.state = PAUSED
        self.bg_cnt = 0
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
                t = self.recording.time_seek(t)
                self.curr_frame = self.recording.frame()
                time.sleep(1/UPDATE_RATE)
            return self.playback_c.out_text(f"{t:.3f}s")            

    def processing_ready_callback(self, func):
        self.processing_ready_callback_func = func 

    def set_recording(self, recording):
        self.recording = recording 
        self.bg_cnt = 0

    def record(self, tinfo, pts, index):
        for i, v in tinfo.items():
            v = v[0:6]
            v = np.insert(v, 0, pts)
            v = np.insert(v, 1, index)
            if i in self.data:
                self.data[i] = np.vstack((self.data[i], v))
            else:
                self.data[i] = np.array([v])

    def calc_bg(self, frame):
        frame = frame[0]
        if self.bg_cnt==0:
            self.bg = frame
        elif self.bg_cnt<BG_CNT_FINAL:
            self.bg = self.bg*(1-BG_AVG_RATIO) + frame*BG_AVG_RATIO
            self.bg = self.bg.astype("uint8")
        else:
            # We only use split version of bg
            self.bg = cv2.split(self.bg)
            self.kapp.push_mods(self.set_state(PROCESSING))
        self.bg_cnt += 1
        return frame

    def prune(self):
        # Delete objects that don't move "much" (set by MIN_RANGE)
        # Go through data find x and y range, if both ranges are less than 
        # threshold then delete.
        for i, data in self.data.copy().items():
            x_range = np.max(data[:, 2]) - np.min(data[:, 2])
            y_range = np.max(data[:, 3]) - np.min(data[:, 3])
            if x_range<MIN_RANGE and y_range<MIN_RANGE:
                del self.data[i]


    def process(self, frame):
        index = frame[2]
        pts = frame[1]
        frame = frame[0]
        frame_split  = cv2.split(frame)
        diff = np.zeros(frame_split[0].shape, dtype="uint16")

        # Compute absolute difference with background frame
        for i in range(3):
            diff += cv2.absdiff(self.bg[i], frame_split[i])

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
            print(tinfo, pts, index)

        return frame

    def set_state(self, state):
        with self.lock:
            if state==CALC_BG:
                self.recording.seek(0)
                mods = self.process_button.out_spinner_disp(True) + self.cancel.out_disabled(True) + self.playback_c.out_max(self.recording.time_len()) + self.playback_c.out_disabled(True) + self.playback_c.out_value(0)            
            elif state==PROCESSING:
                self.data = {}
                self.recording.seek(0)
                self.tracker = CentroidTracker(maxDisappeared=15, maxDistance=200, maxDistanceAdd=50)
                mods = self.process_button.out_spinner_disp(True) + self.cancel.out_disabled(False) + self.playback_c.out_max(self.recording.time_len()) + self.playback_c.out_disabled(True)
            elif state==PAUSED:
                self.curr_frame = self.recording.frame()
                mods = self.process_button.out_spinner_disp(False) + self.cancel.out_disabled(True) + self.playback_c.out_disabled(False)

            self.state = state
            return mods  

    def update(self):
        t = self.recording.time()
        mods = self.playback_c.out_value(t) 
        return mods  

    def frame(self):
        with self.lock:
            if self.state==CALC_BG or self.state==PROCESSING:
                self.curr_frame = self.recording.frame()
                if self.curr_frame is None:
                    self.prune() # Clean up self.data
                    self.kapp.push_mods(self.set_state(PAUSED))
                    if self.processing_ready_callback_func:
                        self.kapp.push_mods(self.processing_ready_callback_func())

            if self.state==CALC_BG:
                self.calc_bg(self.curr_frame)
                return None                
            elif self.state==PROCESSING:
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
            if self.bg_cnt<BG_CNT_FINAL:
                self.kapp.push_mods(self.set_state(CALC_BG))
            else:
                self.kapp.push_mods(self.set_state(PROCESSING))

class Analyze:

    def __init__(self, kapp, camera):

        self.name = "Analyze"
        self.kapp = kapp
        self.camera = camera
        self.stream = camera.stream()
        self.layout = dbc.Collapse(["hello"], id=self.kapp.new_id())

    def find_bounds(self):
        # Find when time begins (min_pts)
        # Find first frame (min_index)
        # Find last frame (max_index)
        max_points = []
        first_index = []
        last_index = []
        first_pts = []
        for i, data in self.data.items():
            max_points.append(len(data))
            first_index.append(int(data[0, 1]))  
            last_index.append(int(data[-1, 1]))   
            first_pts.append(data[0, 0])  
        self.max_points = max(max_points)
        self.first_index = min(first_index)
        self.last_index = max(last_index)
        self.first_pts = min(first_pts)

    def set_data(self, data):
        self.data = data 
        self.find_bounds()

    def frame(self):
        return None

    def focus(self, state):
        pass
            

class MotionScope:

    def __init__(self):
        if not os.path.isdir(MEDIA_DIR):
            os.system(f"mkdir -p {MEDIA_DIR}")
        self.kapp = Vizy()

        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.camera.mode = "768x432x10bpp"
        width, height = calc_video_resolution(*self.camera.resolution)

        self.video = kritter.Kvideo(width=width, height=height)

        style = {"label_width": 3, "control_width": 6}
        self.camera_tab = Camera(self.kapp, self.camera, self.video, style)
        self.capture_tab = Capture(self.kapp, self.camera, style)
        self.process_tab = Process(self.kapp, self.camera)
        self.analyze_tab = Analyze(self.kapp, self.camera)
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
            res = None
            self.run_progress = True
            if val==0:
                Thread(target=self.update_progress, args=(self.save_progress_dialog, )).start()
                self.capture_tab.recording.save(os.path.join(MEDIA_DIR, "out.raw"))
            elif val==1:
                self.capture_tab.recording = self.camera.stream(False)
                Thread(target=self.update_progress, args=(self.load_progress_dialog, )).start()
                self.capture_tab.recording.load(os.path.join(MEDIA_DIR, "out.raw"))
                res = self.set_recording()
            self.run_progress = False
            return res


        @self.capture_tab.recording_ready_callback
        def func():
            return self.set_recording()

        def get_func(tab):
            mods = [Output(t[0].layout.id, "is_open", t is tab) for t in self.tabs] + [Output(t[1], "active", t is tab) for t in self.tabs]
            def func(val):
                self.tab.focus(False)
                self.tab = tab[0]
                self.tab.focus(True)
                return mods 
            return func

        for t in self.tabs:
            func = get_func(t)
            self.kapp.callback_shared(None, [Input(t[1], "n_clicks")])(func)
         
        @self.process_tab.processing_ready_callback
        def func():
            analyze_tab = self.find_tab("Analyze") 
            self.analyze_tab.set_data(self.process_tab.data)
            f = get_func(analyze_tab)
            return [Output(analyze_tab[1], "disabled", False)] + f(None) 

        # Run main gui thread.
        self.run_thread = True
        Thread(target=self.thread).start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        print("shutting down")
        self.run_thread = False

    def set_recording(self):
        if self.capture_tab.recording.len()>BG_CNT_FINAL: 
            process_tab = self.find_tab("Process") 
            process_tab[0].set_recording(self.capture_tab.recording)
            self.file_options[0].disabled = False
            return self.file_menu.out_options(self.file_options) + [Output(process_tab[1], "disabled", False)]

    def find_tab(self, name):
        for t in self.tabs:
            if t[0].name==name:
                return t 
        raise RuntimeError()

    def update_progress(self, dialog):
        self.kapp.push_mods(dialog.out_progress(0) + dialog.out_open(True)) 
        while self.run_progress:
            progress = self.capture_tab.recording.progress()
            self.kapp.push_mods(dialog.out_progress(progress))
            time.sleep(1/UPDATE_RATE)
        self.kapp.push_mods(dialog.out_open(False))

    def thread(self):
        while self.run_thread:
            # Get frame
            frame = self.tab.frame()
            # Send frame
            self.video.push_frame(frame)
        print("exit thread")


if __name__ == "__main__":
    ms = MotionScope()