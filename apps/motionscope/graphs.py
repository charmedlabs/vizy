import numpy as np 
import cv2 
import math
from threading import RLock
from tab import Tab
import plotly.graph_objs as go
import kritter
from dash_devices.dependencies import Input, Output
import dash_html_components as html
import dash_core_components as dcc
import dash_bootstrap_components as dbc

HIGHLIGHT_TIMEOUT = 0.25
OBJECTS = 1
POINTS = 2
LINES = 4
ARROWS = 8 

class Graphs():

    def __init__(self, kapp, data, spacing_map, settings_map, lock, video, num_graphs, style):
        self.kapp = kapp
        self.data = data
        self.spacing_map = spacing_map
        self.settings_map = settings_map
        self.name = "Analyze"
        self.lock = lock
        self.video = video
        self.num_graphs = num_graphs
        self.calib_pixels = None
        self.highlight_timer = kritter.FuncTimer(HIGHLIGHT_TIMEOUT)
        self.unhighlight_timer = kritter.FuncTimer(HIGHLIGHT_TIMEOUT)
        self.highlight_data = None
        self.highlight_lock = RLock()

        # Each map member: (abbreviation, units/meter)
        self.units_map = {"pixels": ("px", 1), "meters": ("m", 1), "centimeters": ("cm", 100), "feet": ("ft", 3.28084), "inches": ("in", 39.3701)}
        self.units_list = [u for u, v in self.units_map.items()]
        self.graph_descs = {"x, y position": ("x position", "y position", ("{}", "{}"), self.xy_pos), "x, y velocity": ("x velocity", "y velocity", ("{}/s", "{}/s"), self.xy_vel), "x, y acceleration": ("x acceleration", "y acceleration", ("{}/s^2", "{}/s^2"), self.xy_accel), "velocity magnitude, direction": ("velocity magnitude", "velocity direction", ("{}/s", "deg"), self.md_vel),  "acceleration magnitude, direction": ("accel magnitude", "accel direction", ("{}/s^2", "deg"), self.md_accel)}

        self.units = "pixels"
        self.data[self.name]['units'] = self.units

        self.num_units = 1
        self.data[self.name]["num_units"] = self.num_units
        self.units_info = self.units_map[self.units]
        self.units_per_pixel = 1 

        self.options = [k for k, v in self.graph_descs.items()]
        self.selections = self.options[0:self.num_graphs//2]
        for i in range(self.num_graphs//2):
            self.data[self.name][f"graph{i}"] = i

        style_dropdown = style.copy()
        style_dropdown["control_width"] = 5 
        self.units_c = kritter.Kdropdown(name='Distance units', options=self.units_list, value=self.units_list[0], style=style_dropdown)

        self.show_options_map = {"objects": OBJECTS, "objects, points": OBJECTS+POINTS, "objects, points, lines": OBJECTS+POINTS+LINES, "objects, points, lines, arrows": OBJECTS+POINTS+LINES+ARROWS}
        show_options_list = [k for k, v in self.show_options_map.items()]
        self.show_options = self.show_options_map[show_options_list[0]]
        self.show_options_c = kritter.Kdropdown(name='Show', options=show_options_list, value=show_options_list[0], style=style_dropdown)

        self.calib = kritter.Ktext(name="Calibration", style=style)
        self.calib_ppu = dbc.Col(id=self.kapp.new_id(), width="auto", style={"padding": "5px"})
        self.calib_input = dbc.Input(value=self.num_units, id=self.kapp.new_id(), type='number', style={"width": 75})
        self.calib_units = dbc.Col(id=self.kapp.new_id(), width="auto", style={"padding": "5px"})
        self.calib.set_layout(None, [self.calib.label, self.calib_ppu, dbc.Col(self.calib_input, width="auto", style={"padding": "0px"}), self.calib_units])
        self.calib_button = kritter.Kbutton(name=[kapp.icon("calculator"), "Calibrate..."])
        self.calib.append(self.calib_button)
        self.calib_collapse = dbc.Collapse(self.calib, is_open=False, id=self.kapp.new_id())

        # Controls layout
        self.controls_layout = [self.show_options_c, self.units_c, self.calib_collapse]
        
        # Graphs layout
        self.graphs = []
        self.menus = []
        self.layout = []

        for i in range(0, self.num_graphs, 2):
            g0 = dcc.Graph(id=self.kapp.new_id(), clear_on_unhover=True, config={'displayModeBar': False})
            g1 = dcc.Graph(id=self.kapp.new_id(), clear_on_unhover=True, config={'displayModeBar': False})
            self.kapp.callback(None, [Input(g0.id, "hoverData")])(self.get_highlight_func(i))
            self.kapp.callback(None, [Input(g1.id, "hoverData")])(self.get_highlight_func(i+1))
            self.graphs.extend((g0, g1))
            menu = kritter.KdropdownMenu(options=self.items())
            self.menus.append(menu)
            self.layout.append(dbc.Row(dbc.Col(menu))) 
            self.layout.append(dbc.Row([dbc.Col(g0), dbc.Col(g1)]))
            menu.callback()(self.get_menu_func(i//2))
        self.layout = html.Div(html.Div(self.layout, style={"margin": "5px", "float": "left"}), id=self.kapp.new_id(), style={'display': 'none'})

        def set_pixels(val):
            self.calib_pixels = val
            return self.update_units()

        self.settings_map.update({f"graph{i}": self.get_menu_func(i) for i in range(self.num_graphs//2)})
        self.settings_map.update({"show_options": self.show_options_c.out_value, "units": self.units_c.out_value, "num_units": lambda val: [Output(self.calib_input.id, "value", val)], "calib_pixels": set_pixels})

        self.video.callback_hover()(self.get_highlight_func(self.num_graphs))

        @self.video.callback_draw()
        def func(val):
            try:
                for k, v in val.items():
                    x = v[0]['x1'] - v[0]['x0']
                    y = v[0]['y1'] - v[0]['y0']
                    length = (x**2 + y**2)**0.5
                    break  
            except: # in case we get unknown callbacks
                return            
            self.video.draw_user(None)
            self.calib_pixels = length
            self.data[self.name]["calib_pixels"] = length
            #  pixels/num_units units / num_units * units/meter = pixels/meter   
            #  1/pixel/meter = meter/pixel
            return self.update_units()

        @self.units_c.callback()
        def func(val):
            units_old_per_meter = self.units_info[1]
            self.units = val
            self.data[self.name]["units"] = val
            self.units_info = self.units_map[val]
            if self.calib_pixels:
                # pixels/num_units units_old * units_old/meter / units_new/meter = pixels/num_units units_new
                self.calib_pixels *= units_old_per_meter/self.units_info[1]
            return self.update_units() 

        @self.show_options_c.callback()
        def func(val):
            self.show_options = self.show_options_map[val]
            self.data[self.name]["show_options"] = val
            return self.out_draw()

        @self.calib_button.callback()
        def func():
            self.video.draw_user("line", line=dict(color="rgba(0, 255, 0, 0.80)"))
            self.video.draw_graph_data(None)
            self.video.draw_clear()
            self.video.draw_text(self.video.source_width/2, self.video.source_height/2, "Point and drag to draw a calibration line.")
            return self.video.out_draw_overlay()

        @self.kapp.callback_shared(None, [Input(self.calib_input.id, "value")])
        def func(num_units):
            if num_units:
                self.num_units = num_units
                self.data[self.name]["num_units"] = num_units
                return self.update_units()


    def unhighlight(self):
        self.kapp.push_mods(self.out_draw())

    def highlight(self):
        with self.highlight_lock:
            keys = list(self.spacing_map.keys())
            index, data = self.highlight_data
            for k, v in data.items():
                # curveNumber is the nth curve, which doesn't necessarily correspond
                # to the key value in spacing_map.
                mods = self.out_draw((index, keys[v[0]['curveNumber']], v[0]['pointIndex']))
                self.kapp.push_mods(mods)
                return

    def update_units(self):
        if self.units=="pixels":
            self.units_per_pixel = 1
            mods = []
        elif self.num_units and self.calib_pixels:
            self.units_per_pixel = self.num_units/self.calib_pixels  
            mods = [Output(self.calib_ppu.id, "children", f"{self.calib_pixels:.2f} pixels per")]  
        else:
            self.units_per_pixel = 1 
            mods = [Output(self.calib_ppu.id, "children", f"? pixels per")]
        return mods + [Output(self.calib_units.id, "children", f"{self.units}.")] + [Output(self.calib_collapse.id, "is_open", self.units!="pixels")] + self.out_draw()

    def draw_arrow(self, p0, p1, color):
        D0 = 9 # back feather
        D1 = 7 # width
        D2 = 12 # back feather tip
        dx = p1[0]-p0[0]
        dy = p1[1]-p0[1]
        h = (dx*dx + dy*dy)**0.5
        ca = dx/h
        sa = dy/h
        tx = p1[0] - ca*D2
        ty = p1[1] - sa*D2
        points = [(p1[0], p1[1]), (tx - sa*D1, ty + ca*D1), (p1[0] - ca*D0, p1[1] - sa*D0), (tx + sa*D1, ty - ca*D1)]
        self.video.draw_shape(points, fillcolor=color, line={"color": "black", "width": 1})

    def items(self):
        return [dbc.DropdownMenuItem(i, disabled=i in self.selections) for i in self.options]

    def get_highlight_func(self, index):
        def func(data):
            with self.highlight_lock:
                if data:
                    self.highlight_data = index, data
                    self.highlight_timer.start(self.highlight)
                    self.unhighlight_timer.cancel()
                else:
                    self.unhighlight_timer.start(self.unhighlight)
                    self.highlight_timer.cancel()
        return func

    def get_menu_func(self, index):
        def func(val):
            self.selections[index] = self.options[val]
            self.data[self.name][f"graph{index}"] = val
            mods = []
            for menu in self.menus:
                mods += menu.out_options(self.items())
            return mods + self.out_draw()
        return func

    def figure(self, title, units, data, annotations):
        layout = dict(title=title, 
            yaxis=dict(zeroline=False, title=f"{title} ({units})"),
            xaxis=dict(zeroline=False, title='time (seconds)'),
            annotations=annotations,
            showlegend=False,
            hovermode='closest',
            width=300, 
            height=200, 
            #xpad=20,
            margin=dict(l=50, b=30, t=25, r=5))
        return dict(data=data, layout=layout)

    def differentiate(self, x, y):
        x_ = x[:-1] 
        xdiff = x[1:] - x_
        y_ = (y[1:]-y[:-1])/xdiff
        return x_, y_

    def scatter(self, x, y, k, units):
        return go.Scatter(x=x, y=y, hovertemplate='(%{x:.3f}s, %{y:.3f}'+units+')', line=dict(color=kritter.get_rgb_color(int(k), html=True)), mode='lines+markers', name='')        

    def add_highlight(self, highlight, k, trace, annotations, domain, range_):
        if highlight and highlight[1]==k:
            # Velocity and acceleration domains are smaller than position.
            # If index is out of range, just exit.
            try:            
                x = domain[highlight[2]]
                y = range_[highlight[2]]
            except:
                return
            text = trace['hovertemplate'].replace('%', '').format(x=x, y=y)

            if x<(domain[-1]+domain[0])/2:
                ax = 6
                xanchor = 'left'
            else:
                ax = -6
                xanchor = 'right'
            annotations.append(dict(x=x, y=y, xref="x", yref="y", text=text, font=dict(color="white"), borderpad=3, showarrow=True, ax=ax, ay=0, xanchor=xanchor, arrowcolor="black", bgcolor=trace['line']['color'], bordercolor="white"))            

    def xy_pos(self, i, units, highlight):
        data = []
        annotations = []
        height = self.data["bg"].shape[0]
        for k, d in self.spacing_map.items():
            domain = d[:, 0]
            if i==0: # x position 
                range_ = d[:, 2]*self.units_per_pixel 
            else: # y position
                # Camera coordinates start at top, so we need to adjust y axis accordingly.
                range_ = (height-1-d[:, 3])*self.units_per_pixel
            trace = self.scatter(domain, range_, k, units)
            data.append(trace)
            self.add_highlight(highlight, k, trace, annotations, domain, range_)
        return data, annotations

    def xy_vel(self, i, units, highlight):
        data = []
        annotations = []
        for k, d in self.spacing_map.items():
            if i==0: # x velocity
                domain, range_ = self.differentiate(d[:, 0], d[:, 2])
                range_ *= self.units_per_pixel
            else: # y velocity
                domain, range_ = self.differentiate(d[:, 0], d[:, 3])
                # Camera coordinates start at top and go down 
                # so we need to flip sign for y axis.                
                range_ *= -self.units_per_pixel
            trace = self.scatter(domain, range_, k, units)
            data.append(trace)
            self.add_highlight(highlight, k, trace, annotations, domain, range_)
        return data, annotations

    def xy_accel(self, i, units, highlight):
        data = []
        annotations = []
        for k, d in self.spacing_map.items():
            if i==0: # x accel
                domain, range_ = self.differentiate(d[:, 0], d[:, 2])
                domain, range_ = self.differentiate(domain, range_)
                range_ *= self.units_per_pixel
            else: # y accel
                domain, range_ = self.differentiate(d[:, 0], d[:, 3])
                domain, range_ = self.differentiate(domain, range_)
                # Camera coordinates start at top and go down 
                # so we need to flip sign for y axis.                
                range_ *= -self.units_per_pixel
            trace = self.scatter(domain, range_, k, units)
            data.append(trace)
            self.add_highlight(highlight, k, trace, annotations, domain, range_)
        return data, annotations

    def md_vel(self, i, units, highlight):
        data = []
        annotations = []
        for k, d in self.spacing_map.items():
            domain, range_x = self.differentiate(d[:, 0], d[:, 2])
            domain, range_y = self.differentiate(d[:, 0], d[:, 3])
            if i==0: # velocity magnitude
                range_ = (range_x*range_x + range_y*range_y)**0.5 # vector magnitude
                range_ *= self.units_per_pixel
            else: # velocity direction
                # Camera coordinates start at top and go down 
                # so we need to flip sign for y axis.                
                range_ = np.arctan2(-range_y, range_x)
                range_ *= 180/math.pi # radians to degrees
            trace = self.scatter(domain, range_, k, units)
            data.append(trace)
            self.add_highlight(highlight, k, trace, annotations, domain, range_)
        return data, annotations

    def md_accel(self, i, units, highlight):
        data = []
        annotations = []
        for k, d in self.spacing_map.items():
            domain, range_x = self.differentiate(d[:, 0], d[:, 2])
            domain, range_x = self.differentiate(domain, range_x)
            domain, range_y = self.differentiate(d[:, 0], d[:, 3])
            domain, range_y = self.differentiate(domain, range_y)
            if i==0: # acceleration magnitude
                range_ = (range_x*range_x + range_y*range_y)**0.5
                range_ *= self.units_per_pixel
            else: # velocity direction
                # Camera coordinates start at top and go down 
                # so we need to flip sign for y axis.                
                range_ = np.arctan2(-range_y, range_x)
                range_ *= 180/math.pi # radians to degrees
            trace = self.scatter(domain, range_, k, units)
            data.append(trace)
            self.add_highlight(highlight, k, trace, annotations, domain, range_)
        return data, annotations

    def out_draw_video(self, highlight):
        self.video.draw_clear()
        data =[]
        height = self.data["bg"].shape[0]
        units = self.units_info[0]
        if highlight and highlight[0]==self.num_graphs: # Don't highlight if we're hovering on this graph.
            highlight = None 
            self.video.overlay_annotations.clear()
        for i, d in self.spacing_map.items():
            color = kritter.get_rgb_color(int(i), html=True)
            x = d[:, 2]*self.units_per_pixel 
            y = (height-1-d[:, 3])*self.units_per_pixel
            customdata = np.column_stack((d[:, 0], x, y))
            hovertemplate = '%{customdata[0]:.3f}s (%{customdata[1]:.3f}'+units+', %{customdata[2]:.3f}'+units+')'
            obj_color = kritter.get_rgb_color(int(i), html=True)
            if self.show_options&POINTS:
                color = obj_color
                marker = dict(size=8, line=dict(width=1, color='black'))   
            else:
                color = "rgba(0,0,0,0)" 
                marker = dict(size=8)
            mode = "markers" if not self.show_options&LINES else "lines+markers"
            data.append(go.Scatter(x=d[:, 2], y=d[:, 3], 
                line=dict(color=color), mode=mode, name='', hovertemplate=hovertemplate, hoverlabel=dict(bgcolor=obj_color), customdata=customdata, marker=marker))
            if self.show_options&ARROWS:
                for i, d_ in enumerate(d):
                    if i<len(d)-1:
                        self.draw_arrow(d_[2:4], d[i+1][2:4], obj_color)
            if highlight and highlight[1]==i:
                text = hovertemplate.replace('%', '').format(customdata=customdata[highlight[2]])
                x = d[highlight[2], 2]
                y = d[highlight[2], 3]
                if x<self.video.source_width//2:
                    ax = 6
                    xanchor = 'left'
                else:
                    ax = -6
                    xanchor = 'right'
                self.video.overlay_annotations.append(dict(x=x, y=y, xref="x", yref="y", text=text, font=dict(color="white"), borderpad=3, showarrow=True, ax=ax, ay=0, xanchor=xanchor, arrowcolor="black", bgcolor=obj_color, bordercolor="white"))

        self.video.draw_graph_data(data)
        return self.video.out_draw_overlay() 

    def out_draw(self, highlight=None):
        with self.lock:
            mods = self.out_draw_video(highlight)
            for i, g in enumerate(self.selections):
                desc = self.graph_descs[g]
                for j in range(2):
                    title = desc[j]
                    units = desc[2][j].format(self.units_info[0])
                    # Don't highlight if we're hovering on this graph.
                    if highlight and highlight[0]==i*2+j: 
                        data, annotations = desc[3](j, units, None)
                    else:
                        data, annotations = desc[3](j, units, highlight)                        
                    figure = self.figure(title, units, data, annotations)
                    mods += [Output(self.graphs[i*2+j].id, "figure", figure)]
            return mods

    def out_disp(self, disp):
        if disp:
            mods = [Output(self.layout.id, "style", {'display': 'block'})]
        else:
            mods = [Output(self.layout.id, "style", {'display': 'none'})]
        return self.video.out_overlay_disp(disp) + mods

    def update(self):
        self.highlight_timer.update()
        self.unhighlight_timer.update()
