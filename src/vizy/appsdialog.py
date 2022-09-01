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
import signal
import json
import cv2
import numpy as np
from datetime import datetime
from threading import Thread, Lock
from termcolor import colored
from quart import send_file
import dash_bootstrap_components as dbc
import dash_core_components as dcc
from dash_devices.dependencies import Input, Output, State
from dash_devices import callback_context
from kritter import Kritter, KsideMenuItem, Kdialog, Ktext, Kdropdown, Kbutton, Kradio, PORT, valid_image_name, MEDIA_DIR
from kritter.kterm import Kterm, RESTART_QUERY
from vizy import BASE_DIR
import dash_html_components as html
from urllib.parse import urlparse, urlencode
from urllib.request import urlopen

# Todo: maybe use a popover to display status changes (exits, running, etc.)  Or maybe we don't 
# display at all and rely on console?

APP_MEDIA = "/appmedia"
DEFAULT_BG = "/media/default_bg.jpg"
DEFAULT_NO_BG = "/media/vizy_eye.png"
IMAGE_WIDTH = 460
IMAGE_HEIGHT = 230
IMAGE_PREFIX = "__"
START_TIMEOUT = 30 # seconds

def _create_image(image_path):
    new_image_path = os.path.join(os.path.dirname(image_path), IMAGE_PREFIX + os.path.basename(image_path))
    if not os.path.isfile(new_image_path) or os.path.getmtime(new_image_path)<os.path.getmtime(image_path):
        # Generate image
        image = cv2.imread(image_path)
        bg = cv2.imread(os.path.join(BASE_DIR, MEDIA_DIR, "bg.jpg"))
        width = image.shape[1]
        height = image.shape[0]
        factor = IMAGE_WIDTH/width 
        if factor*height>IMAGE_HEIGHT: # height constrained
            width = int(width*IMAGE_HEIGHT/height)
            height = IMAGE_HEIGHT
            image = cv2.resize(image, (width, height))
            xcenter = (IMAGE_WIDTH-width)//2
            ycenter = 0
        else: # width constrained
            width = IMAGE_WIDTH
            height = int(height*factor)
            image = cv2.resize(image, (width, height))
            xcenter = 0
            ycenter = (IMAGE_HEIGHT-height)//2
        bg[ycenter:ycenter+image.shape[0], xcenter:xcenter+image.shape[1]] = image
        cv2.imwrite(new_image_path, bg)
    return new_image_path


# I thought about making the selector carousel not shared, so different users could browse 
# programs independently, but there are some shared aspects of the carousel, like the running 
# status and if a prog runs on startup.  Keeping track of this isn't worth the effort for now,
# so I'm punting on this.  You'd need to keep track of self.type per client and update
# all clients when running or startup status changes for a given prog.   

