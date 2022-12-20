#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

# TODO: cleanup -- try to optimize out the numerous class members that don't need to be there.

import os
import glob
import cv2
import time
import json
import datetime
import random
import filecmp
import numpy as np
from collections import defaultdict
from threading import Thread, Lock
import kritter
from kritter import get_color
from kritter.tflite import TFliteDetector
from dash_devices.dependencies import Input, Output
import dash_html_components as html
import dash_bootstrap_components as dbc
from vizy import Vizy, MediaDisplayQueue
from handlers import handle_event, handle_text
from kritter.ktextvisor import KtextVisor, KtextVisorTable, Image, Video

# Minimum allowable detection senstivity/treshold
MIN_THRESHOLD = 0.1
# Maximum allowable detection senstivity/treshold
MAX_THRESHOLD = 0.9
# We start tracking at the current sensitivity setting and stop tracking at the 
# sensitvity - THRESHOLD_HYSTERESIS 
THRESHOLD_HYSTERESIS = 0.2
# Native camera mode
CAMERA_MODE = "768x432x10bpp"
CAMERA_WIDTH = STREAM_WIDTH = 768
# Image average for daytime detection (based on 0 to 255 range)
DAYTIME_THRESHOLD = 20
# Poll period (seconds) for checking for daytime
DAYTIME_POLL_PERIOD = 10

APP_CONFIG_FILE = "object_detector.json"
PROJECT_CONFIG_FILE = "project.json"
CONSTS_FILE = "object_detector_consts.py"
GDRIVE_DIR = "/vizy/object_detector"
TRAIN_FILE = "train_detector.ipynb"
TRAINING_SET_FILE = "training_set.zip"
model = "detector.tflite"
COMMON_OBJECTS = "Common Objects"
DEFAULT_APP_CONFIG = {
    "brightness": 50,
    "tracking": True,
    "smooth_video": False, 
    "gphoto_upload": False,
    "project": COMMON_OBJECTS
}

DEFAULT_PROJECT_CONFIG = {
    "detection_sensitivity": 50,
    "enabled_classes": [],
    "trigger_classes": []
}

BASEDIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(BASEDIR, "media")


class MediaDisplayGrid:
    def __init__(self, media_dir, data_func=None, label_func=None, kapp=None):
        self.page = 0
        self.pages = 0
        self.rows = 4
        self.cols = 4
        self._callback_click = None
        self._callback_render = None
        self.kapp = kritter.Kritter.kapp if kapp is None else kapp
        self.set_data_func(data_func)
        self.set_label_func(label_func)
        self.set_media_dir(media_dir)
        self.begin_button = kritter.Kbutton(name=kritter.Kritter.icon("angle-double-left", padding=0))
        self.prev_button = kritter.Kbutton(name=kritter.Kritter.icon("angle-left", padding=0))
        self.next_button = kritter.Kbutton(name=kritter.Kritter.icon("angle-right", padding=0))
        self.end_button = kritter.Kbutton(name=kritter.Kritter.icon("angle-double-right", padding=0))
        self.status = kritter.Ktext()
        self.begin_button.append(self.prev_button)
        self.begin_button.append(self.next_button)
        self.begin_button.append(self.end_button)
        self.begin_button.append(self.status)

        self.layout = html.Div([html.Div(self.begin_button), html.Div(self._create_images())])

        @self.begin_button.callback()
        def func():
            self.page = 0
            return self.out_images() + self.call_callback_render()

        @self.prev_button.callback()
        def func():
            self.page -= 1
            return self.out_images() + self.call_callback_render()

        @self.next_button.callback()
        def func():
            self.page += 1
            return self.out_images() + self.call_callback_render()

        @self.end_button.callback()
        def func():
            self.page = self.pages-1
            return self.out_images() + self.call_callback_render()

    def _create_images(self):
        children = []
        self.images = []
        for i in range(self.rows):
            row = []
            for j in range(self.cols):
                kimage = kritter.Kimage(overlay=True, style={"display": "inline-block", "margin": "5px"}, service=None)
                self.images.append(kimage)
                col = dbc.Col(kimage.layout, id=self.kapp.new_id(), className="_nopadding")
                
                def func(_kimage):
                    def func_():
                        mods = []
                        if _kimage.path.lower().endswith(".jpg"):
                            if not _kimage.data:
                                height, width, _ = cv2.imread(_kimage.fullpath).shape
                                _kimage.data['width'] = width  
                                _kimage.data['height'] = height
                            mods += self.call_callback_click(_kimage)
                        return mods
                    return func_

                kimage.callback()(func(kimage))
                row.append(col)
            children.append(dbc.Row(row, justify="start", className="_nopadding"))
        return children

    def set_data_func(self, data_func):
        self.data_func = (lambda data : data) if data_func is None else data_func 

    def set_label_func(self, label_func):
        self.label_func = (lambda key, det : det['class']) if label_func is None else label_func

    def render(self, kimage, data, scale):
        try:
            data = self.data_func(data)
        except:
            pass
        try:
            kimage.overlay.update_resolution(width=data['width'], height=data['height'])
            kritter.render_detected(kimage.overlay, data['dets'], label_format=self.label_func, scale=scale)
        except:
            kimage.overlay.draw_clear()
        try:
            kimage.overlay.draw_text(0, data['height']-1, data['timestamp'], fillcolor="black", font=dict(family="sans-serif", size=12, color="white"), xanchor="left", yanchor="bottom")
        except:
            pass 
        return kimage.overlay.out_draw()

    def update_images_and_data(self):
        images = os.listdir(self.media_dir)
        images = [i for i in images if i.endswith(".jpg") or i.endswith(".mp4")]
        images.sort()

        images_and_data = []
        for image in images:
            data = kritter.load_metadata(os.path.join(self.media_dir, image))
            images_and_data.append((image, data))
        self.images_and_data = images_and_data
        self.pages = (len(self.images_and_data)-1)//(self.rows*self.cols) + 1 if self.images_and_data else 0

    def set_media_dir(self, media_dir):
        if media_dir:
            try:
                self.kapp.media_path.remove(self.media_dir)
            except:
                pass
            self.media_dir = media_dir
            self.kapp.media_path.insert(0, self.media_dir)
            self.images_and_data = [] 

    def out_images(self, force_update=False):
        if not self.images_and_data or force_update:
            self.update_images_and_data()
            force_update = True # we need to trigger callback_render if we call update_images_and_data
        mods = []
        if self.page<=0:
            self.page = 0
            mods += self.begin_button.out_disabled(True) + self.prev_button.out_disabled(True)
        if self.page>=self.pages-1:
            if self.pages>0:
                self.page = self.pages-1 
            mods += self.end_button.out_disabled(True) + self.next_button.out_disabled(True)
        if self.pages>1: 
            if self.page>0:
                mods += self.begin_button.out_disabled(False) + self.prev_button.out_disabled(False)
            if self.page<self.pages-1:
                mods += self.end_button.out_disabled(False) + self.next_button.out_disabled(False)
        page_message = f"Page {self.page+1} of {self.pages}" if self.pages>=self.page+1 else ""
        mods += self.status.out_value(page_message)

        offset = self.page*self.rows*self.cols
        self.page_images_and_data = self.images_and_data[offset:offset+self.rows*self.cols]
        for i in range(self.rows*self.cols):
            if i+offset < len(self.images_and_data):
                image, data = self.page_images_and_data[i]
                self.images[i].path = image # for URL
                self.images[i].fullpath = os.path.join(self.media_dir, image)
                self.images[i].data = data
                self.images[i].overlay.draw_clear()
                mods += self.images[i].out_src(image)
                mods += self.render(self.images[i], data, scale=0.33)
                mods += self.images[i].overlay.out_draw() + self.images[i].out_disp(True)
            else:
                mods += self.images[i].out_disp(False)

        if force_update:
            mods += self.call_callback_render()

        return mods

    def call_callback_click(self, kimage):
        if self._callback_click:
            mods = self._callback_click(kimage)
            if isinstance(mods, list):
                return mods 
        return []

    def callback_click(self):
        def wrap_func(func):
            self._callback_click = func
        return wrap_func

    def call_callback_render(self):
        if self._callback_render:
            mods = self._callback_render()
            if isinstance(mods, list):
                return mods     
        return []

    def callback_render(self):
        def wrap_func(func):
            self._callback_render = func
        return wrap_func


