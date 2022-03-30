#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

from tab import Tab
import time
import kritter
from threading import Lock
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
from motionscope_consts import MAX_RECORDING_DURATION, PLAY_RATE, UPDATE_RATE
from dash_devices import callback_context

LOADING = -2
PRE_RECORDING = -1
STOPPED = 0
RECORDING = 1

class Capture(Tab):

    def __init__(self, kapp, data, camera):

        super().__init__("Capture", kapp, data)
        self.ratio = 0.1
        self.update_timer = 0
        self.curr_frame = None
        self.prev_mods = []
        self.lock = Lock()
        self.camera = camera
        self.data["recording"] = None
        self.new_recording = False
        self.pre_record = None
        self.playing = False
        self.paused = False
        self.stream = self.camera.stream()
        self.duration = MAX_RECORDING_DURATION
        self.start_shift = 0
        self.trigger_sensitivity = 50
        self.more = False

        style = {"label_width": 3, "control_width": 6}
        self.status = kritter.Ktext(value="Press Record to begin.")
        self.playback_c = kritter.Kslider(value=0, mxs=(0, 1, .001), updatetext=False, updaterate=0, disabled=True, style={"control_width": 8})

        self.record = kritter.Kbutton(name=[kapp.icon("circle"), "Record"])
        self.play = kritter.Kbutton(name=self.play_name(), disabled=True)
        self.stop_button = kritter.Kbutton(name=[kapp.icon("stop"), "Stop"], disabled=True)
        self.step_backward = kritter.Kbutton(name=kapp.icon("step-backward", padding=0), disabled=True)
        self.step_forward = kritter.Kbutton(name=kapp.icon("step-forward", padding=0), disabled=True)
        self.more_c = kritter.Kbutton(name=kapp.icon("plus", padding=0))

        self.record.append(self.play)
        self.record.append(self.stop_button)
        self.record.append(self.step_backward)
        self.record.append(self.step_forward)
        self.record.append(self.more_c)

        self.start_shift_c = kritter.Kslider(name="Start-shift", value=self.start_shift, mxs=(-5.0, 5, .01), format=lambda val: f'{val:.2f}s', style=style)
        self.duration_c = kritter.Kslider(name="Duration", value=self.duration, mxs=(0, MAX_RECORDING_DURATION, .01), format=lambda val: f'{val:.2f}s', style=style)
        self.trigger_modes = ["button press", "auto-trigger", "auto-trigger, auto-analyze"]
        self.trigger_mode = self.trigger_modes[0]
        self.trigger_modes_c = kritter.Kdropdown(name='Trigger mode', options=self.trigger_modes, value=self.trigger_mode, style=style)
        self.trigger_sensitivity_c = kritter.Kslider(name="Trigger sensitivitiy", value=self.trigger_sensitivity, mxs=(1, 100, 1), style=style)

        more_controls = dbc.Collapse([self.start_shift_c, self.duration_c, self.trigger_modes_c, self.trigger_sensitivity_c], id=kapp.new_id(), is_open=self.more)
        self.layout = dbc.Collapse([self.playback_c, self.status, self.record, more_controls], id=kapp.new_id(), is_open=False)

        @self.start_shift_c.callback()
        def func(val):
            self.start_shift = val
            with self.lock:
                if self.start_shift<0:
                    if self.pre_record is None:
                        self.pre_record = self.camera.record(duration=self.duration, start_shift=self.start_shift)
                    else:
                        self.pre_record.start_shift = val
                else:
                    if self.pre_record:
                        self.pre_record.stop()
                        self.pre_record = None
                    
        @self.duration_c.callback()
        def func(val):
            self.duration = val
            with self.lock:
                # We can change the duration on-the-fly.
                if self.pre_record:
                    self.pre_record.duration = self.duration
                if self.data['recording']:
                    self.data['recording'].duration = self.duration

        @self.more_c.callback()
        def func():
            self.more = not self.more
            return self.more_c.out_name(kapp.icon("minus", padding=0) if self.more else kapp.icon("plus", padding=0)) + [Output(more_controls.id, "is_open", self.more)]

        @self.record.callback()
        def func():
            with self.lock:
                if self.pre_record:
                    print("*** start")
                    self.pre_record.start()
                    self.data['recording'] = self.pre_record
                    self.pre_record = None
                else:
                    self.data['recording'] = self.camera.record(duration=self.duration, start_shift=self.start_shift)
                self.new_recording = True
                self.playing = False
                self.paused = False
            return self.update()

        @self.play.callback()
        def func():
            with self.lock:
                if self.playing:
                    self.paused = not self.paused
                self.playing = True
            return self.update()

        self.stop_button.callback()(self.stop)

        @self.step_backward.callback()
        def func():
            with self.lock:
                self.playing = True  
                self.paused = True 
            self.data["recording"].seek(self.curr_frame[2]-1)
            frame = self.data["recording"].frame()
            return self.playback_c.out_value(frame[1])

        @self.step_forward.callback()
        def func():
            with self.lock:
                self.playing = True  
                self.paused = True 
            frame = self.data["recording"].frame()
            if frame is not None:
                return self.playback_c.out_value(frame[1])


        @self.playback_c.callback()
        def func(t):
            with self.lock:
                # Check for client dragging slider when we're stopped, in which case, 
                # go into paused state.
                if not self.playing and not self.data["recording"].recording() and callback_context.client and t!=0:
                        self.playing = True 
                        self.paused = True

                if self.playing:
                    # Only seek if client actually dragged slider, not when we set it ourselves.
                    if callback_context.client:
                        print("time_seek")
                        t = self.data["recording"].time_seek(t) # Update time to actual value.
                    if self.paused:
                        self.curr_frame = self.data["recording"].frame()
                        self.lock.release()
                        time.sleep(1/UPDATE_RATE)
                        self.lock.acquire()
            if t is not None:
                return self.playback_c.out_text(f"{t:.3f}s")

    def stop(self):
        with self.lock:
            self.playing = False
            self.paused = False
        if self.data["recording"]:
            self.data["recording"].stop()
            self.data["recording"].seek(0)
        return self.update()

    def play_name(self):
        return [self.kapp.icon("pause"), "Pause"] if self.playing and not self.paused else [self.kapp.icon("play"), "Play"]

    def update(self, cmem=None):
        mods = []
        record_disable = False
        with self.lock:
            if self.pre_record and self.pre_record.start_shift<0 and self.pre_record.recording()==PRE_RECORDING:
                if self.pre_record.time_len()<-self.pre_record.start_shift*0.75:
                    record_disable = True
            if self.data["recording"]:
                t = self.data["recording"].time() 
                tlen = self.data["recording"].time_len()
                mods += self.play.out_name(self.play_name())
                recording = self.data["recording"].recording() 
                if self.playing:
                    if self.paused:
                        mods += self.step_backward.out_disabled(self.curr_frame[2]==0) + self.step_forward.out_disabled(self.curr_frame[2]==self.data["recording"].len()-1) + self.status.out_value("Paused")
                    else: 
                        mods += self.playback_c.out_disabled(False) + self.step_backward.out_disabled(True) + self.step_forward.out_disabled(True) + self.playback_c.out_value(t) + self.status.out_value("Playing...") 
                    mods += self.record.out_disabled(True) + self.stop_button.out_disabled(False) + self.play.out_disabled(False) + self.playback_c.out_max(tlen) 
                elif recording!=0:
                    mods += self.playback_c.out_disabled(True) + self.record.out_disabled(True) + self.stop_button.out_disabled(False) + self.play.out_disabled(True) + self.step_backward.out_disabled(True) + self.step_forward.out_disabled(True) + self.playback_c.out_max(self.duration) + self.status.out_value("Recording..." if recording==RECORDING else "Waiting...") + self.playback_c.out_value(tlen)
                else: # Stopped
                    mods += self.playback_c.out_disabled(False) + self.playback_c.out_max(tlen) + self.playback_c.out_value(0) + self.record.out_disabled(record_disable) + self.stop_button.out_disabled(True) + self.step_backward.out_disabled(True) + self.step_forward.out_disabled(False) + self.play.out_disabled(False) + self.status.out_value("Buffering..." if record_disable else "Stopped") + ["stop_marker"]
                    if self.start_shift<0 and self.pre_record is None:
                        print("start pre_record")
                        self.pre_record = self.camera.record(duration=self.duration, start_shift=self.start_shift)

            else: # No self.data["recording"], but 
                mods += self.record.out_disabled(record_disable) + self.status.out_value("Buffering..." if record_disable else "Press Record to begin")

        # Find new mods with respect to the previous mods
        diff_mods = [m for m in mods if not m in self.prev_mods]
        # Save current mods
        self.prev_mods = mods 
        # Stop marker allows us to see the stop event by detecting it in diff_mods.
        if "stop_marker" in diff_mods:
            diff_mods.remove("stop_marker")
            if self.new_recording:
                self.new_recording = False # This prevents a loaded video (from Load) from triggering recording_update
                self.data['recording'] = self.data["recording"]
                if cmem is None:
                    self.kapp.push_mods(diff_mods)
                    diff_mods = self.call_data_update_callback("recording", 1) 
        # Only send new mods
        return diff_mods    

    def data_update(self, changed, cmem=None):
        mods = []
        if "recording" in changed and cmem is None:
            with self.lock:
                self.playing = False
                self.paused = False
            mods += self.update(1)
        return mods

    def frame(self):
        update = False

        if self.playing:
            if not self.paused:
                self.curr_frame = self.data['recording'].frame()
                if self.curr_frame is None:
                    with self.lock:
                        self.playing = False
                        self.paused = False
                    self.data['recording'].seek(0)
                    update = True

        t = time.time()
        if update or t-self.update_timer>1/UPDATE_RATE:
            self.update_timer = t
            mods = self.update()
            if mods:
                self.kapp.push_mods(mods)

        if self.playing and self.curr_frame is not None: # play recording
            return self.curr_frame[0], 1/PLAY_RATE
        else: # stream live
            frame = self.stream.frame()
            if frame:
                return frame[0]

    def focus(self, state):
        return self.stop()
