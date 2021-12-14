from threading import Thread
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


MAX_AREA = 640*480
MAX_RECORDING_DURATION = 5 # seconds
UPDATE_RATE = 10 # updates/second
PLAY_RATE = 30 # frames/second
WIDTH = 736

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


class Capture:

    def __init__(self, kapp, camera, video, style):

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
            elif self.recording.recording():
                mods += self.playback_c.out_disabled(True) + self.record.out_disabled(True) + self.stop.out_disabled(False) + self.play.out_disabled(True) + self.step_backward.out_disabled(True) + self.step_forward.out_disabled(True) + self.playback_c.out_max(self.duration) + self.status.out_value("Recording...") + self.playback_c.out_value(tlen)
            else: # Stopped
                mods += self.playback_c.out_disabled(False) + self.playback_c.out_max(tlen) + self.playback_c.out_value(0) + self.record.out_disabled(False) + self.stop.out_disabled(True) + self.step_backward.out_disabled(True) + self.step_forward.out_disabled(False) + self.play.out_disabled(False) + self.status.out_value("Stopped") 

        # Find new mods with respect to the previous mods
        diff_mods = [m for m in mods if not m in self.prev_mods]
        # Save current mods
        self.prev_mods = mods 
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

        if self.playing and self._frame is not None:
            self.pts_timer += 1/PLAY_RATE
            sleep = self.pts_timer - time.time()
            if sleep>0:
                time.sleep(sleep)
            return self._frame[0]
        else:
            frame = self.stream.frame()[0]
            try:
                self.bg = self.bg*(1-self.ratio) + frame*self.ratio
            except:
                self.bg = frame
            self.bg = self.bg.astype("uint8")
            return frame


class Analyze:

    def __init__(self, kapp):

        self.name = "Analyze"
        analyze = kritter.Kbutton(name=[kapp.icon("refresh"), "Process"])

        self.layout = dbc.Collapse([analyze], id=kapp.new_id(), is_open=False)

class MotionScope:

    def __init__(self):
        self.kapp = Vizy()

        # Create and start camera.
        camera = kritter.Camera(hflip=True, vflip=True)
        camera.mode = "768x432x10bpp"
        width, height = calc_video_resolution(*camera.resolution)
        #navbar = dbc.Navbar(html.Div([dbc.Row([dbc.Col([html.Span(html.Img(src="/media/vizy_eye.png", height="30px"), style={"padding-right": "5px"}), dbc.NavbarBrand("MotionScope")], style={"padding-bottom": "5px"})], align="center", justify="start"), nav]), color="dark", dark=True, style={"max-width": WIDTH})
        #navbar = dbc.Navbar(html.Div([html.Span(html.Img(src="/media/vizy_eye.png", height="30px"), style={"padding-right": "5px", "height": "30px"}), dbc.NavbarBrand("MotionScope"), nav]), color="dark", dark=True, style={"max-width": WIDTH})
        #@self.kapp.callback(None, [Input("nitem", "n_clicks")])
        #def func(val):
        #    print("hello")     

        self.video = kritter.Kvideo(width=width, height=height)

        style = {"label_width": 3, "control_width": 6}
        self.panes = [(Camera(self.kapp, camera, self.video, style), self.kapp.new_id()),  (Capture(self.kapp, camera, self.video, style), self.kapp.new_id()), (Analyze(self.kapp), self.kapp.new_id())]
        self.pane, _ = self.panes[0]
        file_options = ["Save", "Load"]
        self.file_menu = kritter.KdropdownMenu(name="File", options=file_options, nav=True)
        nav_items = [dbc.NavItem(dbc.NavLink(p[0].name, active=i==0, id=p[1])) for i, p in enumerate(self.panes)]
        nav_items.insert(0, self.file_menu.dropdown)
        nav = dbc.Nav(nav_items, pills=True, navbar=True)
        navbar = dbc.Navbar(html.Div([html.Img(src="/media/vizy_eye.png", height="25px", style={"margin": "0 5px 10px 0"}), dbc.NavbarBrand("MotionScope"), nav]), color="dark", dark=True, expand=True, style={"max-width": WIDTH})
        
        self.kapp.layout = html.Div([navbar, self.video, dbc.Card([p[0].layout for p in self.panes], style={"max-width": f"{width-10}px", "margin": "5px"})], style={"margin": "15px 0 15px 15px"})

        @self.file_menu.callback()
        def func(val):
            print(val)

        def get_func(pane):
            mods = [Output(p[0].layout.id, "is_open", p is pane) for p in self.panes] + [Output(p[1], "active", p is pane) for p in self.panes]
            def func(val):
                self.pane = pane[0]
                return mods 
            return func

        for p in self.panes:
            func = get_func(p)
            self.kapp.callback_shared(None, [Input(p[1], "n_clicks")])(func)
         

        # Run main gui thread.
        self.run_thread = True
        Thread(target=self.thread).start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        print("shutting down")
        self.run_thread = False

    def thread(self):
        while self.run_thread:
            # Get frame
            frame = self.pane.frame()
            # Send frame
            self.video.push_frame(frame)
        print("exit thread")


if __name__ == "__main__":
    ms = MotionScope()