class OpenProjectDialog(kritter.Kdialog):
    def __init__(self, get_projects, title=[kritter.Kritter.icon("folder-open"), "Open project"]):
        self._get_projects = get_projects
        self.selection = ''
        self.callback_func = None
        open_button = kritter.Kbutton(name=[kritter.Kritter.icon("folder-open"), "Open"], disabled=True)
        delete_button = kritter.Kbutton(name=[kritter.Kritter.icon("trash"), "Delete"], disabled=True)
        delete_text = kritter.Ktext(style={"control_width": 12})
        yesno = kritter.KyesNoDialog(title="Delete project?", layout=delete_text, shared=True)
        select = kritter.Kdropdown(value=None, placeholder="Select project...")
        select.append(open_button)
        select.append(delete_button)
        super().__init__(title=title, layout=[select, yesno], shared=True)

        @self.callback_view()
        def func(state):
            if state:
                return select.out_options(self.get_projects(True))
            else:
                return select.out_value(None)

        @select.callback()
        def func(selection):
            self.selection = selection
            disabled = not bool(selection)
            return open_button.out_disabled(disabled) + delete_button.out_disabled(disabled)

        @open_button.callback()
        def func():
            mods = []
            if self.callback_func:
                mods += self.callback_func(self.selection, False)
            return self.out_open(False) + mods

        @delete_button.callback()
        def func():
            return delete_text.out_value(f'Are you sure you want to delete "{self.selection}" project?') + yesno.out_open(True)

        @yesno.callback_response()
        def func(val):
            if val:
                mods = []
                if self.callback_func:
                    mods += self.callback_func(self.selection, True)
                projects = self.get_projects(True)
                return select.out_options(projects) + select.out_value(None)

    def get_projects(self, exclude_current=False):
        return self._get_projects(exclude_current)

    def callback_project(self):
        def wrap_func(func):
            self.callback_func = func
        return wrap_func

class NewSaveAsDialog(kritter.Kdialog):
    def __init__(self, get_projects, title=[kritter.Kritter.icon("folder"), "New project"], overwritable=False):
        self._get_projects = get_projects
        self.name = ''
        self.callback_func = None
        name = kritter.KtextBox(placeholder="Enter project name")
        save_button = kritter.Kbutton(name=[kritter.Kritter.icon("save"), "Save"], disabled=True)
        dialog_text = kritter.Ktext(style={"control_width": 12})
        if overwritable:
            dialog = kritter.KyesNoDialog(title="Overwrite project?", layout=dialog_text, shared=True)
        else:
            dialog = kritter.KokDialog(title="Project exists", layout=dialog_text, shared=True)

        name.append(save_button)
        super().__init__(title=title, close_button=[kritter.Kritter.icon("close"), "Cancel"], layout=[name, dialog], shared=True)

        @self.callback_view()
        def func(state):
            if not state:
                return name.out_value("")

        @name.callback()
        def func(val):
            if val:
                self.name = val
            return save_button.out_disabled(not bool(val))

        @save_button.callback()
        def func():
            projects = self.get_projects()
            if self.name in projects:
                if overwritable:
                    return dialog_text.out_value(f'"{self.name}" exists. Do you want to overwrite?') + dialog.out_open(True)
                else:
                    return dialog_text.out_value(f'"{self.name}" already exists.') + dialog.out_open(True)

            mods = []
            if self.callback_func:
                mods += self.callback_func(self.name)
            return self.out_open(False) + mods 

        if overwritable:
            @dialog.callback_response()
            def func(val):
                if val:
                    self.kapp.push_mods(self.out_open(False))
                    if self.callback_func:
                        self.callback_func(self.name)

    def get_projects(self, exclude_current=False):
        return self._get_projects(exclude_current)
 
    def callback_project(self):
        def wrap_func(func):
            self.callback_func = func
        return wrap_func

def create_pvoc(filename, defs, resolution=None, out_filename=None, depth=3):
    if not resolution: 
        image = cv2.imread(filename)
        resolution = (image.shape[1], image.shape[0])
    if not out_filename:
        out_filename = kritter.file_basename(filename)+".xml"
    filename = os.path.split(filename)[1]
    text = \
f"""<annotation verified="yes">
    <folder>folder</folder>
    <filename>{filename}</filename>
    <path>{os.path.join("./folder", filename)}</path>
    <source>
        <database>Unknown</database>
    </source>
    <size>
        <width>{int(resolution[0])}</width>
        <height>{int(resolution[1])}</height>
        <depth>{depth}</depth>
    </size>
    <segmented>0</segmented>
"""
    for d in defs:
        text += \
f"""    <object>
        <name>{d["class"]}</name>
        <pose>Unspecified</pose>
        <truncated>0</truncated>
        <difficult>0</difficult>
        <bndbox>
            <xmin>{int(d["box"][0])}</xmin>
            <ymin>{int(d["box"][1])}</ymin>
            <xmax>{int(d["box"][2])}</xmax>
            <ymax>{int(d["box"][3])}</ymax>
        </bndbox>
    </object>
"""
    text += \
"""</annotation>
"""
    with open(out_filename, "w") as file:
        file.write(text)

VALIDATION_PERCENTAGE = 10
MODEL_MENUS = 2
INIT = 0
LAYOUT = 1
OPEN = 2
CLOSE = 3
NAVLINK = 4
PREPARE = 0
TRAIN = 1


def model_index(model):
    try:
        return int(model.split('.')[0].split('_')[-1])
    except:
        return 0 

