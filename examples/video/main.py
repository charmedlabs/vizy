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
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy, Perspective
from kritter.ktextvisor import KtextVisor, KtextVisorTable, Image


FOCAL_LENGTH = 2260 # measured in pixels, needed for perspective change
FRAMERATE_FOCUS_THRESHOLD = 4

class Video: 
    def __init__(self):
        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream()

        # Create Kritter server.
        kapp = Vizy()
        style = {"label_width": 3, "control_width": 6}

        # Create video component and histogram enable.
        self.video = kritter.Kvideo(width=self.camera.resolution[0], overlay=True)
        hist_enable = kritter.Kcheckbox(name='Histogram', value=False, style=style)

        # Create perspective control and set video modes. 
        self.perspective = Perspective(self.video, FOCAL_LENGTH, self.camera.getmodes()[self.camera.mode], style=style)
        self.perspective.set_video_info_modes([i for m, i in self.camera.getmodes().items()])       

        # Create remaining controls for mode, brightness, framerate, and white balance. 
        mode = kritter.Kdropdown(name='Camera mode', options=self.camera.getmodes(), value=self.camera.mode, style=style)
        brightness = kritter.Kslider(name="Brightness", value=self.camera.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style=style)
        self.shutter = kritter.Kslider(name="Shutter-speed", value=self.camera.shutter_speed, mxs=(.0001, 1/self.camera.framerate, .0001), format=lambda val: f'{val:.4f} s', style=style)
        self.framerate = kritter.Kslider(name="Framerate", value=self.camera.framerate, format=lambda val : f'{val:.2f} fps', updatemode='mouseup', style=style)
        self.framerate.focused = False # Start out in unfocused mode for framerate
        autoshutter = kritter.Kcheckbox(name='Auto-shutter', value=self.camera.autoshutter, style=style)
        shutter_cont = dbc.Collapse(self.shutter, id=kapp.new_id(), is_open=not self.camera.autoshutter, style=style)
        awb = kritter.Kcheckbox(name='Auto-white-balance', value=self.camera.awb, style=style)
        red_gain = kritter.Kslider(name="Red gain", value=self.camera.awb_red, mxs=(0.05, 2.0, 0.01), style=style)
        blue_gain = kritter.Kslider(name="Blue gain", value=self.camera.awb_red, mxs=(0.05, 2.0, 0.01), style=style)
        awb_gains = dbc.Collapse([red_gain, blue_gain], id=kapp.new_id(), is_open=not self.camera.awb)     
        ir_filter = kritter.Kcheckbox(name='IR filter', value=kapp.power_board.ir_filter(), style=style)
        ir_light = kritter.Kcheckbox(name='IR light', value=kapp.power_board.vcc12(), style=style)

        controls = html.Div([hist_enable, self.perspective.layout, mode, brightness, self.framerate, autoshutter, shutter_cont, awb, awb_gains, ir_filter, ir_light])

        # Add video component and controls to layout.
        kapp.layout = html.Div([self.video, controls], style={"padding": "15px"})
        kapp.push_mods(self.handle_framerate())

        @hist_enable.callback()
        def func(value):
            return self.video.out_hist_enable(value)

        @brightness.callback()
        def func(value):
            self.camera.brightness = value

        @self.framerate.callback()
        def func(value):
            self.camera.framerate = value
            return self.handle_framerate()
            
        @mode.callback()
        def func(value):
            self.camera.mode = value
            return self.video.out_width(self.camera.resolution[0]) + self.framerate.out_value(self.camera.framerate) + self.framerate.out_min(self.camera.min_framerate) + self.framerate.out_max(self.camera.max_framerate)

        @autoshutter.callback()
        def func(value):
            self.camera.autoshutter = value
            return Output(shutter_cont.id, 'is_open', not value)

        @self.shutter.callback()
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

        # Invoke KtextVisor client, which relies on the server running.
        # In case it isn't running, we just roll with it.  
        try:
            tv = KtextVisor()
            def grab(sender, words, context):
                frame = self.frame # copy frame
                return Image(frame)
        
            tv_table = KtextVisorTable({"grab": (grab, "Grabs frame and displays it.")})
            @tv.callback_receive()
            def func(words, sender, context):
                return tv_table.lookup(words, sender, context)
        except:
            tv = None

        # Run camera grab thread.
        self.run_grab = True
        Thread(target=self.grab).start()

        # Run Kritter server, which blocks.
        kapp.run()
        self.run_grab = False
        if tv:
            tv.close()

    # This logic deals with the framerate slider, and its transition from "focused" state, 
    # where its range is reduced to min_framerate--to--FRAMERATE_FOCUS_THRESHOLD+0.5 so 
    # you can more easily adjust the framerate at those low values -- to "not focused" state where the 
    # range is normal (min_framerate--to--max_framerate).  It also updates the shutter min/max values
    # to  
    def handle_framerate(self):
        mods = self.framerate.out_min(self.camera.min_framerate) + self.framerate.out_step(.001) 
        if self.camera.min_framerate<FRAMERATE_FOCUS_THRESHOLD:
            mods += self.framerate.out_marks({FRAMERATE_FOCUS_THRESHOLD: ""})
            if self.framerate.focused:
                if self.camera.framerate>FRAMERATE_FOCUS_THRESHOLD:
                    mods += self.framerate.out_max(self.camera.max_framerate)
                    self.framerate.focused = False
            else:
                if self.camera.framerate<=FRAMERATE_FOCUS_THRESHOLD:
                    mods += self.framerate.out_max(FRAMERATE_FOCUS_THRESHOLD+0.5)
                    self.framerate.focused = True
                else:
                    mods += self.framerate.out_max(self.camera.max_framerate)
        else:
            mods += self.framerate.out_max(self.camera.max_framerate) + self.framerate.out_marks({})
        # Change shutter slider ranges based on the framerate
        return mods + self.shutter.out_max(1/self.camera.framerate) + self.shutter.out_value(self.camera.shutter_speed) 

    # Frame grabbing thread
    def grab(self):
        while self.run_grab:
            # Get frame
            frame = self.stream.frame()
            self.frame = self.perspective.transform(frame[0])
            # Send frame
            self.video.push_frame(self.frame)


if __name__ == "__main__":
    Video()
