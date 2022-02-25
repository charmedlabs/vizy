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
import quart
import dash_bootstrap_components as dbc
import kritter
import dash_html_components as html
from dash_devices.dependencies import Input, Output
from kritter.kterm import Kterm
from kritter.keditor import Keditor
from .vizy import Vizy
from .vizypowerboard import VizyPowerBoard
from .aboutdialog import AboutDialog
from .wifidialog import WifiDialog 
from .updatedialog import UpdateDialog 
from .appsdialog import AppsDialog 
from .userdialog import UserDialog
from .systemdialog import SystemDialog
from .rebootdialog import RebootDialog
from .timedialog import TimeDialog
from .gclouddialog import GcloudDialog

VIZY_URL = "https://vizycam.com"
# Permission bits: note, higher order bits don't necessarily mean higher levels of permission.
# The bits just need to be distinct.  
PMASK_GUEST = 1<<0
PMASK_NETWORKING = 1<<1
PMASK_APPS = 1<<2
PMASK_TIME = 1<<3
PMASK_SYSTEM = 1<<4
PMASK_UPDATE = 1<<5
PMASK_SHELL = 1<<7
PMASK_PYTHON = 1<<7
PMASK_CONSOLE = 1<<8
PMASK_EDITOR = 1<<9
PMASK_USER = 1<<10
PMASK_POWER = 1<<11
PMASK_REBOOT = 1<<12
PMASK_GCLOUD = 1<<13

BRIGHTNESS = 0x30

# CSS for side menu items
STYLE = '''
._k-menu-button-item {
    z-index: 1000;
    margin: 0px;
    padding: 0px 10px 0px 10px;
}
'''