class ObjectDetector:
    def __init__(self):

        # Create Kritter server.
        self.kapp = Vizy()

        # Initialize variables
        config_filename = os.path.join(self.kapp.etcdir, APP_CONFIG_FILE)  
        self.project_dir = os.path.join(self.kapp.etcdir, "object_detector")
        self.app_config = kritter.ConfigFile(config_filename, DEFAULT_APP_CONFIG)          
        consts_filename = os.path.join(BASEDIR, CONSTS_FILE) 
        self.config_consts = kritter.import_config(consts_filename, self.kapp.etcdir, ["IMAGES_KEEP", "IMAGES_DISPLAY", "PICKER_TIMEOUT", "MEDIA_QUEUE_IMAGE_WIDTH", "GPHOTO_ALBUM", "TRACKER_DISAPPEARED_DISTANCE", "TRACKER_MAX_DISAPPEARED"])
        self.daytime = kritter.CalcDaytime(DAYTIME_THRESHOLD, DAYTIME_POLL_PERIOD)
        self.open_lock = Lock()
        self.classes = []
        self.layouts = {}
        self.tabs = {}
        self.store_media = None
        self.detector_process = None
        self.detector = None
        self.tracker = None
        self.picker = None
        self._grab_thread = None
        self.tab = "Detect"
        self.test_models = False

        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream()
        self.camera.mode = CAMERA_MODE
        self.camera.brightness = self.app_config['brightness']
        self.camera.framerate = 30
        self.camera.autoshutter = True
        self.camera.awb = True

        # Invoke KtextVisor client, which relies on the server running.
        # In case it isn't running, just roll with it.  
        try:
            self.tv = KtextVisor()
            def mrm(words, sender, context):
                try:
                    n = min(int(words[1]), 10)
                except:
                    n = 1
                res = []
                images_and_data = self.media_queue.get_images_and_data()
                for image, data in images_and_data:
                    try:
                        if image.endswith(".mp4"):
                            res.append(f"{data['timestamp']} Video")
                            res.append(Video(os.path.join(MEDIA_DIR, image)))
                        else:
                            res.append(f"{data['timestamp']} {data['class']}")
                            res.append(Image(os.path.join(MEDIA_DIR, image)))                            
                    except:
                        pass
                    else:
                        if len(res)//2==n:
                            break
                return res
            tv_table = KtextVisorTable({"mrm": (mrm, "Displays the most recent picture, or n media with optional n argument.")})
            @self.tv.callback_receive()
            def func(words, sender, context):
                return tv_table.lookup(words, sender, context)
            @self.tv.callback_receive()
            def func(words, sender, context):
                return handle_text(self, words, sender, context)
            print("*** Texting interface found!")
        except:
            self.tv = None
            print("*** Texting interface not found.")

        self.gcloud = kritter.Gcloud(self.kapp.etcdir)
        self.gphoto_interface = self.gcloud.get_interface("KstoreMedia")
        self.gdrive_interface = self.gcloud.get_interface("KfileClient")

        # Map 1 to 100 (sensitivity) to 0.9 to 0.1 (detection threshold)
        self.sensitivity_range = kritter.Range((1, 100), (0.9, 0.1), inval=50) 

        self._create_tabs()

        self.file_options_map = {
            "header": dbc.DropdownMenuItem(self.app_config['project'], header=True), 
            "divider": dbc.DropdownMenuItem(divider=True), 
            "new": dbc.DropdownMenuItem([kritter.Kritter.icon("folder"), "New..."]), 
            "open": dbc.DropdownMenuItem([kritter.Kritter.icon("folder-open"), "Open..."]), 
            "train": dbc.DropdownMenuItem([kritter.Kritter.icon("train"), "Train..."], disabled=self.gdrive_interface is None), 
            "import_project": dbc.DropdownMenuItem([kritter.Kritter.icon("sign-in"), "Import project..."]), 
            "import_photos": dbc.DropdownMenuItem([kritter.Kritter.icon("sign-in"), "Import photos..."]), 
            "export_project": dbc.DropdownMenuItem([kritter.Kritter.icon("sign-out"), "Export project..."]), 
            "settings": dbc.DropdownMenuItem([kritter.Kritter.icon("gear"), "Settings..."])
        }
        self.file_menu = kritter.KdropdownMenu(name="File", options=list(self.file_options_map.values()), nav=True, item_style={"margin": "0px", "padding": "0px 10px 0px 10px"}, service=None)
        nav_items = []
        for i, v in self.tabs.items():
            v[NAVLINK] = dbc.NavLink(i, active=i==self.tab, id=i+"nav")
            nav_items.append(dbc.NavItem(v[NAVLINK]))    
        nav_items.append(self.file_menu.control)
        nav = dbc.Nav(nav_items, pills=True, navbar=True)
        navbar = dbc.Navbar(nav, color="dark", dark=True, expand=True)

        layouts = [dbc.Collapse(v, is_open=k in self.tabs[self.tab][LAYOUT], id=k+"collapse", style={"margin": "5px"}) for k, v in self.layouts.items()]
        self.kapp.layout = [navbar] + layouts + [self._create_settings_dialog(), self._create_training_image_dialog(), self._create_test_image_dialog(), self._create_dets_image_dialog(), self._create_label_dialog(), self._create_train_dialog(), self._create_open_project_dialog(), self._create_new_project_dialog()] 
        for k, v in self.tabs.items():
            try:
                v[INIT]()
            except:
                pass

        def tab_func(tab):
            def func(val):
                return self._tab_func(tab)
            return func

        for t in self.tabs:
            self.kapp.callback_shared(None, [Input(t+"nav", "n_clicks")])(tab_func(t))
        
        @self.file_menu.callback()
        def func(val):
            file_options = list(self.file_options_map.keys())
            option = file_options[val]
            if option=="open":
                return self.open_project_dialog.out_open(True)
            elif option=="new":
                return self.new_project_dialog.out_open(True)
            elif option=="train":
                return self.train_dialog.out_open(True)
            elif option=="settings":
                return self.settings_dialog.out_open(True)

        self.kapp.push_mods(self._open_project())

        # Run Kritter server, which blocks.
        self.kapp.run()
        self._close_project()

    def _tab_func(self, tab):
        mods = []
        try:
            mods += self.tabs[self.tab][CLOSE]()
        except: 
            pass
        self.tab = tab
        mods += self.tabs[self.tab][OPEN]()
        return mods + [Output(i+"collapse", "is_open", i in self.tabs[tab][LAYOUT]) for i in self.layouts] + [Output(t+"nav", "active", t==tab) for t in self.tabs]

    def _create_info(self):
        self._update_classes()
        info = {"classes": self.classes, "model": "efficientdet_lite0"}
        with open(os.path.join(self.current_project_dir, f"{self.app_config['project']}.json"), "w") as file:
            json.dump(info, file)

    def _prepare(self):
        self.kapp.push_mods(self.upload_button.out_spinner_disp(True) + self.train_button.out_disabled(True) + self.train_status.out_value("Zipping training set..."))
        mods = self.upload_button.out_spinner_disp(False)
        # create zip file
        os.chdir(self.current_project_dir)
        os.system("rm -rf tmp")
        os.system("mkdir tmp tmp/train tmp/validate tmp/.meta")
        os.chdir("tmp")
        files = os.listdir(self.project_training_dir)
        files = [f for f in files if f.endswith(".jpg")]
        for f in files:
            if VALIDATION_PERCENTAGE>=random.randint(1, 100):
                _dir = "validate"
            else:
                _dir = "train"
            ff = os.path.join(self.project_training_dir, f)
            data = kritter.load_metadata(ff)
            try:
                defs = data['defs']
                resolution = (data['width'], data['height'])
            except:
                height, width, _ = cv2.imread(ff).shape
                defs = []
                resolution = (width, height)
                data = {"defs": defs, "width": width, "height": height}
                kritter.save_metadata(ff, data)
            try:
                # create pvoc based on json
                create_pvoc(ff, defs, out_filename=os.path.join(self.current_project_dir, f"tmp/{_dir}", kritter.file_basename(f)+".xml"), resolution=resolution)
            except Exception as e:
                print(e)
                continue
            # copy files
            os.system(f"cp ../training/{f} {_dir}")
            os.system(f"cp ../training/{kritter.get_metadata_filename(f)} .meta")
        os.system(f"rm ../{TRAINING_SET_FILE}")
        os.system(f"zip -r ../{TRAINING_SET_FILE} train validate .meta")
        os.chdir("../..")

        # modify training ipynb
        with open(os.path.join(BASEDIR, TRAIN_FILE)) as file:
            train_code = json.load(file)
        project_dir = {"cell_type": "code", "source": [
            f'PROJECT_NAME = "{self.app_config["project"]}"\n',
            f'PROJECT_DIR = "{os.path.join("/content/drive/MyDrive", GDRIVE_DIR[1:])}/" + PROJECT_NAME'],
            "metadata": {"id": "zXTGWX9ZWaZ9"},
            "execution_count": 0,
            "outputs": []
        }
        train_code['cells'].insert(0, project_dir)
        train_file = os.path.join(self.current_project_dir, TRAIN_FILE)        
        with open(train_file, "w") as file:
            json.dump(train_code, file, indent=2)

        # create classes file
        self._create_info()

        # copy files to gdrive
        self.kapp.push_mods(self.train_status.out_value("Copying files to Google Drive..."))
        try:
            self.gdrive_interface.copy_to(os.path.join(self.current_project_dir, TRAINING_SET_FILE), os.path.join(self.project_gdrive_dir, TRAINING_SET_FILE), True)
        except Exception as e:
            print("Unable to upload training set images to Google Drive.", e)
            return mods + self.train_status.out_value(f'Unable to upload training set images to Google Drive. ("{e}")')
        try:
            self.gdrive_interface.copy_to(os.path.join(self.current_project_dir, f"{self.app_config['project']}.json"), os.path.join(self.project_gdrive_dir, f"{self.app_config['project']}.json"), True)
            g_train_file = os.path.join(self.project_gdrive_dir, TRAIN_FILE)
            self.gdrive_interface.copy_to(train_file, g_train_file, True)
        except Exception as e:
            print("Unable to upload training code to Google Drive.", e)
            return mods + self.train_status.out_value(f'Unable to upload training code to Google Drive. ("{e}")')
        return mods + self._update_train_state() + self.train_status.out_value("Done! Press Train button.")

    def out_tab_disabled(self, tab, disabled):
        return [Output(self.tabs[tab][NAVLINK].id, "disabled", disabled)]

    def _open_project(self, tab_change_allowed=True):
        with self.open_lock: # Use lock since some calls of _open_project are from Dash callbacks, which have their own threads.
            mods = []
            self._close_project()
            self.current_project_dir = os.path.join(self.project_dir, self.app_config['project'])
            if not os.path.exists(self.current_project_dir):
                os.makedirs(self.current_project_dir)
            if self.app_config['project']==COMMON_OBJECTS:
                self.models = []
                self.latest_model = None
                self.project_training_dir = None
                self.file_options_map['train'].disabled = True
                self.file_options_map['import_photos'].disabled = True
                self.file_options_map['export_project'].disabled = True
                mods += self.test_model_checkbox.out_disabled(True) + self.out_tab_disabled('Capture', True) + self.out_tab_disabled('Training set', True) + self.file_menu.out_options(list(self.file_options_map.values()))
            else:
                self.project_models_dir = os.path.join(self.current_project_dir, "models")
                if not os.path.exists(self.project_models_dir):
                    os.makedirs(self.project_models_dir)
                self.project_training_dir = os.path.join(self.current_project_dir, "training")
                if not os.path.exists(self.project_training_dir):
                    os.makedirs(self.project_training_dir)
                self.models = self.get_models()
                self.latest_model = os.path.join(self.current_project_dir, self.models[0]) if self.models else ""
                self.project_gdrive_dir = os.path.join(GDRIVE_DIR, self.app_config['project'])
                self.project_gdrive_models_dir = os.path.join(GDRIVE_DIR, self.app_config['project'], "models")
                self.file_options_map['train'].disabled = False
                self.file_options_map['import_photos'].disabled = True
                self.file_options_map['export_project'].disabled = True
                mods += self.test_model_checkbox.out_disabled(self.latest_model=="") + self.out_tab_disabled('Capture', False) + self.out_tab_disabled('Training set', False) + self.file_menu.out_options(list(self.file_options_map.values()))
            self.project_dets_dir = os.path.join(self.current_project_dir, "dets")
            if not os.path.exists(self.project_dets_dir):
                os.makedirs(self.project_dets_dir)
            config_filename = os.path.join(self.current_project_dir, PROJECT_CONFIG_FILE)
            self.project_config = kritter.ConfigFile(config_filename, DEFAULT_PROJECT_CONFIG.copy())
            self.store_media = kritter.SaveMediaQueue(path=self.project_dets_dir, keep=self.config_consts.IMAGES_KEEP, keep_uploaded=self.config_consts.IMAGES_KEEP)
            if self.app_config['gphoto_upload']:
                self.store_media.store_media = self.gphoto_interface 

            self.media_queue.set_media_dir(self.project_dets_dir)
            self.dets_grid.set_media_dir(self.project_dets_dir)
            if self.project_training_dir:
                self.capture_queue.set_media_dir(self.project_training_dir)
                self.training_grid.set_media_dir(self.project_training_dir)

            if self.app_config['tracking']:
                self.tracker = kritter.DetectionTracker(maxDisappeared=self.config_consts.TRACKER_MAX_DISAPPEARED, maxDistance=self.config_consts.TRACKER_DISAPPEARED_DISTANCE)
                self.picker = kritter.DetectionPicker(timeout=self.config_consts.PICKER_TIMEOUT)
            else:
                self.tracker = None
                self.picker = None

            self._set_threshold()
            self.model_threshold = self.project_config['detection_sensitivity'] - THRESHOLD_HYSTERESIS

            # If we don't have a model, disable detect and detections tabs.
            if self.latest_model=="":
                self.detector_process = None
                self.detector = None
                if tab_change_allowed:
                    mods += self._tab_func('Capture')
                mods += self.out_tab_disabled('Detect', True) + self.out_tab_disabled('Detections', True) 
            else: # If we do have a model, enable detect tab, start process and threads.
                self.detector_process = kritter.Processify(TFliteDetector, (self.latest_model,))
                if self.app_config['smooth_video']:
                    self.detector = kritter.KimageDetectorThread(self.detector_process)
                    classes = self.detector_process.classes()
                else:
                    self.detector = self.detector_process
                    classes = self.detector.classes()
                if not self.project_config['enabled_classes']:
                    self.project_config['enabled_classes'] = classes
                if tab_change_allowed:
                    mods += self._tab_func('Detect')
                mods += self.out_tab_disabled('Detect', False) + self.out_tab_disabled('Detections', False) + self.enabled_classes.out_options(classes)

            return self.sensitivity.out_value(self.project_config['detection_sensitivity']) + self.model_sensitivity.out_value(self.project_config['detection_sensitivity']) + self.enabled_classes.out_value(self.project_config['enabled_classes']) + self.trigger_classes.out_options(self.project_config['enabled_classes']) + self.trigger_classes.out_value(self.project_config['trigger_classes']) + mods

    def _close_project(self):
        self._stop_grab_thread()
        if self.detector and isinstance(self.detector, kritter.KimageDetectorThread):
            self.detector.close()
        if self.detector_process:
            self.detector_process.close()
        if self.store_media:
            self.store_media.close()

    def _update_train_state(self):
        self.kapp.push_mods(self.train_button.out_spinner_disp(True))
        mods = []
        g_train_file = os.path.join(self.project_gdrive_dir, TRAIN_FILE)
        try:
            train_url = self.gdrive_interface.get_url(g_train_file)
        except:
            train_url = None
        mods += self.train_button.out_spinner_disp(False) 
        if train_url:
            mods += self.train_button.out_url(train_url) + self.train_button.out_disabled(False) + self.download_button.out_disabled(False)
        else:
            mods += self.train_button.out_disabled(True) + self.download_button.out_disabled(True)

        return mods

    def _update_classes(self):
        if not self.training_grid.images_and_data:
            self.training_grid.update_images_and_data()
        classes = set()
        for i, data in self.training_grid.images_and_data:
            try:
                for d in data['defs']:
                    classes.add(d['class'])
            except KeyError:
                pass
        self.classes = sorted(classes, key=str.lower)

    def _create_settings_dialog(self):
        style = {"label_width": 5, "control_width": 5}
        self.sensitivity = kritter.Kslider(name="Detection sensitivity", mxs=(1, 100, 1), format=lambda val: f'{int(val)}%', style=style)
        self.enabled_classes = kritter.Kchecklist(name="Enabled classes", clear_check_all=True, scrollable=True, style=style)
        self.trigger_classes = kritter.Kchecklist(name="Trigger classes", clear_check_all=True, scrollable=True, style=style)
        smooth_video = kritter.Kcheckbox(name="Smooth video", value=self.app_config['smooth_video'], style=style)
        tracking = kritter.Kcheckbox(name="Tracking", value=self.app_config['tracking'], style=style)
        upload = kritter.Kcheckbox(name="Upload to Google Photos", value=self.app_config['gphoto_upload'] and self.gphoto_interface is not None, disabled=self.gphoto_interface is None or not self.app_config['tracking'], style=style)
        layout = [self.sensitivity, self.enabled_classes, self.trigger_classes, smooth_video, tracking, upload]
        self.settings_dialog = kritter.Kdialog(title=[kritter.Kritter.icon("gear"), "Settings"], layout=layout)

        @self.sensitivity.callback()
        def func(value):
            self.project_config['detection_sensitivity'] = value
            self._set_threshold() 
            self.project_config.save()

        @self.enabled_classes.callback()
        def func(value):
            # value list comes in unsorted -- let's sort to make it more human-readable
            value.sort(key=lambda c: c.lower())
            self.project_config['enabled_classes'] = value
            # Find trigger classes that are part of enabled classes            
            self.project_config['trigger_classes'] = [c for c in self.project_config['trigger_classes'] if c in value]
            self.project_config.save()
            return self.trigger_classes.out_options(value) + self.trigger_classes.out_value(self.project_config['trigger_classes'])

        @self.trigger_classes.callback()
        def func(value):
            self.project_config['trigger_classes'] = value
            self.project_config.save()

        @smooth_video.callback()
        def func(value):
            self.app_config['smooth_video'] = value  
            self.app_config.save()
            return self._open_project()

        @tracking.callback()
        def func(value):
            self.app_config['tracking'] = value  
            self.app_config.save()
            return self._open_project(False) + self.media_queue.out_disp(value) + upload.out_disabled(not value)

        @upload.callback()
        def func(value):
            self.app_config['gphoto_upload'] = value  
            self.store_media.store_media = self.gphoto_interface if value else None
            self.app_config.save()

        return self.settings_dialog


    def _create_dets_image_dialog(self):
        self.dets_dialog_image = kritter.Kimage(overlay=True, service=None)
        delete_button = kritter.Kbutton(name=[kritter.Kritter.icon("trash"), "Delete"], service=None)
        copy_button = kritter.Kbutton(name=[kritter.Kritter.icon("copy"), "Copy image to training set"], service=None)
        copy_button.append(delete_button)
        self.dets_image_dialog = kritter.Kdialog(title="", layout=self.dets_dialog_image, left_footer=copy_button, size="xl")

        @copy_button.callback()
        def func():
            new_filename = kritter.date_stamped_file("jpg")
            new_filename_fullpath = os.path.join(self.project_training_dir, new_filename)
            new_data = {"defs": [], "width": self.select_kimage.data["width"], "height": self.select_kimage.data["height"]}
            os.system(f"cp '{self.select_kimage.fullpath}' '{new_filename_fullpath}'")
            kritter.save_metadata(new_filename_fullpath, new_data)
            self.select_kimage.data['copy'] = new_filename
            kritter.save_metadata(self.select_kimage.fullpath, self.select_kimage.data)
            return copy_button.out_name("Copied") + copy_button.out_disabled(True)

        @delete_button.callback()
        def func():
            try:
                os.remove(self.select_kimage.fullpath)
                os.remove(kritter.get_metadata_filename(self.select_kimage.fullpath))
            except:
                pass
            return self.dets_grid.out_images(True) + self.dets_image_dialog.out_open(False)

        @self.dets_image_dialog.callback_view()
        def func(state):
            if state:
                if 'copy' in self.select_kimage.data and os.path.exists(os.path.join(self.project_training_dir, self.select_kimage.data['copy'])):
                    return copy_button.out_name("Copied") + copy_button.out_disabled(True)
                else:
                    return copy_button.out_name("Copy image to training set") + copy_button.out_disabled(False)                   

        return self.dets_image_dialog

    def _create_training_image_dialog(self):
        self.training_dialog_image = kritter.Kimage(overlay=True, service=None)
        delete_button = kritter.Kbutton(name=[kritter.Kritter.icon("trash"), "Delete"], service=None)
        clear_button = kritter.Kbutton(name=[kritter.Kritter.icon("close"), "Clear labels"])
        clear_button.append(delete_button)
        self.save_button = kritter.Kbutton(name=[kritter.Kritter.icon("save"), "Save"], disabled=True, service=None)
        self.training_image_dialog = kritter.Kdialog(title="", layout=self.training_dialog_image, close_button=[kritter.Kritter.icon("close"), "Cancel"], left_footer=clear_button, right_footer=self.save_button, size="xl")

        @self.save_button.callback()
        def func():
            kritter.save_metadata(self.select_kimage.fullpath, self.select_kimage.data)
            return self.training_grid.render(self.select_kimage, self.select_kimage.data, 0.33) + self.training_image_dialog.out_open(False)

        @clear_button.callback()
        def func():
            self.training_dialog_image.overlay.draw_clear()
            self.select_kimage.data['defs'] = []
            return self.training_dialog_image.overlay.out_draw() + self.save_button.out_disabled(False)

        @delete_button.callback()
        def func():
            try:
                os.remove(self.select_kimage.fullpath)
                os.remove(kritter.get_metadata_filename(self.select_kimage.fullpath))
            except:
                pass
            return self.training_grid.out_images(True) + self.training_image_dialog.out_open(False)

        @self.training_dialog_image.overlay.callback_draw()
        def func(shape):
            self.select_box = [shape['x0'], shape['y0'], shape['x1'], shape['y1']]
            return self.label_dialog.out_open(True)

        @self.training_image_dialog.callback_view()
        def func(state):
            if not state:
                return self.save_button.out_disabled(True) 

        return self.training_image_dialog

    def _create_test_image_dialog(self):
        self.test_dialog_image = kritter.Kimage(overlay=True, service=None)
        self.test_image_dialog = kritter.Kdialog(title="", layout=self.test_dialog_image, size="xl")

        @self.training_image_dialog.callback_view()
        def func(state):
            if not state:
                return self.save_button.out_disabled(True) 

        return self.test_image_dialog

    def _create_label_dialog(self):
        self.class_select = kritter.KdropdownMenu(name="Class name")
        self.class_textbox = kritter.KtextBox()
        self.class_select.append(self.class_textbox)
        self.add_button = kritter.Kbutton(name=[kritter.Kritter.icon("plus"), "Add"], disabled=True, service=None)
        self.label_dialog = kritter.Kdialog(title="Label", right_footer=self.add_button, close_button=[kritter.Kritter.icon("close"), "Cancel"], layout=self.class_select)

        @self.add_button.callback(self.class_textbox.state_value())
        def func(class_textbox):
            mods = []
            class_textbox = class_textbox.strip()
            if class_textbox not in self.classes:
                self.classes.append(class_textbox)
                self.classes.sort(key=str.lower)
                mods += self.class_select.out_options(self.classes)

            def_ = {'class': class_textbox, 'box': self.select_box}
            try:
                self.select_kimage.data['defs'].append(def_)
            except KeyError:
                self.select_kimage.data['defs'] = [def_]
            mods += self.training_grid.render(self.training_dialog_image, self.select_kimage.data, 0.5)
            return mods + self.save_button.out_disabled(False) + self.label_dialog.out_open(False)

        @self.class_select.callback()
        def func(val):
            return self.class_textbox.out_value(self.classes[val])

        @self.label_dialog.callback_view()
        def func(state):
            if not state:
                return self.class_textbox.out_value("") + self.add_button.out_disabled(True) + self.training_grid.render(self.training_dialog_image, self.select_kimage.data, 0.33)

        @self.class_textbox.callback()
        def func(val):
            return self.add_button.out_disabled(not bool(val.strip()))

        return self.label_dialog

    def _create_train_dialog(self):
        # Create train dialog
        self.upload_button = kritter.Kbutton(name=[kritter.Kritter.icon("cloud-upload"), "Upload training data"], spinner=True, )
        self.train_button = kritter.Kbutton(name=[kritter.Kritter.icon("train"), "Train"], spinner=True, target="_blank", external_link=True)
        self.download_button = kritter.Kbutton(name=[kritter.Kritter.icon("cloud-download"), "Download network"], spinner=True)
        self.upload_button.append(self.train_button)
        self.upload_button.append(self.download_button)
        self.train_status = kritter.Ktext(style={"control_width": 8})
        train_layout = [self.upload_button, self.train_status]
        self.train_dialog = kritter.Kdialog(title=[kritter.Kritter.icon("train"), "Train"], layout=train_layout, shared=True)

        @self.train_dialog.callback_view()
        def func(state):
            if state:
                return self._update_train_state()
            else:
                return self.train_status.out_value("")

        @self.upload_button.callback()
        def func():
            return self._prepare()

        @self.download_button.callback()
        def func():
            self.kapp.push_mods(self.download_button.out_spinner_disp(True) + self.train_status.out_value("Downloading..."))
            g_model = os.path.join(self.project_gdrive_dir, self.app_config['project']+".tflite")
            model = os.path.join(self.current_project_dir, self.app_config['project']+".tflite")
            try:
                mods = []
                self.gdrive_interface.copy_from(g_model, model)
                if self.latest_model!="" and filecmp.cmp(model, self.latest_model):
                    message = "Model file is up to date."  
                else: 
                    message = "Download success!"
                    self._install_next_model(model)
                    mods += self._open_project()

                return self.train_status.out_value(message) + self.download_button.out_spinner_disp(False) + mods
            except Exception as e:
                return self.train_status.out_value(f'Unable to download. ("{e}")') + self.download_button.out_spinner_disp(False)

        return self.train_dialog

    def _install_next_model(self, model):
        # rename/copy model files
        next_model_base = self.next_model()
        next_model = f'{os.path.join(self.project_models_dir, next_model_base)}.tflite' 
        os.system(f"mv '{model}' '{next_model}'")
        model_info = kritter.file_basename(model)+".json"
        next_model_info = f'{os.path.join(self.current_project_dir, next_model_base)}.json' 
        os.system(f"cp '{model_info}' '{next_model_info}'")
        # copy model files back to gdrive
        g_next_model = f'{os.path.join(self.project_gdrive_models_dir, next_model_base)}.tflite'
        g_next_model_info = f'{os.path.join(self.project_gdrive_models_dir, next_model_base)}.json'
        try:
            self.gdrive_interface.copy_to(next_model, g_next_model, True)
            self.gdrive_interface.copy_to(next_model_info, g_next_model_info, True)
        except Exception as e:
            print("Unable to copy models to gdrive:", e)
        # annotate train and validation files
        train_images = glob.glob(os.path.join(self.current_project_dir, "tmp", "train", "*.jpg"))
        train_images = [os.path.basename(i) for i in train_images]
        validate_images = glob.glob(os.path.join(self.current_project_dir, "tmp", "validate", "*.jpg")) 
        validate_images = [os.path.basename(i) for i in validate_images]

        next_model = os.path.basename(next_model)
        for i in train_images:
            i = os.path.join(self.project_training_dir, i)
            data = defaultdict(list, kritter.load_metadata(i))
            if next_model not in data['train']:
                data['train'].append(next_model)
                kritter.save_metadata(i, data)
        for i in validate_images:
            i = os.path.join(self.project_training_dir, i)
            data = defaultdict(list, kritter.load_metadata(i))
            if next_model not in data['validate']:
                data['validate'].append(next_model)
                kritter.save_metadata(i, data)

    def get_projects(self, exclude_current):
        plist = glob.glob(os.path.join(self.project_dir, '*', 'project.json'))
        plist = [os.path.basename(os.path.dirname(i)) for i in plist]
        if exclude_current:
            plist.remove(self.app_config['project'])
        plist.sort(key=str.lower)
        return plist

    def get_models(self):
        mlist = glob.glob(os.path.join(self.project_models_dir, '*.tflite'))
        mlist = [i for i in mlist if model_index(i)>0]
        mlist.sort(key=str.lower, reverse=True)
        return mlist

    def next_model(self):
        next_index = 1 if self.latest_model is None else model_index(self.latest_model)+1
        return f"{self.app_config['project']}_{next_index:02d}"

    def _create_open_project_dialog(self):             
        self.open_project_dialog = OpenProjectDialog(self.get_projects)
        @self.open_project_dialog.callback_project()
        def func(project, delete):
            if delete:
                os.system(f"rm -rf '{os.path.join(self.project_dir, project)}'")
                return []
            else:
                self.app_config['project'] = project
                self.app_config.save()
                return self._open_project()
        return self.open_project_dialog 

    def _create_new_project_dialog(self):
        self.new_project_dialog = NewSaveAsDialog(self.get_projects)
        @self.new_project_dialog.callback_project()
        def func(project):
            self.app_config['project'] = project
            self.app_config.save()
            return self._open_project()
        return self.new_project_dialog 

    def _infer_helper(self, detector, index, grid, images_and_data):
        res = False
        for image, data in images_and_data:
            if not self.run_model[index]:
                return False
            with self.data_lock:
                try:
                    if data['tmp']['dets'][index] is not None:
                        continue
                except KeyError:
                    pass
            res = True
            image = cv2.imread(os.path.join(grid.media_dir, image))
            dets = detector.detect(image, self.model_threshold)
            with self.data_lock:
                if 'tmp' not in data:
                    data['tmp'] = {}
                if 'dets' not in data['tmp']:
                    data['tmp']['dets'] = {}
                data['tmp']['dets'][index] = dets
        if res:
            print("** inferred")
        return res

    def _run_model(self, index, grid, reset):
        print("*** starting", index)
        self.kapp.push_mods(self.model_menus[index].out_spinner_disp(True) + [Output(self.model_legends[index].id, "style", {"display": "none"})])
        disp = "none" if self.model_menus[index].value is None else "block"
        mods = self.model_menus[index].out_spinner_disp(False) + [Output(self.model_legends[index].id, "style", {"display": disp})]
        # reset dets
        if reset:
            print("*** reset", index, self.model_menus[index].value, grid)
            self._reset_model_info(index, grid)
        model = self.model_menus[index].value
        if model is not None:
            model = os.path.join(self.project_models_dir, model)
            detector = TFliteDetector(model)
            print("*** start inferring", index)
            if self._infer_helper(detector, index, grid, grid.page_images_and_data):
                print("*** done page, inferring rest", index)
                self.kapp.push_mods(grid.out_images() + mods)
                self._infer_helper(detector, index, grid, grid.images_and_data)
            else:
                self.kapp.push_mods(mods)
        else:
            print("*** model is none", index)
            self.kapp.push_mods(grid.out_images() + mods)
        print("*** done", index)

    def _infer_test_model(self, index, grid, reset=False):
        self._stop_model(index)
        with self.run_model_lock[index]:
            # run thread
            self.run_model[index] = True
            self.run_model_thread[index] = Thread(target=self._run_model, args=(index, grid, reset))
            self.run_model_thread[index].start()

    def _stop_model(self, index):
        with self.run_model_lock[index]:
            if self.run_model_thread[index]:
                self.run_model[index] = False
                self.run_model_thread[index].join()

    def _infer_test_models(self, reset=False):
        for i, m in enumerate(self.model_menus):
            if m.value is not None:
                self._infer_test_model(i, self.training_grid, reset)

    def _reset_model_info(self, index, grid):
        with self.data_lock:
            for _, data in grid.images_and_data:
                try:
                    data['tmp']['dets'][index] = None
                except KeyError:
                    pass    

    def _model_menu_func(self, index):
        def func(value):
            mods = []
            if self.tab=='Detections':
                self._infer_test_model(index, self.dets_grid, True)
            else:
                self._infer_test_model(index, self.training_grid, True)
            if value is None:
                return

            if index<len(self.model_menus)-1:
                # Create a set of options that haven't been selected yet
                options = [os.path.basename(m) for m in self.models]
                for i in range(index+1):
                    options.remove(self.model_menus[i].value)  
                if options: # don't bother if there are no more left
                    mods += self.model_menus[index+1].out_options(options) + self.model_menus[index+1].out_value(None) + self.model_menus[index+1].out_disp(True)
                for i in range(index+2, len(self.model_menus)):
                    mods += self.model_menus[i].out_disp(False) + self.model_menus[index+1].out_value(None)
            return mods
        return func

    def _reset_model_menus(self):
        models = [os.path.basename(m) for m in self.models]
        return self.model_menus[0].out_disp(True) + self.model_menus[0].out_value(models[0]) + self.model_menus[0].out_options(models)

    def _create_tabs(self):
        # Create video component and histogram enable.
        self.video = kritter.Kvideo(width=self.camera.resolution[0], overlay=True)
        brightness = kritter.Kslider(name="Brightness", value=self.camera.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style={"control_width": 4}, grid=False)
        self.media_queue =  MediaDisplayQueue(None, STREAM_WIDTH, CAMERA_WIDTH, self.config_consts.MEDIA_QUEUE_IMAGE_WIDTH, self.config_consts.IMAGES_DISPLAY, disp=self.app_config['tracking']) 
        self.capture_queue =  MediaDisplayQueue(None, STREAM_WIDTH, CAMERA_WIDTH, self.config_consts.MEDIA_QUEUE_IMAGE_WIDTH, self.config_consts.IMAGES_DISPLAY) 
        self.take_picture_button = kritter.Kbutton(name=[kritter.Kritter.icon("camera"), "Take picture"], service=None, spinner=True)
        self.dets_grid = MediaDisplayGrid(None, label_func=lambda key, det : f"{det['class']} {det['score']*100:.0f}%")
        colors = [[255, 0, 0, 0.5], [0, 255, 0, 0.5]] 

        def data_func(data):
            if self.test_models:
                texts = ['', '']
                dets = []
                timestamps = ['' for i in range(MODEL_MENUS)]
                for k, v in data['tmp']['dets'].items():
                    if v is not None:
                        if 'train' in data and self.model_menus[k].value in data['train']:
                            texts[k] = 'train'
                        elif 'validate' in data and self.model_menus[k].value in data['validate']:
                            texts[k] = 'validate'  
                        else:
                            texts[k] = 'none'
                        for det in v:
                            dets.append({**det, 'color': colors[k]})
                text = f"{texts[0]}, {texts[1]}" if texts[1] else texts[0] 
                return {'width': data['width'], 'height': data['height'], 'dets': dets, 'timestamp': text}
            else:
                return {'width': data['width'], 'height': data['height'], 'dets': data['defs']}

        def label_func(key, det):
            if self.test_models:
                return f"{det['class']} {det['score']*100:.0f}%" 
            else:
                return det['class']
        
        self.training_grid = MediaDisplayGrid(None, data_func=data_func, label_func=label_func)
        self.test_model_checkbox = kritter.Kcheckbox(name="Test models", grid=False, value=False)
        self.model_menus = [kritter.Kdropdown(name="", grid=False, placeholder="Select model", spinner=True) for i in range(MODEL_MENUS)]
        self.model_legends = [html.Div(html.Div(style={"margin": "10px", "width": "20px", "height": "20px", "background-color": f"rgba({colors[i][0]}, {colors[i][1]}, {colors[i][2]}, {colors[i][3]}"}), id=self.kapp.new_id(), style={'display': 'none'}) for i in range(MODEL_MENUS)]
        for i, m in enumerate(self.model_menus):
            m.cols.append(self.model_legends[i])
        self.model_sensitivity = kritter.Kslider(name="Detection sensitivity", mxs=(1, 100, 1), format=lambda val: f'{int(val)}%', updatemode='mouseup', grid=False, style={"control_width": 3})
        reset_button = kritter.Kbutton(name=[kritter.Kritter.icon("close"), "Reset"])
        self.test_collapse = dbc.Collapse(dbc.Card([self.model_sensitivity] + self.model_menus + [reset_button]), id=self.kapp.new_id())
        for i, m in enumerate(self.model_menus):
            m.callback()(self._model_menu_func(i))

        self.run_model_thread = [None for i in range(MODEL_MENUS)]
        self.run_model = [True for i in range(MODEL_MENUS)]
        self.run_model_lock = [Lock() for i in range(MODEL_MENUS)]
        self.data_lock = Lock()

        @self.test_model_checkbox.callback()
        def func(state):
            self.test_models = state
            if state:
                return self._reset_model_menus() + [Output(self.test_collapse.id, "is_open", True)] 
            else:
                for i, m in enumerate(self.model_menus):
                    self._stop_model(i)
                return self.training_grid.out_images() + [Output(self.test_collapse.id, "is_open", False)] 

        @self.model_sensitivity.callback()
        def func(val):
            self.sensitivity_range.inval = val
            threshold = self.sensitivity_range.outval
            self.model_threshold = threshold - THRESHOLD_HYSTERESIS
            if self.model_threshold<MIN_THRESHOLD:
                self.model_threshold = MIN_THRESHOLD  
            self._infer_test_models(True)


        @reset_button.callback()
        def func():
            return self._reset_model_menus()
                       
        # There are some challenges with tabs and their layouts.  Many of the tabs share layout
        # components, but not consistently (as with motionscope).  You can't have the same 
        # component more than once in a given layout, so we necessarily need to chop up the layout
        # and define which pieces go in which tab.  
        self.layouts['video'] = self.video 
        self.layouts['media_queue'] = self.media_queue.layout
        self.layouts['capture_queue'] = self.capture_queue.layout
        self.layouts['brightness'] = brightness
        self.layouts['take_picture'] = self.take_picture_button
        self.layouts['dets_grid'] = self.dets_grid.layout
        self.layouts['training_grid'] = self.training_grid.layout
        self.layouts['test_model'] = [self.test_model_checkbox, self.test_collapse]

        def detect_open():
            self._run_grab_thread()
            return self.media_queue.out_images()
            
        def capture_open():
            self._run_grab_thread()
            self.video.overlay.draw_clear()
            return self.video.overlay.out_draw() + self.capture_queue.out_images()

        def training_set_open():
            self._stop_grab_thread()
            self.stream.stop()
            self._update_classes()
            return self.class_select.out_options(self.classes) + self.training_grid.out_images(True)

        def training_set_close():
            for i, m in enumerate(self.model_menus):
                self._stop_model(i)

        # Tabs might want to be encapsulated in their own Tab superclass/subclass and then 
        # instantiated and put in a list or dict, but this (below) is a simpler solution (for now).
        # There is also a good amount of sharing of data/components between tabs, so putting
        # tabs in separate classes solves some problems but creates others. 
        self.tabs['Detect'] = {
            LAYOUT: ['video', 'media_queue', 'brightness'],
            OPEN: detect_open
        }

        self.tabs['Detections'] = {
            LAYOUT: ['dets_grid'],
            OPEN: lambda : self.dets_grid.out_images(True)
        }

        self.tabs['Capture'] = {
            LAYOUT: ['video', 'capture_queue', 'brightness', 'take_picture'],
            OPEN: capture_open
        }

        self.tabs['Training set'] = {
            LAYOUT: ['training_grid', 'test_model'],
            OPEN: training_set_open,
            CLOSE: training_set_close
        }

        @self.dets_grid.callback_click()
        def func(kimage):
            self.select_kimage = kimage
            try:
                title = kimage.data['timestamp']
            except:
                title = kimage.path 
            return self.dets_dialog_image.out_src(kimage.path) + self.dets_image_dialog.out_title(title) + self.dets_image_dialog.out_open(True) + self.dets_grid.render(self.dets_dialog_image, kimage.data, scale=0.5)

        @self.training_grid.callback_click()
        def func(kimage):
            self.select_kimage = kimage
            try:
                title = kimage.data['timestamp']
            except:
                title = kimage.path 
            if self.test_models:
                return self.test_dialog_image.out_src(kimage.path) + self.test_image_dialog.out_title(title) + self.test_image_dialog.out_open(True) + self.training_grid.render(self.test_dialog_image, kimage.data, scale=0.5)
            else:
                self.training_dialog_image.overlay.draw_user("rect")
                return self.training_dialog_image.out_src(kimage.path) + self.training_image_dialog.out_title(title) + self.training_image_dialog.out_open(True) + self.training_grid.render(self.training_dialog_image, kimage.data, scale=0.5)

        @self.training_grid.callback_render()
        def func():
            self._infer_test_models()

        @brightness.callback()
        def func(value):
            self.app_config['brightness'] = value
            self.camera.brightness = value
            self.app_config.save()

        @self.take_picture_button.callback()
        def func():
            self.kapp.push_mods(self.take_picture_button.out_spinner_disp(True))
            filename = os.path.join(self.project_training_dir, kritter.date_stamped_file("jpg"))
            data = {"defs": [], "width": self.frame.shape[1], "height": self.frame.shape[0]}
            cv2.imwrite(filename, self.frame)
            kritter.save_metadata(filename, data)
            return self.capture_queue.out_images() + self.take_picture_button.out_spinner_disp(False)

    def _set_threshold(self):
        self.sensitivity_range.inval = self.project_config['detection_sensitivity']
        threshold = self.sensitivity_range.outval
        if self.tracker:
            self.tracker.setThreshold(threshold)
        self.low_threshold = threshold - THRESHOLD_HYSTERESIS
        if self.low_threshold<MIN_THRESHOLD:
            self.low_threshold = MIN_THRESHOLD 

    def _timestamp(self):
        return datetime.datetime.now().strftime("%a %H:%M:%S")

    def _run_grab_thread(self):
        # Run camera grab thread.
        if self._grab_thread is None:    
            self.run_thread = True
            self._grab_thread = Thread(target=self.grab_thread)
            self._grab_thread.start()

    def _stop_grab_thread(self):
        # Stop camera grab thread.
        if self._grab_thread is not None:
            self.run_thread = False
            self._grab_thread.join()
            self._grab_thread = None

    # Frame grabbing thread
    def grab_thread(self):
        print("**** starting thread")
        last_tag = ""
        while self.run_thread:
            mods = []
            # Get frame
            self.frame = self.stream.frame()[0]
            if self.tab=="Detect":
                timestamp = self._timestamp()
                # Handle daytime/nighttime logic
                daytime, change = self.daytime.is_daytime(self.frame)
                if change:
                    if daytime:
                        handle_event(self, {"event_type": 'daytime'})
                    else:
                        handle_event(self, {"event_type": 'nighttime'})
                # Handle video tag
                tag =  f"{timestamp} daytime" if daytime else  f"{timestamp} nighttime"
                if tag!=last_tag:
                    self.video.overlay.draw_clear(id="tag")
                    self.video.overlay.draw_text(0, self.frame.shape[0]-1, tag, fillcolor="black", font=dict(family="sans-serif", size=12, color="white"), xanchor="left", yanchor="bottom", id="tag")
                    mods += self.video.overlay.out_draw()
                    last_tag = tag

            if self.detector and self.tab=="Detect" and daytime:
                # Get raw detections from detector thread
                detect = self.detector.detect(self.frame, self.low_threshold)
            else:
                detect = []
            if detect is not None:
                if isinstance(detect, tuple):
                    dets, det_frame = detect 
                else:
                    dets, det_frame = detect, self.frame
                # Remove classes that aren't active
                dets = self._filter_dets(dets)

                # Feed detections into tracker
                if self.tracker:
                    dets = self.tracker.update(dets, showDisappeared=True)
                # Render tracked detections to overlay
                mods += kritter.render_detected(self.video.overlay, dets)
                # Update picker
                if self.picker:
                    mods += self._handle_picks(det_frame, dets)

            # Send frame
            self.video.push_frame(self.frame)

            try:
                self.kapp.push_mods(mods)
            except:
                pass

            # Sleep to give other threads a boost 
            time.sleep(0.01)
        print("**** stopping thread")

    def _handle_picks(self, frame, dets):
        picks = self.picker.update(frame, dets)
        # Get regs (new entries) and deregs (deleted entries)
        regs, deregs = self.picker.get_regs_deregs()
        if regs:
            handle_event(self, {'event_type': 'register', 'dets': regs})
        if picks:
            for i in picks:
                image, data = i[0], i[1]
                # Save picture and metadata, add width and height of image to data so we don't
                # need to decode it to set overlay dimensions.
                timestamp = self._timestamp()
                _data = {'dets': [data], 'width': image.shape[1], 'height': image.shape[0], "timestamp": timestamp}
                self.store_media.store_image_array(image, album=self.config_consts.GPHOTO_ALBUM, data=_data)
                if data['class'] in self.project_config['trigger_classes']:
                    event = {**data, 'image': image, 'event_type': 'trigger', "timestamp": timestamp}
                    handle_event(self, event)
            if deregs:    
                handle_event(self, {'event_type': 'deregister', 'deregs': deregs})
            return self.media_queue.out_images()
        return []       

    def _filter_dets(self, dets):
        dets = [det for det in dets if det['class'] in self.project_config['enabled_classes']]
        return dets


if __name__ == "__main__":
    ObjectDetector()
