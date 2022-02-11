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
import dash_html_components as html
import dash_bootstrap_components as dbc
from dash_devices.dependencies import Output
from dash_devices import callback_context
import vizy.vizypowerboard as vpb
from datetime import datetime
from kritter import Kritter, Ktext, Kdialog, Kdropdown, Kbutton, KsideMenuItem, KokDialog

SYNC_MESSAGE = [html.P("""
The system time synchronizer (systemd-timesyncd) retrieves an accurate time/date from a 
public Internet server and sets it automatically. Your Vizy is currently able to contact the server 
and accurately set the time (sweet!) The "Time" dialog is intended to be used when your Vizy 
is not able to make contact with the server. Note, you will not be able to set the time as long as the 
synchronizer is able to make contact (the time you set will be overwritten.)"""), 
html.P("""If the time is incorrect, the timezone setting may be wrong. Set the
timezone by running "sudo raspi-config" and selecting "Localisation Options".""")]

class TimeDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.run = 0
        self.thread = None
        self.mtime = 0

        style = {"label_width": 4, "control_width": 4}
        self.months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        self.days = [str(i) for i in range(1, 32)]
        self.years = [str(i) for i in range(2021, 2030)]
        self.hours = [str(i) for i in range(1, 24)]
        self.minutes = [str(i) for i in range(0, 60)]

        self.time_c = Ktext(name="Time", style={"label_width": 4, "control_width": 6})
        self.month_c = Kdropdown(name='Month', options=self.months, style=style)
        self.day_c = Kdropdown(name='Day', options=self.days, style=style)
        self.year_c = Kdropdown(name='Year', options=self.years, style=style)
        self.hour_c = Kdropdown(name='Hour', options=self.hours, style=style)
        self.minute_c = Kdropdown(name='Minute', options=self.minutes, style=style)
        self.set = Kbutton(name=[Kritter.icon("clock-o"), "Set"])
        self.ok = KokDialog(layout=SYNC_MESSAGE)
        layout = [self.time_c, self.month_c, self.day_c, self.year_c, self.hour_c, self.minute_c, self.ok]
        dialog = Kdialog(title=[Kritter.icon("clock-o"), "Clock"], left_footer=self.set, layout=layout)
        self.layout = KsideMenuItem("Clock", dialog, "clock-o")

        @dialog.callback_view()
        def func(open):
            if open:
                self.run += 1
                if self.run==1:
                    self.thread = Thread(target=self.update_thread)
                    self.thread.start() 
                clock = datetime.now()
                return self.month_c.out_value(self.months[clock.month-1]) + self.day_c.out_value(str(clock.day)) + self.year_c.out_value(str(clock.year)) + self.hour_c.out_value(str(clock.hour)) + self.minute_c.out_value(str(clock.minute))
            elif self.run>0:  # Stale dialogs in browser can result in negative counts.
                self.run -= 1

        @self.set.callback(self.month_c.state_value() + self.day_c.state_value() + self.year_c.state_value() + self.hour_c.state_value() + self.minute_c.state_value())
        def func(month, day, year, hour, minute):
            clock = datetime(int(year), self.months.index(month)+1, int(day), int(hour), int(minute))
            self.kapp.power_board.rtc(clock)
            self.kapp.power_board.rtc_set_system_datetime(clock)
            return self.update()


    def update_thread(self):
        while(self.run):
            mods = self.update()
            try:
                mtime = os.path.getmtime("/run/systemd/timesync/synchronized")
                # Look for change in mtime, which indicates an update
                if self.mtime and self.mtime!=mtime:
                    mods += self.ok.out_open(True)
                self.mtime = mtime 
            except:
                pass
            self.kapp.push_mods(mods) 
            time.sleep(1)

    def update(self):
        clock = datetime.now()
        return self.time_c.out_value(clock.strftime('%B %d, %Y %H:%M:%S'))

    def close(self):
        self.run = 0 
