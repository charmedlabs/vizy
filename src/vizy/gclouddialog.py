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
from datetime import datetime
import base64
import json
import cv2
import dash_html_components as html
import dash_core_components as dcc
from dash_devices import callback_context
from kritter import Kritter, KtextBox, Ktext, Kdropdown, Kbutton, Kdialog, KokDialog, KsideMenuItem
from dash_devices.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
from kritter import Gcloud, Kritter, GPstoreMedia
from .vizy import BASE_DIR

NO_KEYS = 0
API_KEY = 1
CODE_INPUT = 2
BOTH_KEYS = 3

API_KEY_FILE = "gcloud_api_key.json"

class GcloudDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.state = None
        self.api_key_filename = os.path.join(self.kapp.etcdir, API_KEY_FILE)
        self.gcloud = Gcloud(kapp.etcdir)
        
        style = {"label_width": 3, "control_width": 6}

        self.create_api_key = Kbutton(name=[Kritter.icon("thumbs-up"), "Create API key"], target="_blank", external_link=True, href="https://console.cloud.google.com/projectcreate", style=style, service=None)    
        self.upload_api_key = dcc.Upload(id=Kritter.new_id(), children=html.Div([
                html.Div('Drag and drop API key file here.'),
                html.Div('Or click here to select local file.'),
            ]), style={
                'width': '100%',
                'height': '100px',
                'lineHeight': '20px',
                'padding-top': '30px',
                'borderWidth': '1px',
                'borderStyle': 'dashed',
                'borderRadius': '5px',
                'textAlign': 'center',
            },
            multiple=False
        )  
        self.upload_api_key_div = html.Div(self.upload_api_key, id=Kritter.new_id())      
        self.edit_api_services = Kbutton(name=[Kritter.icon("thumbs-up"), "Edit API services"], target="_blank", external_link=True, style=style, service=None) 
        self.remove_api_key = Kbutton(name=[Kritter.icon("thumbs-up"), "Remove API key"], style=style, service=None) 
        self.error_text = Ktext(style={"control_width": 12})   
        self.error_dialog = KokDialog(title=[Kritter.icon("exclamation"), "Error"], layout=self.error_text)
        layout = [self.create_api_key, self.upload_api_key_div, self.edit_api_services, self.remove_api_key, self.error_dialog]

        dialog = Kdialog(title=[Kritter.icon("google"), "Google Cloud configuration"], layout=layout)
        self.layout = KsideMenuItem("Google Cloud", dialog, "google")

        @dialog.callback_view()
        def func(open):
            if open:
                return self.update()

        @self.kapp.callback(None,
            [Input(self.upload_api_key.id, 'contents')], [State(self.upload_api_key.id, 'filename')]
        )
        def func(contents, filename):
            # Block unauthorized attempts
            if not callback_context.client.authentication&pmask or not contents or not filename:
                return
            # Contents are type and contents separated by comma, so we grab 2nd item.
            # See https://dash.plotly.com/dash-core-components/upload
            contents = base64.b64decode(contents.split(",")[1])
            # Make temp directory 
            print(contents, filename)
            if not filename.lower().endswith('.json'):
                return self.error_text.out_value('The credentials file needs to be in JSON format.') + self.error_dialog.out_open(True)
            try:
                data = json.loads(contents)
                if 'installed' not in data:
                    return self.error_text.out_value('The application type needs to be "desktop app".') + self.error_dialog.out_open(True)
                with open(self.api_key_filename, "wb") as file:
                    file.write(contents)
                self.get_api_project_url()
                self.state = API_KEY
                return self.update()
            except Exception as e:
                return self.error_text.out_value(f"There's been an error: {e}") + self.error_dialog.out_open(True)
 
        @self.remove_api_key.callback()
        def func():
            os.remove(self.api_key_filename)
            self.state = None
            return self.update()
            
    def get_api_project_url(self):
        try:
            with open(self.api_key_filename) as file:
                data = json.load(file)
            self.api_project_url = f"https://console.cloud.google.com/apis/dashboard?project={data['installed']['project_id']}"
        except:
            self.api_project_url = None

    def out_upload_api_key_disp(self, disp):
        return [Output(self.upload_api_key_div.id, "style", {"display": "block"})] if disp else [Output(self.upload_api_key_div.id, "style", {"display": "none"})]

    def update(self):
        if self.state is None:
            self.state = NO_KEYS
            self.get_api_project_url()
            if self.api_project_url:
                self.state = API_KEY

        if self.state==NO_KEYS:
            return self.create_api_key.out_disp(True) + self.out_upload_api_key_disp(True) + self.edit_api_services.out_disp(False) + self.remove_api_key.out_disp(False)

        if self.state==API_KEY:
            return self.create_api_key.out_disp(False) + self.out_upload_api_key_disp(False) + self.edit_api_services.out_disp(True) + self.edit_api_services.out_url(self.api_project_url) + self.remove_api_key.out_disp(True)
