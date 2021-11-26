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

class Camera:

    def __init__(self, kapp, camera, video, style):

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

class Capture:

    def __init__(self, kapp, camera, video, style):

        self.kapp = kapp
        self.start_shift = 0
        self.duration = 5
        self.trigger_sensitivity = 50
        self.more = False

        status = kritter.Ktext(value="Waiting")
        playback_c = kritter.Kslider(value=0, mxs=(0, 1, .01), format=lambda val: f"{val:.2f}s", disabled=True, style=style)

        record = kritter.Kbutton(name=[kapp.icon("circle"), "Record"])
        play = kritter.Kbutton(name=[kapp.icon("play"), "Play"])
        stop = kritter.Kbutton(name=[kapp.icon("stop"), "Stop"])
        step_backward = kritter.Kbutton(name=kapp.icon("step-backward", padding=0))
        step_forward = kritter.Kbutton(name=kapp.icon("step-forward", padding=0))
        more_c = kritter.Kbutton(name="More...")

        record.append(play)
        record.append(stop)
        record.append(step_backward)
        record.append(step_forward)
        record.append(more_c)

        save = kritter.Kbutton(name=[kapp.icon("save"), "Save"])
        load = kritter.KdropdownMenu(name="Load")
        delete = kritter.KdropdownMenu(name="Delete")
        save.append(load)
        save.append(delete)


        start_shift_c = kritter.Kslider(name="Start-shift", value=self.start_shift, mxs=(-5.0, 5, .01), format=lambda val: f'{val:.2f}s', style=style)
        duration_c = kritter.Kslider(name="Duration", value=self.duration, mxs=(0, 15, .01), format=lambda val: f'{val:.2f}s', style=style)
        trigger_modes = ["button press", "auto-trigger", "auto-trigger/analyze"]
        self.trigger_mode = trigger_modes[0]
        trigger_modes_c = kritter.Kdropdown(name='Trigger mode', options=trigger_modes, value=self.trigger_mode, style=style)
        trigger_sensitivity_c = kritter.Kslider(name="Trigger sensitivitiy", value=self.trigger_sensitivity, mxs=(1, 100, 1), style=style)

        more_controls = dbc.Collapse([save, start_shift_c, duration_c, trigger_modes_c, trigger_sensitivity_c], id=kapp.new_id(), is_open=self.more)
        self.layout = dbc.Collapse([status, playback_c, record, more_controls], id=kapp.new_id(), is_open=False)

        @more_c.callback()
        def func():
            self.more = not self.more
            return more_c.out_name("Less..." if self.more else "More...") + [Output(more_controls.id, "is_open", self.more)]


class Analyze:

    def __init__(self, kapp):

        analyze = kritter.Kbutton(name=[kapp.icon("refresh"), "Process"])

        self.layout = dbc.Collapse([analyze], id=kapp.new_id(), is_open=False)

class MotionScope:

    def __init__(self):
        self.kapp = Vizy()

        # Create and start camera.
        camera = kritter.Camera(hflip=True, vflip=True)
        camera.mode = "768x432x10bpp"
        width, height = calc_video_resolution(*camera.resolution)
        self.stream = camera.stream()
        self.video = kritter.Kvideo(width=width, height=height)

        style = {"label_width": 3, "control_width": 6}
        self.panes = {"Camera": Camera(self.kapp, camera, self.video, style), "Capture": Capture(self.kapp, camera, self.video, style), "Analyze": Analyze(self.kapp)}
        self.mode_options = [k for k, v in self.panes.items()]
        self.mode = self.mode_options[0] 
        self.mode_c = kritter.Kradio(options=self.mode_options, value=self.mode)

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