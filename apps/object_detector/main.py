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
import cv2
import time
import json
import datetime
import random
import numpy as np
from threading import Thread
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

CONFIG_FILE = "object_detector.json"
CONSTS_FILE = "object_detector_consts.py"
GDRIVE_DIR = "/vizy/object_detector"
TRAIN_FILE = "train_detector.ipynb"
TRAINING_SET_FILE = "training_set.zip"
CNN_FILE = "detector.tflite"

DEFAULT_CONFIG = {
    "brightness": 50,
    "detection_sensitivity": 50,
    "enabled_classes": None,
    "trigger_classes": [],
    "gphoto_upload": False
}

BASEDIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(BASEDIR, "media")


class MediaDisplayGrid:
    def __init__(self, media_dir, kapp=None):
        self.images_and_data = []
        self.classes = []
        self.page = 0
        self.pages = 0
        self.rows = 4
        self.cols = 4
        self.media_dir = media_dir
        self.kapp = kritter.Kritter.kapp if kapp is None else kapp
        self.kapp.media_path.insert(0, self.media_dir)
        self.begin_button = kritter.Kbutton(name=kritter.Kritter.icon("angle-double-left", padding=0))
        self.prev_button = kritter.Kbutton(name=kritter.Kritter.icon("angle-left", padding=0))
        self.next_button = kritter.Kbutton(name=kritter.Kritter.icon("angle-right", padding=0))
        self.end_button = kritter.Kbutton(name=kritter.Kritter.icon("angle-double-right", padding=0))
        self.status = kritter.Ktext()
        self.begin_button.append(self.prev_button)
        self.begin_button.append(self.next_button)
        self.begin_button.append(self.end_button)
        self.begin_button.append(self.status)
        self.dialog_image = kritter.Kimage(overlay=True, service=None)
        self.delete_button = kritter.Kbutton(name=[kritter.Kritter.icon("trash"), "Delete"], service=None)
        self.clear_button = kritter.Kbutton(name=[kritter.Kritter.icon("close"), "Clear labels"])
        self.delete_button.append(self.clear_button)
        self.save_button = kritter.Kbutton(name=[kritter.Kritter.icon("save"), "Save"], disabled=True, service=None)
        self.image_dialog = kritter.Kdialog(title="", layout=self.dialog_image, close_button=[kritter.Kritter.icon("close"), "Cancel"], left_footer=self.delete_button, right_footer=self.save_button, size="xl")

        self.class_select = kritter.KdropdownMenu(name="Class name")
        self.class_textbox = kritter.KtextBox()
        self.class_select.append(self.class_textbox)
        self.add_button = kritter.Kbutton(name=[kritter.Kritter.icon("plus"), "Add"], disabled=True, service=None)
        self.label_dialog = kritter.Kdialog(title="Label", right_footer=self.add_button, close_button=[kritter.Kritter.icon("close"), "Cancel"], layout=self.class_select)

        self.layout = html.Div([html.Div(self.begin_button), html.Div(self._create_images()), self.image_dialog, self.label_dialog])

        @self.add_button.callback(self.class_textbox.state_value())
        def func(class_textbox):
            mods = []
            class_textbox = class_textbox.strip()
            if class_textbox not in self.classes:
                self.classes.append(class_textbox)
                self.classes.sort(key=str.lower)
                mods += self.class_select.out_options(self.classes)

            det = {'class': class_textbox, 'box': self.select_box}
            try:
                self.select_kimage.data['dets'] = [{'class': self.select_kimage.data['class'], 'box': self.select_kimage.data['box']}, det]
            except:
                self.select_kimage.data['dets'].append(det)
            mods += self._render_dets(self.dialog_image.overlay, self.select_kimage.data, 0.5)
            return mods + self.save_button.out_disabled(False) + self.label_dialog.out_open(False)

        @self.save_button.callback()
        def func():
            kritter.save_metadata(self.select_kimage.fullpath, self.select_kimage.data)
            return self._render_dets(self.select_kimage.overlay, self.select_kimage.data, 0.33) + self.image_dialog.out_open(False)

        @self.label_dialog.callback_view()
        def func(state):
            if not state:
                return self.class_textbox.out_value("") + self.add_button.out_disabled(True) + self._render_dets(self.dialog_image.overlay, self.select_kimage.data, 0.33)

        @self.image_dialog.callback_view()
        def func(state):
            if not state:
                self.select_kimage.data = kritter.load_metadata(self.select_kimage.fullpath)
                return self.save_button.out_disabled(True)

        @self.class_textbox.callback()
        def func(val):
            return self.add_button.out_disabled(not bool(val.strip()))

        @self.begin_button.callback()
        def func():
            self.page = 0
            return self.out_images()

        @self.prev_button.callback()
        def func():
            self.page -= 1
            return self.out_images()

        @self.next_button.callback()
        def func():
            self.page += 1
            return self.out_images()

        @self.end_button.callback()
        def func():
            self.page = self.pages-1
            return self.out_images()

        @self.clear_button.callback()
        def func():
            self.dialog_image.overlay.draw_clear()
            self.select_kimage.data['dets'] = []
            return self.dialog_image.overlay.out_draw() + self.save_button.out_disabled(False)

        @self.delete_button.callback()
        def func():
            try:
                os.remove(self.select_kimage.fullpath)
                os.remove(kritter.file_basename(self.select_kimage.fullpath)+".json")
            except:
                pass
            return self.out_images() + self.image_dialog.out_open(False)

        @self.dialog_image.overlay.callback_draw()
        def func(shape):
            self.select_box = [shape['x0'], shape['y0'], shape['x1'], shape['y1']]
            return self.label_dialog.out_open(True)

        @self.class_select.callback()
        def func(val):
            return self.class_textbox.out_value(self.classes[val])

    def _render_dets(self, overlay, data, scale):
        try:
            overlay.update_resolution(width=data['width'], height=data['height'])
            if 'class' in data:
                kritter.render_detected(overlay, [data], label_format=lambda key, det : det['class'], scale=scale)
            else:
                kritter.render_detected(overlay, data['dets'], label_format=lambda key, det : det['class'], scale=scale)
        except:
            overlay.draw_clear()

        return overlay.out_draw()

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
                            title = _kimage.path 
                            _kimage.fullpath = os.path.join(BASEDIR, self.media_dir, _kimage.path)
                            if not _kimage.data:
                                height, width, _ = cv2.imread(_kimage.fullpath).shape
                                _kimage.data['dets'] = []
                                _kimage.data['width'] = width  
                                _kimage.data['height'] = height
                            self.select_kimage = _kimage
                            try:
                                title = f"{_kimage.data['timestamp']}, {title}"
                            except:
                                pass
                            mods += self.dialog_image.out_src(_kimage.path) + self.image_dialog.out_title(title) + self.image_dialog.out_open(True)
                            self.dialog_image.overlay.draw_user("rect")
                            mods += self._render_dets(self.dialog_image.overlay, _kimage.data, scale=0.5)
                        return mods
                    return func_

                kimage.callback()(func(kimage))
                row.append(col)
            children.append(dbc.Row(row, justify="start", className="_nopadding"))
        return children

    def _update_classes(self):
        files = os.listdir(self.media_dir)
        files = [i for i in files if i.endswith(".json")]
        classes = set()
        for f in files:
            with open(os.path.join(self.media_dir, f)) as file:
                data = json.load(file)
            try:
                classes.add(data['class'])
            except:
                for d in data['dets']:
                    classes.add(d['class'])
        self.classes = sorted(classes, key=str.lower)

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
        self._update_classes()

    def out_images(self):
        self.update_images_and_data()
        mods = self.class_select.out_options(self.classes)
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
        mods += self.status.out_value(f"Page {self.page+1} of {self.pages}")

        offset = self.page*self.rows*self.cols
        for i in range(self.rows*self.cols):
            if i+offset < len(self.images_and_data):
                image, data = self.images_and_data[i+offset]
                self.images[i].path = image
                self.images[i].data = data
                self.images[i].overlay.draw_clear()
                try:
                    mods += self.images[i].out_src(image)
                    mods += self._render_dets(self.images[i].overlay, data, scale=0.33)
                    self.images[i].overlay.draw_text(0, data['height']-1, data['timestamp'], fillcolor="black", font=dict(family="sans-serif", size=12, color="white"), xanchor="left", yanchor="bottom")
                except:
                    pass
                mods += self.images[i].overlay.out_draw() + self.images[i].out_disp(True)
            else:
                mods += self.images[i].out_disp(False)
        return mods


