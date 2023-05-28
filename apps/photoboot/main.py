import threading
import subprocess
import os
import time
import kritter
import dash_html_components as html
import vizy
from vizy import MediaDisplayQueue
import vizy.vizypowerboard as vpb
from inputs import get_gamepad
import datetime

BASE_DIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(BASE_DIR, "media")

CAMERA_MODE = "2016x1520x10bpp"
#"2016x1520x10bpp"
CAMERA_WIDTH = 800
# Streaming and maximum rendering resolution
STREAM_WIDTH = 800

class Photoboot:

    def __init__(self):
        # Set up Vizy class, Camera, etc.
        self.kapp = vizy.Vizy()
        
        # Create unique identifier to mark photos
        self.uuid = bytes(self.kapp.uuid).hex().upper()
        
        self.camera = kritter.Camera(hflip=True, vflip=True)
        self.stream = self.camera.stream()
        self.camera.mode = CAMERA_MODE
        self.camera.brightness = 52
        self.camera.framerate = 25
        self.camera.autoshutter = True
        self.camera.awb = True
        self.pb = vpb.VizyPowerBoard()
        self.pb.ir_filter(state=True)

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
                            res.append(f"{data['timestamp']} {data['dets'][0]['class']}")
                            res.append(Image(os.path.join(MEDIA_DIR, image)))                            
                    except:
                        pass
                    else:
                        if len(res)//2==n:
                            break
                return res
            tv_table = KtextVisorTable({"mrm": (mrm, "Displays the most recent picture/video, or n media with optional n argument.")})
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
        
        if not os.path.exists(MEDIA_DIR):
            os.mkdir(MEDIA_DIR)
            
        self.store_media = kritter.SaveMediaQueue(path=MEDIA_DIR, keep=6000, keep_uploaded=6000)
            
        self.take_pic = False
        
        style = {"label_width": 3, "control_width": 6}
        self.mode_c = kritter.Kradio(options=["Preview", "View"], value="Preview", style=style)
        self.video = kritter.Kvideo(width=STREAM_WIDTH)
        
        self.media_queue =  MediaDisplayQueue(MEDIA_DIR, STREAM_WIDTH, CAMERA_WIDTH, 200, 10)
        self.pic = kritter.Kbutton(name="Take pic", spinner=True)
        
        # Put video window in the layout
        #self.video = kritter.Kvideo(width=800)
        self.kapp.layout = html.Div([html.Div([self.video, self.media_queue.layout, self.pic])], style={"padding": "15px"})
        self.kapp.push_mods(self.media_queue.out_images())

 
        # Run camera grab thread.
        self.run_grab = True
        threading.Thread(target=self.grab).start()
        threading.Thread(target=self.joyevents).start()
        threading.Thread(target=self.button).start()
 
        self.pb.led(0, 255, 155, 3)
        self.pb.buzzer(800, 1000)
        
        @self.pic.callback()
        def func():
            print("ui knapp call back")
            #self.take_pic = True
            self.take_picture()
        
        # Run Vizy webserver, which blocks.
        self.kapp.run()
        self.run_grab = False
    
        
        
    def button(self):
        while True:
            if self.pb.button_pressed():
                self.take_picture()
                
            time.sleep(0.1)
        
    def joyevents(self):
        while True:
            events = get_gamepad()
            for event in events:
                print(event.ev_type, event.code, event.state)
                if event.ev_type == 'Key':
                    if event.code == 'BTN_TRIGGER':
                        
                        if event.state == 1:
                            self.take_picture()
            time.sleep(0.1)
                            
                            
    def take_picture(self):
        self.pb.led(255, 255, 0, 1)
        print("first beeps")
        self.pb.buzzer(1000, 500, 100, 3)
        print("wait...")
        time.sleep(2)
        print("ready")
        self.pb.buzzer(1000, 100, 100, 3)
        time.sleep(1)
        self.take_pic = True
 
    def grab(self):
        env = os.environ.copy()
        del env['LIBCAMERA_IPA_MODULE_PATH']
        while self.run_grab:
            mods = []
            timestamp = self._timestamp()
            frame = self.stream.frame()[0]
            # Send frame
            self.video.push_frame(frame)
            
            
            if self.take_pic:
                self.kapp.push_mods(self.pic.out_spinner_disp(True))
                self.pb.led(255, 255, 255, 1)
                self.store_media.store_image_array(frame, album="self.config_consts.GPHOTO_ALBUM", desc="Manual picture", data={'uuid': self.uuid, 'width': frame.shape[0], 'height': frame.shape[1]})
                self.stream.stop()
                filename = datetime.datetime.now().strftime("media/%Y_%m_%d_%H_%M_%S_%f.jpg")                
                subprocess.run(["libcamera-still", "-n", "--hflip", "--vflip", "-o", os.path.join(BASE_DIR, filename), "--awb", "auto", "--metering", "average" ,"--ev", "0.3"], env=env)

                self.kapp.push_mods(self.pic.out_spinner_disp(False))
                
                mods += self.media_queue.out_images()
                self.take_pic = False
                
            try:
                self.kapp.push_mods(mods)
            except: 
                pass

            # Sleep to give other threads a boost 
            time.sleep(0.01)
                
    
    def _timestamp(self):
        return datetime.datetime.now().strftime("%a %H:%M:%S")
if __name__ == "__main__":
    Photoboot()
