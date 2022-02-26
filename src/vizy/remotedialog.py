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
import dash_html_components as html
import dash_core_components as dcc
from kritter import Kritter, Ktext, Kbutton, Kdialog, KsideMenuItem
from dash_devices.dependencies import Input, Output, State

class RemoteDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp

        style = {"label_width": 2, "control_width": 8}
        self.status = Ktext(name="Status", value="Press Start to get remote access.", style=style)
        self.url = dcc.Store(data="https://hello.com", id=Kritter.new_id())
        self.start_button = Kbutton(name=[Kritter.icon("play"), "Start"])
        self.copy_button = Kbutton(name=[Kritter.icon("copy"), "Copy URL"])
        self.start_button.append(self.copy_button)
        layout = [self.status, self.url]

        self.dialog = Kdialog(title=[Kritter.icon("binoculars"), "Remote"], layout=layout, left_footer=self.start_button)
        self.layout = KsideMenuItem("Remote", self.dialog, "binoculars")

        # This code copies to the clipboard using a hacky method.  
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
        self.kapp.clientside_callback(script, Output("_none", Kritter.new_id()), [Input(self.copy_button.id, "n_clicks")], state=[State(self.url.id, "data")])

