import os
import time 
from threading import Thread
from dash_devices.dependencies import Input, Output
from vizy import Vizy, ConfigFile, import_config
import vizy.vizypowerboard as vpb
from kritter import Kritter, Camera, Gcloud, GPstoreMedia, SaveMediaQueue, Kvideo, Kbutton, Kslider, Kcheckbox, Kdialog, render_detected
from kritter.tf import TFDetector, BIRDFEEDER
import dash_html_components as html
import dash_bootstrap_components as dbc

CONFIG_FILE = "birdfeeder.json"
DEFAULT_CONFIG = {
    "brightness": 50,
    "sensitivity": 50,
    "picture period": 5,
    "defense duration": 3, 
    "post labels": True,
    "post pests": True
}

CONSTS_FILE = "birdfeeder_consts.py"
APP_DIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(APP_DIR, "media")
STREAM_WIDTH = 768
STREAM_HEIGHT = 432
MIN_THRESHOLD = 5 
MAX_THRESHOLD = 100
PIC_WIDTH = 1920
PIC_HEIGHT = 1080 
ASPECT_RATIO = 1.15
CROPPED_WIDTH = int(PIC_HEIGHT*ASPECT_RATIO)
X_OFFSET = int((PIC_WIDTH-CROPPED_WIDTH)/2)

