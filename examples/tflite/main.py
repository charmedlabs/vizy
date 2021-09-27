from threading import Thread
from vizy import Vizy
from kritter import Camera, Kvideo, render_detected
from kritter.tflite import TFliteDetector, COCO

# Frame processing thread
def process(video, stream, tflite, run):
    detected = []
    while run():
        # Get frame
        frame = stream.frame()[0]
        # Send frame
        _detected = tflite.detect(frame, block=False)
        # If we detect something...
        if _detected is not None:
            # ...save for render_detected() overlay. 
            detected = _detected
        # Overlay detection boxes and labels ontop of frame.
        render_detected(frame, detected)
        # Push frame to the video window in browser.
        video.push_frame(frame)


def main():
    camera = Camera(hflip=True, vflip=True)
    stream = camera.stream()

    kapp = Vizy()
    video = Kvideo(width=camera.resolution[0], height=camera.resolution[1])

    kapp.layout = [video]
    tflite = TFliteDetector(COCO)
    tflite.open()

    run_process = True
    process_thread = Thread(target=process, args=(video, stream, tflite, lambda: run_process))
    process_thread.start()

    # Run Kritter server, which blocks.
    kapp.run()
    run_process = False
    tflite.close()

if __name__ == '__main__':
    main()
