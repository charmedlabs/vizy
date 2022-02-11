#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

import numpy as np 
import cv2 
import time
import collections
from threading import RLock
from tab import Tab
import kritter
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
from motionscope_consts import WIDTH, PLAY_RATE
from graphs import Graphs
  

GRAPH_UPDATE_TIMEOUT = 0.15

def merge_data(map, add):
    for i, d in add.items():
        if i in map:
            map[i] = np.vstack((map[i], d))
        else:
            map[i] = np.array([d])


class Analyze(Tab):

    def __init__(self, kapp, data, camera, video, num_graphs):

        super().__init__("Analyze", kapp, data)
        self.stream = camera.stream()
        self.lock = RLock()
        self.graph_update_timer = kritter.FuncTimer(GRAPH_UPDATE_TIMEOUT)
        self.data_spacing_map = {}
        style = {"label_width": 2, "control_width": 7, "max_width": WIDTH}

        self.spacing_c = kritter.Kslider(name="Spacing", mxs=(1, 10, 1), updaterate=6, style=style)
        self.time_c = kritter.Kslider(name="Time", range=True, value=[0, 10], mxs=(0, 10, 1), updaterate=6, style=style)

        self.settings_map = {"spacing": self.spacing_c.out_value, "time": self.time_c.out_value}
        self.graphs = Graphs(self.kapp, self.data, self.data_spacing_map, self.settings_map, self.lock, video, num_graphs, style) 

        self.layout = dbc.Collapse([self.spacing_c, self.time_c] + self.graphs.controls_layout, id=self.kapp.new_id())

        @self.spacing_c.callback()
        def func(val):
            self.data[self.name]["spacing"] = val
            self.spacing = val
            self.render()

        @self.time_c.callback()
        def func(val):
            self.data[self.name]["time"] = val     
            self.curr_first_index, self.curr_last_index = val
            self.render()


    def precompute(self):
        # Keep in mind that self.data['obj_data'] may have multiple objects with
        # data point indexes that don't correspond perfectly with data point indexes
        # of sibling objects.
        max_points = []
        ptss = []
        indexes = []
        self.data_index_map = collections.defaultdict(dict)
        for k, data in self.data['obj_data'].items():
            max_points.append(len(data))
            ptss = np.append(ptss, data[:, 0])  
            indexes = np.append(indexes, data[:, 1]).astype(int)
            for d in data:
                self.data_index_map[int(d[1])][k] = d
        self.time_index_map = dict(zip(list(indexes), list(ptss))) 
        self.time_index_map = dict(sorted(self.time_index_map.items()))
        self.indexes = list(self.time_index_map.keys()) # sorted and no duplicates
        ptss = np.array(list(self.time_index_map.values())) # sorted and no duplicates
        self.curr_first_index = self.indexes[0]
        self.curr_last_index = self.indexes[-1]
        # Periods can be greater than actual frame period because of dropped frames.
        # Finding the minimum period of all frames is overkill, but gets us what we want.   
        self.frame_period = np.min(ptss[1:]-ptss[:-1]) 
        self.zero_index_map = dict(zip(self.indexes, [0]*len(self.indexes)))
        self.curr_render_index_map = self.zero_index_map.copy()
        self.max_points = max(max_points)

    def recompute(self):
        self.data_spacing_map.clear() 
        self.next_render_index_map = self.zero_index_map.copy()
        self.next_render_index_map[self.curr_first_index] = 1
        t0 = self.time_index_map[self.curr_first_index]
        merge_data(self.data_spacing_map, self.data_index_map[self.curr_first_index])
        for i, t in self.time_index_map.items():
            if i>self.curr_last_index:
                break
            if t-t0>=self.frame_period*(self.spacing-0.5):
                self.next_render_index_map[i] = 1
                merge_data(self.data_spacing_map, self.data_index_map[i])
                t0 = t

    def compose_frame(self, index, val):
        if val>0:
            self.data['recording'].seek(index)
            frame = self.data['recording'].frame()[0]
        else:
            frame = self.data['bg']
        dd = self.data_index_map[index]  
        for k, d in dd.items():
            self.pre_frame[int(d[5]):int(d[5]+d[7]), int(d[4]):int(d[4]+d[6]), :] = frame[int(d[5]):int(d[5]+d[7]), int(d[4]):int(d[4]+d[6]), :]

    def compose(self):
        next_values = list(self.next_render_index_map.values())
        diff = list(np.array(next_values) - np.array(list(self.curr_render_index_map.values())))
        for i, d in enumerate(diff):
            # If i in diff is -1 (erase) change diff's neighbors within distance n=3 to 
            # to 1's if next_value at same location is 1. (This is needed because objects overlap
            # between frames.)
            if d<0:
                for j in range(3):
                    if i>j and next_values[i-j-1]>0:
                        diff[i-j-1] = 1
                    if i<len(next_values)-j-1 and next_values[i+j+1]>0:
                        diff[i+j+1] = 1

        diff_map = dict(zip(self.indexes, diff))

        # Erase all objects first
        for i, v in diff_map.items():
            if v<0: 
                self.compose_frame(i, v)
        # Then add objects
        for i, v in diff_map.items():
            if v>0: 
                self.compose_frame(i, v)

        self.curr_render_index_map = self.next_render_index_map
        self.curr_frame = self.pre_frame.copy()

    def graph_update(self):
        self.kapp.push_mods(self.graphs.out_draw())

    def render(self):
        with self.lock:
            self.recompute()
            self.compose()
            self.graph_update_timer.start(self.graph_update)

    def data_update(self, changed, cmem=None):
        if self.name in changed:
            # Copy before we push any mods, because the mods will change the values
            # when the callbacks are called.
            settings = self.data[self.name].copy()

        if "obj_data" in changed and self.data['obj_data']:
            self.pre_frame = self.data['bg'].copy()
            self.spacing = 1
            self.precompute()
            self.time_c.set_format(lambda val : f'{self.time_index_map[val[0]]:.3f}s → {self.time_index_map[val[1]]:.3f}s')
            # Send mods off because they might conflict with mods self.name, and 
            # calling push_mods forces calling render() early. 
            self.kapp.push_mods(self.spacing_c.out_max(self.max_points//8) + self.spacing_c.out_value(self.spacing) + self.time_c.out_min(self.indexes[0]) + self.time_c.out_max(self.indexes[-1]) + self.time_c.out_value((self.curr_first_index, self.curr_last_index)))

        if self.name in changed:
            for k, s in self.settings_map.items():
                try:
                    # Push each mod individually because of they will affect each other
                    self.kapp.push_mods(s(settings[k]))
                except:
                    pass
        return []

    def frame(self):
        self.graphs.update()
        self.graph_update_timer.update()
        time.sleep(1/PLAY_RATE)
        return self.curr_frame

    def focus(self, state):
        if state:
            self.stream.stop()
            return self.graphs.out_draw() + self.graphs.out_disp(True)
        else:
            return self.graphs.out_disp(False)   

