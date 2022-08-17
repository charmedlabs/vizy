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
import subprocess
import json
import datetime
from threading import Thread, Condition
import dash_bootstrap_components as dbc
import dash_html_components as html
import dash_core_components as dcc
from kritter import Kritter, ConfigFile, Ktext, Kbutton, Kdialog, KtextBox, Kcheckbox, KsideMenuItem
from kritter.ktextvisor import KtextVisor, KtextVisorTable
from dash_devices.dependencies import Input, Output, State

CONFIG_FILE = "remote.json"
DEFAULT_CONFIG = {
    "domain": "lhr.rocks",
    "subdomain": "",
    "start-up enable": False
 }

KEY_FILE = "remote_key"

class RemoteDialog:

    def __init__(self, kapp, tv, pmask):
        self.kapp = kapp
        self.process = None
        self.run = False
        self.remote_address = None
        self.cond = Condition()

        self.config_filename = os.path.join(self.kapp.etcdir, CONFIG_FILE)
        self.config = ConfigFile(self.config_filename, DEFAULT_CONFIG)

        self.key_filename = os.path.join(self.kapp.etcdir, KEY_FILE)
        # Generate ssh key even though we may not need it.  Once generated
        # we won't need to generate again.
        if not os.path.exists(self.key_filename):
            os.system(f'ssh-keygen -f {self.key_filename} -P ""')
        # Store key so we can copy.    
        self.url_store = dcc.Store(id=Kritter.new_id())
        with open(self.key_filename+".pub") as f:
            self.key_store = dcc.Store(data=f.read(), id=Kritter.new_id())

        style = {"label_width": 4, "control_width": 8}
        self.custom_domain_c = Kcheckbox(name='Custom domain', value=self.config['subdomain']!="", style=style)
        self.subdomain_c = KtextBox(name="Subdomain", value=self.config['subdomain'], placeholder="Enter subdomain", style=style)
        localhost = Kbutton(name=[Kritter.icon("external-link"), "localhost.run"], href="https://admin.localhost.run", external_link=True, target="_blank")
        copy_key = Kbutton(name=[Kritter.icon("copy"), "Copy key"], spinner=True)
        localhost.append(copy_key)
        self.su_enable_c = Kcheckbox(name="Enable on start-up", value=self.config['start-up enable'], style=style)
        domain_card = dbc.Card([self.subdomain_c, self.su_enable_c, localhost])
        self.domain_cont = dbc.Collapse(domain_card, id=kapp.new_id(), is_open=self.config['subdomain']!="", style=style)

        self.start_button = Kbutton(name=[Kritter.icon("play"), "Start"], spinner=True)
        # Use dbc button for copying URL because it can be rendered inline.
        self.copy_url = dbc.Button(Kritter.icon("copy", padding=0), size="sm", id=Kritter.new_id(), style={"margin": "0 5px 0 5px"})
        self.status = Ktext(grid=False, value='Press start to enable Web Sharing.', style=style)
        layout = [self.custom_domain_c, self.domain_cont, self.status, self.url_store, self.key_store]

        self.dialog = Kdialog(title=[Kritter.icon("share-alt"), "Web Sharing"], layout=layout, left_footer=self.start_button)
        self.layout = KsideMenuItem("Web Sharing", self.dialog, "share-alt")

        # Start ssh tunnel on start-up if needed.
        if self.config['start-up enable'] and self.config['subdomain']:
            self.start_stop(True)

        @self.custom_domain_c.callback(self.subdomain_c.state_value())
        def func(val, domain):
            if val:
                self.config['subdomain'] = domain
            else:
                self.config['subdomain'] = ""
            self.start_stop(False)                
            self.config.save()
            return Output(self.domain_cont.id, 'is_open', val)

        @self.subdomain_c.callback()
        def func(val):
            self.config['subdomain'] = val.strip()
            self.config.save()

        @self.su_enable_c.callback()
        def func(val):
            self.config['start-up enable'] = val 
            self.config.save()

        @self.start_button.callback()
        def func():
            self.start_stop(not self.run)
                
        # This code copies to the clipboard using the hacky method.  
        # (You need a secure page (https) to perform navigator.clipboard operations.)   
        script = """
            function(click, url) {
                var textArea = document.createElement("textarea");
                textArea.value = url;
                textArea.style.position = "fixed";  
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();
                document.execCommand('copy');
                textArea.remove();
            }
        """
        self.kapp.clientside_callback(script, Output("_none", Kritter.new_id()), [Input(self.copy_url.id, "n_clicks")], state=[State(self.url_store.id, "data")])
        self.kapp.clientside_callback(script, Output("_none", Kritter.new_id()), [Input(copy_key.id, "n_clicks")], state=[State(self.key_store.id, "data")])

        def remote(words, sender, context):
            # If we're not running, start thread
            if not self.run:
                self.start_stop(True) 
                # Wait for result
                with self.cond:
                    self.cond.wait()

            # Return result 
            if self.remote_address:
                return self.remote_address
            else:                         
                return "Web sharing wasn't able to start."

        tv_table = KtextVisorTable({"webshare": (remote, "Get web share URL for Vizy.")})
        @tv.callback_receive()
        def func(words, sender, context):
            return tv_table.lookup(words, sender, context)

    def start_stop(self, start):
        # If no change necessary...
        if self.run==start:
            return 
        # Start spinner before thread exits to avoid race condition.
        self.kapp.push_mods(self.start_button.out_spinner_disp(True))
        self.run = start
        if start:
            Thread(target=self.thread).start()
        else:
            if self.process:
                try:
                    self.process.terminate()
                except:
                    pass

    def new_url(self, url):
        status = ['Go to ', html.A(url, href=url, target="_blank"), self.copy_url]
        if self.config['subdomain']=="":
            # Add time so we have an idea as to whether the prevous link expired on us. 
            status.extend([html.Br(), f'(Created at {datetime.datetime.now().strftime("%I:%M:%S %p")})'])
        return [Output(self.url_store.id, "data", url)] + self.status.out_value(status)


    def thread(self):
        # Create an ssh tunnel with localhost.run.  The StrictHostKeyChecking flag prevents 
        # ssh from asking if you want to connect to an "unknown host" (unknown to it). 
        if self.config['subdomain']!="":
            command = ["ssh", "-i", self.key_filename, "-oStrictHostKeyChecking=no", "-R", f"{self.config['subdomain']}.{self.config['domain']}:80:localhost:80", "root@localhost.run", "--", "--output", "json"]
        else:
            command = ["ssh", "-oStrictHostKeyChecking=no", "-R", "80:localhost:80", "nokey@localhost.run", "--", "--output", "json"]
        status = 'Press start to enable Web Sharing.'
        while self.run:
            self.remote_address = None
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            while True:
                out = self.process.stdout.readline()
                if out==b"":
                    break
                out = json.loads(out.decode("utf-8"))
                if out['status']=="success":
                    self.remote_address = f"https://{out['address']}"
                    self.kapp.push_mods(self.new_url(self.remote_address) + self.start_button.out_name([Kritter.icon("stop"), "Stop"]) + self.start_button.out_spinner_disp(False))
                else:
                    try:
                        status = f"Connection wasn't established: {out['message']}"
                    except:
                        status = f"Connection wasn't established."                        
                    self.run = False
                    self.process.terminate()
                    self.remote_address = None
                    break
                # Notify textvisor
                with self.cond:
                    self.cond.notify()

            self.process.wait()
            self.kapp.push_mods(self.start_button.out_name([Kritter.icon("play"), "Start"]) + self.start_button.out_spinner_disp(False) + self.status.out_value(status))
        self.remote_address = None
        # Notify textvisor
        with self.cond:
            self.cond.notify()

    def close(self):
        self.start_stop(False)
