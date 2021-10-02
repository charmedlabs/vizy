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

class AppsDialog:

    def __init__(self, kapp, pmask_console, pmask, user="pi"):
        self.kapp = kapp
        self.user = user
        self.restart = False

        style = {"label_width": 4, "control_width": 5}
        bstyle = {"vertical_padding": 0}
        # Run start-up app first
        app = kapp.vizy_config.config['software']['start-up app']
        if app:
            self.prog = os.path.join(self.kapp.appsdir, app, "main.py")
            self.name = app + " (app)"
        else:
            example = kapp.vizy_config.config['software']['start-up example']
            self.prog = os.path.join(self.kapp.examplesdir, example, "main.py")
            self.name = example + " (example)"

        self.startup = Kdropdown(name='Start-up app', style=style)
        self.curr_prog = Ktext(name="Currently running", value=self.name, style={"label_width": 4, "control_width": 8})
        self.run_app = Kdropdown(name='Run app', style=style)
        self.run_app_button = Kbutton(name="Run", spinner=True, disabled=True, style=bstyle)
        self.run_app.append(self.run_app_button)
        self.run_example = Kdropdown(name='Run example', style=style)
        self.run_example_button = Kbutton(name="Run", spinner=True, disabled=True, style=bstyle)
        self.run_example.append(self.run_example_button)

        layout = [self.curr_prog, self.run_app, self.run_example, self.startup]

        dialog = Kdialog(title="Apps/examples", layout=layout, kapp=self.kapp)
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
            self.name = self.app_name + " (app)" 
            self.restart = True
            return run_app.out_disabled(True) + self.run_app_button.out_spinner_disp(True)

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
            self.name = self.example_name + " (example)" 
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
        thread = Thread(target=self.wfc_thread, args=(None,))
        thread.start()


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

    def wfc_thread(self, pid):
        while self.run_thread:
            # Update iframe 
            pid = self.console.start_single_process( f"sudo -E -u {self.user} python3 {self.prog}")
            # Wait for app to come up before we update the iframe, otherwise we might
            # get a frowny face :(
            while True: 
                try:
                    self.kapp.push_mods(self.kapp.out_main_src(""))
                    urlopen(f'http://localhost:{PORT}')
                    break
                except:
                    time.sleep(0.5)
            self.update_clients()
            try:
                self.kapp.push_mods(self.run_app.out_value(None) + self.run_app_button.out_spinner_disp(False) + self.run_example.out_value(None) + self.run_example_button.out_spinner_disp(False) + self.curr_prog.out_value(self.name) + self.run_app_button.out_disabled(True) + self.run_example_button.out_disabled(True) + self.run_app.out_disabled(False) + self.run_example.out_disabled(False))
            except:
                pass
            name = self.name
            while self.run_thread:
                obj = os.waitid(os.P_PID, pid, os.WEXITED|os.WNOHANG)
                if obj:
                    print(colored(f"\nApp has exited with result {obj.si_status}.", "green"))
                    self.kapp.push_mods(self.curr_prog.out_value(f"{name} exited, code {obj.si_status}"))
                    pid = None
                    break
                if self.restart:
                    if pid:
                        os.kill(pid, signal.SIGTERM)
                    self.restart = False
                time.sleep(0.5)

    def close(self):        
        self.run_thread = False
