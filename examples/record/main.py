from threading import Thread, RLock
import time
import cv2
import kritter
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy


WAITING = 0
RECORDING = 1
SAVING = 2
STREAM_WIDTH = 768
STREAM_HEIGHT = 432


class Video:

    def __init__(self):
        # Create and start camera.
        self.lock = RLock()
        self.record_state = WAITING
        self.camera = kritter.Camera(hflip=True, vflip=True, mode="1920x1080x10bpp", framerate=20)
        self.stream = self.camera.stream()

        # Create Kritter server.
        self.kapp = Vizy()
        gcloud = kritter.Gcloud(self.kapp.etcdir)
        self.gpsm = kritter.GPstoreMedia(gcloud)

        style = {"label_width": 3, "control_width": 6}
         # Create video component.
        self.video = kritter.Kvideo(width=STREAM_WIDTH, height=STREAM_HEIGHT)
        self.record_stop = kritter.Kbutton(name="Record", spinner=True)
        hist_enable = kritter.Kcheckbox(name='Histogram', value=False, style=style)
        mode = kritter.Kdropdown(name='Camera mode', options=self.camera.getmodes(), value=self.camera.mode, style=style)
        brightness = kritter.Kslider(name="Brightness", value=self.camera.brightness, mxs=(0, 100, 1), format=lambda val: '{}%'.format(val), style=style)
        framerate = kritter.Kslider(name="Framerate", value=self.camera.framerate, mxs=(self.camera.min_framerate, self.camera.max_framerate, 1), format=lambda val : '{} fps'.format(val), style=style)
        autoshutter = kritter.Kcheckbox(name='Auto-shutter', value=self.camera.autoshutter, style=style)
        shutter = kritter.Kslider(name="Shutter-speed", value=self.camera.shutter_speed, mxs=(.0001, 1/self.camera.framerate, .0001), format=lambda val: '{:.4f} s'.format(val), style=style)
        shutter_cont = dbc.Collapse(shutter, id=kritter.Kritter.new_id(), is_open=not self.camera.autoshutter, style=style)
        awb = kritter.Kcheckbox(name='Auto-white-balance', value=self.camera.awb, style=style)
        red_gain = kritter.Kslider(name="Red gain", value=self.camera.awb_red, mxs=(0.05, 2.0, 0.01), style=style)
        blue_gain = kritter.Kslider(name="Blue gain", value=self.camera.awb_red, mxs=(0.05, 2.0, 0.01), style=style)
        awb_gains = dbc.Collapse([red_gain, blue_gain], id=kritter.Kritter.new_id(), is_open=not self.camera.awb)            
        ir_filter = kritter.Kcheckbox(name='IR filter', value=self.kapp.power_board.ir_filter(), style=style)

        @self.record_stop.callback()
        def func():
            print("record", self.record_state)
            if self.record_state==SAVING:
                return
            else:
                self.record_state += 1
                return self.update()

        @hist_enable.callback()
        def func(value):
            return self.video.out_hist_enable(value)

        @brightness.callback()
        def func(value):
            self.camera.brightness = value

        @framerate.callback()
        def func(value):
            self.camera.framerate = value
            return shutter.out_value(self.camera.shutter_speed) + shutter.out_max(1/self.camera.framerate)

        @mode.callback()
        def func(value):
            self.camera.mode = value
            return self.video.out_width(self.camera.resolution[0]) + self.video.out_height(self.camera.resolution[1]) + framerate.out_value(self.camera.framerate) + framerate.out_min(self.camera.min_framerate) + framerate.out_max(self.camera.max_framerate)

        @autoshutter.callback()
        def func(value):
            self.camera.autoshutter = value
            return Output(shutter_cont.id, 'is_open', not value)

        @shutter.callback()
        def func(value):
            self.camera.shutter_speed = value    

        @awb.callback()
        def func(value):
            self.camera.awb = value
            return Output(awb_gains.id, 'is_open', not value)

        @red_gain.callback()
        def func(value):
            self.camera.awb_red = value

        @blue_gain.callback()
        def func(value):
            self.camera.awb_blue = value

        @ir_filter.callback()
        def func(value):
            self.kapp.power_board.ir_filter(value)
            
        controls = html.Div([self.record_stop, hist_enable, mode, brightness, framerate, autoshutter,shutter_cont, awb, awb_gains, ir_filter])

        # Add video component and controls to layout.
        self.kapp.layout = html.Div([self.video, controls], style={"margin": "15px"})

        # Run camera grab thread.
        self.run_grab = True
        grab_thread = Thread(target=self.grab)
        grab_thread.start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self.run_grab = False

    # Frame grabbing thread
    def grab(self):
        while self.run_grab:
            # Get frame
            frame = self.stream.frame()
            if frame is None:
                print("************")
            # Send frame
            self.video.push_frame(frame)
            self.handle_record()

    def save_video(self):
        self.gpsm.store_video_stream(self.record, fps=self.camera.framerate)
        self.record = None # free up memory

    def update(self):
        with self.lock:
            if self.record_state==WAITING:
                print("**waiting")
                return self.record_stop.out_name("Record")+self.record_stop.out_spinner_disp(False)
            elif self.record_state==RECORDING:
                print("**recording")
                self.record = self.camera.record()
                return self.record_stop.out_name("Stop")+self.record_stop.out_spinner_disp(True, disable=False)
            elif self.record_state==SAVING:
                print("**saving")
                self.record.stop()
                self.save_thread = Thread(target=self.save_video)
                self.save_thread.start()
                return self.record_stop.out_name("Saving")+self.record_stop.out_spinner_disp(True)


    def handle_record(self):
        with self.lock:
            if self.record_state==RECORDING:
                if not self.record.recording():
                    self.record_state = SAVING
                    self.kapp.push_mods(self.update())
            elif self.record_state==SAVING:
                if not self.save_thread.is_alive():
                    self.record_state = WAITING
                    self.kapp.push_mods(self.update())

if __name__ == "__main__":
    video = Video()
