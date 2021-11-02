import time
import subprocess
from threading import Thread
from dash_devices import callback_context
import vizy.vizypowerboard as vpb
import dash_html_components as html
from kritter import Kritter, Ktext, Kcheckbox, Kdialog, KsideMenuItem

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

def get_cpu_usage(cores=4):
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

    def __init__(self, kapp, pmask_button):
        self.kapp = kapp
        self.run = 0
        self.thread = None

        style = {"label_width": 4, "control_width": 8}
        cam_config = self.kapp.vizy_config.config['hardware']['camera']
        cam_desc = f"{cam_config['type']} with {cam_config['IR-cut']} IR-cut, Rev {cam_config['version']}"
        pb_ver = self.kapp.power_board.hw_version()
        flash_total, flash_free = get_flash()
        # SD cards are in SI units for giga (10^9) instead of binary (2^23)
        # We don't dynamically update flash numbers.
        flash = f"{round(flash_total*1024/pow(10, 9))} GB, {flash_free*1024/pow(10, 9):.4f} GB free"
        self.cpu_c = Ktext(name="CPU", value=get_cpu_info(), style=style)
        self.camera_c = Ktext(name="Camera", value=cam_desc, style=style)
        self.power_board_c = Ktext(name="Power board", value=f"Rev {pb_ver[0]}.{pb_ver[1]}", style=style)
        self.flash_c = Ktext(name="Flash", value=flash, style=style)
        self.ram_c = Ktext(name="RAM", style=style)
        self.cpu_usage_c = Ktext(name="CPU usage", style=style)
        self.cpu_temp_c = Ktext(name="CPU temperature", style=style)
        self.voltage_input_c = Ktext(name="Input voltage", style=style)
        self.voltage_5v_c = Ktext(name="5V voltage", style=style)
        self.ext_button_c = Kcheckbox(name="External button", value=self.ext_button(), disp=False, style=style, service=None)

        layout = [self.cpu_c, self.camera_c, self.power_board_c, self.flash_c, self.ram_c, self.cpu_usage_c, self.cpu_temp_c, self.voltage_input_c, self.voltage_5v_c, self.ext_button_c]
        dialog = Kdialog(title=[Kritter.icon("info-circle"), "System Information"], layout=layout)
        self.layout = KsideMenuItem("System", dialog, "info-circle")

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
                return self.ext_button_c.out_disp(client.authentication&pmask_button)

        @self.ext_button_c.callback()
        def func(val):
            # Being able to change the button configuration is privileged. 
            if not callback_context.client.authentication&pmask_button:
                return 
            self.ext_button(val)             

    def ext_button(self, value=None):
        if value is None:
            return bool(self.kapp.power_board.dip_switches()&vpb.DIPSWITCH_EXT_BUTTON)
        _value = self.kapp.power_board.dip_switches()
        if (value):
            _value |= vpb.DIPSWITCH_EXT_BUTTON    
        else:
            _value &= ~vpb.DIPSWITCH_EXT_BUTTON   
        self.kapp.power_board.dip_switches(_value) 

    def update_thread(self):
        while(self.run):
            self.kapp.push_mods(self.update()) 
            time.sleep(1)

    def update(self):
        cpu_temp = vpb.get_cpu_temp()
        ram_total, ram_free = get_ram()
        ram = f"{round(ram_total/(1<<20))} GB, {ram_free/(1<<20):.4f} GB free"
        usage = get_cpu_usage()
        usage = [round(usage[0]), round(usage[1]), round(usage[2]), round(usage[3])]
        total_usage = usage[0]+usage[1]+usage[2]+usage[3]
        style = {"width": "45px", "float": "left"}
        cpu_usage = [
            html.Span(f"{usage[0]}%", style=style),
            html.Span(f"{usage[1]}%", style=style), 
            html.Span(f"{usage[2]}%", style=style), 
            html.Span(f"{usage[3]}%", style=style), 
            html.Span(f"({total_usage}%)", style=style) 
        ]
        return self.ram_c.out_value(ram) + self.cpu_usage_c.out_value(cpu_usage) + \
            self.voltage_5v_c.out_value(f"{self.kapp.power_board.measure(vpb.CHANNEL_5V):.2f}V") + \
            self.voltage_input_c.out_value(f"{self.kapp.power_board.measure(vpb.CHANNEL_VIN):.2f}V") + \
            self.cpu_temp_c.out_value(f"{cpu_temp:.1f}\u00b0C, {cpu_temp*1.8+32:.1f}\u00b0F")    
  
    def close(self):
        self.run = 0 
