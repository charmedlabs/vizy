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
from quart import send_file
from tflite_support.task import core
from tflite_support.task import processor
from tflite_support.task import vision
from threading import Thread, Lock
import kritter
from kritter.tflite import TFliteDetector
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy
from kritter import get_bgr_color

MIN_THRESHOLD = 0.1
THRESHOLD = 0.5
MAX_THRESHOLD = 0.9
THRESHOLD_HYSTERESIS = 0.2

BASEDIR = os.path.dirname(__file__)
MEDIA_DIR = os.path.join(BASEDIR, "media")

class ObjectDetector:
    def __init__(self):

        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream()
        self.camera.mode = "768x432x10bpp"
        self.camera.brightness = 50
        self.camera.framerate = 30
        self.camera.autoshutter = True
        self.camera.awb = True

        self.tracker = kritter.DetectionTracker()
        self.detector_process = kritter.Processify(TFliteDetector, (None, ))
        self.detector = kritter.KimageDetectorThread(self.detector_process)
        self.set_threshold(THRESHOLD)

        # Create Kritter server.
        kapp = Vizy()
        style = {"label_width": 4, "control_width": 6}

        # Create video component and histogram enable.
        self.video = kritter.Kvideo(width=self.camera.resolution[0], overlay=True)
        brightness = kritter.Kslider(name="Brightness", value=self.camera.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style=style)
        image_div = html.Div([
            html.Div(html.Img(id=kapp.new_id(), src="/media/out0.jpg", style={"max-width": "320px", "width": "100%", "height": "100%"}), style={"padding": "5px 5px 0px"}),
            html.Div(html.Img(id=kapp.new_id(), src="/media/out1.jpg", style={"max-width": "320px", "width": "100%", "height": "100%"}), style={"padding": "5px 5px 0px"}),
            html.Div(html.Img(id=kapp.new_id(), src="/media/out2.jpg", style={"max-width": "320px", "width": "100%", "height": "100%"}), style={"padding": "5px 5px 0px"}),
        ], style={"width": "320px", "height": "416px", "overflow-y": "auto"})
        threshold = kritter.Kslider(name="Detection threshold", value=THRESHOLD*100, mxs=(MIN_THRESHOLD*100, MAX_THRESHOLD*100, 1), format=lambda val: f'{int(val)}%', style=style)

        kapp.media_path.insert(0, MEDIA_DIR)

        @brightness.callback()
        def func(value):
            self.camera.brightness = value

        @threshold.callback()
        def func(value):
            self.set_threshold(value/100) 

        controls = html.Div([brightness, threshold])

        # Add video component and controls to layout.
        kapp.layout = html.Div([html.Div([html.Div(self.video, style={"float": "left"}), image_div]), controls], style={"padding": "15px"})

        # Run camera grab thread.
        self.run_thread = True
        self._grab_thread = Thread(target=self.grab_thread)
        self._grab_thread.start()

        # Run Kritter server, which blocks.
        kapp.run()
        self.run_thread = False
        self._grab_thread.join()
        self.detector.close()
        self.detector_process.close()

    def set_threshold(self, threshold):
        self.tracker.setThreshold(threshold)
        self.low_threshold = threshold - THRESHOLD_HYSTERESIS
        if self.low_threshold<MIN_THRESHOLD:
            self.low_threshold = MIN_THRESHOLD 

    # Frame grabbing thread
    def grab_thread(self):
        dets = []
        while self.run_thread:
            # Get frame
            frame = self.stream.frame()[0]
            _dets = self.detector.detect(frame, self.low_threshold)
            if _dets is not None:
                dets = self.tracker.update(_dets, showDisappeared=True)
            kritter.render_detected(frame, dets, font_size=0.6)
            # Send frame
            self.video.push_frame(frame)


if __name__ == "__main__":
    ObjectDetector()

