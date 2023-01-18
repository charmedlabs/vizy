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
import os
import json
import collections
from threading import RLock
from tab import Tab
import dash_html_components as html
from quart import redirect, send_file
import kritter
from kritter import Gcloud
from dash_devices.dependencies import Output
import dash_bootstrap_components as dbc
from graphs import Graphs, transform
from pandas import DataFrame


GRAPH_UPDATE_TIMEOUT = 0.15
EXPORT_FILENAME = "motionscope_data"
MAX_OBJECTS = len(kritter.get_color.colors) # For now we only display as many objects as we have colors
REDIRECT_PAGE = """
<!DOCTYPE html>
<html>
<body>
Your Google Sheet can be found here: <a href="{0}">{0}</a>.
</body>
</html>
"""

def merge_data(map, add):
    for i, d in add.items():
        if i in map:
            map[i] = np.vstack((map[i], d))
        else:
            map[i] = np.array([d])


class Analyze(Tab):

    def __init__(self, main):

        super().__init__("Analyze", main.data)
        self.main = main
        self.gtabular = Gcloud(self.kapp.etcdir).get_interface("KtabularClient")
        self.matrix = np.identity(3, dtype="float32")
        self.stream = main.camera.stream()
        self.perspective = main.perspective
        self.lock = RLock()
        self.graph_update_timer = kritter.FuncTimer(GRAPH_UPDATE_TIMEOUT)
        self.data_spacing_map = {}
        self.data_index_map = {}
        style = {"label_width": 3, "control_width": 6, "max_width": self.main.config_consts.WIDTH}

        self.export_map = {"Table...": ("table", None), "Comma-separated values (.csv)": ("csv", None), "Excel (.xlsx)": ("xlsx", None), "JSON (.json)": ("json", None)}
        if self.gtabular:
            self.export_map["Google Sheets"] = ("sheets", None)

        self.spacing_c = kritter.Kslider(name="Spacing", mxs=(1, 10, 1), updaterate=6, style=style)
        self.time_c = kritter.Kslider(name="Time", range=True, mxs=(0, 10, 1), updaterate=6, style=style)

        self.settings_map = {"spacing": self.spacing_c.out_value, "time": self.time_c.out_value, "obj_render": self.update_obj_render}
        self.graphs = Graphs(self.kapp, self.data, self.data_spacing_map, self.settings_map, self.lock, self.main.video, self.main.config_consts.GRAPHS, style) 
        options = [dbc.DropdownMenuItem(k, id=self.kapp.new_id(), href="export/"+v[0], target="_blank", external_link=True) for k, v in self.export_map.items()]
        # We don't want the export funcionality to be shared! (service=None)
        self.export = kritter.KdropdownMenu(name="Export data", options=options, service=None)
        self.obj_box_ids = [self.kapp.new_id() for i in range(MAX_OBJECTS)]
        self.obj_checkboxes = [kritter.Kcheckbox(name=html.Div(html.Div(id=self.obj_box_ids[i])), style=style, disp=False) for i in range(MAX_OBJECTS)]

        self.layout = dbc.Collapse([self.spacing_c, self.time_c] + self.graphs.controls_layout + self.obj_checkboxes + [self.export], id=self.kapp.new_id())

        def checkbox_func(index):
            def func(val):
                objs = list(self.sorted_obj_data.keys())
                if  self.data[self.name]["obj_render"][objs[index]]!=val:
                    self.data[self.name]["obj_render"][objs[index]] = val
                    # reset composite frame
                    self.curr_render_index_map = self.zero_index_map.copy()
                    self.next_render_index_map = self.zero_index_map.copy()
                    self.pre_frame = self.data['bg'].copy()
                    self.render()
            return func 
        for i in range(MAX_OBJECTS):
            self.obj_checkboxes[i].callback()(checkbox_func(i))

        @self.kapp.server.route("/export/<path:form>")
        async def export(form):
            try:
                filename = EXPORT_FILENAME if self.main.project is None else self.main.project
                if form=="table":
                    data = self.data_frame()
                    return data.to_html(na_rep="", index=False, justify="left")
                elif form=="csv":
                    data = self.data_frame()
                    filename = f"{filename}.csv"
                    filepath = os.path.join(self.main.current_project_dir, filename)
                    data.to_csv(filepath, na_rep="", index=False)
                    return await send_file(filepath, cache_timeout=0, as_attachment=True, attachment_filename=filename)
                elif form=="xlsx":
                    data = self.data_frame()
                    filename = f"{filename}.xlsx"
                    filepath = os.path.join(self.main.current_project_dir, filename)
                    data.to_excel(filepath, na_rep="", index=False)
                    return await send_file(filepath, cache_timeout=0, as_attachment=True, attachment_filename=filename)
                elif form=="json":
                    data = self.data_dict()
                    filename = f"{filename}.json"
                    filepath = os.path.join(self.main.current_project_dir, filename)
                    with open(filepath, "w") as file:
                        json.dump(data, file)
                    return await send_file(filepath, cache_timeout=0, as_attachment=True, attachment_filename=filename)
                elif form =="sheets":
                    url = self.export_gtable(filename)
                    # There are issues with automatic redirects to Google Docs, but this
                    # is ok, because they get to see the share url for the Google Sheet.  
                    # We could popup a dialog instead, which might look cleaner... 
                    return REDIRECT_PAGE.format(url)  
                else:
                    return "Data format not supported."
            except Exception as e:
                return f"No data available. ({e})"
        
        # This gets called when our perspective matrix changes
        @self.perspective.callback_change()
        def func(matrix):
            with self.lock:
                self.matrix = matrix
                self.graphs.matrix = matrix
                # Recalculate using matrix, re-render graph (if we have focus), but no need to 
                # re-render objects because they are transformed as part of the image.
                self.recompute()
                if self.focused:
                    self.graph_update_timer.start(lambda: self.kapp.push_mods(self.graphs.update_units()))

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

    def update_obj_render(self, obj_render_map):
        mods = []
        for i, v in enumerate(obj_render_map.values()):
            mods += self.obj_checkboxes[i].out_value(v)
        return mods 

    def export_gtable(self, filename):
        filename += " (MotionScope)"
        data = self.data_frame()
        sheet = self.gtabular.lookup(filename)
        if sheet is not None:
            self.gtabular.clear(sheet)
            self.gtabular.append_data(sheet, data)
        else:
            sheet = self.gtabular.create(filename, data)
        return self.gtabular.get_url(sheet)

    def data_frame(self):
        headers, data = self.graphs.data_dump(self.data_spacing_map)
        data_table = []
        for i, (k, v) in enumerate(data.items()):
            _, color = kritter.get_color(int(k), name=True)
            data_table.append([f"object {i+1}, {color}:"])
            data_table.extend(v.tolist())
        return DataFrame(data_table, columns=headers)

    def data_dict(self):
        headers, data = self.graphs.data_dump(self.data_spacing_map)
        data_dict = {}
        for i, (k, v) in enumerate(data.items()):
            _, color = kritter.get_color(int(k), name=True)
            object_dict = {}
            for j, h in enumerate(headers):
                object_dict[h] = v[:, j:j+1].T[0].tolist()
            data_dict[f"object {i+1}, {color}"] = object_dict
        return data_dict

    def precompute(self):
        # Keep in mind that self.data['obj_data'] may have multiple objects with
        # data point indexes that don't correspond perfectly with data point indexes
        # of sibling objects.
        with self.lock:
            max_points = []
            ptss = []
            indexes = []
            self.data_index_map = collections.defaultdict(dict)
            for k, data in self.sorted_obj_data.items():
                max_points.append(len(data))
                ptss = np.append(ptss, data[:, 0])  
                indexes = np.append(indexes, data[:, 1]).astype(int)
                for d in data:
                    self.data_index_map[int(d[1])][k] = d
            self.time_index_map = dict(zip(list(indexes), list(ptss))) 
            self.time_index_map = dict(sorted(self.time_index_map.items()))
            self.indexes = list(self.time_index_map.keys()) # sorted and no duplicates
            self.time_list = list(self.time_index_map.values())
            self.frame_period = (self.time_list[-1] - self.time_list[0])/(self.indexes[-1] - self.indexes[0])
            self.curr_first_index = self.indexes[0]
            self.curr_last_index = self.indexes[-1]
            self.zero_index_map = dict(zip(self.indexes, [0]*len(self.indexes)))
            self.curr_render_index_map = self.zero_index_map.copy()
            self.max_points = max(max_points)

    def transform_and_crop(self, data):
        height, width, _ = self.data["bg"].shape
        for i in data:
            d = data[i]
            # Apply matrix transformation to centroids.
            transform(self.matrix, d, cols=(2, 3))
            # Filter points based on what appears in the video window.             
            data[i] = np.delete(d, np.where((d[:, 2]<0) | (d[:, 2]>=width) | (d[:, 3]<0) | (d[:, 3]>=height))[0], axis=0)

    def recompute(self):
        if not self.data_index_map:
            return
        t0 = self.time_list[0] + self.frame_period*(self.curr_first_index-self.indexes[0])
        self.data_spacing_map.clear() 
        self.next_render_index_map = self.zero_index_map.copy()
        if self.curr_first_index in self.next_render_index_map:
            self.next_render_index_map[self.curr_first_index] = 1
        merge_data(self.data_spacing_map, self.data_index_map[self.curr_first_index])
        for i, t in self.time_index_map.items():
            if i>self.curr_last_index:
                break
            if t-t0>=self.frame_period*(self.spacing-0.5):
                self.next_render_index_map[i] = 1
                merge_data(self.data_spacing_map, self.data_index_map[i])
                t0 = t

        # Remove objects we aren't supposed to render
        for k, v in self.data[self.name]["obj_render"].items():
            if not v:
                del self.data_spacing_map[k]
        self.transform_and_crop(self.data_spacing_map)

    def compose_frame(self, index, val):
        if val>0:
            self.data['recording'].seek(index)
            frame = self.data['recording'].frame()[0]
        else:
            frame = self.data['bg']
        dd = self.data_index_map[index]  
        for k, d in dd.items():
            if self.data[self.name]["obj_render"][k]: # only render if it's enabled in obj_render_map
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

    def handle_legend(self):
        mods = []
        objs = list(self.sorted_obj_data.keys())
        for i in range(MAX_OBJECTS):
            if i<len(self.sorted_obj_data):
                mods += self.obj_checkboxes[i].out_disp(True) + self.obj_checkboxes[i].out_value(True)
                mods += [Output(self.obj_box_ids[i], "style", {"float": "right", "width": "20px", "height": "20px", "background-color": kritter.get_color(int(objs[i]), html=True)})]
            else:
                mods += self.obj_checkboxes[i].out_disp(False)
        return mods 
            
    def render(self):
        if not self.data_index_map:
            return
        with self.lock:
            self.recompute()
            self.compose()
            self.graph_update_timer.start(lambda: self.kapp.push_mods(self.graphs.out_draw()))

    def settings_update(self, settings):
        settings = settings.copy() 
        for k, s in self.settings_map.items():
            try: 
                # Push each mod individually because of they will affect each other
                self.kapp.push_mods(s(settings[k]))
            except:
                pass
        return []

    def data_update(self, changed, cmem=None):
        if self.name in changed:
            # Copy before we push any mods, because the mods will change the values
            # when the callbacks are called.
            settings = self.data[self.name].copy()

        if "obj_data" in changed and self.data['obj_data']:
            def time_format(val):
                t0 = self.time_list[0] + self.frame_period*(val[0]-self.indexes[0])
                t1 = self.time_list[0] + self.frame_period*(val[1]-self.indexes[0])
                return f'{t0:.3f}s → {t1:.3f}s'

            # Sort object data by objects with the most data first
            self.sorted_obj_data = dict(sorted(self.data['obj_data'].items(), reverse=True, key=lambda item: len(item[1])))
            # Change key of objects to be integers counting 0, 1, 2, ...
            self.sorted_obj_data = {i:v for i, (k, v) in enumerate(self.sorted_obj_data.items())}
            # Initial object render map is all objects are rendered
            self.data[self.name]["obj_render"] = {i: True for i in self.sorted_obj_data}
            # Remove off the end of the object data if there are too many objects
            while len(self.sorted_obj_data)>MAX_OBJECTS:
                objs = list(self.sorted_obj_data.keys())
                del self.sorted_obj_data[objs[-1]]

            self.pre_frame = self.data['bg'].copy()
            self.spacing = 1
            self.precompute()
            self.time_c.set_format(time_format)
            # Send mods off because they might conflict with mods self.name, and 
            # calling push_mods forces calling render() early. 
            self.kapp.push_mods(self.spacing_c.out_max(self.max_points//3) + self.spacing_c.out_value(self.spacing) + self.time_c.out_min(self.indexes[0]) + self.time_c.out_max(self.indexes[-1]) + self.time_c.out_value((self.curr_first_index, self.curr_last_index)) + self.handle_legend())

        if self.name in changed:
            self.settings_update(settings)
        return []

    def reset(self):
        with self.lock:
            try:
                self.data_index_map.clear()
                self.data_spacing_map.clear()
            except:
                pass
            mods = self.graphs.reset()
        return mods + self.settings_update(self.main.config_consts.DEFAULT_ANALYZE_SETTINGS)

    def frame(self):
        self.graphs.update()
        self.graph_update_timer.update()
        time.sleep(1/self.main.config_consts.PLAY_RATE)
        return self.curr_frame

    def focus(self, state):
        super().focus(state)
        if state:
            self.stream.stop()
            return self.graphs.out_draw() + self.graphs.out_disp(True) + self.perspective.out_disp(True)
        else:
            self.graph_update_timer.cancel()
            self.graphs.cancel()
            return self.graphs.out_disp(False)   

