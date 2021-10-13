import os
import time 
from threading import Thread
from vizy import Vizy
import vizy.vizypowerboard as vpb
from kritter import Kritter, Camera, Gcloud, GPstoreMedia, SaveMediaQueue, Kvideo, Kbutton, Kslider, Kcheckbox, Kdialog, render_detected
from kritter.tf import TFDetector, BIRDFEEDER
import dash_html_components as html
import dash_bootstrap_components as dbc


APP_DIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(APP_DIR, "media")
ALBUM = "Birdfeeder"
STREAM_WIDTH = 768
STREAM_HEIGHT = 432
MIN_THRESHOLD = 10 
MAX_THRESHOLD = 100
DEFEND_BIT = 0 

class Birdfeeder:

    def __init__(self):
        self.pic_timer = time.time()
        self.take_pic = False
        self.brightness = 50
        self.sensitivity = 20
        self.pic_period = 5
        self.post_label = True
        self.defense_duration = 3
        camera = Camera(hflip=True, vflip=True)
        camera.brightness = self.brightness
        # Set camera to maximum resolution (1920x1020 is max resolution for camera stream currently)
        camera.mode = "1920x1080x10bpp"
        self.stream = camera.stream()

        style = {"max_width": STREAM_WIDTH}
        self.kapp = Vizy()
        self.kapp.power_board.vcc12(True)
        self.kapp.power_board.io_set_mode(DEFEND_BIT, vpb.IO_MODE_HIGH_CURRENT)
        self.kapp.power_board.io_bits(self.kapp.power_board.io_bits() | (1<<DEFEND_BIT)) # set defend bit to high (turn off)

        gcloud = Gcloud(self.kapp.etcdir)
        gpsm = GPstoreMedia(gcloud)
        self.media_q = SaveMediaQueue(gpsm, MEDIA_DIR)
        self.video = Kvideo(width=STREAM_WIDTH, height=STREAM_HEIGHT)
        self.brightness_c = Kslider(name="Brightness", value=self.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style={"control_width": 3}, grid=False)
        self.take_pic_c = Kbutton(name=[Kritter.icon("camera"), "Take picture"], spinner=True, style=style)
        self.defend = Kbutton(name=[Kritter.icon("bomb"), "Defend"], spinner=True)
        self.config = Kbutton(name=[Kritter.icon("gear"), "Settings"], service=None)
        self.take_pic_c.append(self.defend)
        self.take_pic_c.append(self.config)
        self.take_pic_c.append(self.brightness_c)

        dstyle = {"label_width": 5, "control_width": 5}
        self.sensitivity_c = Kslider(name="Detection sensitivity", value=self.sensitivity, mxs=(0, 100, 1), format=lambda val: f'{val}%', style=dstyle)
        self.pic_period_c = Kslider(name="Seconds between pics", value=self.pic_period, mxs=(1, 60, 1), format=lambda val: f'{val}s', style=dstyle)
        self.defense_duration_c = Kslider(name="Defense duration", value=self.defense_duration, mxs=(.1, 10, .1), format=lambda val: f'{val}s', style=dstyle)
        self.post_label_c = Kcheckbox(name="Post pics with labels", value=self.post_label, style=dstyle)
        dlayout = [self.sensitivity_c, self.defense_duration_c, self.pic_period_c, self.post_label_c]
        self.settings = Kdialog(title="Settings", layout=dlayout)

        self.kapp.layout = html.Div([self.video, self.take_pic_c, self.settings], style={"padding": "15px"})

        @self.defend.callback()
        def func():
            self.kapp.push_mods(self.defend.out_spinner_disp(True))
            self.kapp.power_board.io_bits(self.kapp.power_board.io_bits() & ~(1<<DEFEND_BIT))
            time.sleep(self.defense_duration)
             # set defend bit to low (turn on)
            self.kapp.power_board.io_bits(self.kapp.power_board.io_bits() | (1<<DEFEND_BIT)) # set defend bit to high (turn off)
            return self.defend.out_spinner_disp(False)

        @self.brightness_c.callback()
        def func(val):
            camera.brightness = val 

        @self.sensitivity_c.callback()
        def func(val):
            self.sensitivity = val
            self._update_sensitivity()

        @self.pic_period_c.callback()
        def func(val):
            self.pic_period = val

        @self.defense_duration_c.callback()
        def func(val):
            self.defense_duration = val

        @self.post_label_c.callback()
        def func(val):
            print("label", val)
            self.post_label = val 

        @self.take_pic_c.callback()
        def func():
            self.take_pic = True
            return self.take_pic_c.out_spinner_disp(True)

        @self.config.callback()
        def func():
            return self.settings.out_open(True)

        self.tflow = TFDetector(BIRDFEEDER)
        self._update_sensitivity()
        self.tflow.open()
        self.run_thread = True
        thread_ = Thread(target=self.thread)
        thread_.start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self.run_thread = False
        self.tflow.close()
        self.media_q.close()

    def _update_sensitivity(self):
        threshold = 100-self.sensitivity 
        threshold *= (MAX_THRESHOLD-MIN_THRESHOLD)/100
        threshold += MIN_THRESHOLD
        self.tflow.set_threshold(threshold/100)

    def _detected_desc(self, detected):
            if len(detected)==0:
                return "Snapped picture"
            desc = ""
            for d in detected:
                desc += f"{d.label}, "
            return desc[0:-2]

    def _save_pic(self, image, detected):
        t = time.time()
        if t-self.pic_timer>self.pic_period:
            self.pic_timer = t
            desc = self._detected_desc(detected)
            print("saving", desc)
            self.media_q.store_image_array(image, album=ALBUM, desc=desc)

    def thread(self):
        detected = []
        while self.run_thread:
            # Get frame
            frame = self.stream.frame()[0]
            # Send frame
            _detected = self.tflow.detect(frame, block=False)
            # If we detect something...
            if _detected is not None:
                detected = _detected
                if _detected and not self.post_label:
                    self._save_pic(frame, _detected)

            # Overlay detection boxes and labels ontop of frame.
            render_detected(frame, detected)
            # Push frame to the video window in browser.
            self.video.push_frame(frame)
            if _detected and self.post_label:
                self._save_pic(frame, _detected)
            if self.take_pic:
                desc = self._detected_desc(detected)
                print("saving", desc)
                self.media_q.store_image_array(frame, album=ALBUM, desc=desc)
                self.kapp.push_mods(self.take_pic_c.out_spinner_disp(False))
                self.take_pic = False                


if __name__ == '__main__':
    bf = Birdfeeder()
