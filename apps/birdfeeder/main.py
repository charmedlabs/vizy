import os 
from threading import Thread
from vizy import Vizy
from kritter import Kritter, Camera, Gcloud, GPstoreMedia, SaveMediaQueue, Kvideo, Kbutton, Kslider, Kdialog, render_detected
from kritter.tf import TFDetector, BIRDFEEDER
import dash_html_components as html
import dash_bootstrap_components as dbc


APP_DIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(APP_DIR, "media")
ALBUM = "Birdfeeder"
STREAM_WIDTH = 768
STREAM_HEIGHT = 432


class Birdfeeder:

    def __init__(self):
        self.take_pic = False
        camera = Camera(hflip=True, vflip=True)
        camera.mode = "1920x1080x10bpp"
        self.stream = camera.stream()

        style = {"label_width": 2, "control_width": 3, "max_width": "760"}
        self.kapp = Vizy()
        gcloud = Gcloud(self.kapp.etcdir)
        gpsm = GPstoreMedia(gcloud)
        self.media_q = SaveMediaQueue(gpsm, MEDIA_DIR)
        self.video = Kvideo(width=STREAM_WIDTH, height=STREAM_HEIGHT)
        self.brightness = Kslider(name="Brightness", value=camera.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style=style, grid=False)
        self.take_pic_c = Kbutton(name=[Kritter.icon("camera"), "Take picture"], spinner=True, style=style)
        self.defend = Kbutton(name=[Kritter.icon("bomb"), "Defend"], spinner=True)
        self.config = Kbutton(name=[Kritter.icon("gear"), "Settings"], service=None)
        self.take_pic_c.append(self.defend)
        self.take_pic_c.append(self.config)
        self.take_pic_c.append(self.brightness)

        self.sensitivity = Kslider(name="Sensitivity", value=camera.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style=style)
        self.settings = Kdialog(title="Settings", layout=[self.sensitivity])

        self.kapp.layout = html.Div([self.video, self.take_pic_c, self.settings], style={"padding": "15px"})
        self.tflow = TFDetector(BIRDFEEDER)
        self.tflow.open()

        @self.take_pic_c.callback()
        def func():
            self.take_pic = True
            return self.take_pic_c.out_spinner_disp(True)

        @self.config.callback()
        def func():
            return self.settings.out_open(True)

        self.run_thread = True
        thread_ = Thread(target=self.thread)
        thread_.start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self.run_thread = False
        self.tflow.close()
        self.media_q.close()

    def thread(self):
        detected = []
        while self.run_thread:
            # Get frame
            frame = self.stream.frame()[0]
            # Send frame
            _detected = self.tflow.detect(frame, block=False)
            # If we detect something...
            if _detected is not None:
                # ...save for render_detected() overlay. 
                detected = _detected
            # Overlay detection boxes and labels ontop of frame.
            render_detected(frame, detected)
            # Push frame to the video window in browser.
            self.video.push_frame(frame)
            if self.take_pic:
                print("saving...")
                self.media_q.store_image_array(frame, album=ALBUM, desc="Snapped picture")
                self.kapp.push_mods(self.take_pic_c.out_spinner_disp(False))
                self.take_pic = False                


if __name__ == '__main__':
    bf = Birdfeeder()
