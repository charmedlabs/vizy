#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

import subprocess
import os
import re
import time
import json
from threading import Thread, Timer, Lock
import dash_bootstrap_components as dbc
import dash_core_components as dcc
from dash_devices.dependencies import Input, Output
from dash_devices import callback_context
from kritter import file_in_path, Kritter, KsideMenuItem, Kdialog, Ktext, KtextBox, Kradio, Kdropdown, Kbutton
from .wificonnection import WifiConnection, get_strength, WIFI_SSID, WIFI_AP
import dash_html_components as html
from .configfile import ConfigFile

TRIES = 3
TIMEOUT = 10
OTHER_NETWORK = "Other..."

CONFIG_FILE = "wifi.json"
DEFAULT_CONFIG = {
    "mode": "access point",
    "access point": {
        "name": None,
        "password": "12345678"
    },
    "network": {
        "name": None,
        "other": False,
        "password": None 
    } 
}


class WifiDialog:

    def __init__(self, kapp, pmask):
        if os.geteuid()!=0:
            raise RuntimeError("You need to run with root permissions (psst, use sudo).")

        self.connection = None
        self.timer = None
        self.networks_updated = False
        self.kapp = kapp
        self.nlock = Lock()
        self.status = ""
        self.mode_options = ["Access Point", "Connect to network"]
        self.password_view = False
        self.load_config()

        style = {"label_width": 2, "control_width": 9}
        style2 = {"label_width": 2, "control_width": 7}
        self.status_c = Ktext(grid=False, style=style)
        self.mode_c = Kradio(name="Mode", options=self.mode_options, value=self.mode, style=style)
        self.ssid_name_c = Kdropdown(name="Network", options=[self.ssid_network, OTHER_NETWORK], value=self.ssid_network, style=style2)
        self.ap_name_c = KtextBox(name="Network name", value=self.ap_network, style=style2)
        self.ssid_password_c = KtextBox(name="Password", type="password", style=style2)
        self.password_view_c = Kbutton(name=Kritter.icon("eye", padding=0))
        self.ssid_password_c.append(self.password_view_c)
        self.ap_password_c = KtextBox(name="Password", style=style2) 
        self.apply = Kbutton(name=[Kritter.icon("check-square-o"), "Apply"], spinner=True)
        self.refresh = Kbutton(name=Kritter.icon("refresh", padding=0), spinner=True)
        self.ssid_name_c.append(self.refresh)
        self.ssid_other_c = KtextBox(name="Other network", style=style2)
        self.password_po = dbc.Popover(dbc.PopoverBody("Password must be at least 8 characters."), id=Kritter.new_id(), is_open=False, target=self.ap_password_c.id)

        layout = [self.mode_c, self.ssid_name_c, self.ssid_other_c, self.ap_name_c, self.ssid_password_c, self.ap_password_c, self.password_po, self.status_c]
        dialog = Kdialog(title=[Kritter.icon("wifi"), "WiFi Configuration"], left_footer=self.apply, layout=layout)
        self.layout = KsideMenuItem("WiFi", dialog, "wifi")

        self.run_thread(self.connect, ap_revert=False, ui=False)
        
        @dialog.callback_view()
        def func(open):
            if open:
                return self.set_mode()
            else:
                return Output(self.password_po.id, "is_open", False)

        @self.ssid_name_c.callback()
        def func(network):
            res = self.ssid_other_c.out_disp(network==OTHER_NETWORK) 
            if self.ssid_network!=network and network!=OTHER_NETWORK:   
                res += self.ssid_password_c.out_value("")
            return res 

        @self.mode_c.callback()
        def func(mode):
            self.set_timer()
            return self.set_mode(mode)

        @self.apply.callback(self.mode_c.state_value() + self.ssid_name_c.state_value() + self.ssid_other_c.state_value() + self.ap_name_c.state_value() + self.ssid_password_c.state_value() + self.ap_password_c.state_value())
        def func(mode, ssid_network, ssid_other, ap_network, ssid_password, ap_password):
            # Block unauthorized attempts
            if not callback_context.client.authentication&pmask:
                return  
            self.set_timer()            
            self.mode = mode
            if ssid_network==OTHER_NETWORK:
                self.ssid_other = True
                self.ssid_network = ssid_other
            else:
                self.ssid_other = False
                self.ssid_network = ssid_network
            self.ap_network = ap_network
            self.ssid_password = ssid_password
            if self.mode==self.mode_options[0] and len(ap_password)<8:
                return Output(self.password_po.id, "is_open", True)
            self.ap_password = ap_password

            self.run_thread(self.connect)
            # Remember the connection
            self.save_config()
            return self.apply.out_spinner_disp(True) + [Output(self.password_po.id, "is_open", False)]

        @self.password_view_c.callback()
        def func():
            self.password_view = not self.password_view 
            return self.ssid_password_c.out_type("text") if self.password_view else self.ssid_password_c.out_type("password")

        @self.refresh.callback()
        def func():
            self.set_timer()
            self.run_thread(self.update_networks)

    def load_config(self):
        config_filename = os.path.join(self.kapp.etcdir, CONFIG_FILE)      
        self.config = ConfigFile(config_filename, DEFAULT_CONFIG)                

        if self.config['mode']=="access point" or self.kapp.power_board.boot_mode()==1:
            self.mode = self.mode_options[0]
        else:
            self.mode = self.mode_options[1]

        if self.config['access point']['name'] is None or self.kapp.power_board.boot_mode()==1:
            hash_val = abs(hash(tuple(self.kapp.uuid)))%10000
            self.ap_network = f'vizy-{hash_val}'
            self.ap_password = DEFAULT_CONFIG['access point']['password']
        else:
            self.ap_network = self.config['access point']['name']
            self.ap_password = self.config['access point']['password']
        self.ssid_network = self.config['network']['name']
        self.ssid_other = self.config['network']['other']
        self.ssid_password = self.config['network']['password']

    def save_config(self):
        if self.mode==self.mode_options[0]: # AP    
            self.config['mode'] = "access point"
            self.config['access point']['name'] = self.ap_network
            self.config['access point']['password'] = self.ap_password
        else:
            self.config['mode'] = "network"
            self.config['network']['other'] = self.ssid_other
            self.config['network']['name'] = self.ssid_network
            self.config['network']['password'] = self.ssid_password
        self.config.save()

    def set_timer(self):
        # Client may be connected through wifi AP mode and when they try to 
        # connect to a wifi network and fail, they are no longer connected via 
        # AP mode (oops), so we automatically revert to AP mode after a connection
        # failure and a timeout. 

        # Cancel timer if there's a previous timer
        if self.timer:
            self.timer.cancel()
        self.timer = Timer(TIMEOUT, self.connect, args=(True, True))
        self.timer.start()

    def run_thread(self, target, **kwargs):
        thread = Thread(target=target, kwargs=kwargs)
        thread.start()

    def connect(self, ap_revert=False, ui=True):  
        if ap_revert:
            if self.connection:
                return # No need to connect...
            self.mode = self.mode_options[0]

        self.kapp.indicate("WAITING")
        self.status = "Configuring..."
        try:
            self.kapp.push_mods(self.status_c.out_value(self.status))
        except:
            pass 

        if self.mode==self.mode_options[0]: # AP
            network = self.ap_network
            password = self.ap_password
            mode = WIFI_AP
        else: # SSID 
            network = self.ssid_network
            password = self.ssid_password
            mode = WIFI_SSID

        with self.nlock:
            connection = WifiConnection(network, password, mode)
            self.connection = connection.activate()

        # Turn off waiting indication
        self.kapp.indicate("OFF") # No longer waiting
        if self.connection is None:
            if mode==WIFI_AP:
                self.status = f'Unable to create Access Point "{self.ap_network}"'
            else:
                self.status = f'Unable to connect to "{self.ssid_network}"'
                self.kapp.indicate("ERROR")
                if ui:
                    # Revert to AP mode
                    self.set_timer()
                else:
                    # Revert to AP mode immediately
                    self.connect(True, False)
        else:
            if mode==WIFI_AP:
                self.status = f'Access Point "{self.ap_network}" is running'
                if self.kapp.power_board.boot_mode()==1:
                    self.status += " (safe mode)"
                self.kapp.indicate("AP_CREATED")
            else:
                strength = get_strength(connection.ssid)
                self.status = f'Connected to "{self.ssid_network}", strength {strength}%'
                self.kapp.indicate("OK")
                self.kapp.indicate("WIFI_CONNECTED")
        try:
            self.kapp.push_mods(self.status_c.out_value(self.status) + self.apply.out_spinner_disp(False))
        except:
            pass


    def update_networks(self):
        self.kapp.push_mods(self.refresh.out_spinner_disp(True))

        with self.nlock:
            iwlist = []
            # Grab output of iwlist.  Try a couple times in case we fail.
            for i in range(TRIES):
                try:
                    iwlist = subprocess.check_output('sudo iwlist wlan0 scanning', shell=True).decode('unicode_escape')
                    break
                except:
                    time.sleep(1)
                    continue
        if not iwlist:
            self.kapp.push_mods(self.refresh.out_spinner_disp(False))
            return
        # Extract ESSIDs, which will be between quotes.
        networks = re.findall('"([^"]*)"', iwlist)
        # Get rid of oddly-named networks that consist of just whitespace or control characters.
        networks = [n for n in networks if re.sub(r'\W+', '', n)!=""]
        # Get rid of duplicates
        networks = list(set(networks))
        # Sort list ignoring upper/lowercase.
        networks.sort(key=lambda n: n.lower())
        networks.append(OTHER_NETWORK)
        mods = self.ssid_name_c.out_options(networks) + self.refresh.out_spinner_disp(False)
        if self.ssid_network not in networks and not self.ssid_other:
            self.ssid_password = ""
            mods += self.ssid_name_c.out_value(None) + self.ssid_password_c.out_value(None)
        self.kapp.push_mods(mods)
        self.networks_updated = True

    def set_mode(self, mode=None):
        res = []
        if mode is None:
            mode = self.mode
            res += self.mode_c.out_value(self.mode)    
        if mode==self.mode_options[0]: # AP
            res += self.ssid_name_c.out_disp(False) + self.refresh.out_disp(False) + self.ssid_other_c.out_disp(False) + self.ssid_password_c.out_disp(False) + self.password_view_c.out_disp(False) + self.ap_name_c.out_disp(True) + self.ap_name_c.out_value(self.ap_network) + self.ap_password_c.out_disp(True) + self.ap_password_c.out_value(self.ap_password) + self.status_c.out_value(self.status)
        else: # SSID
            # If we haven't queried the networks out there, go ahead and do so.     
            if not self.networks_updated:
                self.run_thread(self.update_networks)

            res += self.ssid_name_c.out_disp(True) + self.refresh.out_disp(True) + self.ap_name_c.out_disp(False) + self.ap_password_c.out_disp(False) + self.ssid_password_c.out_disp(True) + self.password_view_c.out_disp(True) + self.ssid_password_c.out_value(self.ssid_password) + self.status_c.out_value(self.status)
            if self.ssid_other:
                res += self.ssid_name_c.out_value(OTHER_NETWORK) + self.ssid_other_c.out_disp(True) + self.ssid_other_c.out_value(self.ssid_network)
            else:
                res += self.ssid_name_c.out_value(self.ssid_network) + self.ssid_other_c.out_disp(False)

        return res
