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
from tkinter import dialog
import cv2
import dash_html_components as html
import dash_core_components as dcc
from dash_devices import callback_context
from kritter import Kritter, KtextBox, Ktext, Kdropdown, Kbutton, Kdialog, KokDialog, KsideMenuItem
from dash_devices.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
from kritter import Kritter
from .vizy import BASE_DIR


"""
Dialog development plan:
Onboarding Dialog.  
You can look at the code in VizyVisor like TimeDialog or GcloudDialog to see how dialogs are done.  
1. needs to accept a token as input, save it to the etc directory as a json file (like GcloudDialog does).  
2. A button to test things 
    a. needs to receive a message --> bring up another dialog and wait for a message, then print it the message
    b. User dismisses by pressing OK. 
"""




NO_KEYS = 0
API_KEY = 1
BOTH_KEYS = 3

BOT_TOKEN_FILE = "telegram_bot_token.json"

class TelegramDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.state = None # state of token presence - has a token been successfully added or not
        self.bot_token_filename = os.path.join(self.kapp.etcdir, BOT_TOKEN_FILE)
        # self.gcloud = Gcloud(kapp.etcdir) # 
        
        style = {"label_width": 3, "control_width": 6} # overall style..?

        # copied from gclouddialog.py
        self.error_text = Ktext(style={"control_width": 12})   
        self.error_dialog = KokDialog(title=[Kritter.icon("exclamation-circle"), "Error"], layout=self.error_text)
        self.success_text = Ktext(style={"control_width": 12})   
        self.success_dialog = KokDialog(title=[Kritter.icon("check-square-o"), "Success"], layout=self.success_text)

        # also copied from gclouddialogue.py
        self.code = KtextBox(style={"control_width": 12}, placeholder="Paste bot token here.", service=None)
        self.submit = Kbutton(name=[Kritter.icon("cloud-upload"), "Submit"], service=None)
        self.code_dialog = Kdialog(title=[Kritter.icon("google"), "Submit code"], layout=self.code, left_footer=self.submit)

        self.title = Ktext(name="Telegram", style={"label_width":12, "control_width": 12})

        layout = [self.title, self.error_dialog, self.success_dialog, self.code_dialog]
        dialog = Kdialog(title=[Kritter.icon("clock-o"), "Telegram"], layout=layout)
        self.layout = KsideMenuItem("Telegram", dialog, "clock-o") # keeping clock-o for as temp icon 

        # taken from gcloudialogue.py
        # needs to be changed to work with telegram
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


        # taken from gcloudialogue.py
        # defines callback method for submitting new Bot Token
        # behavior dependant on 'State' --> existance of Token or not
        @self.submit.callback(self.code.state_value())
        def func(code):
            try:
                self.gcloud.set_code(code) # needs to work with telegram instead
            except Exception as e:
                print(f"Encountered exception while setting code: {e}")
            self.state = None
            return self.code_dialog.out_open(False) + self.update()
