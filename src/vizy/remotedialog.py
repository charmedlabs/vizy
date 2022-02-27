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
import subprocess
import json
import datetime
from threading import Thread
import dash_bootstrap_components as dbc
import dash_html_components as html
import dash_core_components as dcc
from kritter import Kritter, Ktext, Kbutton, Kdialog, KsideMenuItem
from dash_devices.dependencies import Input, Output, State

class RemoteDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.process = None
        self.run = False

        style = {"label_width": 2, "control_width": 10}
        self.url_store = dcc.Store(data="https://hello.com", id=Kritter.new_id())
        self.start_button = Kbutton(name=[Kritter.icon("play"), "Start"], spinner=True)
        self.copy_button = dbc.Button(Kritter.icon("copy", padding=0), id=Kritter.new_id(), style={"margin": "0 5px 0 5px"})
        self.status = Ktext(name="Status", value='Press start to get remote access.', style=style)
        layout = [self.status, self.url_store]

        self.dialog = Kdialog(title=[Kritter.icon("binoculars"), "Remote"], layout=layout, left_footer=self.start_button)
        self.layout = KsideMenuItem("Remote", self.dialog, "binoculars")

        @self.start_button.callback()
        def func():
            # Start spinner before thread exits to avoid race condition.
            self.kapp.push_mods(self.start_button.out_spinner_disp(True))
            if self.run:
                self.run = False
                try:
                    self.process.terminate()
                except:
                    pass
            else:
                self.run = True
                Thread(target=self.thread).start()
                

        # This code copies to the clipboard using the hacky method.  
        # (You need a secure page (https) to perform navigator.clipboard operations.)   
        script = """
            function(click, url) {
                var textArea = document.createElement("textarea");
                textArea.value = url;
                textArea.style.position = "fixed";  
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();
                document.execCommand('copy');
                textArea.remove();
            }
        """
        self.kapp.clientside_callback(script, Output("_none", Kritter.new_id()), [Input(self.copy_button.id, "n_clicks")], state=[State(self.url_store.id, "data")])

    def new_url(self, url):
        return [Output(self.url_store.id, "data", url)] + self.status.out_value([f'Go to: {url}', self.copy_button, f'(Created at {datetime.datetime.now().strftime("%I:%M:%S %p")})'])

    def thread(self):
        command = ["ssh", "-oStrictHostKeyChecking=no", "-R", "80:localhost:80", "nokey@localhost.run", "--", "--output", "json"]
        while self.run:
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.kapp.push_mods(self.start_button.out_name([Kritter.icon("stop"), "Stop"]) + self.start_button.out_spinner_disp(False))
            while True:
                out = self.process.stdout.readline()
                if out==b"":
                    break
                out = json.loads(out.decode("utf-8"))
                print("URL:", out['address'])
                self.kapp.push_mods(self.new_url(f"https://{out['address']}"))
            self.process.wait()
            self.kapp.push_mods(self.start_button.out_name([Kritter.icon("play"), "Start"]) + self.start_button.out_spinner_disp(False) + self.status.out_value('Press start to get remote access.'))

    def close(self):
        self.run = False
        if self.process:
            try:
                self.process.terminate()
            except:
                pass



