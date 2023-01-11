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
from threading import Thread, RLock
from kritter import Kritter, import_config
import kritter
import time
import json
import base64
import glob
import collections
from dash_devices.dependencies import Input, Output, State
import dash_core_components as dcc
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy, Perspective, OpenProjectDialog, NewSaveAsDialog
import vizy.vizypowerboard as vpb
from camera import Camera 
from capture import Capture
from process import Process
from analyze import Analyze
from tab import Tab

"""
todo:

testing:
xtest null case (no motion)
xtest short vid < BG_CNT_FINAL frames
transitions -- load file while processing, move to capture while processing (then back again)

documentation:
data:
0 pts
1 index
2 x centroid
3 y centroid
4 rect-x
5 rect-y
6 rect-width
7 rect-height

"""

CONSTS_FILE = "motionscope_consts.py"
APP_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_FILE = "data.json"
VIDEO_FILE = "video.raw"

IMPORT_FILE = "import.zip"
GDRIVE_DIR = "/vizy/motionscope"
SHARE_KEY_TYPE = "MSPG" # MotionScope Project, Google Drive

class ExportProjectDialog(kritter.Kdialog):

    def __init__(self, gdrive, key_type, file_info_func, key_func=None):
        self.gdrive = gdrive
        self.key_type = key_type
        self.file_info_func = file_info_func
        self.key_func = key_func
        self.export = kritter.Kbutton(name=[kritter.Kritter.icon("cloud-upload"), "Export"], spinner=True)
        self.status = kritter.Ktext(style={"control_width": 12})
        self.copy_key = kritter.Kbutton(name=[kritter.Kritter.icon("copy"), "Copy share key"], disp=False)
        self.key_store = dcc.Store(data="hello_there", id=kritter.Kritter.new_id())
        super().__init__(title=[kritter.Kritter.icon("cloud-upload"), "Export project"], layout=[self.export, self.status, self.copy_key, self.key_store], shared=True)

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
        self.kapp.clientside_callback(script, Output("_none", kritter.Kritter.new_id()), [Input(self.copy_key.id, "n_clicks")], state=[State(self.key_store.id, "data")])

        def _update_status(percent):
            self.kapp.push_mods(self.status.out_value(f"Copying to Google Drive ({percent}%)..."))

        @self.callback_view()
        def func(state):
            if not state:
                return self.status.out_value("") + self.copy_key.out_disp(False)

        @self.export.callback()
        def func():
            self.kapp.push_mods(self.export.out_spinner_disp(True) + self.status.out_value("Zipping project files...") + self.copy_key.out_disp(False))
            file_info = self.file_info_func()
            os.chdir(file_info['project_dir'])
            files_string = ''
            for i in file_info['files']:
                files_string += f" '{i}'"
            files_string = files_string[1:]
            export_file = kritter.time_stamped_file("zip", f"{file_info['project_name']}_export_")
            os.system(f"zip -r '{export_file}' {files_string}")
            gdrive_file = os.path.join(file_info['gdrive_dir'], export_file)
            try:
                self.gdrive.copy_to(os.path.join(file_info['project_dir'], export_file), gdrive_file, True, _update_status)
            except Exception as e:
                print("Unable to upload project export file to Google Drive.", e)
                self.kapp.push_mods(self.status.out_value(f'Unable to upload project export file to Google Drive. ({e})'))
                return 
            url = self.gdrive.get_url(gdrive_file)
            pieces = url.split("/")
            # Remove obvous non-id pieces
            pieces = [i for i in pieces if i.find(".")<0 and i.find("?")<0]
            # sort by size
            pieces.sort(key=len, reverse=True)
            # The biggest piece is going to be the id.  Encode with the project name, surround by V's to 
            # prevent copy-paste errors (the key might be emailed, etc.)  
            key = f"V{base64.b64encode(json.dumps([self.key_type, file_info['project_name'], pieces[0]]).encode()).decode()}V"
            # Write key to file for safe keeping
            key_filename = os.path.join(file_info['project_dir'], kritter.time_stamped_file("key", "share_key_"))
            with open(key_filename, "w") as file:
                file.write(key)
            if self.key_func:
                self.key_func(key)
            return self.status.out_value(["Done!  Press ", html.B("Copy share key"), " button to copy to clipboard."]) + self.copy_key.out_disp(True) + self.export.out_spinner_disp(False) + [Output(self.key_store.id, "data", key)]


