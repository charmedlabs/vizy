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

BOT_TOKEN_FILE = "telegram_bot_token.json"

class TelegramDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.state = None
        self.bot_token_filename = os.path.join(self.kapp.etcdir, BOT_TOKEN_FILE)
        self.gcloud = Gcloud(kapp.etcdir)
        
        style = {"label_width": 3, "control_width": 6}

