#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

from threading import Thread
import kritter
from dash_devices.dependencies import Output, State
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy
from math import sqrt 

import numpy as np
import cv2
from kritter import Kritter

GRID_DIVS = 10 

class Perspective:

    def __init__(self, camera, video, style=kritter.default_style, closed=True, shift=True, shear=True):
        self.camera = camera
        self.video = video
        self.reset()

        self.more = not closed
        control_style = style
        style = style.copy()
        style['control_width'] = 0.1
        enable = kritter.Kcheckbox(name="Perspective", value=self.more, style=style)
        self.more_c = kritter.Kbutton(name=Kritter.icon("plus", padding=0), size="sm", disabled=closed)
        enable.append(self.more_c)
        grid = kritter.Kcheckbox(name="Show grid", value=False, style=style)
        reset = kritter.Kbutton(name=[Kritter.icon("undo"), "Reset"], size="sm")
        more_center = kritter.Kbutton(name=[Kritter.icon("plus"), "Shear"], size="sm")
        if shear:
            reset.append(more_center)
        roll_c = kritter.Kslider(name="Roll", value=self.roll, mxs=(-90, 90, 0.1), format=lambda val: f'{val:.1f}°',style=control_style, )
        pitch_c = kritter.Kslider(name="Pitch", value=self.pitch, mxs=(-45, 45, 0.1), format=lambda val: f'{val:.1f}°', style=control_style)
        yaw_c = kritter.Kslider(name="Yaw", value=self.yaw, mxs=(-45, 45, 0.1), format=lambda val: f'{val:.1f}°', style=control_style)
        zoom_c = kritter.Kslider(name="Zoom", value=self.zoom, mxs=(0.5, 10, 0.01), format=lambda val: f'{val:.1f}x', style=control_style)
        shift_x_c = kritter.Kslider(name="Shift x", value=self.shift_x, mxs=(-1, 1, 0.01), format=lambda val: f'{round(val*100)}%', style=control_style)
        shift_y_c = kritter.Kslider(name="Shift y", value=self.shift_y, mxs=(-1, 1, 0.01), format=lambda val: f'{round(val*100)}%', style=control_style)
        shear_x_c = kritter.Kslider(name="Shear x", value=self.center_x, mxs=(-1, 1, 0.01), style=control_style)
        shear_y_c = kritter.Kslider(name="Shear y", value=self.center_y, mxs=(-1, 1, 0.01), style=control_style)

        controls = [roll_c, pitch_c, yaw_c, zoom_c]
        if shift:
            controls += [shift_x_c, shift_y_c]
        controls += [grid, reset]
        if shear:
            collapse_center = dbc.Collapse([shear_x_c, shear_y_c] ,id=Kritter.new_id())
            controls += [collapse_center]
        self.collapse = dbc.Collapse(dbc.Card(controls), id=Kritter.new_id())
        self.layout = html.Div([enable, self.collapse])

        @more_center.callback([State(collapse_center.id, "is_open")])
        def func(is_open):
            return more_center.out_name([Kritter.icon("plus"), "Shear"] if is_open else [Kritter.icon("minus"), "Shear"]) + [Output(collapse_center.id, "is_open", not is_open)] 

        @self.more_c.callback()
        def func():
            return self.set_more(not self.more)

        @enable.callback()
        def func(val):
            mods = self.more_c.out_disabled(not val)
            if not val:
                mods += self.set_more(False) + grid.out_value(False)
            return mods

        @reset.callback()
        def func():
            return roll_c.out_value(0) + pitch_c.out_value(0) + yaw_c.out_value(0) + zoom_c.out_value(1) + shift_x_c.out_value(0) + shift_y_c.out_value(0)

        @grid.callback()
        def func(value):
            if value:
                step = self.camera.resolution[0]//(GRID_DIVS+2)
                for i in range(step//2, self.camera.resolution[0], step):
                    self.video.draw_line(i, 0, i, self.camera.resolution[1], line={"color": f"rgba(0, 255, 0, 0.25)", "width": 2})
                for i in range(step//2, self.camera.resolution[1], step):
                    self.video.draw_line(0, i, self.camera.resolution[0], i, line={"color": f"rgba(0, 255, 0, 0.25)", "width": 2})
            else:
                self.video.draw_clear() 
            return self.video.out_draw_overlay()

    def set_more(self, val):
            self.more = val
            return self.more_c.out_name(Kritter.icon("minus", padding=0) if self.more else Kritter.icon("plus", padding=0)) + [Output(self.collapse.id, "is_open", self.more)]

    def reset(self):
        self._matrix = None
        self.roll = 0
        self.pitch = 0
        self.yaw = 0
        self.zoom = 1
        self.shift_x = 0
        self.shift_y = 0
        self.center_x = 0
        self.center_y = 0

    def calc(self, roll, pitch, yaw):
        pass 

    @property
    def matrix(self):
        return np.float32([[1, 0, 0], [0, 1, 0], [0, 0, 1]]) if self._matrix is None else self._matrix

    @property 
    def f(self):
        return self._f 

    @f.setter
    def f(self, value):
        self._f = f  

    def transform(self, image):
        return image if self._matrix is None else cv2.warpPerspective(image, self._matrix, self.camera.resolution, flags=cv2.INTER_LINEAR)

class Video:
    def __init__(self):
        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream()

        # Create Kritter server.
        kapp = Vizy()
        style = {"label_width": 3, "control_width": 6}
         # Create video component.
        self.video = kritter.Kvideo(width=self.camera.resolution[0], overlay=True)
        hist_enable = kritter.Kcheckbox(name='Histogram', value=False, style=style)
        mode = kritter.Kdropdown(name='Camera mode', options=self.camera.getmodes(), value=self.camera.mode, style=style)
        brightness = kritter.Kslider(name="Brightness", value=self.camera.brightness, mxs=(0, 100, 1), format=lambda val: '{}%'.format(val), style=style)
        framerate = kritter.Kslider(name="Framerate", value=self.camera.framerate, mxs=(self.camera.min_framerate, self.camera.max_framerate, 1), format=lambda val : '{} fps'.format(val), style=style)
        autoshutter = kritter.Kcheckbox(name='Auto-shutter', value=self.camera.autoshutter, style=style)
        shutter = kritter.Kslider(name="Shutter-speed", value=self.camera.shutter_speed, mxs=(.0001, 1/self.camera.framerate, .0001), format=lambda val: '{:.4f} s'.format(val), style=style)
        shutter_cont = dbc.Collapse(shutter, id=kapp.new_id(), is_open=not self.camera.autoshutter, style=style)
        awb = kritter.Kcheckbox(name='Auto-white-balance', value=self.camera.awb, style=style)
        red_gain = kritter.Kslider(name="Red gain", value=self.camera.awb_red, mxs=(0.05, 2.0, 0.01), style=style)
        blue_gain = kritter.Kslider(name="Blue gain", value=self.camera.awb_red, mxs=(0.05, 2.0, 0.01), style=style)
        awb_gains = dbc.Collapse([red_gain, blue_gain], id=kapp.new_id(), is_open=not self.camera.awb)     
        perspective = Perspective(self.camera, self.video, style=style)       
        ir_filter = kritter.Kcheckbox(name='IR filter', value=kapp.power_board.ir_filter(), style=style)
        ir_light = kritter.Kcheckbox(name='IR light', value=kapp.power_board.vcc12(), style=style)

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
            return self.video.out_width(self.camera.resolution[0]) + framerate.out_value(self.camera.framerate) + framerate.out_min(self.camera.min_framerate) + framerate.out_max(self.camera.max_framerate)

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
            kapp.power_board.ir_filter(value)

        @ir_light.callback()
        def func(value):
            kapp.power_board.vcc12(value)
             
        @self.video.callback_click()
        def func(val):
            print(val)

        controls = html.Div([hist_enable, mode, brightness, framerate, autoshutter,shutter_cont, awb, awb_gains, perspective.layout, ir_filter, ir_light])

        # Add video component and controls to layout.
        kapp.layout = html.Div([self.video, controls], style={"padding": "15px"})

        # Run camera grab thread.
        self.run_grab = True
        Thread(target=self.grab).start()

        # Run Kritter server, which blocks.
        kapp.run()
        self.run_grab = False

    # Frame grabbing thread
    def grab(self):
        while self.run_grab:
            # Get frame
            frame = self.stream.frame()
            # Send frame
            self.video.push_frame(frame)


if __name__ == "__main__":
    Video()
