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


MIN_FRAMERATE = 1 

class Camera(Tab):

    def __init__(self, main):

        super().__init__("Camera", main.data)
        self.main = main
        self.stream = main.camera.stream()

        style = {"label_width": 3, "control_width": 6, "max_width": main.config_consts.WIDTH}

        modes = ["640x480x10bpp (cropped)", "768x432x10bpp"]
        all_modes = main.camera.getmodes()
        main.perspective.set_video_info_modes([all_modes[m] for m in modes])

        self.mode = kritter.Kdropdown(name='Camera mode', options=modes, style=style)
        self.brightness = kritter.Kslider(name="Brightness", mxs=(0, 100, 1), format=lambda val: f'{val}%', style=style)
        self.framerate = kritter.Kslider(name="Framerate", mxs=(max(int(main.camera.min_framerate), MIN_FRAMERATE), int(main.camera.max_framerate), 1), format=lambda val : f'{val} fps', updatemode='mouseup', style=style)
        self.autoshutter = kritter.Kcheckbox(name='Auto-shutter', style=style)
        self.shutter = kritter.Kslider(name="Shutter-speed", mxs=(.0001, 1/main.camera.framerate, .0001), format=lambda val: f'{val:.4f}s', style=style)
        shutter_cont = dbc.Collapse(self.shutter, id=self.kapp.new_id(), is_open=not main.camera.autoshutter, style=style)
        self.awb = kritter.Kcheckbox(name='Auto-white-balance', style=style)
        self.red_gain = kritter.Kslider(name="Red gain", mxs=(0.05, 2.0, 0.01), style=style)
        self.blue_gain = kritter.Kslider(name="Blue gain", mxs=(0.05, 2.0, 0.01), style=style)
        awb_gains = dbc.Collapse([self.red_gain, self.blue_gain], id=self.kapp.new_id())   

        self.settings_map = {"mode": self.mode, "brightness": self.brightness, "framerate": self.framerate, "autoshutter": self.autoshutter, "shutter": self.shutter, "awb": self.awb, "red_gain": self.red_gain, "blue_gain": self.blue_gain}

        @self.mode.callback()
        def func(value):
            self.data[self.name]["mode"] = value
            main.camera.mode = value
            return self.framerate.out_value(main.camera.framerate) + self.framerate.out_min(max(int(main.camera.min_framerate), MIN_FRAMERATE)) + self.framerate.out_max(int(main.camera.max_framerate))

        @self.brightness.callback()
        def func(value):
            self.data[self.name]["brightness"] = value
            main.camera.brightness = value

        @self.framerate.callback()
        def func(value):
            self.data[self.name]["framerate"] = value
            main.camera.framerate = value
            return self.shutter.out_value(main.camera.shutter_speed) + self.shutter.out_max(1/main.camera.framerate)

        @self.autoshutter.callback()
        def func(value):
            self.data[self.name]["autoshutter"] = value
            main.camera.autoshutter = value
            return Output(shutter_cont.id, 'is_open', not value)

        @self.shutter.callback()
        def func(value):
            self.data[self.name]["shutter"] = value
            main.camera.shutter_speed = value    

        @self.awb.callback()
        def func(value):
            self.data[self.name]["awb"] = value
            main.camera.awb = value
            return Output(awb_gains.id, 'is_open', not value)

        @self.red_gain.callback()
        def func(value):
            self.data[self.name]["red_gain"] = value
            main.camera.awb_red = value

        @self.blue_gain.callback()
        def func(value):
            self.data[self.name]["blue_gain"] = value
            main.camera.awb_blue = value
         
        self.layout = dbc.Collapse([self.mode, self.brightness, self.framerate, self.autoshutter, shutter_cont, self.awb, awb_gains], id=self.kapp.new_id(), is_open=True)

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

    def focus(self, state):
        if state:    
            return self.main.perspective.out_disp(True)

    def reset(self):
        return self.settings_update(self.main.config_consts.DEFAULT_CAMERA_SETTINGS)

    def frame(self):
        frame = self.stream.frame()
        if frame:
            return frame[0]

