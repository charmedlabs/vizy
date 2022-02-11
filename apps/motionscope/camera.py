#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

from tab import Tab
import kritter
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc

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
            return self.framerate.out_value(camera.framerate) + self.framerate.out_min(camera.min_framerate) + self.framerate.out_max(camera.max_framerate)

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
        frame = self.stream.frame()
        if frame:
            return frame[0]

