from threading import Thread
import kritter
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy
from math import sqrt 

MAX_AREA = 640*480

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

class Setup:

    def __init__(self, kapp, camera, video, style):

        modes = ["640x480x10bpp (cropped)", "768x432x10bpp", "1280x720x10bpp"]
        mode = kritter.Kdropdown(name='Camera mode', options=modes, value=camera.mode, style=style)
        brightness = kritter.Kslider(name="Brightness", value=camera.brightness, mxs=(0, 100, 1), format=lambda val: '{}%'.format(val), style=style)
        framerate = kritter.Kslider(name="Framerate", value=camera.framerate, mxs=(camera.min_framerate, camera.max_framerate, 1), format=lambda val : '{} fps'.format(val), style=style)
        autoshutter = kritter.Kcheckbox(name='Auto-shutter', value=camera.autoshutter, style=style)
        shutter = kritter.Kslider(name="Shutter-speed", value=camera.shutter_speed, mxs=(.0001, 1/camera.framerate, .0001), format=lambda val: '{:.4f} s'.format(val), style=style)
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

class Capture:

    def __init__(self, kapp):

        capture = kritter.Kbutton(name=[kapp.icon("eye"), "Capture"])

        self.layout = dbc.Collapse([capture], id=kapp.new_id(), is_open=False)

class Analyze:

    def __init__(self, kapp):

        analyze = kritter.Kbutton(name=[kapp.icon("refresh"), "Process"])

        self.layout = dbc.Collapse([analyze], id=kapp.new_id(), is_open=False)

class MotionScope:

    def __init__(self):
        self.kapp = Vizy()

        # Create and start camera.
        camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = camera.stream()
        self.video = kritter.Kvideo(width=camera.resolution[0], height=camera.resolution[1])

        style = {"label_width": 3, "control_width": 6}
        self.panes = {"Setup": Setup(self.kapp, camera, self.video, style), "Capture": Capture(self.kapp), "Analyze": Analyze(self.kapp)}
        self.mode_options = [k for k, v in self.panes.items()]
        self.mode = self.mode_options[0] 
        self.mode_c = kritter.Kradio(options=self.mode_options, value=self.mode, style={"horizontal_padding": 0, "vertical_padding": 0})

        self.kapp.layout = html.Div([self.video, self.mode_c, dbc.Card([v.layout for k, v in self.panes.items()], style={"max-width": "736px"})], style={"margin": "15px"})

        @self.mode_c.callback()
        def func(mode):
            mods = []
            for k, v in self.panes.items():
                if k==mode:
                    mods.append(Output(v.layout.id, "is_open", True))
                else:
                    mods.append(Output(v.layout.id, "is_open", False))
            return mods

        # Run main gui thread.
        self.run_thread = True
        Thread(target=self.thread).start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self.run_thread = False

    def thread(self):
        while self.run_thread:
            # Get frame
            frame = self.stream.frame()
            # Send frame
            self.video.push_frame(frame)


if __name__ == "__main__":
    ms = MotionScope()