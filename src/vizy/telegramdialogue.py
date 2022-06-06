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

NO_KEYS = 0
API_KEY = 1
BOTH_KEYS = 3

BOT_TOKEN_FILE = "telegram_bot_token.json"

class TelegramDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.state = None
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

        self.text = Ktext(name="Telegram", style={"label_width":1, "control_width": 1})

        layout = [self.text, self.error_dialog, self.success_dialog, self.code_dialog]
        dialog = Kdialog(title=[Kritter.icon("clock-o"), "Telegram"], layout=layout)
        self.layout = KsideMenuItem("Telegram", dialog, "clock-o") # keeping clock-o for as temp icon 


