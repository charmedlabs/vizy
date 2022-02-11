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
from threading import Thread
import dash_bootstrap_components as dbc
from dash_devices.dependencies import Output
from dash_devices import callback_context
import vizy.vizypowerboard as vpb
from kritter import Kritter, Ktext, Kradio, Kdialog, Kslider, Kbutton, KsideMenuItem

# The on time can't be less than the MIN_TIME in the future, otherwise, there might not
# be enough time to shut down!
MIN_TIME = 30 # seconds

class RebootDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.run = 0
        self.thread = None
        self.time = 0
        self.ontime = 0
        self.seconds = self.minutes = self.hours = self.days = 0 

        style = {"label_width": 2, "control_width": 9}
        self.options = ["Reboot", "Power off", "Power off, on"]
        self.type_c = Kradio(value=self.options[0], options=self.options, style=style)
        self.apply = Kbutton(name=[Kritter.icon("check-square-o"), "Apply"], spinner=True)
        self.seconds_c = Kslider(name="Seconds", value=0, mxs=(0, 59, 1))
        self.minutes_c = Kslider(name="Minutes", value=0, mxs=(0, 59, 1))
        self.hours_c = Kslider(name="Hours", value=0, mxs=(0, 23, 1))
        self.days_c = Kslider(name="Days", value=0, mxs=(0, 30, 1))
        self.ontime_c = Ktext(name="Turn-on time")
        self.currtime_c = Ktext(name="Current time")
        self.on_controls = dbc.Collapse([self.currtime_c, self.ontime_c, self.seconds_c, self.minutes_c, self.hours_c, self.days_c], id=Kritter.new_id(), is_open=False)
        layout = [self.type_c, self.on_controls]
        dialog = Kdialog(title=[Kritter.icon("power-off"), "Reboot/power"], layout=layout, left_footer=self.apply, close_button=[Kritter.icon("close"), "Cancel"])
        self.layout = KsideMenuItem("Reboot/power", dialog, "power-off")

        @dialog.callback_view()
        def func(open):
            if open:
                self.run += 1
                if self.run==1:
                    self.thread = Thread(target=self.update_thread)
                    self.thread.start()
                return self.type_c.out_value(self.options[0])
            elif self.run>0:  # Stale dialogs in browser can result in negative counts.
                self.run -= 1

        @self.type_c.callback()
        def func(type):
            if type==self.options[2]: # off, on
                return [Output(self.on_controls.id, "is_open", True)] + self.update()
            else:
                return Output(self.on_controls.id, "is_open", False)

        @self.seconds_c.callback()
        def func(seconds):
            self.seconds = seconds
            return self.update()

        @self.minutes_c.callback()
        def func(minutes):
            self.minutes = minutes
            return self.update()

        @self.hours_c.callback()
        def func(hours):
            self.hours = hours
            return self.update()

        @self.days_c.callback()
        def func(days):
            self.days = days
            return self.update()

        @self.apply.callback(self.type_c.state_value())
        def func(type):
            if not callback_context.client.authentication&pmask:
                return  
            # This is a bit of reassuring feedback that the reboot/power down is taking effect.
            self.kapp.push_mods(self.apply.out_spinner_disp(True))
            time.sleep(2)
            # More feedback...
            self.kapp.push_mods(self.kapp.out_main(None))
            # Give it time to propagate to the browser before we get terminated.
            time.sleep(1)
            if type==self.options[0]: # Reboot
                os.system("reboot now")
            elif type==self.options[1]: # Power off
                self.kapp.power_board.power_off_requested(True)
            else: # Power off then on
                # Set power on alarm accordingly.
                self.kapp.power_board.power_on_alarm_seconds(self.ontime - time.time())
                self.kapp.power_board.power_off_requested(True)

    def update_thread(self):
        while(self.run):
            self.kapp.push_mods(self.update()) 
            time.sleep(1)

    def update(self):
        t0 = time.time() 
        t1 = self.seconds + self.minutes*60 + self.hours*60*60 + self.days*60*60*24
        if self.time+t1-t0<MIN_TIME:
            self.time = t0
        if t1<MIN_TIME:
            t1 = MIN_TIME
        self.ontime = self.time + t1
        return self.ontime_c.out_value(time.strftime('%c', time.localtime(self.ontime))) + self.currtime_c.out_value(time.strftime('%c', time.localtime(t0)))

    def close(self):
        self.run = 0 