class AppsDialog:

    def __init__(self, kapp, pmask_console, pmask, user="pi"):
        self.kapp = kapp
        self.user = user
        self.restart = False
        self.modified = False
        self.progs_lock = Lock() # We need this because we're updating the progs list asynchronously
        self.ftime = []

        self.progmap = {
            "Apps": {"typename": "app", "path": "apps"}, 
            "Examples": {"typename": "example", "path": "examples"}
        }
        self.types = list(self.progmap.keys())
        self.type = self.types[0]
        style = {"label_width": 3, "control_width": 6}
        self.update_progs()
        # Run start-up app first
        self._set_default_prog()

        self.select_type = Kradio(value=self.type, options=self.types, style={"label_width": 0})
        self.run_button = Kbutton(name=[Kritter.icon("play-circle"), "Run"], spinner=True)
        self.info_button = Kbutton(name=[Kritter.icon("info-circle"), "More info"], target="_blank")
        self.startup_button = Kbutton(name=[Kritter.icon("power-off"), "Run on start-up"])
        self.run_button.append(self.info_button)
        self.run_button.append(self.startup_button)
        self.status = Ktext(style={"label_width": 0 , "control_width": 12})
        self.carousel = dbc.Carousel(items=self.citems(), active_index=0, controls=True, indicators=True, interval=None, id=Kritter.new_id())
        layout = [self.select_type, self.carousel, self.run_button, self.status] 

        dialog = Kdialog(title=[Kritter.icon("asterisk"), "Apps/examples"], layout=layout, kapp=self.kapp)
        self.layout = KsideMenuItem("Apps/examples", dialog, "asterisk", kapp=self.kapp)

        self.console = Kterm("", single=True, name="Console", wfc_thread=False, protect=self.kapp.login.protect(pmask_console)) 
        self.kapp.server.register_blueprint(self.console.server, url_prefix="/console")

        # Setup route for apps media 
        @self.kapp.server.route(os.path.join(APP_MEDIA,'<path:file>'))
        async def appmedia(file):
            if valid_image_name(file):
                filename = os.path.join(self.kapp.homedir, file)
                if os.path.isfile(filename):
                    return await send_file(filename)
            return ''

        @self.select_type.callback()
        def func(value):
            self.type= value
            return [Output(self.carousel.id, "items", self.citems()), Output(self.carousel.id, "active_index", 0)]

        @self.kapp.callback_shared(None, [Input(self.carousel.id, "active_index")])
        def func(index):
            with self.progs_lock:
                prog = self.progs[self.type][index]
            mods = self.info_button.out_disabled(not bool(prog['url']))
            if prog['url']:
                mods += self.info_button.out_url(prog['url'])
            startup = self.kapp.vizy_config['software']['start-up app']==prog['path']
            return mods + self.startup_button.out_disabled(startup) 

        @self.startup_button.callback([State(self.carousel.id, "active_index")])
        def func(index):
            with self.progs_lock:
                self.kapp.vizy_config['software']['start-up app'] = self.progs[self.type][index]['path'] 
            self.kapp.vizy_config.save()
            return [Output(self.carousel.id, "items", self.citems())] + self.startup_button.out_disabled(True) 

        @self.run_button.callback([State(self.carousel.id, "active_index")])
        def func(index):
            # Block unauthorized attempts
            if not callback_context.client.authentication&pmask:
                return
            with self.progs_lock:
                self.prog = self.progs[self.type][index]
            self.name = f"{self.prog['name']} {self.progmap[self.type]['typename']}" 
            self.restart = True
            return self.run_button.out_spinner_disp(True)

        @self.kapp.callback_connect
        def func(client, connect):
            # We want to refresh apps list when user refreshes browser.
            if connect:
                if self._ftime_update():
                    print(f"{self.prog['name']} has changed, restarting...")
                    self.modified = True
                self.update_progs()
                return [Output(self.carousel.id, "items", self.citems()), Output(self.carousel.id, "active_index", 0)]


        # Run exec thread
        self.run_thread = True
        thread = Thread(target=self.wfc_thread)
        thread.start()

    def _find(self, path):
        with self.progs_lock:
            for k, v in self.progs.items():
                for a in v:
                    if a['path']==path:
                        return k, a 
        return None, None

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

    def _media_path(self, path):
        relpath = os.path.relpath(path, self.kapp.homedir)
        if relpath.startswith(".."):
            return None
        return os.path.join(APP_MEDIA, relpath)

    # Update file time list, return True if changed.
    def _ftime_update(self):
        ftime = [os.path.getmtime(f) for f in self.prog['files']]
        result = ftime!=self.ftime
        self.ftime = ftime
        return result

    def _app_info(self, path, app):
        info = {
            "name": app,
            "version": "",
            "author": "",
            "email": "",
            "path": None,
            "executable": None, 
            "description": "", 
            "files": [],
            "image": None,
            "image_no_bg": None,
            "url": None
        }
        path = os.path.join(path, app)
        info['path'] = os.path.relpath(path, self.kapp.homedir)
        if info['path'].startswith(".."):
            print (f"App at {path} isn't in Vizy directory ({self.kapp.homedir})")
            return None

        info_file = os.path.join(path, "info.json")
        try:
            if os.path.isfile(info_file):
                with open(info_file) as f:
                    info.update(json.load(f))
                info['files'] = [self._app_file_path(path, f) for f in info['files']]
                info['files'] = [f for f in info['files'] if f is not None]

            if not info['executable']:
                executable = os.path.join(path, "main.py")
                if os.path.isfile(executable):  
                    info['executable'] = executable
                else:
                    pyfiles = [f for f in os.listdir(path) if f.endswith(".py")]
                    if len(pyfiles)==1:
                        info['executable'] = os.path.join(path, pyfiles[0])
                    elif len(pyfiles)>1:
                        print(f"There's more than 1 python file in {path}!  Use info.json to specify which file to execute.")
                        return None
                    else:
                        print(f"Can't figure out how to run program in {path}.")
                        return None

            if not info['files']:
                files = os.listdir(path)
                info['files'] = [os.path.join(path, f) for f in files if f.lower().endswith(".py")]  
                if len(info['files'])==0:
                    return None
        except Exception as e:
            print(f"Exception: {e} while reading {path}")
            return None


        # Find most recent file date.
        mrfd = max([os.path.getmtime(f) for f in info['files']])
        # Get date string of mrf.
        info['mrfd']  = datetime.fromtimestamp(mrfd).strftime("%b %-d, %Y")

        # Create media path to image
        if info['image']:
            try:
                image_path = _create_image(self._app_file_path(path, info['image']))
                info['image_no_bg'] = self._media_path(self._app_file_path(path, info['image']))
                info['image'] = self._media_path(image_path)
            except: 
                pass
        if not info['image'] or not info['image_no_bg']:
            info['image'] = DEFAULT_BG
            info['image_no_bg'] = DEFAULT_NO_BG
        # Add python3 to executable if appropriate
        executable = info['executable'].lower()
        if executable.endswith(".py") and not executable.startswith("python3"):
            info['executable'] = "python3 " + info['executable']

        return info    

    def _set_default_prog(self):
        app = self.kapp.vizy_config['software']['start-up app']
        if app:
            type_, self.prog = self._find(app)
        else:
            self.prog = None
        
        if not self.prog:
            type_ = self.types[0]
            with self.progs_lock:
                self.prog = self.progs[type_][0]
        self.name = f"{self.prog['name']} {self.progmap[type_]['typename']}"

    def _exit_poll(self, msg):
            obj = os.waitid(os.P_PID, self.pid, os.WEXITED|os.WNOHANG)
            if obj:
                msg = f"{self.name_} {msg}"
                msg_colored = colored(f"{msg}. Return code: {obj.si_status}", "green")
                print(msg_colored)
                self.console.print(msg_colored)
                self.kapp.push_mods(self.status.out_value(msg))
                self.pid = None
            return bool(obj)

    def citems(self):
        with self.progs_lock:
            self._citems = [
                {"key": p['path'], "src": p['image'], 
                    "header": f"{p['name']} (running)" if p==self.prog else p['name'], 
                    "caption": f"{p['description']} (Runs on start-up.)" if self.kapp.vizy_config['software']['start-up app']==p['path'] else p['description']
                } 
                for p in self.progs[self.type]
            ]
        return self._citems
        
    def update_progs(self):
        with self.progs_lock:
            self.progs = {}
            for k, v in self.progmap.items():
                appdir = os.path.join(self.kapp.homedir, v['path'])
                self.progs[k] = [self._app_info(appdir, f) for f in os.listdir(appdir)]
                self.progs[k] = [p for p in self.progs[k] if p is not None]
                self.progs[k].sort(key=lambda f: f['name'].lower()) # sort by name ignoring upper/lowercase

    def _out_editor_files(self):
        # Remove homedir from files, assumes they are all in the homedir, which may change...
        files = [os.path.relpath(f, self.kapp.homedir) for f in self.prog['files']]
        files = {"files": files}
        url = f"/editor/load{urlencode(files, True)}"
        return self.kapp.editor_item.out_url(url) + self.kapp.about_dialog.view_edit_button.out_url(url)

    def wfc_thread(self):
        msg = ""
        while self.run_thread:
            self._ftime_update()
            self.pid = self.console.start_single_process(f"sudo -E -u {self.user} {self.prog['executable']}")
            self.name_ = self.name
            start_msg = msg if msg else f"Starting {self.name_}..."
            self.console.print(colored(start_msg, "green"))
            mods = self.kapp.out_main_src("") + self.kapp.out_start_message(start_msg) 
            # Wait for app to come up
            t0 = time.time()
            while True: 
                try:
                    self.kapp.push_mods(mods)
                    urlopen(f'http://localhost:{PORT}')
                    break
                except:
                    # If program exits...
                    if self._exit_poll("has failed to start, starting default program..."):
                        self._set_default_prog()
                        break
                    # or if program doesn't start after a timeout period, kill it,
                    # which will cause the default program to run
                    if time.time()-t0>START_TIMEOUT:
                        t0 = 1e10 
                        os.kill(self.pid, signal.SIGTERM)
                    time.sleep(0.5)
                            

            if self.pid:
                self.kapp.push_mods(self.kapp.out_main_src("/app") + self._out_editor_files() + [Output(self.carousel.id, "items", self.citems())] + self.kapp.out_set_program(self.prog) + self.run_button.out_spinner_disp(False) + self.status.out_value(self.name + " is running"))
                msg = ""
                while self.run_thread:
                    if self._exit_poll(f"has exited, starting {self.name}..."):
                        break
                    if self.restart:
                        if self.pid:
                            os.kill(self.pid, signal.SIGTERM)
                        self.restart = False
                    if self.modified:
                        if self.pid:
                            os.kill(self.pid, signal.SIGTERM)
                            msg = f"{self.name_} has been modified, restarting..."
                        self.modified = False
                    time.sleep(0.5)

    def exit_app(self):
        self.close()
        os.kill(self.pid, signal.SIGTERM)

    def close(self):        
        self.run_thread = False
