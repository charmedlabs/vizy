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
from kritter import Kritter, KtextBox, Ktext, Kbutton, Kdialog, KsideMenuItem, KyesNoDialog, Kdropdown
from kritter.ktextvisor import KtextVisor, KtextVisorTable, Response, Image
from kritter import Kritter, TextingClient
from dash_devices import callback_context

class TextingDialog:
    def __init__(self, kapp, client, tv, pmask):
        self.kapp = kapp
       
        # Initialize Client and define callback_receive
        self.texting_client = client # TextingClient(self.kapp.etcdir)
        self.text_visor = tv # KtextVisor(self.texting_client)

        style = {"label_width": 2, "control_width": 6} 
        
        # Set token components
        self.token_text = KtextBox(name="Token", placeholder="Paste Token Here", style=style)
        self.submit_token = Kbutton(name=[Kritter.icon('thumbs-up'), "Submit"], spinner=True)
        self.token_text.append(self.submit_token)

        # Remove, test components
        self.remove_token = Kbutton(name=[Kritter.icon("remove"), "Remove Token"])

        # Subscriber List, manageable list of message recipients
        self.subscribers = self.text_visor.config['subscribers']
        self.subscriber_selection = ''
        self.delete_button = Kbutton(name=[Kritter.icon("trash"), "Delete"], disabled=True)
        self.delete_text = Ktext(style={"control_width": 12})
        self.delete_subscriber_yesno = KyesNoDialog(title="Delete Subscriber?", layout=self.delete_text, shared=True)
        self.subscriber_select = Kdropdown(value=None, placeholder="Select subscriber...", options=self.subscribers.values())
        self.subscriber_select.append(self.delete_button) 

        # Display status
        self.status = Ktext(style={"control_width": 12})

        layout = [self.token_text, self.remove_token, self.subscriber_select, self.delete_subscriber_yesno, self.status]
        dialog = Kdialog(title=[Kritter.icon("commenting"), "Texting Bot Configuration"], layout=layout)

        self.layout = KsideMenuItem("Texting", dialog, "commenting") 
        
        # Get and run state of dialog
        self.update_state() # set token for first time, ensuring proper display

        @dialog.callback_view()
        def func(open):
            if open:
                return self.update_state() # Entering -- update GUI state.

        @self.submit_token.callback(self.token_text.state_value())
        def func(token):
            if not callback_context.client.authentication&pmask:
                return
            self.kapp.push_mods(self.submit_token.out_spinner_disp(True))
            mods = self.submit_token.out_spinner_disp(False) 
            try:
                self.texting_client.set_token(token)
            except Exception as e:
                return mods + self.status.out_value(f"There has been an error: {e}")
            return mods + self.update_state()
                
        @self.remove_token.callback()
        def func():
            if not callback_context.client.authentication&pmask:
                return
            try:
                self.texting_client.remove_token()
            except Exception as e:
                return self.status.out_value(f"There has been an error: {e}")
            return self.update_state()

        @self.subscriber_select.callback()
        def func(selection):
            self.subscriber_selection = selection
            disabled = not bool(selection)
            return self.delete_button.out_disabled(disabled)

        @self.delete_button.callback()
        def func():
            return self.delete_text.out_value(f'Are you sure you want to delete "{self.subscriber_selection}" subscriber from list?') + self.delete_subscriber_yesno.out_open(True)

        @self.delete_subscriber_yesno.callback_response()
        def func(val):
            # remove subscriber from recipient list where user's name is key
            if val:
                # find id associated with username
                userid = [id for (id, name) in self.subscribers.items() if name == self.subscriber_selection]
                userid = userid[0]              # unwrap id
                del self.subscribers[userid]    # delete key from subscribers
                self.text_visor.config['subscribers'] = self.subscribers    # update subscriber list
                self.text_visor.config.save()                               # save list to file
                self.kapp.push_mods(self.subscriber_select.out_value(''))   # clear output
                return self.update_state()

    def update_state(self):
        # update subscriber list
        self.text_visor.config.load()
        self.subscribers = self.text_visor.config['subscribers']
        self.kapp.push_mods(self.subscriber_select.out_options(self.subscribers.values()))
        if self.texting_client.running(): # Running is the same as having a token...
            return self.token_text.out_disp(False) + self.submit_token.out_disp(False) + self.remove_token.out_disp(True) + self.status.out_value("Connected!") + self.subscriber_select.out_disp(True) + self.delete_button.out_disp(True) # + self.delete_subscriber_yesno.out_disp(True)
        else: # ... and not running, no token
            return self.token_text.out_disp(True) + self.submit_token.out_disp(True) + self.remove_token.out_disp(False) + self.token_text.out_value("") + self.status.out_value("Enter Vizy Bot Token to connect.") + self.subscriber_select.out_disp(False) + self.delete_button.out_disp(False) # + self.delete_subscriber_yesno.out_disp(False)
  
    def close(self):
        self.text_visor.close()  
