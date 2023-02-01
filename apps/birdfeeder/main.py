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
import json
import datetime
from urllib.request import urlopen
import numpy as np
from threading import Thread, RLock
import kritter
from kritter import get_color
from kritter.tflite import TFliteClassifier, TFliteDetector
from dash_devices.dependencies import Input, Output
import dash_html_components as html
from vizy import Vizy, MediaDisplayQueue
import vizy.vizypowerboard as vpb
from handlers import handle_event, handle_text
from kritter.ktextvisor import KtextVisor, KtextVisorTable, Image, Video

# Minimum allowable detection senstivity/treshold
MIN_THRESHOLD = 0.1
# Maximum allowable detection senstivity/treshold
MAX_THRESHOLD = 0.9
# We start tracking at the current sensitivity setting and stop tracking at the 
# sensitvity - THRESHOLD_HYSTERESIS 
THRESHOLD_HYSTERESIS = 0.2
# Native camera mode
CAMERA_MODE = "1920x1080x10bpp"
CAMERA_WIDTH = 1920
# Streaming and maximum rendering resolution
STREAM_WIDTH = 800
# Time in seconds to buffer defense videos 
PRE_POST_ROLL = 1 
# Image average for daytime detection (based on 0 to 255 range)
DAYTIME_THRESHOLD = 20
# Poll period (seconds) for checking for daytime
DAYTIME_POLL_PERIOD = 10

CONFIG_FILE = "birdfeeder.json"
CONSTS_FILE = "birdfeeder_consts.py"
NON_BIRD = "Non-bird"

DEFAULT_CONFIG = {
    "brightness": 50,
    "detection_sensitivity": 75,
    "species_of_interest": None, # This will be filled in with all species
    "pest_species": [NON_BIRD],
    "trigger_species": [],
    "gphoto_upload": False,
    "share_photos": False,
    "share_url": '',
    "share_url_emailed": False,
    "smooth_video": False,
    "text_new_species": False,
    "defense_duration": 3, 
    "record_defense": False,
    "seen_species": []
}

BASEDIR = os.path.dirname(os.path.realpath(__file__))
MEDIA_DIR = os.path.join(BASEDIR, "media")
# Video states
WAITING = 0
RECORDING = 1
SAVING = 2

class BirdInference:

    def __init__(self, classifier):
        self.detector = TFliteDetector(os.path.join(BASEDIR, "bird_detector.tflite"))
        self.classifier = TFliteClassifier(classifier)

    def detect(self, image, threshold=0.75):
        dets = self.detector.detect(image, threshold)
        res = []
        for d in dets:
            if d['class']=="Bird":
                box = d['box']
                bird = image[box[1]:box[3], box[0]:box[2]]
                bird_type = self.classifier.classify(bird)
                obj = {"class": bird_type[0]['class'], "score": bird_type[0]['score'], "box": box}
            else:
                obj = d
            res.append(obj)
        return res

    def classes(self):
        return [NON_BIRD] + self.classifier.classes()


 
