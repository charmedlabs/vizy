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
from kritter import get_color
from kritter.tflite import TFliteDetector
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
import dash_html_components as html
from vizy import Vizy

MIN_THRESHOLD = 0.1
MAX_THRESHOLD = 0.9
THRESHOLD_HYSTERESIS = 0.2

CONFIG_FILE = "object_detector.json"
DEFAULT_CONFIG = {
    "brightness": 50,
    "detection_threshold": 50,
    "enabled_classes": None,
}
BASEDIR = os.path.dirname(__file__)
MEDIA_DIR = os.path.join(BASEDIR, "media")



class ObjectDetector:
    def __init__(self):

        # Create Kritter server.
        self.kapp = Vizy()
        self.kapp.media_path.insert(0, MEDIA_DIR)

        config_filename = os.path.join(self.kapp.etcdir, CONFIG_FILE)      
        self.config = kritter.ConfigFile(config_filename, DEFAULT_CONFIG)               

        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream()
        self.camera.mode = "768x432x10bpp"
        self.camera.brightness = self.config['brightness']
        self.camera.framerate = 30
        self.camera.autoshutter = True
        self.camera.awb = True

        self.tracker = kritter.DetectionTracker()
        self.detector_process = kritter.Processify(TFliteDetector, (None, ))
        self.detector = kritter.KimageDetectorThread(self.detector_process)
        if self.config['enabled_classes'] is None:
            self.config['enabled_classes'] = self.detector_process.classes()
        self.set_threshold(self.config['detection_threshold']/100)

        style = {"label_width": 3, "control_width": 6}

        # Create video component and histogram enable.
        self.video = kritter.Kvideo(width=self.camera.resolution[0], overlay=True)
        brightness = kritter.Kslider(name="Brightness", value=self.camera.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style=style)
        image_div = html.Div([
            html.Div(html.Img(id=self.kapp.new_id(), src="/media/out0.jpg", style={"max-width": "320px", "width": "100%", "height": "100%"}), style={"padding": "5px 5px 0px"}),
            html.Div(html.Img(id=self.kapp.new_id(), src="/media/out1.jpg", style={"max-width": "320px", "width": "100%", "height": "100%"}), style={"padding": "5px 5px 0px"}),
            html.Div(html.Img(id=self.kapp.new_id(), src="/media/out2.jpg", style={"max-width": "320px", "width": "100%", "height": "100%"}), style={"padding": "5px 5px 0px"}),
        ], style={"width": "320px", "height": "416px", "overflow-y": "auto"})
        threshold = kritter.Kslider(name="Detection threshold", value=self.config['detection_threshold'], mxs=(MIN_THRESHOLD*100, MAX_THRESHOLD*100, 1), format=lambda val: f'{int(val)}%', style=style)
        enabled_classes = kritter.Kchecklist(name="Enabled classes", options=self.detector_process.classes(), value=self.config['enabled_classes'], clear_check_all=True, scrollable=True)

        @brightness.callback()
        def func(value):
            self.config['brightness'] = value
            self.camera.brightness = value
            self.config.save()

        @threshold.callback()
        def func(value):
            self.config['detection_threshold'] = value
            self.set_threshold(value/100) 
            self.config.save()

        @enabled_classes.callback()
        def func(value):
            self.config['enabled_classes'] = value
            self.config.save()

        controls = html.Div([brightness, threshold, enabled_classes])
        # Add video component and controls to layout.
        self.kapp.layout = html.Div([html.Div([html.Div(self.video, style={"float": "left"}), image_div]), controls], style={"padding": "15px"})

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

    def set_threshold(self, threshold):
        self.tracker.setThreshold(threshold)
        self.low_threshold = threshold - THRESHOLD_HYSTERESIS
        if self.low_threshold<MIN_THRESHOLD:
            self.low_threshold = MIN_THRESHOLD 

    # Frame grabbing thread
    def grab_thread(self):
        while self.run_thread:
            # Get frame
            frame = self.stream.frame()[0]
            # Get raw detections from detector thread
            dets = self.detector.detect(frame, self.low_threshold)
            if dets is not None:
                # Remove classes that aren't active
                dets = self._filter_dets(dets)
                # Feed detections into tracker
                dets = self.tracker.update(dets, showDisappeared=True)
                # Render tracked detections to overlay
                self.kapp.push_mods(kritter.render_detected(self.video.overlay, dets))
            # Send frame
            self.video.push_frame(frame)

    def _filter_dets(self, dets):
        dets = [det for det in dets if det['class'] in self.config['enabled_classes']]
        return dets
        
if __name__ == "__main__":
    ObjectDetector()

