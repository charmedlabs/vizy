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
import time
import datetime
import subprocess
from threading import Thread
import kritter
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy

BASE_DIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(BASE_DIR, "media")

MOST_RECENT = 0 
PREVIOUS = 1 
NEXT = 2

class TakePic:

    def __init__(self):
        # Set up vizy class, config files.
        self.kapp = Vizy()
        if not os.path.exists(MEDIA_DIR):
            os.mkdir(MEDIA_DIR)
        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream()
        self.take_pic = False
        self.camera.mode = "2016x1520x10bpp"
        self.shutter = 1
        self.gain = 1

        style = {"label_width": 3, "control_width": 6}
        self.mode_c = kritter.Kradio(options=["Preview", "View"], value="Preview", style=style)
        self.video = kritter.Kvideo(width=self.camera.resolution[0])
        self.brightness = kritter.Kslider(name="Preview brightness", value=self.camera.brightness, mxs=(0, 100, 1), format=lambda val: '{}%'.format(val), style=style)
        self.framerate = kritter.Kslider(name="Preview framerate", value=self.camera.framerate, mxs=(self.camera.min_framerate, self.camera.max_framerate, 1), format=lambda val : '{} fps'.format(val), style=style)

        self.disp_pic = html.Img(id=self.kapp.new_id(), style={"max-width": "4056px", "width": "100%", "height": "100%"})
        self.pic_div = html.Div(self.disp_pic, id=self.kapp.new_id(), style={"display": "none"})
        self.prev_pic = kritter.Kbutton(name=self.kapp.icon("step-backward", padding=0))
        self.next_pic = kritter.Kbutton(name=self.kapp.icon("step-forward", padding=0))
        self.pic_info = kritter.Ktext()

        self.ir_filter = kritter.Kcheckbox(name='IR filter', grid=False, value=self.kapp.power_board.ir_filter(), style=style)

        self.pic = kritter.Kbutton(name="Take pic", spinner=True)
        self.shutter_c = kritter.Kslider(name="Shutter", value=self.shutter, mxs=(.01, 30, .001), format=lambda val : f'{val:.3f}s', style=style)
        self.gain_c = kritter.Kslider(name="Gain", value=self.gain, mxs=(.1, 100, .01), style=style)

        self.preview = dbc.Collapse(dbc.Card([self.video, self.brightness, self.framerate, self.shutter_c, self.gain_c]), is_open=True, id=self.kapp.new_id())
        self.prev_pic.append(self.next_pic)
        self.view = dbc.Collapse(dbc.Card([self.pic_div, self.pic_info, self.prev_pic]), is_open=False, id=self.kapp.new_id())

        self.pic.append(self.ir_filter)
        self.kapp.layout = html.Div([self.preview, self.view, self.mode_c, self.pic], style={"margin": "15px"})

        @self.brightness.callback()
        def func(value):
            self.camera.brightness = value

        @self.framerate.callback()
        def func(value):
            self.camera.framerate = value

        @self.ir_filter.callback()
        def func(value):
            self.kapp.power_board.ir_filter(value)
             
        @self.prev_pic.callback()
        def func():
            return self.show_pic(PREVIOUS)

        @self.next_pic.callback()
        def func():
            return self.show_pic(NEXT)

        @self.pic.callback()
        def func():
            self.take_pic = True

        @self.shutter_c.callback()
        def func(val):
            self.shutter = val

        @self.gain_c.callback()
        def func(val):
            print("gain", val)
            self.gain = val 

        @self.mode_c.callback()
        def func(val):
            return [Output(self.preview.id, "is_open", val=="Preview"), Output(self.view.id, "is_open", val=="View")]

        # Add our own media path
        self.kapp.media_path.insert(0, MEDIA_DIR)

        self.kapp.push_mods(self.show_pic(MOST_RECENT))
        self.kapp.push_mods(self.gain_c.out_value(2))
        
        # Run camera grab thread.
        self.run_grab = True
        grab_thread = Thread(target=self.grab)
        grab_thread.start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self.run_grab = False

    def show_pic(self, which):
        pics = os.listdir(MEDIA_DIR)
        pics = sorted(pics)
        if which==MOST_RECENT:
            if len(pics)==0:
                return
            index = len(pics)-1
        elif which==PREVIOUS:
            index = pics.index(self.curr_pic)-1
            if index<0:
                return 
        elif which==NEXT:
            index = pics.index(self.curr_pic)+1
            if index>=len(pics):
                return
        self.curr_pic = pics[index]
        return [Output(self.disp_pic.id, "src",  f"media/{self.curr_pic}"), Output(self.pic_div.id, "style", {"display": "block"})] + self.prev_pic.out_disabled(index==0) + self.next_pic.out_disabled(index==len(pics)-1) + self.pic_info.out_value(self.curr_pic)

    def grab(self):
        env = os.environ.copy()
        del env['LIBCAMERA_IPA_MODULE_PATH']
        while self.run_grab:
            # Get frame
            frame = self.stream.frame()
            # Send frame
            self.video.push_frame(frame)

            if self.take_pic:
                filename = datetime.datetime.now().strftime("media/%Y_%m_%d_%H_%M_%S.jpg")
                self.stream.stop()
                self.kapp.push_mods(self.pic.out_spinner_disp(True))
                subprocess.run(["libcamera-still", "-n", "--hflip", "--vflip", "-o", os.path.join(BASE_DIR, filename), "--shutter", f"{int(self.shutter*1000000)}", "--gain", f"{self.gain:.2f}"], env=env)
                self.kapp.push_mods(self.pic.out_spinner_disp(False) + self.show_pic(MOST_RECENT) + self.mode_c.out_value("View"))
                self.take_pic = False


if __name__ == "__main__":
    tp = TakePic()