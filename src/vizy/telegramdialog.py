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
from kritter import KtextBox, Ktext, Kdropdown, Kbutton, Kdialog, KokDialog, KsideMenuItem
from dash_devices.dependencies import Input, Output, State
import dash_bootstrap_components as dbc
from kritter import Kritter #, TelegramClient # mimicing Gcloud setup..
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
        self.state = None # state of token presence, mimicing Gcloud
        self.bot_token_filename = os.path.join(self.kapp.etcdir, BOT_TOKEN_FILE)
        
        style = {"label_width": 3, "control_width": 6} # overall style..?

        self.token_text = KtextBox(name="Token", style=style)
        self.submit_btn = Kbutton(name=[Kritter.icon("check-square-o"), "Submit"])

        layout = [self.token_text]
        dialog = Kdialog(
            title=[Kritter.icon("clock-o"), "Telegram"], 
            left_footer=self.submit_btn,
            layout=layout)
        self.layout = KsideMenuItem("Telegram", dialog, "clock-o") # temp clock icon?

        @self.submit_btn.callback()
        def func():
            """Save Token to specified filepath"""
            print(f"filepath : {BOT_TOKEN_FILE}")