class Birdfeeder:

    def __init__(self):
        # Set up vizy class, config files.
        self.kapp = Vizy()
        config_filename = os.path.join(self.kapp.etcdir, CONFIG_FILE)      
        self.config = ConfigFile(config_filename, DEFAULT_CONFIG)               
        consts_filename = os.path.join(APP_DIR, CONSTS_FILE) 
        self.config_consts = import_config(consts_filename, self.kapp.etcdir, ["THRESHOLDS", "PESTS", "ALBUM", "DEFEND_BIT"])     

        # Initialize power board defense bit.
        self.kapp.power_board.vcc12(True)
        self.kapp.power_board.io_set_mode(self.config_consts.DEFEND_BIT, vpb.IO_MODE_HIGH_CURRENT)
        self.kapp.power_board.io_set_bit(self.config_consts.DEFEND_BIT) # set defend bit to high (turn off)

        # Initialize variables.
        self.pic_timer = time.time()
        self.take_pic = False
        self.defend_thread = None

        # Initialize camera.
        camera = Camera(hflip=True, vflip=True)
        camera.brightness = self.config.config['brightness']
        # Set camera to maximum resolution (1920x1020 is max resolution for camera stream currently)
        camera.mode = "1920x1080x10bpp"
        self.stream = camera.stream()

        # Instantiate GUI elements.
        style = {"max_width": STREAM_WIDTH}
        gcloud = Gcloud(self.kapp.etcdir)
        gpsm = GPstoreMedia(gcloud)
        self.media_q = SaveMediaQueue(gpsm, MEDIA_DIR)
        self.video = Kvideo(width=STREAM_WIDTH, height=STREAM_HEIGHT)
        self.brightness= Kslider(name="Brightness", value=self.config.config['brightness'], mxs=(0, 100, 1), format=lambda val: f'{val}%', style={"control_width": 3}, grid=False)
        self.take_pic_c = Kbutton(name=[Kritter.icon("camera"), "Take picture"], spinner=True, style=style)
        self.defend = Kbutton(name=[Kritter.icon("bomb"), "Defend"], spinner=True)
        self.config_c = Kbutton(name=[Kritter.icon("gear"), "Settings"], service=None)
        self.take_pic_c.append(self.defend)
        self.take_pic_c.append(self.config_c)
        self.take_pic_c.append(self.brightness)

        # Instantiate config dialog elements.
        dstyle = {"label_width": 5, "control_width": 5}
        self.sensitivity = Kslider(name="Detection sensitivity", value=self.config.config['sensitivity'], mxs=(0, 100, 1), format=lambda val: f'{val}%', style=dstyle)
        self.pic_period = Kslider(name="Seconds between pics", value=self.config.config['picture period'], mxs=(1, 60, 1), format=lambda val: f'{val}s', style=dstyle)
        self.defense_duration = Kslider(name="Defense duration", value=self.config.config['defense duration'], mxs=(.1, 10, .1), format=lambda val: f'{val}s', style=dstyle)
        self.post_labels = Kcheckbox(name="Post pics with labels", value=self.config.config['post labels'], style=dstyle)
        self.post_pests = Kcheckbox(name="Post pics of pests", value=self.config.config['post pests'], style=dstyle)
        self.edit_consts = Kbutton(name=[Kritter.icon("edit"), "Edit constants"], service=None)
        dlayout = [self.sensitivity, self.defense_duration, self.pic_period, self.post_labels, self.post_pests]
        self.settings = Kdialog(title="Settings", layout=dlayout, left_footer=self.edit_consts)

        self.kapp.layout = html.Div([self.video, self.take_pic_c, self.settings], style={"padding": "15px"})

        # Callbacks...

        @self.defend.callback()
        def func():
            self.kapp.push_mods(self.defend.out_spinner_disp(True))
            self._run_defense(True)
            return self.defend.out_spinner_disp(False)

        @self.brightness.callback()
        def func(val):
            camera.brightness = val 
            self.config.config['brightness'] = val

        @self.sensitivity.callback()
        def func(val):
            self.config.config['sensitivity'] = val
            self._update_sensitivity()

        @self.pic_period.callback()
        def func(val):
            self.config.config['picture period'] = val

        @self.defense_duration.callback()
        def func(val):
            self.config.config['defense duration'] = val

        @self.post_labels.callback()
        def func(val):
            self.config.config['post labels'] = val 

        @self.post_pests.callback()
        def func(val):
            self.config.config['post pests'] = val 

        @self.take_pic_c.callback()
        def func():
            self.take_pic = True
            return self.take_pic_c.out_spinner_disp(True)

        @self.config_c.callback()
        def func():
            return self.settings.out_open(True)

        # Fire off editor for editing constants file.
        # (Clientside code needs to be tucked further under the hood... need to 
        # add this to Vizy, so please pardon the mess...)
        script = """
        function(value) {
            window.open(window.location.protocol + "//" + window.location.hostname + "/editor/loadfiles=etc%2Fbirdfeeder_consts.py", "_blank");
        }
        """
        self.kapp.clientside_callback(script,
                Output("_none", Kritter.new_id()), [Input(self.edit_consts.id, 'n_clicks')])


        # Initialize Tensorflow code.  Set threshold really low so we can apply our 
        # own threshold.
        self.tflow = TFDetector(BIRDFEEDER, 0.05)
        self._update_sensitivity()
        self.tflow.open()
        self.run_thread = True
        thread = Thread(target=self._thread)
        thread.start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        # Server has exited, clean things up and exit.
        self.run_thread = False
        thread.join()
        self.tflow.close()
        self.media_q.close()

    def _run_defense(self, block):
        if not block:
            if not self.defend_thread or not self.defend_thread.is_alive():
                self.defend_thread = Thread(target=self._run_defense, args=(True,))
                self.defend_thread.start()
            return
        else:
             # set defend bit to low (turn on)
            self.kapp.power_board.io_reset_bit(self.config_consts.DEFEND_BIT)
            time.sleep(self.config.config['defense duration'])
             # set defend bit to hight (turn off)
            self.kapp.power_board.io_set_bit(self.config_consts.DEFEND_BIT) # set defend bit to high (turn off)

    def _update_sensitivity(self):
        # Scale sensitivity to threshold
        threshold = 100-self.config.config['sensitivity'] 
        threshold *= (MAX_THRESHOLD-MIN_THRESHOLD)/100
        threshold += MIN_THRESHOLD
        self.threshold = threshold/100

    def _detected_desc(self, detected):
            if len(detected)==0:
                return "Snapped picture"
            desc = ""
            for d in detected:
                desc += f"{d.label}, "
            return desc[0:-2]

    def _save_pic(self, image, detected):
        t = time.time()
        # Save picture if timer expires
        if t-self.pic_timer>self.config.config['picture period']:
            self.pic_timer = t
            desc = self._detected_desc(detected)
            print("saving", desc)
            self.media_q.store_image_array(image, album=self.config_consts.ALBUM, desc=desc)

    def _handle_pests(self, detected):
        defend = False
        for d in detected:
            if d.index in self.config_consts.PESTS:
                d.label += " INTRUDER!"
                defend = True
        if defend:
            self._run_defense(False)
        return defend

    def _threshold_valid(self, d):
        i = d.index-1
        if self.config_consts.THRESHOLDS[i][0]*d.score>=self.threshold:
            x_centroid = (d.box[0] + d.box[2])/2
            y_centroid = (d.box[1] + d.box[3])/2
            x_min = self.config_consts.THRESHOLDS[i][1][0]*PIC_WIDTH
            x_max = self.config_consts.THRESHOLDS[i][1][1]*PIC_WIDTH
            y_min = self.config_consts.THRESHOLDS[i][1][2]*PIC_HEIGHT
            y_max = self.config_consts.THRESHOLDS[i][1][3]*PIC_HEIGHT
            return x_min <= x_centroid and x_centroid <= x_max and y_min <= y_centroid and y_centroid <= y_max
        else:
            return False 

    def _threshold(self, detected):
        if detected is None:
            return None
        else:
            return [d for d in detected if self._threshold_valid(d)]

    def _thread(self):
        detected = []
        pests = False
        config_ = self.config.config

        while self.run_thread:
            # Handle changing config
            config = self.config.config.copy()
            if config_!=config:
                self.config.save()
            config_ = config

            # Get frame
            frame = self.stream.frame()[0]
            # Crop the edges off because the 16x9 aspect ratio can confuse the network
            cropped = frame[0:PIC_HEIGHT, X_OFFSET:(X_OFFSET+CROPPED_WIDTH)]
            # Send frame
            _detected = self.tflow.detect(cropped, block=False)
            # Apply thresholds
            _detected = self._threshold(_detected)

            # If we detect something...
            if _detected is not None:
                detected = _detected
                pests = self._handle_pests(_detected)
                # Save pic of bird without label
                if _detected and not self.config.config['post labels'] and (not pests or self.config.config['post pests']):
                    self._save_pic(frame, _detected)

            # Overlay detection boxes and labels ontop of frame.
            render_detected(frame, detected, x_offset=X_OFFSET)

            # Push frame to the video window in browser.
            self.video.push_frame(frame)

            # Save pic of bird with label
            if _detected and self.config.config['post labels'] and (not pests or self.config.config['post pests']):
                self._save_pic(frame, _detected)

            # Handle manual picture
            if self.take_pic:
                desc = self._detected_desc(detected)
                print("saving", desc)
                self.media_q.store_image_array(frame, album=self.config_consts.ALBUM, desc=desc)
                self.kapp.push_mods(self.take_pic_c.out_spinner_disp(False))
                self.take_pic = False 


if __name__ == '__main__':
    bf = Birdfeeder()
