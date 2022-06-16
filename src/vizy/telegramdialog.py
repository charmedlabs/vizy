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
from kritter import Kritter #, TelegramClient # mimicing Gcloud setup..
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

""" Updated Design 
1. Button & Display affected by token state
    a. NO_TOKEN --> token textbox and 'submit' button together 
    b. BOT_TOKEN --> 'send test message' button and 'remove token' buttons 
"""

NO_TOKEN = 0
BOT_TOKEN = 1

BOT_TOKEN_FILE = "telegram_bot_token.json"

class TelegramDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.state = None # state of token presence, mimicing Gcloud
        self.bot_token_filename = os.path.join(self.kapp.etcdir, BOT_TOKEN_FILE)
        # Available Styles
        style = {"label_width": 3, "control_width": 6} # overall style..?
        # Main Dialog Title
        self.title = Ktext(name="Telegram Inner Title", style=style)
        # Token Submission 
        token_line = KtextBox(name="Bot Token", placeholder="Paste Bot Token Here", style=style)
        submit_token = Kbutton(name=[Kritter.icon('thumbs-up'), "Submit"])
        self.token_submission = token_line.append(submit_token)
        # Test Messages
        self.send_test_message = Kbutton(name=[name=[Kritter.icon("telegram"), "Send Test Message"], spinner=True, service=None)
        # Remove Token 
        self.remove_token = Kbutton(name=[Kritter.icon("remove"), "Remove"])
        # Final Layout and Dialog Design  
        self.dialog = Kdialog(
            title=[Kritter.icon("telegram"), "Telegram"], 
            layout=[
                # self.title, 
                self.token_submission,
                self.send_test_message, 
                self.remove_token])
        # 
        self.layout = KsideMenuItem("Telegram", dialog, "telegram")

        @self.dialog.callback_view()
        def func():
            """Change appearance of dialog depending on Token State"""
            pass

        @self.submit_token.callback()
        def func():
            """
            Saves text from token_textbox to Bot Token File
            Changes to 'has token state'
            """
            pass

        @self.send_test_messaage.callback()
        def func():
            """Sends predetermined test message to Bot"""
            pass

        @self.remove_token.callback()
        def func():
            """
            Removes token from Bot Token File location
            Changes to 'no token state'
            """
            pass