class Birdfeeder:
    def __init__(self):

        # Create Kritter server.
        self.kapp = Vizy()

        # Initialize variables.
        config_filename = os.path.join(self.kapp.etcdir, CONFIG_FILE)      
        self.config = kritter.ConfigFile(config_filename, DEFAULT_CONFIG)               
        consts_filename = os.path.join(BASEDIR, CONSTS_FILE) 
        self.config_consts = kritter.import_config(consts_filename, self.kapp.etcdir, ["IMAGES_KEEP", "IMAGES_DISPLAY", "PICKER_TIMEOUT", "GPHOTO_ALBUM", "MEDIA_QUEUE_IMAGE_WIDTH", "DEFEND_BIT", "CLASSIFIER", "TRACKER_DISAPPEARED_DISTANCE", "TRACKER_MAX_DISAPPEARED", "TRACKER_CLASS_SWITCH"]) 
        self.lock = RLock()
        self.record = None
        self._grab_thread = None
        self.detector = None
        self.record_state = WAITING
        self.take_pic = False
        self.defend_thread = None
        self.daytime = kritter.CalcDaytime(DAYTIME_THRESHOLD, DAYTIME_POLL_PERIOD)
        # Create unique identifier to mark photos
        self.uuid = bytes(self.kapp.uuid).hex().upper()
        # Map 1 to 100 (sensitivity) to 0.9 to 0.1 (detection threshold)
        self.sensitivity_range = kritter.Range((1, 100), (0.9, 0.1), inval=self.config['detection_sensitivity']) 

        # Initialize power board defense bit.
        self.kapp.power_board.vcc12(True)
        self.kapp.power_board.io_set_mode(self.config_consts.DEFEND_BIT, vpb.IO_MODE_HIGH_CURRENT)
        self.kapp.power_board.io_set_bit(self.config_consts.DEFEND_BIT) # set defend bit to high (turn off)

        # Create and start camera.
        self.camera = kritter.Camera(hflip=True, vflip=True, mem_reserve=50)
        self.stream = self.camera.stream()
        self.camera.mode = CAMERA_MODE
        self.camera.brightness = self.config['brightness']
        self.camera.framerate = 20
        self.camera.autoshutter = True
        self.camera.awb = True

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
            tv_table = KtextVisorTable({"mrm": (mrm, "Displays the most recent birdfeeder picture/video, or n media with optional n argument.")})
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

        self.gcloud = kritter.Gcloud(self.kapp.etcdir)
        self.gphoto_interface = self.gcloud.get_interface("KstoreMedia")
        self.store_media = kritter.SaveMediaQueue(path=MEDIA_DIR, keep=self.config_consts.IMAGES_KEEP, keep_uploaded=self.config_consts.IMAGES_KEEP)
        if self.config['gphoto_upload']:
            self.store_media.store_media = self.gphoto_interface 
        self.tracker = kritter.DetectionTracker(maxDisappeared=self.config_consts.TRACKER_MAX_DISAPPEARED, maxDistance=self.config_consts.TRACKER_DISAPPEARED_DISTANCE, classSwitch=self.config_consts.TRACKER_CLASS_SWITCH)
        self.picker = kritter.DetectionPicker(timeout=self.config_consts.PICKER_TIMEOUT)
        self.detector_process = kritter.Processify(BirdInference, (os.path.join(BASEDIR, self.config_consts.CLASSIFIER),))
        self._handle_detector()

        if self.config['species_of_interest'] is None:
            self.config['species_of_interest'] = self.detector_process.classes()
            self.config['species_of_interest'].remove(NON_BIRD)
            self.config.save()
        self._set_threshold()
        self._handle_sharing()

        dstyle = {"label_width": 5, "control_width": 5}

        # Create video component and histogram enable.
        self.video = kritter.Kvideo(width=STREAM_WIDTH, overlay=True)
        brightness = kritter.Kslider(name="Brightness", value=self.camera.brightness, mxs=(0, 100, 1), format=lambda val: f'{val}%', style={"control_width": 4}, grid=False)
        self.take_pic_c = kritter.Kbutton(name=[kritter.Kritter.icon("camera"), "Take picture"], spinner=True)
        self.video_c = kritter.Kbutton(name=[kritter.Kritter.icon("video-camera"), "Take video"], spinner=True)
        self.defend = kritter.Kbutton(name=[kritter.Kritter.icon("bomb"), "Defend"], spinner=True)
        settings_button = kritter.Kbutton(name=[kritter.Kritter.icon("gear"), "Settings..."], service=None)
        self.take_pic_c.append(self.video_c)
        self.take_pic_c.append(self.defend)
        self.take_pic_c.append(settings_button)

        self.media_queue =  MediaDisplayQueue(MEDIA_DIR, STREAM_WIDTH, CAMERA_WIDTH, self.config_consts.MEDIA_QUEUE_IMAGE_WIDTH, self.config_consts.IMAGES_DISPLAY) 
        sensitivity = kritter.Kslider(name="Detection sensitivity", value=self.config['detection_sensitivity'], mxs=(1, 100, 1), format=lambda val: f'{int(val)}%', style=dstyle)
        species_of_interest = kritter.Kchecklist(name="Species of interest", options=self.detector_process.classes(), value=self.config['species_of_interest'], clear_check_all=True, scrollable=True, style=dstyle)
        pest_species = kritter.Kchecklist(name="Pest species", options=self.detector_process.classes(), value=self.config['pest_species'], clear_check_all=True, scrollable=True, style=dstyle)
        trigger_species = kritter.Kchecklist(name="Trigger species", options=self.detector_process.classes(), value=self.config['trigger_species'], clear_check_all=True, scrollable=True, style=dstyle)
        smooth_video = kritter.Kcheckbox(name="Smooth video", value=self.config['smooth_video'], style=dstyle)
        upload = kritter.Kcheckbox(name="Upload to Google Photos", value=self.config['gphoto_upload'], disabled=self.gphoto_interface is None, style=dstyle)
        share = kritter.Kcheckbox(name="Share photos to help improve accuracy", value=self.config['share_photos'], disabled=self.gphoto_interface is None, spinner=True, style=dstyle)
        text_new = kritter.Kcheckbox(name="Text new species", value=self.config['text_new_species'], style=dstyle, disabled=self.tv is None)
        defense_duration = kritter.Kslider(name="Defense duration", value=self.config['defense_duration'], mxs=(0, 10, .1), format=lambda val: f'{val}s', style=dstyle)
        rdefense = kritter.Kcheckbox(name="Record defense", value=self.config['record_defense'], style=dstyle)

        dlayout = [species_of_interest, pest_species, trigger_species, sensitivity, defense_duration, rdefense, upload, share, text_new, smooth_video]
        settings = kritter.Kdialog(title=[kritter.Kritter.icon("gear"), "Settings"], layout=dlayout)
        controls = html.Div([brightness, self.take_pic_c])

        # Add video component and controls to layout.
        self.kapp.layout = html.Div([html.Div([self.video, self.media_queue.layout]), controls, settings], style={"padding": "15px"})
        self.kapp.push_mods(self.media_queue.out_images())

        @brightness.callback()
        def func(value):
            self.config['brightness'] = value
            self.camera.brightness = value
            self.config.save()

        @self.video_c.callback()
        def func():
            if self.record_state==SAVING:
                return
            else:
                with self.lock:
                    self.record_state += 1
                    return self._update_record()

        @self.take_pic_c.callback()
        def func():
            self.take_pic = True
            return self.take_pic_c.out_spinner_disp(True)

        @self.defend.callback()
        def func():
            self._run_defense(True)

        @sensitivity.callback()
        def func(value):
            self.config['detection_sensitivity'] = value
            self._set_threshold() 
            self.config.save()

        @species_of_interest.callback()
        def func(value):
            self.config['species_of_interest'] = value
            self.config.save()

        @pest_species.callback()
        def func(value):
            self.config['pest_species'] = value
            self.config.save()

        @trigger_species.callback()
        def func(value):
            self.config['trigger_species'] = value
            self.config.save()

        @smooth_video.callback()
        def func(value):
            self.config['smooth_video'] = value  
            self.config.save()
            self._stop_detector_and_thread()
            self._handle_detector()
            self._run_grab_thread()

        @upload.callback()
        def func(value):
            self.config['gphoto_upload'] = value  
            self.store_media.store_media = self.gphoto_interface if value else None
            self.config.save()

        @share.callback()
        def func(value):
            self.kapp.push_mods(share.out_spinner_disp(True))
            mods = share.out_spinner_disp(False)
            self.config['share_photos'] = value  
            self.store_media.store_media = self.gphoto_interface if value else None
            self._handle_sharing()
            self.config.save()
            if value and not self.config['gphoto_upload']: 
                return mods + upload.out_value(True)
            return mods

        @text_new.callback()
        def func(value):
            self.config['text_new_species'] = value 
            self.config.save()

        @defense_duration.callback()
        def func(value):
            self.config['defense_duration'] = value 
            self.config.save()

        @rdefense.callback()
        def func(value):
            self.config['record_defense'] = value 
            self.config.save()

        @settings_button.callback()
        def func():
            return settings.out_open(True)

        # Run camera grab thread.
        self.run_thread = True
        self._grab_thread = Thread(target=self.grab_thread)
        self._grab_thread.start()

        # Run Kritter server, which blocks.
        self.kapp.run()
        self._stop_detector_and_thread()
        self.detector_process.close()
        self.store_media.close()

    def _run_grab_thread(self):
        # Run camera grab thread.
        if self._grab_thread is None:    
            self.run_thread = True
            self._grab_thread = Thread(target=self.grab_thread)
            self._grab_thread.start()

    def _stop_detector_and_thread(self):
        # Stop thread
        if self._grab_thread is not None:
            self.run_thread = False
            self._grab_thread.join()
            self._grab_thread = None
        # Stop detector
        if self.detector and isinstance(self.detector, kritter.KimageDetectorThread):
            self.detector.close()

    def _handle_detector(self):
        if self.config['smooth_video']:
            self.detector = kritter.KimageDetectorThread(self.detector_process)
        else:
            self.detector = self.detector_process

    def _handle_sharing(self):
        if self.config['share_photos'] and not self.config['share_url_emailed'] and self.gphoto_interface is not None:
            # Try to get location information so we know where the pictures are coming from
            try:
                res = urlopen('https://ipinfo.io/json')
                location_data = json.load(res)
            except:
                location_data = {}
            # Only send location info -- not IP information
            location_data = {"country": location_data.get('country', 'Unknown'), "region": location_data.get('region', 'Unknown'), "city": location_data.get('city', 'Unknown'), "loc": location_data.get('loc', 'Unknown')}
            try:
                self.config['share_url'] = self.gphoto_interface.get_share_url(self.config_consts.GPHOTO_ALBUM)
                if self.config['share_url']:
                    email = self.gcloud.get_interface("KtextClient") # Gmail
                    message = {**location_data, "uuid": self.uuid, "url": self.config['share_url']}
                    message = json.dumps(message)
                    email.text("vizycamera@gmail.com", message, subject="Birdfeeder album share")
                    email.send()
                    self.config['share_url_emailed'] = True
                    self.config.save()
            except Exception as e:
                print(f"Tried to send photo album share URL but failed. ({e})")


    def _set_threshold(self):
        self.sensitivity_range.inval = self.config['detection_sensitivity']
        threshold = self.sensitivity_range.outval
        self.tracker.setThreshold(threshold)
        self.low_threshold = threshold - THRESHOLD_HYSTERESIS
        if self.low_threshold<MIN_THRESHOLD:
            self.low_threshold = MIN_THRESHOLD 

    # Frame grabbing thread
    def grab_thread(self):
        last_tag = ""
        while self.run_thread:
            mods = []
            timestamp = self._timestamp()
            # Get frame
            frame = self.stream.frame()[0]

            # Handle daytime/nighttime logic
            daytime, change = self.daytime.is_daytime(frame)
            if change:
                if daytime:
                    handle_event(self, {"event_type": 'daytime'})
                else:
                    handle_event(self, {"event_type": 'nighttime'})

            # Handle video tag
            tag =  f"{timestamp} daytime" if daytime else  f"{timestamp} nighttime"
            if tag!=last_tag:
                self.video.overlay.draw_clear(id="tag")
                self.video.overlay.draw_text(0, frame.shape[0]-1, tag, fillcolor="black", font=dict(family="sans-serif", size=12, color="white"), xanchor="left", yanchor="bottom", id="tag")
                mods += self.video.overlay.out_draw()
                last_tag = tag

            if daytime:
                detect = self.detector.detect(frame, self.low_threshold)
            else:
                detect = [], None
            if detect is not None:
                if isinstance(detect, tuple):
                    dets, det_frame = detect 
                else:
                    dets, det_frame = detect, frame
                # Remove classes that aren't active
                dets = self._filter_dets(dets)
                # Feed detections into tracker
                dets = self.tracker.update(dets, showDisappeared=True)
                # Update picker
                mods += self._handle_picks(det_frame, dets)
                # Deal with pests
                self._handle_pests(dets)
                # Render tracked detections to overlay
                mods += kritter.render_detected(self.video.overlay, dets)

            # Sleep to give other threads a boost 
            time.sleep(0.01)

            # Send frame
            self.video.push_frame(frame)
            # Handle manual picture
            if self.take_pic:
                self.store_media.store_image_array(frame, album=self.config_consts.GPHOTO_ALBUM, desc="Manual picture", data={'uuid': self.uuid, 'width': frame.shape[0], 'height': frame.shape[1], "timestamp": self._timestamp()})
                mods += self.media_queue.out_images() + self.take_pic_c.out_spinner_disp(False)
                self.take_pic = False 

            # Handle manual video
            mods += self._handle_record()            

            try:
                self.kapp.push_mods(mods)
            except: 
                pass

            # Sleep to give other threads a boost 
            time.sleep(0.01)

    def _run_defense(self, block):
        if not block:
            if not self.defend_thread or not self.defend_thread.is_alive():
                self.defend_thread = Thread(target=self._run_defense, args=(True,))
                self.defend_thread.start()
            return
        else:
            handle_event(self, {"event_type": 'defend'})
            self.kapp.push_mods(self.defend.out_spinner_disp(True))
            # If self.record isn't None, we're in the middle of recording/saving, so skip
            if self.config['record_defense'] and self.record is None:
                with self.lock:
                    self.record = self.camera.record()
                    self.save_thread = Thread(target=self._save_video, args=("Defense video",))
                    self.save_thread.start()
                    self.record_state = SAVING
                    self.kapp.push_mods(self._update_record(False))
                time.sleep(PRE_POST_ROLL)
            # set defend bit to low (turn on)
            self.kapp.power_board.io_reset_bit(self.config_consts.DEFEND_BIT)
            time.sleep(self.config['defense_duration'])
            # set defend bit to high (turn off)
            self.kapp.power_board.io_set_bit(self.config_consts.DEFEND_BIT) 
            if self.config['record_defense']:
                if self.record:
                    time.sleep(PRE_POST_ROLL)
                    try: # self.record may be None here because we've been sleeping...
                        self.record.stop()
                    except: 
                        pass
            self.kapp.push_mods(self.defend.out_spinner_disp(False))

    def _handle_pests(self, dets):
        defend = False
        for k, v in dets.items():
            for j in self.config['pest_species']:
                if v['class']==j:
                    v['class'] += " INTRUDER!"
                    defend = True
        if defend:
            self._run_defense(False)
        

    def _timestamp(self):
        return datetime.datetime.now().strftime("%a %H:%M:%S")

    def _handle_picks(self, frame, dets):
        mods = []
        picks = self.picker.update(frame, dets)
        # Get regs (new entries) and deregs (deleted entries)
        regs, deregs = self.picker.get_regs_deregs()
        if regs:
            handle_event(self, {'event_type': 'register', 'dets': regs})
        if picks:
            for i in picks:
                image, data = i[0], i[1]
                timestamp = self._timestamp()
                _data = {'dets': [data], 'width': image.shape[1], 'height': image.shape[0], "timestamp": timestamp, 'uuid': self.uuid}
                event = {**data, 'image': image, "timestamp": timestamp}
                if data['class'] in self.config['species_of_interest']:
                    event['event_type'] = 'species_of_interest'
                    handle_event(self, event)
                    # Save picture and metadata, add width and height of image to data so we don't
                    # need to decode it to set overlay dimensions.
                    self.store_media.store_image_array(image, album=self.config_consts.GPHOTO_ALBUM, data=_data)
                    if data['class'] not in self.config['seen_species']:
                        self.config['seen_species'].append(data['class'])
                        self.config.save()
                        if self.tv and self.config['text_new_species']:
                            # Send new species text message with image
                            self.tv.send([f"New species! {timestamp} {data['class']}", Image(image)])
                if data['class'] in self.config['trigger_species']:
                    event['event_type'] = 'trigger'
                    handle_event(self, event)
                if data['class'] in self.config['pest_species']: # pest_species
                    event['event_type'] = 'pest_species'
                    handle_event(self, event)
            mods = self.media_queue.out_images()
        if deregs:    
            handle_event(self, {'event_type': 'deregister', 'deregs': deregs})
        return mods      

    def _filter_dets(self, dets):
        classes = set(self.config['species_of_interest']).union(self.config['pest_species'])
        dets = [det for det in dets if det['class'] in classes]
        return dets

    def _update_progress(self, percentage):
        if self.record_state==SAVING:
            self.kapp.push_mods(self.video_c.out_name([kritter.Kritter.icon("video-camera"), f"Saving... {percentage}%"]))

    def _save_video(self, desc):
        self.store_media.store_video_stream(self.record, fps=self.camera.framerate, album=self.config_consts.GPHOTO_ALBUM, desc=desc, data={'uuid': self.uuid, 'width': self.camera.resolution[0], 'height': self.camera.resolution[1], "timestamp": self._timestamp()}, thumbnail=True, progress_callback=self._update_progress)
        self.record = None # free up memory, indicate that we're done.
        self.kapp.push_mods(self.media_queue.out_images())

    def _update_record(self, stop=True):
        with self.lock:
            if self.record_state==WAITING:
                return self.video_c.out_name([kritter.Kritter.icon("video-camera"), "Take video"])+self.video_c.out_spinner_disp(False)
            elif self.record_state==RECORDING:
                # Record, save, encode simultaneously
                self.record = self.camera.record()
                self.save_thread = Thread(target=self._save_video, args=("Manual video",))
                self.save_thread.start()
                return self.video_c.out_name([kritter.Kritter.icon("video-camera"), "Stop video"])+self.video_c.out_spinner_disp(True, disable=False)
            elif self.record_state==SAVING:
                if stop:
                    self.record.stop()
                return self.video_c.out_name([kritter.Kritter.icon("video-camera"), "Saving..."])+self.video_c.out_spinner_disp(True)

    def _handle_record(self):
        with self.lock:
            if self.record_state==RECORDING:
                if not self.record.recording():
                    self.record_state = SAVING
                    return self._update_record()
            elif self.record_state==SAVING:
                if not self.save_thread.is_alive():
                    self.record_state = WAITING
                    return self._update_record()
        return []

if __name__ == "__main__":
    Birdfeeder()
