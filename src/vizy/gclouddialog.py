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
import cv2
import dash_html_components as html
import dash_core_components as dcc
from dash_devices import callback_context
from kritter import Kritter, KtextBox, Ktext, Kdropdown, Kbutton, Kdialog, KsideMenuItem
from dash_devices.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
from kritter import Gcloud, Kritter, GPstoreMedia
from .vizy import BASE_DIR

NO_KEYS = 0
API_KEY = 1
CODE_INPUT = 2
BOTH_KEYS = 3

class GcloudDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.state = None
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

        layout = [self.create_api_key, self.upload_api_key]

        dialog = Kdialog(title=[Kritter.icon("google"), "Google Cloud configuration"], layout=layout)
        self.layout = KsideMenuItem("Google Cloud", dialog, "google")

        @self.kapp.callback_shared(None,
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
 

    def update(self):
        return
        if self.state!=CODE_INPUT:
            self.state = UNAUTHORIZED if self.gcloud.creds() is None else AUTHORIZED

        if self.state==UNAUTHORIZED:
            return self.authenticate.out_disp(True) + self.code.out_disp(False) + self.submit.out_disp(False) + self.test_image.out_disp(False) + self.remove.out_disp(False) + self.out_status(None)
        elif self.state==CODE_INPUT:
            return self.authenticate.out_disp(False) + self.code.out_disp(True) + self.submit.out_disp(True) + self.code.out_value("") + self.test_image.out_disp(False) + self.remove.out_disp(False) + self.out_status(None)
        else:
            return self.authenticate.out_disp(False) + self.code.out_disp(False) + self.submit.out_disp(False) + self.test_image.out_disp(True) + self.remove.out_disp(True) + self.out_status(None)