def create_pvoc(filename, dets, resolution=None, out_filename=None, depth=3):
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
    for det in dets:
        text += \
f"""    <object>
        <name>{det["class"]}</name>
        <pose>Unspecified</pose>
        <truncated>0</truncated>
        <difficult>0</difficult>
        <bndbox>
            <xmin>{int(det["box"][0])}</xmin>
            <ymin>{int(det["box"][1])}</ymin>
            <xmax>{int(det["box"][2])}</xmax>
            <ymax>{int(det["box"][3])}</ymax>
        </bndbox>
    </object>
"""
    text += \
"""</annotation>
"""
    with open(out_filename, "w") as file:
        file.write(text)

VALIDATION_PERCENTAGE = 10
INIT = 0
LAYOUT = 1
OPEN = 2
CLOSE = 3

class ObjectDetector:
    def __init__(self):

        # Create Kritter server.
        self.kapp = Vizy()

        # Initialize variables
        self.project = None
        config_filename = os.path.join(self.kapp.etcdir, CONFIG_FILE)      
        self.config = kritter.ConfigFile(config_filename, DEFAULT_CONFIG)               
        consts_filename = os.path.join(BASEDIR, CONSTS_FILE) 
        self.config_consts = kritter.import_config(consts_filename, self.kapp.etcdir, ["IMAGES_KEEP", "IMAGES_DISPLAY", "PICKER_TIMEOUT", "MEDIA_QUEUE_IMAGE_WIDTH", "GPHOTO_ALBUM", "TRACKER_DISAPPEARED_DISTANCE", "TRACKER_MAX_DISAPPEARED"])     
        self.daytime = kritter.CalcDaytime(DAYTIME_THRESHOLD, DAYTIME_POLL_PERIOD)
        # Map 1 to 100 (sensitivity) to 0.9 to 0.1 (detection threshold)
        self.sensitivity_range = kritter.Range((1, 100), (0.9, 0.1), inval=self.config['detection_sensitivity']) 
        self.layouts = {}
        self.tabs = {}
        self.tab = "Detect"

        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream()
        self.camera.mode = CAMERA_MODE
        self.camera.brightness = self.config['brightness']
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
        self.project = "foo2"
        self.project_dir = os.path.join(BASEDIR, "projects", self.project)

        self.store_media = kritter.SaveMediaQueue(path=MEDIA_DIR, keep=self.config_consts.IMAGES_KEEP, keep_uploaded=self.config_consts.IMAGES_KEEP)
        if self.config['gphoto_upload']:
            self.store_media.store_media = self.gphoto_interface 
        self.tracker = kritter.DetectionTracker(maxDisappeared=self.config_consts.TRACKER_MAX_DISAPPEARED, maxDistance=self.config_consts.TRACKER_DISAPPEARED_DISTANCE)
        self.picker = kritter.DetectionPicker(timeout=self.config_consts.PICKER_TIMEOUT)
        #self.detector_process = kritter.Processify(TFliteDetector, (None, ))
        self.detector_process = kritter.Processify(TFliteDetector, (os.path.join(self.project_dir, CNN_FILE),))
        self.detector = kritter.KimageDetectorThread(self.detector_process)
        if self.config['enabled_classes'] is None:
            self.config['enabled_classes'] = self.detector_process.classes()
        self._set_threshold()

        self.create_tabs()

        self.file_menu = kritter.KdropdownMenu(name="File", options=[dbc.DropdownMenuItem("COCO"), dbc.DropdownMenuItem("Custom")], nav=True, item_style={"margin": "0px", "padding": "0px 10px 0px 10px"})
        nav_items = [dbc.NavItem(dbc.NavLink(i, active=i==self.tab, id=i+"nav")) for i in self.tabs]
        nav_items = [self.file_menu.control] + nav_items
        settings_button = dbc.NavLink("Settings...", id=self.kapp.new_id())
        nav_items.append(dbc.NavItem(settings_button))
        nav = dbc.Nav(nav_items, pills=True, navbar=True)
        navbar = dbc.Navbar(nav, color="dark", dark=True, expand=True)

        dstyle = {"label_width": 5, "control_width": 5}
        sensitivity = kritter.Kslider(name="Detection sensitivity", value=self.config['detection_sensitivity'], mxs=(1, 100, 1), format=lambda val: f'{int(val)}%', style=dstyle)
        enabled_classes = kritter.Kchecklist(name="Enabled classes", options=self.detector_process.classes(), value=self.config['enabled_classes'], clear_check_all=True, scrollable=True, style=dstyle)
        trigger_classes = kritter.Kchecklist(name="Trigger classes", options=self.config['enabled_classes'], value=self.config['trigger_classes'], clear_check_all=True, scrollable=True, style=dstyle)
        upload = kritter.Kcheckbox(name="Upload to Google Photos", value=self.config['gphoto_upload'] and self.gphoto_interface is not None, disabled=self.gphoto_interface is None, style=dstyle)
        dlayout = [sensitivity, enabled_classes, trigger_classes, upload]
        settings = kritter.Kdialog(title=[kritter.Kritter.icon("gear"), "Settings"], layout=dlayout)

        layouts = [dbc.Collapse(v, is_open=k in self.tabs[self.tab][LAYOUT], id=k+"collapse", style={"margin": "5px"}) for k, v in self.layouts.items()]
        self.kapp.layout = [navbar] + layouts + [settings]

        for k, v in self.tabs.items():
            try:
                v[INIT]()
            except:
                pass

        def tab_func(tab):
            def func(val):
                mods = []
                try:
                    mods += self.tabs[self.tab][CLOSE]()
                except: 
                    pass
                self.tab = tab
                try:
                    mods += self.tabs[self.tab][OPEN]()
                except: 
                    pass
                return mods + [Output(i+"collapse", "is_open", i in self.tabs[tab][LAYOUT]) for i in self.layouts] + [Output(t+"nav", "active", t==tab) for t in self.tabs]
            return func

        for t in self.tabs:
            self.kapp.callback_shared(None, [Input(t+"nav", "n_clicks")])(tab_func(t))

        @self.kapp.callback(None, [Input(settings_button.id, "n_clicks")])
        def func(arg):
            return settings.out_open(True)     
                   
        @sensitivity.callback()
        def func(value):
            self.config['detection_sensitivity'] = value
            self._set_threshold() 
            self.config.save()

        @enabled_classes.callback()
        def func(value):
            # value list comes in unsorted -- let's sort to make it more human-readable
            value.sort(key=lambda c: c.lower())
            self.config['enabled_classes'] = value
            # Find trigger classes that are part of enabled classes            
            self.config['trigger_classes'] = [c for c in self.config['trigger_classes'] if c in value]
            self.config.save()
            return trigger_classes.out_options(value) + trigger_classes.out_value(self.config['trigger_classes'])

        @trigger_classes.callback()
        def func(value):
            self.config['trigger_classes'] = value
            self.config.save()

        @upload.callback()
        def func(value):
            self.config['gphoto_upload'] = value  
            self.store_media.store_media = self.gphoto_interface if value else None
            self.config.save()


        # Run camera grab thread.
        self.run_thread = True
        self._grab_thread = Thread(target=self.grab_thread)
        self._grab_thread.start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self.run_thread = False
        self._grab_thread.join()
        self.detector.close()
        self.detector_process.close()
        self.store_media.close()

    def _create_classes(self):
        text = "CLASSES = [\n"
        for c in self.media_grid.classes:
            text += f'  "{c}",\n'
        text = text[:-2] # remove last comma, to make it look nice
        text += "\n]\n\n"
        text += 'TYPE = "efficientdet_lite0"\n'

        with open(os.path.join(self.project_dir, f"{self.project}_consts.py"), "w") as file:
            file.write(text)

    def _prepare(self):
        self.kapp.push_mods(self.train_button.out_spinner_disp(True))
        # create zip file
        os.chdir(self.project_dir)
        os.system("rm -rf tmp")
        os.system("mkdir tmp tmp/train tmp/validate")
        os.chdir("tmp")
        media_dir = os.path.join(self.project_dir, "media")
        files = os.listdir(media_dir)
        files = [f for f in files if f.endswith(".jpg")]
        for f in files:
            if VALIDATION_PERCENTAGE>=random.randint(1, 100):
                _dir = "validate"
            else:
                _dir = "train"
            ff = os.path.join(media_dir, f)
            data = kritter.load_metadata(ff)
            try:
                # create pvoc based on json
                create_pvoc(ff, data['dets'], out_filename=os.path.join(self.project_dir, f"tmp/{_dir}", kritter.file_basename(f)+".xml"), resolution=(data['width'], data['height']))
            except Exception as e:
                print(e)
                continue
            # copy file
            os.system(f"cp ../media/{f} {_dir}")
        os.system(f"rm ../{TRAINING_SET_FILE}")
        os.system(f"zip -r ../{TRAINING_SET_FILE} train validate")
        os.chdir("../..")

        # modify training ipynb
        with open(os.path.join(BASEDIR, TRAIN_FILE)) as file:
            train_code = json.load(file)
        project_dir = {"cell_type": "code", "source": [
            f'PROJECT_NAME = "{self.project}"\n',
            f'PROJECT_DIR = "{os.path.join("/content/drive/MyDrive", GDRIVE_DIR[1:])}/" + PROJECT_NAME'],
            "metadata": {"id": "zXTGWX9ZWaZ9"},
            "execution_count": 0,
            "outputs": []
        }
        train_code['cells'].insert(0, project_dir)
        train_file = os.path.join(self.project_dir, TRAIN_FILE)        
        with open(train_file, "w") as file:
            json.dump(train_code, file, indent=2)

        # create classes file
        self._create_classes()

        # copy files to gdrive
        try:
            g_train_file = os.path.join(GDRIVE_DIR, self.project, TRAIN_FILE)
            self.gdrive_interface.copy_to(train_file, g_train_file, True)
            train_url = self.gdrive_interface.get_url(g_train_file)
            self.gdrive_interface.copy_to(os.path.join(self.project_dir, f"{self.project}_consts.py"), os.path.join(GDRIVE_DIR, self.project, f"{self.project}_consts.py"), True)
        except Exception as e:
            print("Unable to upload training code to Google Drive.", e)
            return self.train_button.out_spinner_disp(False)
        try:
            self.gdrive_interface.copy_to(os.path.join(self.project_dir, TRAINING_SET_FILE), os.path.join(GDRIVE_DIR, self.project, TRAINING_SET_FILE), True)
        except Exception as e:
            print("Unable to upload training set images to Google Drive.", e)
            return self.train_button.out_spinner_disp(False)
    
        return self._set_train(train_url) 

    def _set_train(self, url):
        if url:
            self.train_button.name = "Train" 
            return self.train_button.out_spinner_disp(False) + self.train_button.out_name("Train") + self.train_button.out_url(url)
        else:
            self.train_button.name = "Prepare" 
            return self.train_button.out_spinner_disp(False) + self.train_button.out_name("Prepare") + self.train_button.out_url(None)

    def create_tabs(self):
        # Create video component and histogram enable.
        self.video = kritter.Kvideo(width=self.camera.resolution[0], overlay=True)
        brightness = kritter.Kslider(name="Brightness", value=self.camera.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style={"control_width": 4}, grid=False)
        self.media_queue =  MediaDisplayQueue(MEDIA_DIR, STREAM_WIDTH, CAMERA_WIDTH, self.config_consts.MEDIA_QUEUE_IMAGE_WIDTH, self.config_consts.IMAGES_DISPLAY) 
        self.capture_queue =  MediaDisplayQueue(os.path.join(self.project_dir, "media"), STREAM_WIDTH, CAMERA_WIDTH, self.config_consts.MEDIA_QUEUE_IMAGE_WIDTH, self.config_consts.IMAGES_DISPLAY) 
        self.take_picture_button = kritter.Kbutton(name=[kritter.Kritter.icon("camera"), "Take picture"], service=None, spinner=True)
        self.train_button = kritter.Kbutton(name="Prepare", spinner=True, target="_blank", external_link=True, disabled=self.gdrive_interface is None)
        self.media_grid = MediaDisplayGrid(os.path.join(self.project_dir, "media"))

        # There are some challenges with tabs and their layouts.  Many of the tabs share layout
        # components, but not consistently (as with motionscope).  You can't have the same 
        # component more than once in a given layout, so we necessarily need to chop up the layout
        # and define which pieces go in which tab.  
        self.layouts['video'] = self.video 
        self.layouts['media_queue'] = self.media_queue.layout
        self.layouts['capture_queue'] = self.capture_queue.layout
        self.layouts['brightness'] = brightness
        self.layouts['take_picture'] = self.take_picture_button
        self.layouts['grid'] = [self.media_grid.layout, self.train_button]

        def capture_open():
            self.video.overlay.draw_clear()
            return self.video.overlay.out_draw() + self.capture_queue.out_images()

        # Tabs might want to be encapsulated in their own Tab superclass/subclass and then 
        # instantiated and put in a list or dict, but this (below) is a simpler solution (for now).
        # There is also a good amount of sharing of data/components between tabs, so putting
        # tabs in separate classes solves some problems but creates others. 
        self.tabs['Detect'] = {
            INIT: lambda : self.kapp.push_mods(self.media_queue.out_images()),
            LAYOUT: ['video', 'media_queue', 'brightness']
        }

        self.tabs['Capture'] = {
            LAYOUT: ['video', 'capture_queue', 'brightness', 'take_picture'],
            OPEN: capture_open,
        }

        self.tabs['Training set'] = {
            LAYOUT: ['grid'],
            OPEN: lambda : self.media_grid.out_images()
        }

        @brightness.callback()
        def func(value):
            self.config['brightness'] = value
            self.camera.brightness = value
            self.config.save()

        @self.take_picture_button.callback()
        def func():
            self.kapp.push_mods(self.take_picture_button.out_spinner_disp(True))
            cv2.imwrite(os.path.join(self.project_dir, kritter.date_stamped_file("jpg")), self.frame)
            return self.capture_queue.out_images() + self.take_picture_button.out_spinner_disp(False)

        @self.train_button.callback()
        def func():
            if self.train_button.name=="Prepare":
                return self._prepare()

    def _set_threshold(self):
        self.sensitivity_range.inval = self.config['detection_sensitivity']
        threshold = self.sensitivity_range.outval
        self.tracker.setThreshold(threshold)
        self.low_threshold = threshold - THRESHOLD_HYSTERESIS
        if self.low_threshold<MIN_THRESHOLD:
            self.low_threshold = MIN_THRESHOLD 

    def _timestamp(self):
        return datetime.datetime.now().strftime("%a %H:%M:%S")

    # Frame grabbing thread
    def grab_thread(self):
        last_tag = ""
        while self.run_thread:
            mods = []
            timestamp = self._timestamp()
            # Get frame
            self.frame = self.stream.frame()[0]

            if self.tab=="Detect":
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

            if self.tab=="Detect" and daytime:
                # Get raw detections from detector thread
                detect = self.detector.detect(self.frame, self.low_threshold)
            else:
                detect = [], None
            if detect is not None:
                dets, det_frame = detect
                # Remove classes that aren't active
                dets = self._filter_dets(dets)
                # Feed detections into tracker
                dets = self.tracker.update(dets, showDisappeared=True)
                # Render tracked detections to overlay
                mods += kritter.render_detected(self.video.overlay, dets)
                # Update picker
                mods += self._handle_picks(det_frame, dets)

            # Send frame
            self.video.push_frame(self.frame)

            try:
                self.kapp.push_mods(mods)
            except:
                pass

            # Sleep to give other threads a boost 
            time.sleep(0.01)

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
                self.store_media.store_image_array(image, album=self.config_consts.GPHOTO_ALBUM, data={**data, 'width': image.shape[1], 'height': image.shape[0], "timestamp": timestamp})
                if data['class'] in self.config['trigger_classes']:
                    event = {**data, 'image': image, 'event_type': 'trigger', "timestamp": timestamp}
                    handle_event(self, event)
            if deregs:    
                handle_event(self, {'event_type': 'deregister', 'deregs': deregs})
            return self.media_queue.out_images()
        return []       

    def _filter_dets(self, dets):
        dets = [det for det in dets if det['class'] in self.config['enabled_classes']]
        return dets


if __name__ == "__main__":
    ObjectDetector()
