import threading
import kritter
import vizy
from subprocess import run 
import os 
from kritter.tflite import TFliteDetector
import time

MEDIA_DIR = os.path.join(os.path.dirname(__file__), "media")
PIC_TIMEOUT = 10
PIC_ALBUM = "Vizy Pet Companion"

class PetCompanion:

    def __init__(self):
        
        # Set up Vizy class, Camera, etc.
        self.kapp = vizy.Vizy()
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream()
        self.pic_timer = 0
        self.kapp.power_board.vcc12(False) # Turn off

        # Put components in the layout
        self.video = kritter.Kvideo(width=800, overlay=True)
        brightness = kritter.Kslider(name="Brightness", value=self.camera.brightness, mxs=(0, 100, 1), format=lambda val: '{}%'.format(val), grid=False)
        call_pet_button = kritter.Kbutton(name="Call pet")
        dispense_treat_button = kritter.Kbutton(name="Dispense treat")
        self.kapp.layout = [self.video, brightness, call_pet_button, dispense_treat_button]

        # Start TensorFlow 
        self.tflite = TFliteDetector(threshold=0.5)
        
        # Set up Google Photos and media queue
        gcloud = kritter.Gcloud(self.kapp.etcdir)
        gpsm = kritter.GPstoreMedia(gcloud)
        self.media_q = kritter.SaveMediaQueue(gpsm, MEDIA_DIR)

        @brightness.callback()
        def func(value):
            self.camera.brightness = value
            
        @call_pet_button.callback()
        def func():
            print("Calling pet...")
            audio_file = os.path.join(os.path.dirname(__file__), "hey.wav")
            run(["omxplayer", audio_file])

        @dispense_treat_button.callback()
        def func():
            print("Dispensing treat...")
            self.kapp.power_board.vcc12(True) # Turn on
            time.sleep(0.5) # Wait a little to give solenoid time to dispense treats 
            self.kapp.power_board.vcc12(False) # Turn off

        # Run camera grab thread.
        self.run_grab = True
        threading.Thread(target=self.grab).start()

        # Run Vizy webserver, which blocks.
        self.kapp.run()
        self.run_grab = False
        self.media_q.close()

    def upload_pic(self, image):
        t = time.time()
        # Save picture if timer expires
        if t-self.pic_timer>PIC_TIMEOUT:
            self.pic_timer = t
            print("Uploading pic...")
            self.media_q.store_image_array(image, album=PIC_ALBUM)

    def filter_detected(self, dets):
        # Discard detections other than dogs and cats. 
        dets = [det for det in dets if det['class']=="dog" or det['class']=="cat"]
        return dets 
    
    def grab(self):
        while self.run_grab:
            # Get frame
            frame = self.stream.frame()[0]
            # Run TensorFlow detector
            dets = self.tflite.detect(frame)
            # If we detect something...
            if dets is not None:
                self.kapp.push_mods(kritter.render_detected(self.video.overlay, dets))
                dets = self.filter_detected(dets)
                # Save picture if we still see something after filtering
                if dets:
                    self.upload_pic(frame)
            # Send frame
            self.video.push_frame(frame)

if __name__ == "__main__":
    PetCompanion()