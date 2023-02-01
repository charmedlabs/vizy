#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

import time
import subprocess
from threading import Thread
from dash_devices import callback_context
import vizy.vizypowerboard as vpb
import dash_html_components as html
from kritter import Kritter, Ktext, Kcheckbox, Kdropdown, Kdialog, KsideMenuItem
from kritter.ktextvisor import KtextVisorTable

CORES = 4

def get_ram():
    total = 0
    free = 0
    try:
        with open('/proc/meminfo', 'r') as f:
            while total==0 or free==0:
                line = f.readline()
                if not line:
                    break
                parts = line.split()
                if "MEMTOTAL:" in [p.upper() for p in parts]:
                    total = [int(p) for p in parts if p.isdigit()][0]
                if "MEMAVAILABLE:" in [p.upper() for p in parts]:
                    free = [int(p) for p in parts if p.isdigit()][0]
    except:
        pass
    return total, free    


def get_flash():
    total = 0
    free = 0
    try:
        with open('/proc/partitions', 'r') as f:
            while True:
                line = f.readline()
                if not line:
                    break
                parts = line.split()
                if "MMCBLK0" in [p.upper() for p in parts]:
                    total = [int(p) for p in parts if p.isdigit()][-1]
    except:
        pass
    try:
        out = subprocess.check_output(["df", "/root"])
        parts = out.split()
        # Last number is the amount that's free.
        free = [int(p) for p in parts if p.isdigit()][-1]
    except:
        pass 
    return total, free

def get_cpu_usage(cores=CORES):
    usage = [0 for i in range(cores)]
    res = [0 for i in range(cores)]
    try:
        with open('/proc/stat', 'r') as f:
            while True:
                line = f.readline()
                if not line:
                    break
                parts = line.split()
                for i in range(cores):
                    # Gather stats on each CPU core.
                    if f"CPU{i}" in [p.upper() for p in parts]:
                        vals = [int(p) for p in parts if p.isdigit()]
                        usage[i] = vals[0] + vals[1] + vals[2]
        t = time.time()
        if get_cpu_usage.t0:
            for i in range(cores):
                u = (usage[i]-get_cpu_usage.usage0[i])/(t-get_cpu_usage.t0)
                res[i] = 100 if u>100 else u # Rounding errors can result in 101%
        get_cpu_usage.t0 = t
        get_cpu_usage.usage0 = usage
    except:
        pass
    res = [round(u) for u in res]    
    return res

get_cpu_usage.t0 = 0

def get_cpu_info():
    try:
        with open('/proc/device-tree/model', 'r') as f:
            return f.readline().strip()[0:-1]
    except:
        pass
    return ""


