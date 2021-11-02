import os
import time
import signal
from threading import Thread
from termcolor import colored
from dash_devices.dependencies import Input, Output
from dash_devices import callback_context
from kritter import Kritter, KsideMenuItem, Kdialog, Ktext, Kdropdown, Kbutton, PORT
from kritter.kterm import Kterm, RESTART_QUERY
import dash_html_components as html
from urllib.parse import urlparse
from urllib.request import urlopen

# Todo: maybe use a popover to display status changes (exits, running, etc.)  Or maybe we don't 
# display at all and rely on console?

class AppsDialog:

    def __init__(self, kapp, pmask_console, pmask, user="pi"):
        self.kapp = kapp
        self.user = user
        self.restart = False

        style = {"label_width": 3, "control_width": 6}
        # Run start-up app first
        self._set_default_app()

        self.startup = Kdropdown(name='Start-up app', style=style)
        self.status = Ktext(name="Status", value=self.name, style={"label_width": 3, "control_width": 8})
        # The 2 lines below expand the status text and center it vertically within the row.  
        # It seems like a special case (for now).
        self.status.cols[1].className = "d-flex justify-content-center"
        self.status.cols[1].style = {"min-height": "50px", "flex-direction": "column"}
        self.run_app = Kdropdown(name='Run app', style=style)
        self.run_app_button = Kbutton(name=[Kritter.icon("play-circle"), "Run"], spinner=True, disabled=True)
        self.run_app.append(self.run_app_button)
        self.run_example = Kdropdown(name='Run example', style=style)
        self.run_example_button = Kbutton(name=[Kritter.icon("play-circle"), "Run"], spinner=True, disabled=True)
        self.run_example.append(self.run_example_button)

        layout = [self.status, self.run_app, self.run_example, self.startup]

        dialog = Kdialog(title=[Kritter.icon("asterisk"), "Apps/examples"], layout=layout, kapp=self.kapp)
        self.layout = KsideMenuItem("Apps/examples", dialog, "asterisk", kapp=self.kapp)

        self.console = Kterm("", single=True, name="Console", wfc_thread=False, protect=kapp.login.protect(pmask_console)) 
        self.kapp.server.register_blueprint(self.console.server, url_prefix="/console")

        @self.startup.callback()
        def func(value):
            if value:
                kapp.vizy_config.config['software']['start-up app'] = value 
                kapp.vizy_config.save()

        @self.run_app.callback()
        def func(value):
            if value: # If we get set to None, we want to ignore
                self.app_name = value
                # Enable run button now that we've selecting an app.
                self.kapp.push_mods(self.run_app_button.out_disabled(False))

        @self.run_app_button.callback()
        def func():
            # Block unauthorized attempts
            if not callback_context.client.authentication&pmask:
                return
            self.prog = os.path.join(self.kapp.appsdir, self.app_name, "main.py")    
            self.name = self.app_name + " app" 
            self.restart = True
            return self.run_app.out_disabled(True) + self.run_app_button.out_spinner_disp(True)

        @self.run_example.callback()
        def func(value):
            if value: # If we get set to None, we want to ignore
                self.example_name = value
                # Enable run button now that we've selecting an app.
                self.kapp.push_mods(self.run_example_button.out_disabled(False))

        @self.run_example_button.callback()
        def func():
            # Block unauthorized attempts
            if not callback_context.client.authentication&pmask:
                return
            self.prog = os.path.join(self.kapp.examplesdir, self.example_name, "main.py")   
            self.name = self.example_name + " example" 
            self.restart = True
            return self.run_example.out_disabled(True) + self.run_example_button.out_spinner_disp(True)

        @self.kapp.callback_connect
        def func(client, connect):
            # We want to refresh apps list when user refreshes browser.
            if connect:
                self.update_apps_examples()
                apps_options = self.run_app.out_options(self.apps) + self.startup.out_options(self.apps) + self.run_example.out_options(self.examples) + self.startup.out_value(kapp.vizy_config.config['software']['start-up app'])
                self.kapp.push_mods(apps_options)

                self.update_client(client)

        # Run exec thread
        self.run_thread = True
        thread = Thread(target=self.wfc_thread)
        thread.start()


    def _set_default_app(self):
        app = self.kapp.vizy_config.config['software']['start-up app']
        if app:
            self.prog = os.path.join(self.kapp.appsdir, app, "main.py")
            self.name = app + " app"
        else:
            example = self.kapp.vizy_config.config['software']['start-up example']
            self.prog = os.path.join(self.kapp.examplesdir, example, "main.py")
            self.name = example + " example"

    def _exit_poll(self, msg):
            obj = os.waitid(os.P_PID, self.pid, os.WEXITED|os.WNOHANG)
            if obj:
                msg = f"{self.name_} {msg}"
                print(colored(f"{msg}. Return code: {obj.si_status}", "green"))
                self.kapp.push_mods(self.status.out_value(msg))
                self.pid = None
            return bool(obj)

    def update_client(self, client):
        url = urlparse(client.origin)
        # This is the default URL behavior -- it can be different for each client and app.
        new_src = url._replace(netloc=f"{url.hostname}:{PORT}").geturl()
        self.kapp.push_mods(self.kapp.out_main_src(new_src), client)                

    def update_clients(self):
        for c in self.kapp.clients:
            self.update_client(c)

    def update_apps_examples(self):
        # Find all apps in the appsdir
        self.apps = []
        files = os.listdir(self.kapp.appsdir)
        for f in files:
            # Only directories with main.py are considered valid apps.
            if os.path.isfile(os.path.join(self.kapp.appsdir, f, "main.py")):
                self.apps.append(f)
            self.apps.sort(key=lambda n: n.lower()) # sort ignoring upper/lowercase
        # Find all examples in the examplessdir
        self.examples = []
        files = os.listdir(self.kapp.examplesdir)
        for f in files:
            # Only directories with main.py are considered valid apps.
            if os.path.isfile(os.path.join(self.kapp.examplesdir, f, "main.py")):
                self.examples.append(f)
            self.examples.sort(key=lambda n: n.lower()) # sort ignoring upper/lowercase

    def wfc_thread(self):
        while self.run_thread:
            self.pid = self.console.start_single_process( f"sudo -E -u {self.user} python3 {self.prog}")
            self.name_ = self.name
            # Wait for app to come up
            mods = self.kapp.out_main_src("") + self.kapp.out_disp_spinner(True) 
            while True: 
                try:
                    self.kapp.push_mods(mods)
                    urlopen(f'http://localhost:{PORT}')
                    break
                except:
                    if self._exit_poll("has exited early, starting default program..."):
                        self._set_default_app()
                        break
                    time.sleep(0.5)

            if self.pid:
                self.update_clients()
                self.kapp.push_mods(self.kapp.out_disp_spinner(False))
                try:
                    self.kapp.push_mods(self.run_app.out_value(None) + self.run_app_button.out_spinner_disp(False) + self.run_example.out_value(None) + self.run_example_button.out_spinner_disp(False) + self.status.out_value(self.name + " is running") + self.run_app_button.out_disabled(True) + self.run_example_button.out_disabled(True) + self.run_app.out_disabled(False) + self.run_example.out_disabled(False))
                except:
                    pass
                while self.run_thread:
                    if self._exit_poll(f"has exited, starting {self.name}..."):
                        break
                    if self.restart:
                        if self.pid:
                            os.kill(self.pid, signal.SIGTERM)
                        self.restart = False
                    time.sleep(0.5)

    def exit_app(self):
        self.close()
        os.kill(self.pid, signal.SIGTERM)

    def close(self):        
        self.run_thread = False