class ImportProjectDialog(kritter.Kdialog):

    def __init__(self, gdrive, project_dir, key_type):
        self.gdrive = gdrive
        self.project_dir = project_dir
        self.key_type = key_type
        self.callback_func = None
        self.key_c = kritter.KtextBox(placeholder="Paste share key here")
        self.import_button = kritter.Kbutton(name=[kritter.Kritter.icon("cloud-download"), "Import"], spinner=True, disabled=True)
        self.key_c.append(self.import_button)
        self.status = kritter.Ktext(style={"control_width": 12})
        self.confirm_text = kritter.Ktext(style={"control_width": 12})
        self.confirm_dialog = kritter.KyesNoDialog(title="Confirm", layout=self.confirm_text, shared=True)
        super().__init__(title=[kritter.Kritter.icon("cloud-download"), "Import project"], layout=[self.key_c, self.status, self.confirm_dialog], shared=True)

        @self.confirm_dialog.callback_response()
        def func(val):
            if val:
                self.project_name = self._next_project()
                self.kapp.push_mods(self.confirm_dialog.out_open(False))
                return self._import()

        @self.callback_view()
        def func(state):
            if not state:
                return self.status.out_value("") + self.key_c.out_value("") + self.import_button.out_disabled(True)

        @self.key_c.callback()
        def func(key):
            return self.import_button.out_disabled(False)

        @self.import_button.callback(self.key_c.state_value())
        def func(key):
            self.kapp.push_mods(self.import_button.out_spinner_disp(True))
            mods = self.import_button.out_spinner_disp(False)
            key = key.strip()
            if key.startswith('V') and key.endswith('V'):
                try:
                    key = key[1:-1]
                    data = json.loads(base64.b64decode(key.encode()).decode())
                    if data[0]!=self.key_type:
                        raise RuntimeError("This is not the correct type of key.") 
                    self.project_name = data[1]
                    self.key = data[2]
                    # We could add a callback here for client code to verify and raise exception
                except Exception as e:
                    return mods +  self.status.out_value(f"This key appears to be invalid. ({e})") 
                if os.path.exists(os.path.join(self.project_dir, self.project_name)):
                    return mods + self.confirm_text.out_value(f'A project named "{self.project_name}" already exists.  Would you like to save it as "{self._next_project()}"?') + self.confirm_dialog.out_open(True)
                return mods + self._import()
            else:
                return mods + self.status.out_value('Share keys start and end with a "V" character.') 

    def _next_project(self):
        project_name = self.project_name+"_"
        while os.path.exists(os.path.join(self.project_dir, project_name)):
            project_name += "_"
        return project_name 

    def _update_status(self, percent):
        self.kapp.push_mods(self.status.out_value(f"Downloading {self.project_name} project ({percent}%)..."))

    def _import(self):
        try:
            new_project_dir = os.path.join(self.project_dir, self.project_name)
            os.makedirs(new_project_dir)
            import_file = os.path.join(new_project_dir, IMPORT_FILE) 
            self.gdrive.download(self.key, import_file, self._update_status)
            self.kapp.push_mods(self.status.out_value("Unzipping project files..."))
            os.chdir(new_project_dir)
            os.system(f"unzip {IMPORT_FILE}")
            os.remove(import_file)
        except Exception as e:
            print("Unable to import project.", e)
            os.rmdir(new_project_dir)
            self.kapp.push_mods(self.status.out_value(f'Unable to import project. ({e})'))
            return []
        self.kapp.push_mods(self.status.out_value("Done!")) 
        time.sleep(1)
        mods = self.out_open(False)
        if self.callback_func:
            res = self.callback_func(self.project_name)
            if isinstance(res, list):
                mods += res
        return mods 

    def callback(self):
        def wrap_func(func):
            self.callback_func = func
        return wrap_func


# Do a nested dictionary update
def deep_update(d1, d2):
    if all((isinstance(d, dict) for d in (d1, d2))):
        for k, v in d2.items():
            d1[k] = deep_update(d1.get(k), v)
        return d1
    return d2