class SystemDialog:

    def __init__(self, kapp, tv, pmask):
        self.kapp = kapp
        self.run = 0
        self.thread = None

        style = {"label_width": 4, "control_width": 8}
        cam_config = self.kapp.vizy_config['hardware']['camera']
        cam_desc = f"{cam_config['type']} with {cam_config['IR-cut']} IR-cut, Rev {cam_config['version']}"
        pb_ver = self.kapp.power_board.hw_version()
        fw_ver = self.kapp.power_board.fw_version()
        flash_total, flash_free = get_flash()
        # SD cards are in SI units for giga (10^9) instead of binary (2^23)
        # We don't dynamically update flash numbers.
        flash = f"{round(flash_total*1024/pow(10, 9))} GB, {flash_free*1024/pow(10, 9):.4f} GB free"
        self.cpu_c = Ktext(name="CPU", value=get_cpu_info(), style=style)
        self.camera_c = Ktext(name="Camera", value=cam_desc, style=style)
        self.power_board_c = Ktext(name="Power board", value=f"PCB rev {pb_ver[0]}.{pb_ver[1]}, firmware ver {fw_ver[0]}.{fw_ver[1]}.{fw_ver[2]}", style=style)
        self.flash_c = Ktext(name="Flash", value=flash, style=style)
        self.ram_c = Ktext(name="RAM", style=style)
        self.cpu_usage_c = Ktext(name="CPU usage", style=style)
        self.cpu_temp_c = Ktext(name="CPU temperature", style=style)
        self.voltage_input_c = Ktext(name="Input voltage", style=style)
        self.voltage_5v_c = Ktext(name="5V voltage", style=style)
        self.ext_button_c = Kcheckbox(name="External button", value=self.ext_button(), disp=False, style=style, service=None)
        power_button_mode_map = {"Power on when button pressed": vpb.DIPSWITCH_POWER_DEFAULT_OFF, "Power on when power applied": vpb.DIPSWITCH_POWER_DEFAULT_ON, "Remember power state": vpb.DIPSWITCH_POWER_SWITCH, "Always on, power-off disabled": vpb.DIPSWITCH_POWER_PLUG}
        power_button_mode_map2 = {v: k for k, v in power_button_mode_map.items()} 
        power_button_modes = [k for k, v in power_button_mode_map.items()]
        try:
            value = power_button_mode_map2[self.power_button_mode()]
        except:
            value = "Unknown"
        self.power_button_mode_c = Kdropdown(name="Power on behavior", options=power_button_modes, value=value, style=style)

        layout = [self.cpu_c, self.camera_c, self.power_board_c, self.flash_c, self.ram_c, self.cpu_usage_c, self.cpu_temp_c, self.voltage_input_c, self.voltage_5v_c, self.ext_button_c, self.power_button_mode_c]
        dialog = Kdialog(title=[Kritter.icon("gears"), "System Information"], layout=layout)
        self.layout = KsideMenuItem("System", dialog, "gears")

        @dialog.callback_view()
        def func(open):
            if open:
                self.run += 1
                if self.run==1:
                    self.thread = Thread(target=self.update_thread)
                    self.thread.start()
            elif self.run>0:  # Stale dialogs in browser can result in negative counts.
                self.run -= 1

        @self.kapp.callback_connect
        def func(client, connect):
            if connect:
                # Being able to change the button configuration is privileged. 
                return self.ext_button_c.out_disp(client.authentication&pmask) + self.power_button_mode_c.out_disp(client.authentication&pmask)

        @self.ext_button_c.callback()
        def func(val):
            # Being able to change the button configuration is privileged. 
            if not callback_context.client.authentication&pmask:
                return 
            self.ext_button(val)    

        @self.power_button_mode_c.callback()
        def func(val):
            # Being able to change the button button mode is privileged. 
            if not callback_context.client.authentication&pmask:
                return 
            self.power_button_mode(power_button_mode_map[val])    

        # setup KtextClient keywords, callbacks, and descriptions         
        def system_info(words, sender, context):
            sysinfo = self.get_system_info(1)
            info = {} # format to str -- ktextVisor ln.133 | TypeError: can only concatenate str (not <"int", "float", "list">) to str 
            info['cpu-usage'] = ' '.join([f"{c}%" for c in sysinfo['cpu']['usage']]) + f" ({sum(sysinfo['cpu']['usage'])})%"
            info['cpu-temp'] = f"{sysinfo['cpu']['temp']:.1f}\u00b0C, {sysinfo['cpu']['temp']*1.8+32:.1f}\u00b0F"
            info['ram'] = f"{round(sysinfo['ram']['total']/(1<<20))} GB, {sysinfo['ram']['free']/(1<<20):.4f} GB free"  
            # flash memory | SD cards are in SI units for giga (10^9) instead of binary (2^23) 
            info['flash'] = f"{round(sysinfo['flash']['total']*1024/pow(10, 9))} GB, {sysinfo['flash']['free']*1024/pow(10, 9):.4f} GB free"
            info['voltage'] = ' '.join([f"{v}: {sysinfo['voltage'][v]:.2f}V" for v in sysinfo['voltage']])
            return info

        tv_table = KtextVisorTable({
            "sysinfo" : (system_info, "Prints current system information.")})
        @tv.callback_receive()
        def func(words, sender, context):
            return tv_table.lookup(words, sender, context)


    def ext_button(self, value=None):
        if value is None:
            return bool(self.kapp.power_board.dip_switches()&vpb.DIPSWITCH_EXT_BUTTON)
        _value = self.kapp.power_board.dip_switches()
        if (value):
            _value |= vpb.DIPSWITCH_EXT_BUTTON    
        else:
            _value &= ~vpb.DIPSWITCH_EXT_BUTTON   
        self.kapp.power_board.dip_switches(_value) 

    def power_button_mode(self, value=None):
        if value is None:
            return self.kapp.power_board.dip_switches()&vpb.DIPSWITCH_POWER_PLUG
        _value = self.kapp.power_board.dip_switches()
        _value &= ~vpb.DIPSWITCH_POWER_PLUG   
        _value |= value    
        self.kapp.power_board.dip_switches(_value) 

    def update_thread(self):
        while(self.run):
            self.kapp.push_mods(self.update()) 
            time.sleep(1)

    def update(self):
        '''fetches system information and updates GUI'''
        system_info = self.get_system_info()
        # format fields
        style = {"width": "45px", "float": "left"}
        cpu_temp = f"{system_info['cpu']['temp']:.1f}\u00b0C, {system_info['cpu']['temp']*1.8+32:.1f}\u00b0F"
        ram = f"{round(system_info['ram']['total']/(1<<20))} GB, {system_info['ram']['free']/(1<<20):.4f} GB free"
        cpu_usage = [html.Span(f"{u}%", style=style) for u in system_info['cpu']['usage']]
        cpu_usage.append(html.Span(f"{sum(system_info['cpu']['usage'])}%"))
        voltage_5v = f"{system_info['voltage']['5v']:.2f}V"
        voltage_input = f"{system_info['voltage']['input']:.2f}V"
        # return mods to push
        return self.ram_c.out_value(ram) + \
            self.cpu_usage_c.out_value(cpu_usage) + \
            self.voltage_5v_c.out_value(voltage_5v) + \
            self.voltage_input_c.out_value(voltage_input) + \
            self.cpu_temp_c.out_value(cpu_temp)   

    def get_system_info(self, period=0):
        '''returns dict of current system information'''
        if period:
            # get_cpu_usage needs an averaging period to make an accurate measurement
            get_cpu_usage()
            time.sleep(period)
        cpu_usage = get_cpu_usage()
        cpu_temp = vpb.get_cpu_temp() 
        ram_total, ram_free = get_ram() 
        flash_total, flash_free = get_flash() 
        voltage_5v = self.kapp.power_board.measure(vpb.CHANNEL_5V)
        voltage_input = self.kapp.power_board.measure(vpb.CHANNEL_VIN)
        return {
            'cpu': { 'temp' : cpu_temp, 'usage' : cpu_usage },
            'ram': { 'total' : ram_total, 'free' : ram_free },
            'flash': { 'total': flash_total, 'free': flash_free },
            'voltage': { '5v': voltage_5v, 'input': voltage_input }
        }

    def close(self):
        self.run = 0 
