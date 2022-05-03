#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#


import kritter
from dash_devices.dependencies import Output, State
import dash_bootstrap_components as dbc
import dash_html_components as html
import math
import numpy as np
import cv2
from kritter import Kritter

GRID_DIVS = 20
I_MATRIX = np.float32([[1, 0, 0], [0, 1, 0], [0, 0, 1]]) 

def line_x(x0, y0, x1, y1, x):
    if x1==x0:
        x1 = x0+1e-10
    return (x-x0)*(y1-y0)/(x1-x0)+y0

def line_y(x0, y0, x1, y1, y):
    if y1==y0:
        y1 = y0+1e-10
    return (y-y0)*(x1-x0)/(y1-y0)+x0

class Perspective:

    def __init__(self, video, f, video_info, style=kritter.default_style, closed=True, shift=True, shear=True):
        self.video = video
        self.grid = False
        self.pixelsize = 1
        self.crop = [1, 1]
        self.offset = [0, 0]
        self.f = f 
        self.shear = [0, 0]
        self.reset()

        control_style = style
        style = style.copy()
        style['control_width'] = 0.1
        self.enable = not closed
        self.enable_c = kritter.Kcheckbox(name="Perspective", value=not closed, style=style)
        self.more_c = kritter.Kbutton(name=Kritter.icon("plus", padding=0), size="sm", disabled=closed)
        self.enable_c.append(self.more_c)
        grid = kritter.Kcheckbox(name="Show grid", value=False, style=style)
        reset = kritter.Kbutton(name=[Kritter.icon("undo"), "Reset"], size="sm")
        more_shear = kritter.Kbutton(name=[Kritter.icon("plus"), "Shear"], size="sm")
        if shear:
            reset.append(more_shear)
        self.roll_c = kritter.Kslider(name="Roll", value=self.roll, mxs=(-90, 90, 0.1), format=lambda val: f'{val:.1f}°',style=control_style, )
        self.pitch_c = kritter.Kslider(name="Pitch", value=self.pitch, mxs=(-45, 45, 0.1), format=lambda val: f'{val:.1f}°', style=control_style)
        self.yaw_c = kritter.Kslider(name="Yaw", value=self.yaw, mxs=(-45, 45, 0.1), format=lambda val: f'{val:.1f}°', style=control_style)
        self.zoom_c = kritter.Kslider(name="Zoom", value=self.zoom, mxs=(0.5, 10, 0.01), format=lambda val: f'{val:.1f}x', style=control_style)
        self.shift_x_c = kritter.Kslider(name="Shift x", value=self.shift[0], mxs=(-1, 1, 0.01), format=lambda val: f'{round(val*100)}%', style=control_style)
        self.shift_y_c = kritter.Kslider(name="Shift y", value=self.shift[1], mxs=(-1, 1, 0.01), format=lambda val: f'{round(val*100)}%', style=control_style)
        self.shear_x_c = kritter.Kslider(name="Shear x", value=self.shear[0], mxs=(-1, 1, 0.01), style=control_style)
        self.shear_y_c = kritter.Kslider(name="Shear y", value=self.shear[1], mxs=(-1, 1, 0.01), style=control_style)

        controls = [self.roll_c, self.pitch_c, self.yaw_c, self.zoom_c]
        if shift:
            controls += [self.shift_x_c, self.shift_y_c]
        controls += [grid, reset]
        if shear:
            collapse_shear = dbc.Collapse([self.shear_x_c, self.shear_y_c] ,id=Kritter.new_id())
            controls += [collapse_shear]
        self.collapse = dbc.Collapse(dbc.Card(controls, style={"margin-left": "5px", "margin-right": "5px"}), id=Kritter.new_id())
        self.layout = html.Div([self.enable_c, self.collapse])
        # Initialize mode
        self.set_video_info(video_info)

        @more_shear.callback([State(collapse_shear.id, "is_open")])
        def func(is_open):
            return more_shear.out_name([Kritter.icon("plus"), "Shear"] if is_open else [Kritter.icon("minus"), "Shear"]) + [Output(collapse_shear.id, "is_open", not is_open)] 

        @self.more_c.callback([State(self.collapse.id, "is_open")])
        def func(is_open):
            return self.set_more(not is_open)

        @self.enable_c.callback()
        def func(value):
            self.enable = value
            if value:
                self.calc_matrix()
            else:
                self._matrix = I_MATRIX
            mods = self.more_c.out_disabled(not value)
            if not value:
                mods += self.set_more(False) + grid.out_value(False)
            return mods

        @self.roll_c.callback()
        def func(value):
            self.roll = value
            self.calc_matrix()

        @self.pitch_c.callback()
        def func(value):
            self.pitch = value
            self.calc_matrix()

        @self.yaw_c.callback()
        def func(value):
            self.yaw = value
            self.calc_matrix()

        @self.zoom_c.callback()
        def func(value):
            self.zoom = value
            self.calc_matrix()

        @self.shift_x_c.callback()
        def func(value):
            self.shift[0] = value
            self.calc_matrix()

        @self.shift_y_c.callback()
        def func(value):
            self.shift[1] = value
            self.calc_matrix()

        @self.shear_x_c.callback()
        def func(value):
            self.shear[0] = value
            self.calc_matrix()

        @self.shear_y_c.callback()
        def func(value):
            self.shear[1] = value
            self.calc_matrix()

        @reset.callback()
        def func():
            self.reset() # reset values first -- there can be a race condition.
            return self.roll_c.out_value(0) + self.pitch_c.out_value(0) + self.yaw_c.out_value(0) + self.zoom_c.out_value(1) + self.shift_x_c.out_value(0) + self.shift_y_c.out_value(0)

        @grid.callback()
        def func(value):
            self.grid = value
            return self.draw_grid()

    def out_enable(self, enable):
        return self.enable_c.out_value(enable)

    def reset(self):
        self._matrix = I_MATRIX
        self.roll = 0
        self.pitch = 0
        self.yaw = 0
        self.zoom = 1
        self.shift = [0, 0]

    def draw_grid(self):
        self.video.draw_clear() 
        if self.grid:
            step = self.resolution[0]//(GRID_DIVS+2)
            for i in range(step//2, self.resolution[0], step):
                self.video.draw_line(i, 0, i, self.resolution[1], line={"color": f"rgba(0, 255, 0, 0.25)", "width": 2})
            for i in range(step//2, self.resolution[1], step):
                self.video.draw_line(0, i, self.resolution[0], i, line={"color": f"rgba(0, 255, 0, 0.25)", "width": 2})
        return self.video.out_draw_overlay()

    def set_more(self, val):
            return self.more_c.out_name(Kritter.icon("minus", padding=0) if val else Kritter.icon("plus", padding=0)) + [Output(self.collapse.id, "is_open", val)]

    def calc_roll(self):
        roll = self.roll*math.pi/180
        croll = math.cos(roll)
        sroll = math.sin(roll)
        T1 = np.float32([[1, 0, self.resolution[0]/2], [0, 1, self.resolution[1]/2], [0, 0, 1]])
        R = np.float32([[croll, -sroll, 0], [sroll, croll, 0], [0, 0, 1]])
        T2 = np.float32([[1, 0, -self.resolution[0]/2], [0, 1, -self.resolution[1]/2], [0, 0, 1]])
        Z = np.float32([[self.zoom, 0, 0], [0, self.zoom, 0], [0, 0, 1]])
        return T1@R@Z@T2

    def calc_pitch_yaw(self):
        center_x = self.resolution[0]*(1 + self.shear[0]*self.crop[0] + self.offset[0])/2
        center_y = self.resolution[1]*(1 + self.shear[1]*self.crop[1] + self.offset[1])/2

        pitch = self.pitch*math.pi/180
        yaw = self.yaw*math.pi/180
        if pitch==0:
            x0 = 0
            x1 = self.resolution[0]
        else:
            vanish = center_x, self.f/math.tan(pitch) + center_y
            x0 = line_y(0, self.resolution[1], vanish[0], vanish[1], 0)
            x1 = line_y(self.resolution[0], self.resolution[1], vanish[0], vanish[1], 0)
        if yaw==0:
            y0 = 0
            y1 = self.resolution[1]
        else:
            vanish = self.f/math.tan(yaw) + center_x, center_y
            y0 = line_x(self.resolution[0], 0, vanish[0], vanish[1], 0)
            y1 = line_x(self.resolution[0], self.resolution[1], vanish[0], vanish[1], 0)
        p_in = np.float32([[0, y1], [self.resolution[0], self.resolution[1]], [x1, 0], [x0, y0]])
        phi = math.atan(self.resolution[1]/2/self.f)
        y_stretch = math.sin(math.pi/2+phi)/math.sin(math.pi/2+pitch-phi)
        w = self.resolution[0]/y_stretch
        x_offset = (self.resolution[0] - w)/2
        phi = math.atan(self.resolution[0]/2/self.f)
        x_stretch = math.sin(math.pi/2+phi)/math.sin(math.pi/2+yaw-phi)
        h = self.resolution[1]/x_stretch
        y_offset = (self.resolution[1] - h)/2
        p_out = np.float32([[x_offset, self.resolution[1]-y_offset], [self.resolution[0]-x_offset, self.resolution[1]-y_offset], [self.resolution[0]-x_offset, y_offset], [x_offset, y_offset]])
        return cv2.getPerspectiveTransform(p_in, p_out)

    def calc_matrix(self):
        self._matrix = np.float32([[1, 0, self.shift[0]*self.resolution[0]], [0, 1, self.shift[1]*self.resolution[1]], [0, 0, 1]])@self.calc_roll()@self.calc_pitch_yaw()

    @property
    def matrix(self):
        return self._matrix

    def get_params(self):
        return {"enable": self.enable, "roll": self.roll, "pitch": self.pitch, "yaw": self.yaw, "zoom": self.zoom, "shift": self.shift, "shear": self.shear}

    def set_params(self, value):
        for k, v in value.items():
            try:
                setattr(self, k, v)
            except:
                pass
        self.calc_matrix()
        return self.out_enable(self.enable_c) + self.roll_c.out_value(self.roll) + self.pitch_c.out_value(self.pitch) + self.yaw_c.out_value(self.yaw) + self.zoom_c.out_value(self.zoom) + self.shift_x_c.out_value(self.shift[0]) + self.shift_y_c.out_value(self.shift[1]) + self.shear_x_c.out_value(self.shear[0]) + self.shear_y_c.out_value(self.shear[1])

    def set_intrinsics(self, f, shear_x, shear_y):
        self.f = f 
        self.shear[0] = shear_x
        self.shear[1] = shear_y 

    def set_video_info(self, info):
        self.resolution = info['resolution']
        self.crop = info['crop'] 
        self.offset = info['offset']
        pixelsize = info['pixelsize'][0]
        self.f *= self.pixelsize/pixelsize
        self.pixelsize = pixelsize
        self.calc_matrix()
        return self.draw_grid()

    def transform(self, image):
        return image if np.array_equal(self._matrix, I_MATRIX) else cv2.warpPerspective(image, self._matrix, self.resolution, flags=cv2.INTER_LINEAR)
