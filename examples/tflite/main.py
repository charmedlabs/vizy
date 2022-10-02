#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

from threading import Thread
from vizy import Vizy
from kritter import Camera, Kvideo, Kslider, render_detected
from kritter.tflite import TFliteDetector

class TFliteExample:

    def __init__(self):
        # Instantiate Vizy's camera and camera stream
        camera = Camera(hflip=True, vflip=True)
        self.stream = camera.stream()
        # Initialize detection sensitivity (50%)
        self.sensitivity = 0.50
        # Instantiate Vizy server, video object, and sensitivity slider 
        self.kapp = Vizy()
        self.video = Kvideo(width=camera.resolution[0], overlay=True)
        sensitivity_c = Kslider(name="Sensitivity", value=self.sensitivity*100, mxs=(10, 90, 1), format=lambda val: f'{int(val)}%', grid=False)
        # Set application layout
        self.kapp.layout = [self.video, sensitivity_c]

        # Callback for sensitivity slider
        @sensitivity_c.callback()
        def func(value):
            # Update sensitivity value, convert from %
            self.sensitivity = value/100 

        # Instantiate TensorFlow Lite detector
        self.tflite = TFliteDetector()

        # Start processing thread
        self.run_process = True
        Thread(target=self.process).start()

        # Run Vizy server, which blocks.
        self.kapp.run()
        self.run_process = False

    # Frame processing thread
    def process(self):
        while self.run_process:
            # Get frame
            frame = self.stream.frame()[0]
            # Run detection
            dets = self.tflite.detect(frame, self.sensitivity)
            # If we detect something...
            if dets is not None:
                self.kapp.push_mods(render_detected(self.video.overlay, dets))
            # Push frame to the video window in browser.
            self.video.push_frame(frame)


if __name__ == '__main__':
    TFliteExample()
