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
from kritter import Kritter, KtextBox, Ktext, Kbutton, Kdialog, KsideMenuItem
from kritter import Kritter, TelegramClient
from dash_devices import callback_context


class TelegramDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.echo = False
        
        # Initialize Client and define callback_receive
        self.telegram_client = TelegramClient(self.kapp.etcdir)
        @self.telegram_client.callback_receive()
        def func(sender, message):
            print(f"Received: {message} from {sender}.")
            if self.echo:
                self.kapp.push_mods(self.status.out_value(f'Received: "{message}"!') + self.echo_test.out_spinner_disp(False))
                self.telegram_client.text(sender, f'You said "{message}".')
                self.echo = False

        style = {"label_width": 2, "control_width": 6} 
        
        # Set token components
        self.token_text = KtextBox(name="Token", placeholder="Paste Token Here", style=style)
        self.submit_token = Kbutton(name=[Kritter.icon('thumbs-up'), "Submit"], spinner=True)
        self.token_text.append(self.submit_token)

        # Remove, test components
        self.remove_token = Kbutton(name=[Kritter.icon("remove"), "Remove Token"])
        self.echo_test = Kbutton(name=[Kritter.icon("comments"), "Echo test"], spinner=True)
        self.remove_token.append(self.echo_test)

        # Display status
        self.status = Ktext(style={"control_width": 12})

        layout = [self.token_text, self.remove_token, self.status]
        dialog = Kdialog(title=[Kritter.icon("commenting"), "Telegram Bot Configuration"], layout=layout)

        self.layout = KsideMenuItem("Telegram", dialog, "commenting") 
        
        # Get and run state of dialog
        self.update_state() # set token for first time, ensuring proper display

        @dialog.callback_view()
        def func(open):
            if open:
                return self.update_state() # Entering -- update GUI state.
            else:
                self.echo = False # Leaving -- turn off echo if it's on.

        @self.submit_token.callback(self.token_text.state_value())
        def func(token):
            if not callback_context.client.authentication&pmask:
                return
            self.kapp.push_mods(self.submit_token.out_spinner_disp(True))
            mods = self.submit_token.out_spinner_disp(False) 
            try:
                self.telegram_client.set_token(token)
            except Exception as e:
                return mods + self.status.out_value(f"There has been an error: {e}")
            return mods + self.update_state()
                
        @self.remove_token.callback()
        def func():
            if not callback_context.client.authentication&pmask:
                return
            try:
                self.telegram_client.remove_token()
            except Exception as e:
                return self.status.out_value(f"There has been an error: {e}")
            return self.update_state()
        
        @self.echo_test.callback()
        def func():
            if not callback_context.client.authentication&pmask:
                return
            self.echo = True
            return self.echo_test.out_spinner_disp(True) + self.status.out_value("Send a message to the Vizy Bot from your Telegram App...")

    def update_state(self):
        mods = self.echo_test.out_spinner_disp(False)
        if self.telegram_client.running(): # Running is the same as having a token...
            return mods + self.token_text.out_disp(False) + self.submit_token.out_disp(False) + self.remove_token.out_disp(True) + self.echo_test.out_disp(True) + self.status.out_value("Connected!")
        else: # ... and not running, no token
            return mods + self.token_text.out_disp(True) + self.submit_token.out_disp(True) + self.remove_token.out_disp(False) + self.echo_test.out_disp(False) + self.token_text.out_value("") + self.status.out_value("Enter Vizy Bot Token to connect.")
    
