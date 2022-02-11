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
from kritter import Camera, Kvideo, render_detected
from kritter.tf import TFDetector, COCO

# Frame processing thread
def process(video, stream, tflow, run):
    detected = []
    while run():
        # Get frame
        frame = stream.frame()[0]
        # Send frame
        _detected = tflow.detect(frame, block=False)
        # If we detect something...
        if _detected is not None:
            # ...save for render_detected() overlay. 
            detected = _detected
        # Overlay detection boxes and labels ontop of frame.
        render_detected(frame, detected, font_size=0.6)
        # Push frame to the video window in browser.
        video.push_frame(frame)


def main():
    camera = Camera(hflip=True, vflip=True)
    stream = camera.stream()

    kapp = Vizy()
    video = Kvideo(width=camera.resolution[0], height=camera.resolution[1])

    kapp.layout = [video]
    tflow = TFDetector(COCO)
    tflow.open()

    run_process = True
    process_thread = Thread(target=process, args=(video, stream, tflow, lambda: run_process))
    process_thread.start()

    # Run Kritter server, which blocks.
    kapp.run()
    run_process = False
    tflow.close()


if __name__ == '__main__':
    main()
