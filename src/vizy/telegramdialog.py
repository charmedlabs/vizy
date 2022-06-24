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
from kritter import Kritter, TelegramClient
from .vizy import BASE_DIR


"""
Dialog development plan:
Onboarding Dialog.  
You can look at the code in VizyVisor like TimeDialog or GcloudDialog to see how dialogs are done.  
1. needs to accept a token as input, save it to the etc directory as a json file (like GcloudDialog does).
    a. activates 'has token' state 
2. A button to test things 
    a. needs to receive a message
        i. bring up another dialog and wait for a message
        ii. print the message once received
    b. User dismisses by pressing OK. 
"""

"""
Token States
- change display depending on token state
"""
NO_TOKEN = 0
HAS_TOKEN = 1

class TelegramDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.state = None # state of token presence - has a token been successfully added or not
        self.token = None # shouldn't expose bot token ? 
        # self.telegram_client = TelegramClient(self.kapp.etcdir)

        # @self.telegram_client.callback_receive()
        # def func(sender, message):
        #     print(f"Received: {message} from {sender}.")
        #     self.telegram_client.text(sender, f'You said "{message}"')
        #     # Test url image
        #     # self.telegram_client.image(sender, 'https://upload.wikimedia.org/wikipedia/commons/thumb/9/9a/Gull_portrait_ca_usa.jpg/300px-Gull_portrait_c)    

        # Styles
        style = {"label_width": 3, "control_width": 6} # overall style..?
        
        # Main Dialog Title 
        self.inner_title = Ktext(name="Telegram Client", style=style)
        
        # Token Submission 
        self.token_text = KtextBox(name="Bot Token", placeholder="Paste Bot Token Here", style=style)
        self.token_submit_btn = Kbutton(name=[Kritter.icon('thumbs-up'), "Submit"])
        self.token_text.append(self.token_submit_btn)

        # Test Messages
        self.test_message_text = KtextBox(name="Test Message", value="test message!", style=style)
        self.self.remove_token_btn = Kbutton(name=[Kritter.icon("telegram"), "Send"])
        self.test_message_text.append(self.self.remove_token_btn)

        # Remove Token 
        self.remove_token = Kbutton(name=[Kritter.icon("remove"), "Remove"])

        # Final Layout and Dialog Design  
        layout = [self.inner_title, self.token_text, self.test_message_text, self.remove_token]
        dialog = Kdialog(title=[Kritter.icon("telegram"), "Telegram Bot Configuration"], layout=layout)
        #  vizy visor can remove display via this layout if user is not given permission
        self.layout = KsideMenuItem("Telegram", dialog, "clock-o") # keeping clock-o for as temp icon 


        @dialog.callback_view()
        def func(open):
            """Change appearance of dialog depending on Token State"""
            if open:
                return self.update_state()

        @self.token_submit_btn.callback()
        # def func(token):
        def func():
            '''pass in content of token_text, save locally to kapp.ectdir
            encrypt ?
            save multiple ? 
            '''
            # try:
            #     self.telegram_client.set_token(token) 
            # except Exception as e:
            #     print(f"Encountered exception while setting code: {e}")
            # self.state = None
            # return self.text_token.out_open(False) + self.update()
            m = f'token text submit click'
            print(m)

        @self.self.remove_token_btn.callback()
        # def func(token):
        def func():
            m = f'test message submit click'
            print(m)

        @self.remove_token.callback()
        def func():
            m = f'remove click'
            print(m)

    def fetch_token(self):
        """Attemts to read token from specified Filepath"""
        try:
            self.token = self.telegram_client.token
        except:
            self.token = None
        
    # needs to be changed to work with telegram
    def update_state(self):
        if self.state is None:
            self.state = NO_TOKEN
            self.fetch_token()
            if self.token:
                self.state = HAS_TOKEN

        # if self.state==NO_TOKEN:
        #     return self.create_api_key.out_disp(True) + self.out_upload_api_key_disp(True) + self.edit_api_services.out_disp(False) + self.remove_api_key.out_disp(False) + self.authorize.out_disp(False) + self.remove_authorization.out_disp(False) + self.test_image.out_disp(False) + self.test_email.out_disp(False)
        # elif self.state==HAS_TOKEN:
        #     return self.create_api_key.out_disp(False) + self.out_upload_api_key_disp(False) + self.edit_api_services.out_disp(True) + self.edit_api_services.out_url(self.api_project_url) + self.remove_api_key.out_disp(True) + self.authorize.out_disp(True) + self.authorize.out_url(self.auth_url) + self.remove_authorization.out_disp(False) + self.test_image.out_disp(False) + self.test_email.out_disp(False)
        #     # interfaces = self.gcloud.available_interfaces()
        #     # return self.create_api_key.out_disp(False) + self.out_upload_api_key_disp(False) + self.edit_api_services.out_disp(True) + self.edit_api_services.out_url(self.api_project_url) + self.remove_api_key.out_disp(True) + self.authorize.out_disp(False) + self.remove_authorization.out_disp(True) + self.test_image.out_disp("KstoreMedia" in interfaces) + self.test_email.out_disp("KtextClient" in interfaces)
        # else:
        #     pass