class VizyVisor(Vizy):

    def __init__(self, user="pi"):
        super().__init__()
        self.user = user
        self.wifi_state = None
        self.style = STYLE
        
        # Set up side menu
        self.side_menu_entries = [] 
        self.prog_name = dbc.NavbarBrand("Program", id="_prog_name", style={"padding": 0})
        self.prog_link = html.A(self.prog_name, target="_blank", id="_prog_link", style={"display": "none"})
        self.message = html.Span("Starting application...", id="_message")
        self.start_message = html.Div([self.message, dbc.Spinner(color="white", size='sm', spinner_style={"margin": "auto 0 auto 5px"})], id="_message_div", style={"color": "white", "width": "100%", "margin": "auto", "display": "block"})
        self.side_div = html.Div([dbc.DropdownMenu(self.side_menu_entries, id="_dropdown", toggleClassName="fa fa-bars fa-lg bg-dark", caret=False, direction="left", style={"text-align": "right", "width": "100%", "margin": "auto"})])
        self.navbar = dbc.Navbar(html.Div([html.A(html.Img(src="/media/vizy_eye.png", style={"height": "25px"}), href=VIZY_URL, target="_blank", style={"margin": "auto 5px auto 0"}), self.prog_link, self.start_message, self.side_div], style={"width": "100%", "display": "inherit"}), color="dark", dark=True)
        self.iframe = html.Iframe(id=kritter.Kritter.new_id(), src="", style={"width": "100%", "height": "100%", "display": "block", "border": "none"})

        self.execterm = kritter.ExecTerm(self)
        self.apps_dialog = AppsDialog(self, PMASK_CONSOLE, PMASK_APPS)
        self.about_dialog = AboutDialog(self, PMASK_GUEST)
        self.user_dialog = UserDialog(self, PMASK_USER)
        self.wifi_dialog = WifiDialog(self, PMASK_NETWORKING)
        self.time_dialog = TimeDialog(self, PMASK_TIME)
        self.system_dialog = SystemDialog(self, PMASK_POWER)
        self.update_dialog = UpdateDialog(self, self.apps_dialog.exit_app, PMASK_UPDATE)
        self.reboot_dialog = RebootDialog(self, PMASK_REBOOT)
        self.gcloud_dialog = GcloudDialog(self, PMASK_GCLOUD)
        self.console_item = kritter.KsideMenuItem("App console", "/console", "desktop", target="_blank")
        self.shell_item = kritter.KsideMenuItem("Shell", "/shell", "terminal", target="_blank")
        self.python_item = kritter.KsideMenuItem("Python", "/python", "product-hunt", target="_blank")
        self.editor_item = kritter.KsideMenuItem("Editor", "/editor", "edit", target="_blank")
        self.logout_item = kritter.KsideMenuItem("Logout", "/logout", "sign-out")

        side_menu_items = [self.about_dialog.layout, self.apps_dialog.layout, self.console_item, self.user_dialog.layout, self.wifi_dialog.layout, self.time_dialog.layout, self.gcloud_dialog.layout, self.system_dialog.layout, self.shell_item, self.python_item,  self.editor_item, 
            self.update_dialog.layout, self.logout_item, self.reboot_dialog.layout] 

        # Add dialog layouts to main layout
        for i in side_menu_items:
            self.side_menu_entries.append(i.layout) 
            if i.dialog is not None:
                # Add dialog to layout
                self.side_div.children.append(i.dialog.layout) 
        # Add execterm dialog to layout
        self.side_div.children.append(self.execterm.layout) 

        # Put iframe in a flex-box that can grow to occupy available space in viewport.
        self.layout = html.Div([self.navbar, html.Div(self.iframe, style={"flex-grow": "1"})], style={"display": "flex", "flex-direction": "column", "height": "100%"})

        # We're running with root privileges, and we don't want the shell and 
        # python to run with root privileges also. 
        # We also want to change to the Vizy home directory.
        self.shell = Kterm(f'cd "{self.homedir}"; sudo -E -u {self.user} bash', name="Shell", protect=self.login.protect(PMASK_SHELL)) 
        self.python = Kterm(f'cd "{self.homedir}"; sudo -E -u {self.user} python3', name="Python", protect=self.login.protect(PMASK_PYTHON))
        self.editor = Keditor(path=self.homedir, settings_file=os.path.join(self.etcdir, "editor_settings.json"), protect=self.login.protect(PMASK_EDITOR))


        self.server.register_blueprint(self.shell.server, url_prefix="/shell")
        self.server.register_blueprint(self.python.server, url_prefix="/python")
        self.server.register_blueprint(self.editor.server, url_prefix="/editor")
        app = kritter.Proxy(f"http://localhost:{kritter.PORT}")
        self.server.register_blueprint(app.server, url_prefix="/app")

        @self.callback_connect
        def func(client, connect):
            self.indicate()
            if connect:
                # Deal with permissions for a given user
                def hide(item):
                    return [Output(item.layout.id, "style", {"display": "none"})]
                mods = []
                if not client.authentication&PMASK_APPS:
                    mods += hide(self.apps_dialog.layout)
                if not client.authentication&PMASK_NETWORKING:
                    mods += hide(self.wifi_dialog.layout)
                if not client.authentication&PMASK_SHELL:
                    mods += hide(self.shell_item)
                if not client.authentication&PMASK_PYTHON:
                    mods += hide(self.python_item)
                if not client.authentication&PMASK_CONSOLE:
                    mods += hide(self.console_item)
                if not client.authentication&PMASK_EDITOR:
                    mods += hide(self.editor_item)
                if not client.authentication&PMASK_UPDATE:
                    mods += hide(self.update_dialog.layout)
                if not client.authentication&PMASK_USER:
                    mods += hide(self.user_dialog.layout)
                if not client.authentication&PMASK_REBOOT:
                    mods += hide(self.reboot_dialog.layout)
                if not client.authentication&PMASK_TIME:
                    mods += hide(self.time_dialog.layout)
                if not client.authentication&PMASK_SYSTEM:
                    mods += hide(self.system_dialog.layout)
                if not client.authentication&PMASK_GCLOUD:
                    mods += hide(self.gcloud_dialog.layout)

                # Put user's name next to the logout selection
                children = self.logout_item.layout.children
                children[1] = f"Logout ({client.username})"
                mods += [Output(self.logout_item.layout.id, "children", children)]

                return mods

    # If we're being accessed through an SSH tunnel, the client's browser may be requesting
    # through http or https.  Vizy always uses http, which is reflected in the headers,
    # so when you have an iframe with relative url, the browser will use http even though 
    # the other side of the tunnel is https.  Looking at the forwarded protocol 
    # (X-Forward-Proto) we can determine if the other side of the tunnel is https 
    # and insert an upgrade CSP tag so that the secure things happen.  
    # This is overriden from Dash. 
    def interpolate_index(self, *args, **kwargs):
        index = super().interpolate_index(*args, **kwargs)
        match = "<head>"
        i = len(match)
        tag = '\n<meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">'
        try:
            if quart.request.headers['X-Forwarded-Proto']=='https':    
                i += index.find(match)
                return index[:i] + tag + index[i:]
        except: 
            pass
        return index

    def out_main_src(self, src):
        return [Output(self.iframe.id, "src", src)]

    def out_start_message(self, message):
        return [Output(self.message.id, "children", message), Output(self.start_message.id, "style", {"color": "white", "width": "100%", "margin": "auto", "display": "block"}), Output(self.prog_link.id, "style", {"display": "none"})]

    def out_set_program(self, prog):
        url = VIZY_URL if prog['url'] is None else prog['url']
        return [Output(self.start_message.id, "style", {"display": "none"}), Output(self.prog_name.id, "children", prog['name']), Output(self.prog_link.id, "href", url), Output(self.prog_link.id, "style", {"margin": "auto auto auto 0", "display": "block"})] + self.about_dialog.out_update(prog) 

    def indicate(self, what=""):
        what = what.upper()

        # Save wifi state
        if what=="AP_CREATED" or what=="WIFI_CONNECTED":
            self.wifi_state = what

        if what=="VIZY_EXITING":
            self.power_board.led_background(BRIGHTNESS//2, BRIGHTNESS//2, 0) # back to yellow
        elif what=="OFF":
            self.power_board.led()
        elif what=="WAITING":
            self.power_board.led_unicorn(8)
        elif what=="ERROR":
            self.power_board.buzzer(250, 100, 30, 2) # double boop
        elif what=="OK":
            self.power_board.buzzer(2000, 250) # single beep
        elif what=="VIZY_RUNNING":
            self.power_board.led_background(0, BRIGHTNESS, 0) # green
        elif self.clients:
            self.power_board.led_background(BRIGHTNESS//2, 0, BRIGHTNESS//2) # magenta
        elif what=="AP_CREATED":
            self.power_board.led_background(0, BRIGHTNESS//2, BRIGHTNESS//2) # cyan
        elif what=="WIFI_CONNECTED":
            self.power_board.led_background(0, 0, BRIGHTNESS) # blue
        elif self.wifi_state is None:
            self.indicate("VIZY_RUNNING")
        else:
            self.indicate(self.wifi_state)

    def run(self):
        super().run() 
        # Exit thread in apps_dialog
        self.system_dialog.close()
        self.apps_dialog.close()
        self.reboot_dialog.close()
        self.time_dialog.close()
        self.indicate("VIZY_EXITING")
