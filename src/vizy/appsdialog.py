import os
import time
import signal
import json
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
        self.update_apps_examples()
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
            app = self._find(self.apps, self.app_name)
            self.executable = app['executable']    
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
            example = self._find(self.examples, self.example_name)
            self.executable = example['executable']  
            self.name = self.example_name + " example" 
            self.restart = True
            return self.run_example.out_disabled(True) + self.run_example_button.out_spinner_disp(True)

        @self.kapp.callback_connect
        def func(client, connect):
            # We want to refresh apps list when user refreshes browser.
            if connect:
                self.update_apps_examples()
                apps = [a['name'] for a in self.apps]
                examples = [a['name'] for a in self.examples]
                apps_options = self.run_app.out_options(apps) + self.startup.out_options(apps) + self.run_example.out_options(examples) + self.startup.out_value(kapp.vizy_config.config['software']['start-up app'])
                self.kapp.push_mods(apps_options)

                self.update_client(client)

        # Run exec thread
        self.run_thread = True
        thread = Thread(target=self.wfc_thread)
        thread.start()

    def _find(self, info_list, name):
        for i in info_list:
            if name==i['name']:
                return i 
        return None

    def _app_file_path(self, path, file):
        file = os.path.expandvars(file) # expand any env variables
        if os.path.isabs(file):
            if os.path.isfile(file):
                return file
            else:
                return None # if it's abs and doesn't exist, it's not a valid file
        else: # if it's not abs, add the path and see if it exists
            path_file = os.path.join(path, file)
            if os.path.isfile(path_file):
                return path_file
            else:
                return None

    def _app_info(self, path, app):
        info = {
            "name": app,
            "executable": None, 
            "description": None, 
            "files": [],
            "image": None,
            "url": None
        }
        path = os.path.join(path, app)
        info_file = os.path.join(path, "info.json")
        if os.path.isfile(info_file):
            try:
                info.update(json.loads(info_file))
            except Exception as e:
                print(f"Exception reading {info_file}: {e}")
                return None
            info['files'] = [self._app_file_path(path, f) for f in info['files']]
            info['files'] = [f for f in info['files'] if f is not None]
        else:
            executable = os.path.join(path, "main.py")
            if os.path.isfile(executable):  
                info['executable'] = executable
                files = os.listdir(path)
                info['files'] = [f for f in files if f.lower().endswith(".py")]      
            else:
                return None
            # Add abs path to image
        if info['image']:
            info['image'] = self._app_file_path(path, info['image'])
        # Add python3 to executable if appropriate
        executable = info['executable'].lower()
        if executable.endswith(".py") and not executable.startswith("python3"):
            info['executable'] = "python3 " + info['executable']

        return info    

    def _set_default_app(self):
        app_name = self.kapp.vizy_config.config['software']['start-up app']
        if app_name:
            self.executable = self._find(self.apps, app_name)['executable']
            self.name = app_name + " app"
        else:
            example_name = self.kapp.vizy_config.config['software']['start-up example']
            self.executable = self._find(self.examples, example_name)['executable'] 
            self.name = example_name + " example"

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
        self.apps = [self._app_info(self.kapp.appsdir, f) for f in os.listdir(self.kapp.appsdir)]
        self.apps = [f for f in self.apps if f is not None]
        self.apps.sort(key=lambda f: f['name'].lower()) # sort by name ignoring upper/lowercase
        self.examples = [self._app_info(self.kapp.examplesdir,f) for f in os.listdir(self.kapp.examplesdir)]
        self.examples = [f for f in self.examples if f is not None]
        self.examples.sort(key=lambda f: f['name'].lower()) # sort by name ignoring upper/lowercase

    def wfc_thread(self):
        while self.run_thread:
            self.pid = self.console.start_single_process( f"sudo -E -u {self.user} {self.executable}")
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
