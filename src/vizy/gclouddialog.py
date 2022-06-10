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
from kritter import Gcloud, Kritter
from .vizy import BASE_DIR

NO_KEYS = 0
API_KEY = 1
BOTH_KEYS = 3

API_KEY_FILE = "gcloud_api_key.json"

class GcloudDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.state = None
        self.api_key_filename = os.path.join(self.kapp.etcdir, API_KEY_FILE)
        self.gcloud = Gcloud(kapp.etcdir)
        
        style = {"label_width": 3, "control_width": 6}

        self.create_api_key = Kbutton(name=[Kritter.icon("edit"), "Create API key"], target="_blank", external_link=True, href="https://console.cloud.google.com/projectcreate", style=style, service=None)    
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
        self.edit_api_services = Kbutton(name=[Kritter.icon("edit"), "Edit API services"], target="_blank", external_link=True, style=style, service=None) 
        self.remove_api_key = Kbutton(name=[Kritter.icon("trash"), "Remove API key"], style=style, service=None) 
        self.edit_api_services.append(self.remove_api_key)
        self.authorize = Kbutton(name=[Kritter.icon("thumbs-up"), "Authorize"], target="_blank", external_link=True, style=style, service=None) 

        self.remove_authorization = Kbutton(name=[Kritter.icon("trash"), "Remove authorization"], service=None)
        self.test_image = Kbutton(name=[Kritter.icon("cloud-upload"), "Upload test image"], spinner=True, service=None)
        self.test_email = Kbutton(name=[Kritter.icon("envelope"), "Send test email..."], spinner=True, service=None)
        self.test_image.append(self.test_email)

        self.error_text = Ktext(style={"control_width": 12})   
        self.error_dialog = KokDialog(title=[Kritter.icon("exclamation-circle"), "Error"], layout=self.error_text)
        self.success_text = Ktext(style={"control_width": 12})   
        self.success_dialog = KokDialog(title=[Kritter.icon("check-square-o"), "Success"], layout=self.success_text)

        self.code = KtextBox(style={"control_width": 12}, placeholder="Paste code text here.", service=None)
        self.submit = Kbutton(name=[Kritter.icon("cloud-upload"), "Submit"], service=None)
        self.code_dialog = Kdialog(title=[Kritter.icon("google"), "Submit code"], layout=self.code, left_footer=self.submit)

        self.email = KtextBox(style={"control_width": 12}, placeholder="Type email address", service=None)
        self.send_email = Kbutton(name=[Kritter.icon("envelope"), "Send"], service=None)
        self.email_dialog = Kdialog(title=[Kritter.icon("google"), "Send test email"], layout=self.email, left_footer=self.send_email)

        layout = [self.create_api_key, self.upload_api_key_div, self.edit_api_services, self.authorize, self.remove_authorization, self.test_image, self.error_dialog, self.success_dialog, self.code_dialog, self.email_dialog]

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
            if not filename.lower().endswith('.json'):
                return self.error_text.out_value('The credentials file needs to be in JSON format.') + self.error_dialog.out_open(True)
            try:
                data = json.loads(contents)
                if 'installed' not in data:
                    return self.error_text.out_value('The application type needs to be "desktop app".') + self.error_dialog.out_open(True)
                with open(self.api_key_filename, "wb") as file:
                    file.write(contents)
                self.get_urls()
                self.state = API_KEY
                return self.update()
            except Exception as e:
                return self.error_text.out_value(f"There's been an error: {e}") + self.error_dialog.out_open(True)
 
        @self.remove_api_key.callback()
        def func():
            os.remove(self.api_key_filename)
            self.state = None
            # We need to reset the contents, otherwise we won't get a callback when 
            # uploading the same file.
            return [Output(self.upload_api_key.id, 'contents', None)] + self.update()

        @self.authorize.callback()
        def func():
            return self.code.out_value("") + self.code_dialog.out_open(True)

        @self.submit.callback(self.code.state_value())
        def func(code):
            try:
                self.gcloud.set_code(code)
            except Exception as e:
                print(f"Encountered exception while setting code: {e}")
            self.state = None
            return self.code_dialog.out_open(False) + self.update()

        @self.test_email.callback()
        def func():
            return self.email_dialog.out_open(True) 

        @self.remove_authorization.callback()
        def func():
            self.gcloud.remove_creds()
            self.state = None
            return self.update()

        @self.test_image.callback()
        def func():
            # Enable spinner, showing we're busy, and since we're not shared, we need to 
            # send mods to specific client.
            self.kapp.push_mods(self.test_image.out_spinner_disp(True), callback_context.client)
            image = self.generate_test_image()
            # Upload                                                   
            gpsm = self.gcloud.get_interface("KstoreMedia")
            result = self.test_image.out_spinner_disp(False)
            try:
                gpsm.store_image_array(image, desc="Vizy test image")
                result += self.success_text.out_value(["Success! Check your Google Photos account ", dcc.Link("(photos.google.com)", target="_blank", href="https://photos.google.com")]) + self.success_dialog.out_open(True)
            except Exception as e:
                result += self.error_text.out_value(f"An error occurred: {e}") + self.error_dialog.out_open(True)
            return result

        @self.send_email.callback(self.email.state_value())
        def func(email):
            # Enable spinner, showing we're busy, and since we're not shared, we need to 
            # send mods to specific client.
            self.kapp.push_mods(self.test_email.out_spinner_disp(True), callback_context.client)
            gtc = self.gcloud.get_interface("KtextClient")
            gtc.text(email, "This is a test. Thank you for your cooperation.", subject="Vizy test email")
            gtc.image(email, self.generate_test_image())
            result = self.test_email.out_spinner_disp(False) + self.email_dialog.out_open(False) + self.email.out_value("")
            try:
                gtc.send()
                result += self.success_text.out_value(["Success! Check your Gmail account ", dcc.Link("(mail.google.com)", target="_blank", href="https://mail.google.com")]) + self.success_dialog.out_open(True)
            except Exception as e:
                result += self.error_text.out_value(f"An error occurred: {e}") + self.error_dialog.out_open(True)
            return result

    def generate_test_image(self):
        image =  cv2.imread(os.path.join(BASE_DIR, "test.jpg"))
        date = datetime.now().strftime("%m-%d-%Y %H:%M:%S")
        image = cv2.putText(image, "VIZY TEST IMAGE",  (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (25, 25, 25), 3)
        image = cv2.putText(image, date,  (50, 140), cv2.FONT_HERSHEY_SIMPLEX, 1, (25, 25, 25), 3)
        return image

    def get_urls(self):
        try:
            with open(self.api_key_filename) as file:
                data = json.load(file)
            self.api_project_url = f"https://console.cloud.google.com/apis/dashboard?project={data['installed']['project_id']}"
            self.auth_url = self.gcloud.get_url(self.api_key_filename)
        except:
            self.api_project_url = None
            self.auth_url = None

    def out_upload_api_key_disp(self, disp):
        return [Output(self.upload_api_key_div.id, "style", {"display": "block"})] if disp else [Output(self.upload_api_key_div.id, "style", {"display": "none"})]

    def update(self):
        if self.state is None:
            self.state = NO_KEYS
            self.get_urls()
            if self.api_project_url:
                self.state = API_KEY
                if self.gcloud.creds():
                    self.state = BOTH_KEYS

        if self.state==NO_KEYS:
            return self.create_api_key.out_disp(True) + self.out_upload_api_key_disp(True) + self.edit_api_services.out_disp(False) + self.remove_api_key.out_disp(False) + self.authorize.out_disp(False) + self.remove_authorization.out_disp(False) + self.test_image.out_disp(False) + self.test_email.out_disp(False)
        elif self.state==API_KEY:
            return self.create_api_key.out_disp(False) + self.out_upload_api_key_disp(False) + self.edit_api_services.out_disp(True) + self.edit_api_services.out_url(self.api_project_url) + self.remove_api_key.out_disp(True) + self.authorize.out_disp(True) + self.authorize.out_url(self.auth_url) + self.remove_authorization.out_disp(False) + self.test_image.out_disp(False) + self.test_email.out_disp(False)
        else: # self.state==BOTH_KEYS
            interfaces = self.gcloud.available_interfaces()
            return self.create_api_key.out_disp(False) + self.out_upload_api_key_disp(False) + self.edit_api_services.out_disp(True) + self.edit_api_services.out_url(self.api_project_url) + self.remove_api_key.out_disp(True) + self.authorize.out_disp(False) + self.remove_authorization.out_disp(True) + self.test_image.out_disp("KstoreMedia" in interfaces) + self.test_email.out_disp("KtextClient" in interfaces)