class MotionScope:

    def __init__(self):
        self.data = collections.defaultdict(dict)
        self.kapp = Vizy()
        self.project_dir = os.path.join(self.kapp.etcdir, "motionscope")
        self.current_project_dir = self.project_dir    
        if not os.path.exists(self.project_dir):
            os.makedirs(self.project_dir)
        consts_filename = os.path.join(APP_DIR, CONSTS_FILE) 
        self.config_consts = import_config(consts_filename, self.kapp.etcdir, ["WIDTH", "PADDING", "GRAPHS", "MAX_RECORDING_DURATION", "START_SHIFT", "MIN_RANGE", "PLAY_RATE", "UPDATE_RATE", "FOCAL_LENGTH", "BG_AVG_RATIO", "BG_CNT_FINAL", "EXT_BUTTON_CHANNEL", "DEFAULT_CAMERA_SETTINGS", "DEFAULT_CAPTURE_SETTINGS", "DEFAULT_PROCESS_SETTINGS", "DEFAULT_ANALYZE_SETTINGS"])     
        self.lock = RLock()
        self.vpb = vpb.VizyPowerBoard()

        self.gdrive= kritter.Gcloud(self.kapp.etcdir).get_interface("KfileClient")

        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.camera.mode = "768x432x10bpp"

        style = {"label_width": 3, "control_width": 6, "max_width": self.config_consts.WIDTH}
        # Set video width to dynamically scale with width of window or WIDTH, whichever
        # is less.  We subtract 2*PADDING because it's on both sides. 
        self.video = kritter.Kvideo(overlay=True, video_style={"width": f"min(calc(100vw - {2*self.config_consts.PADDING}px), {self.config_consts.WIDTH}px)"})
        self.perspective = Perspective(self.video, self.config_consts.FOCAL_LENGTH, self.camera.getmodes()[self.camera.mode], style=style)       
        self.camera_tab = Camera(self)
        self.capture_tab = Capture(self)
        self.process_tab = Process(self)
        self.analyze_tab = Analyze(self)
        self.tabs = [self.camera_tab, self.capture_tab, self.process_tab, self.analyze_tab]
        for t in self.tabs:
            t.id_nav = self.kapp.new_id()    
        self.tab = self.camera_tab

        self.file_options_map = {
            "open": dbc.DropdownMenuItem([Kritter.icon("folder-open"), "Open..."], disabled=True), 
            "save": dbc.DropdownMenuItem([Kritter.icon("save"), "Save"], disabled=True), 
            "save-as": dbc.DropdownMenuItem([Kritter.icon("save"), "Save as..."]), 
            "import_project": dbc.DropdownMenuItem([kritter.Kritter.icon("sign-in"), "Import project..."]), 
            "export_project": dbc.DropdownMenuItem([kritter.Kritter.icon("sign-out"), "Export project..."]), 
            "close": dbc.DropdownMenuItem([Kritter.icon("folder"), "Close"], disabled=True)}
        self.file_menu = kritter.KdropdownMenu(name="File", options=list(self.file_options_map.values()), nav=True, item_style={"margin": "0px", "padding": "0px 10px 0px 10px"})
        self.sa_dialog = NewSaveAsDialog(self.get_projects, title=[kritter.Kritter.icon("folder"), "Save project as"], overwritable=True)
        self.open_dialog = OpenProjectDialog(self.get_projects)
 
        nav_items = [dbc.NavItem(dbc.NavLink(t.name, active=i==0, id=t.id_nav, disabled=t.name=="Process" or t.name=="Analyze")) for i, t in enumerate(self.tabs)]
        nav_items.append(self.file_menu.control)
        nav = dbc.Nav(nav_items, pills=True, navbar=True)
        navbar = dbc.Navbar(nav, color="dark", dark=True, expand=True)

        self.save_progress_dialog = kritter.KprogressDialog(title="Saving...", shared=True)
        self.load_progress_dialog = kritter.KprogressDialog(title="Loading...", shared=True)

        controls_layout = html.Div([
            # Navbar stays fixed at top
            navbar, 
            # Everything else scrolls.
            html.Div([
                html.Div([
                    html.Div([self.video, 
                        dbc.Card([self.perspective.layout] + [t.layout for t in self.tabs], 
                            style={"max-width": f"{self.config_consts.WIDTH}px", "margin-top": "10px", "margin-bottom": "10px"}
                        )
                    ], style={"float": "left"}), 
                    html.Div(self.analyze_tab.graphs.layout)
                ], style={"padding": f"{self.config_consts.PADDING}px"})
            # Next Div is scrollable, occupies all of available viewport.    
            ], style={"overflow": "auto"})
        # Outermost Div is flexbox 
        ], style={"display": "flex", "height": "100%", "flex-direction": "column"})

        self.kapp.layout = [controls_layout, self.save_progress_dialog, self.load_progress_dialog, self.sa_dialog, self.open_dialog, self._create_import_project_dialog(), self._create_export_project_dialog()]

        @self.open_dialog.callback_project()
        def func(project, delete):
            if delete:
                os.system(f"rm -rf '{os.path.join(self.project_dir, project)}'")
            else:
                self.open_project(project)

        @self.sa_dialog.callback_project()
        def func(project):
            self.set_project(project)
            self.save()

        @self.file_menu.callback()
        def func(val):
            file_options = list(self.file_options_map.keys())
            ss = file_options[val]
            if ss=="open":
                return self.open_dialog.out_open(True)
            elif ss=="save":
                self.save()
                return
            elif ss=="save-as": 
                return self.sa_dialog.out_open(True)
            elif ss=="export_project":
                return self.export_project_dialog.out_open(True)
            elif ss=="import_project":
                return self.import_project_dialog.out_open(True)
            elif ss=="close":
                return self.reset()

        for t in self.tabs:
            func = self.get_tab_func(t)
            self.kapp.callback_shared(None, [Input(t.id_nav, "n_clicks")])(func)
        
        @self.capture_tab.data_update_callback
        def func(changed, cmem):
            return self.data_update(changed, cmem)

        @self.process_tab.data_update_callback
        def func(changed, cmem):
            return self.data_update(changed, cmem)

        self.kapp.push_mods(self.load_update() + self.reset())

        # Run main gui thread.
        self.run_thread = True
        Thread(target=self.thread).start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self.run_thread = False

    def _create_import_project_dialog(self):
        self.import_project_dialog = ImportProjectDialog(self.gdrive, self.project_dir, SHARE_KEY_TYPE)

        @self.import_project_dialog.callback()
        def func(project_name):
            # open imported project
            self.open_project(project_name)

        return self.import_project_dialog

    def _create_export_project_dialog(self):
        def file_info_func():
            return {
                "project_name": self.project, 
                "project_dir": self.current_project_dir, 
                "files": [DATA_FILE, VIDEO_FILE], 
                "gdrive_dir": GDRIVE_DIR
            }

        self.export_project_dialog = ExportProjectDialog(self.gdrive, SHARE_KEY_TYPE, file_info_func)

        return self.export_project_dialog

    def get_projects(self, exclude_current=False):
        plist = glob.glob(os.path.join(self.project_dir, '*', DATA_FILE))
        plist = [os.path.basename(os.path.dirname(i)) for i in plist]
        if exclude_current:
            try:
                plist.remove(self.project)
            except:
                pass
        plist.sort(key=str.lower)
        return plist

    def open_project(self, project):
        # Display load progress dialog to give user feedback.  
        self.kapp.push_mods(self.load_progress_dialog.out_progress(0) + self.load_progress_dialog.out_open(True))
        # Reset state of application to make sure no remnant settings are left behind.
        self.kapp.push_mods(self.reset())
        self.set_project(project)
        filename = os.path.join(self.current_project_dir, VIDEO_FILE)
        exists = os.path.exists(filename)
        self.run_progress = True
        # Create recording object (save_load_progress needs it)
        if exists:
            self.data['recording'] = self.camera.stream(False)
        Thread(target=self.save_load_progress, args=(self.load_progress_dialog, )).start()
        # Load (this blocks)
        if exists:
            self.data['recording'].load(filename)
        self.run_progress = False

    def reset(self):
        mods = []
        # Reset tabs
        for t in self.tabs:
            mods += t.reset()
        # Push tab reset first to reset variables, etc. 
        self.kapp.push_mods(mods + self.perspective.out_reset() + self.perspective.out_enable(False))
        self.data['recording'] = None
        try:
            del self.file_options_map['header']
            del self.file_options_map['divider']
            del self.data['obj_data']
            del self.project
        except KeyError:
            pass
        self.file_options_map['save'].disabled = True
        self.file_options_map['close'].disabled = True
        # Reset perspective and disable
        f = self.get_tab_func(self.camera_tab)
        return f(None) + [Output(self.analyze_tab.id_nav, "disabled", True), Output(self.process_tab.id_nav, "disabled", True)] + self.file_menu.out_options(list(self.file_options_map.values()))  

    def save(self):
        self.run_progress = True
        Thread(target=self.save_load_progress, args=(self.save_progress_dialog, )).start()
        if self.data['recording'] is not None:
            self.data['recording'].save(os.path.join(self.current_project_dir, VIDEO_FILE))
        self.run_progress = False

    def set_project(self, project):
        self.project = project
        self.current_project_dir = os.path.join(self.project_dir, self.project)
        if not os.path.exists(self.current_project_dir):
            os.makedirs(self.current_project_dir)
        try:
            del self.file_options_map['header']
            del self.file_options_map['divider']
        except KeyError:
            pass
        self.file_options_map['save'].disabled = False
        self.file_options_map['close'].disabled = False
        self.file_options_map = {**{"header": dbc.DropdownMenuItem(self.project, header=True), "divider": dbc.DropdownMenuItem(divider=True)}, **self.file_options_map}
        self.kapp.push_mods(self.file_menu.out_options(list(self.file_options_map.values())))

    def get_tab_func(self, tab):
        def func(val):
            mods = [Output(t.layout.id, "is_open", t is tab) for t in self.tabs] + [Output(t.id_nav, "active", t is tab) for t in self.tabs]
            with self.lock:
                res = self.tab.focus(False)
                if res:
                    mods += res
                self.tab = tab
                res = self.tab.focus(True)
            if res:
                mods += res
            return mods 
        return func

    def data_update(self, changed, cmem=None):
        mods = []
        for t in self.tabs:
            mods += t.data_update(changed, cmem)
        if "recording" in changed:
            if self.data['recording'].len()>self.config_consts.BG_CNT_FINAL: 
                mods += self.file_menu.out_options(list(self.file_options_map.values())) + [Output(self.process_tab.id_nav, "disabled", False)]
        if "obj_data" in changed:
            if self.data['obj_data']:
                f = self.get_tab_func(self.analyze_tab)
                mods += [Output(self.analyze_tab.id_nav, "disabled", False)] + f(None)
            else: 
                mods += [Output(self.analyze_tab.id_nav, "disabled", True)]

        return mods           

    def load_update(self):
        projects = self.get_projects() 
        self.file_options_map['open'].disabled = not bool(projects) 
        return self.file_menu.out_options(list(self.file_options_map.values()))

    def save_load_progress(self, dialog):
        self.kapp.push_mods(dialog.out_progress(0) + dialog.out_open(True)) 

        # Update progress while file is being saved/loaded.
        _progress = 0
        if self.data['recording'] is not None:
            while self.run_progress:
                progress = self.data['recording'].progress()
                if progress>_progress:
                    self.kapp.push_mods(dialog.out_progress(progress-2))
                    _progress = progress
                time.sleep(1/self.config_consts.UPDATE_RATE)
        self.kapp.push_mods(dialog.out_progress(99))

        mods = []
        # Save/load rest of data.
        filename = os.path.join(self.current_project_dir, DATA_FILE)
        # Save
        if dialog is self.save_progress_dialog: 
            with open(filename, 'w') as f:
                self.data['Perspective'] = self.perspective.get_params()
                data = self.data.copy()
                # We don't need bg, and recording is already saved.
                if 'bg' in data:
                    del data['bg']
                if 'recording' in data:
                    del data['recording']
                json.dump(data, f, cls=kritter.JSONEncodeFromNumpy) 
            mods += self.load_update()
        # Load        
        else: 
            # Inform tabs that we have a recording.
            if self.data['recording'] is not None:
                mods += self.data_update("recording")
            try:
                with open(filename) as f:
                    data = json.load(f, cls=kritter.JSONDecodeToNumpy)
                deep_update(self.data, data)

                # Inform tabs that we have a list of changed
                changed = list(data.keys())
                mods += self.data_update(changed)
                # This will fire off draw events for graphs in a different thread...
                mods += self.perspective.set_params(self.data['Perspective'])
                # ...so let's make sure we draw graphs with updated perspective here to 
                # avoid the race condition.\
                mods += self.analyze_tab.graphs.out_draw()
            except Exception as e:
                print(f"Error loading: {e}")

        self.kapp.push_mods(mods)
        # Display for at least 1 second
        time.sleep(1)
        self.kapp.push_mods(dialog.out_open(False))

    def thread(self):

        while self.run_thread:
            time.sleep(1e-3) # A tiny sleep to reduce latency of other threads.
            with self.lock:
                # Get frame
                frame = self.tab.frame()
            # Send frame
            if isinstance(frame, tuple): 
                # Capture can send frameperiod with frame 
                # so it renders correctly
                frame_ = self.perspective.transform(frame[0])
                self.video.push_frame(frame_, frame[1])
            elif frame is not None:
                frame = self.perspective.transform(frame)
                self.video.push_frame(frame)
        self.vpb.led(0, 0, 0)



if __name__ == "__main__":
        ms = MotionScope()
