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
import asyncio
import traceback
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

from quart import Quart, Response, Blueprint, request, websocket, copy_current_websocket_context, render_template, send_file
import aiohttp

class PortProxy:

    def __init__(self, port):
        self.port = port
        self.server = Blueprint(f'PortProxy{port}', __name__, template_folder=None, static_folder=None, static_url_path=None)

        @self.server.route('/', defaults={'path': ''}, methods=['GET', 'POST'])
        @self.server.route('/<path:path>', methods=['GET', 'POST'])
        async def proxy(path):
            #print("**** path", request.method, path)
            if request.method=='GET':
                async with aiohttp.ClientSession(cookies=request.cookies) as session:
                    try:
                        async with session.get(f'http://vizyalpha.local:{self.port}/{path}') as resp:
                            return Response(await resp.read(), mimetype=resp.content_type)
                    except aiohttp.client_exceptions.ClientConnectorError:
                        print("**** return error 0")
                        return "Application not ready", 400
            else: # POST
                data = await request.get_data()
                async with aiohttp.ClientSession(cookies=request.cookies) as session:
                    try:
                        async with session.post(f'http://vizyalpha.local:{self.port}/{path}', data=data, headers=dict(request.headers)) as resp:
                            return Response(await resp.read(), mimetype=resp.content_type)
                    except aiohttp.client_exceptions.ClientConnectorError:
                        print("**** return error 1")
                        return "Application not ready", 400

        @self.server.websocket('_push')
        async def wsproxy(authentication=None, username=None):
            session = aiohttp.ClientSession(cookies=websocket.cookies)
            try: 
                async with session.ws_connect(f'http://vizyalpha.local:{self.port}/_push') as ws:
                    print("**** connect!", ws)
                    async def recv():
                        print("*** start receive")
                        while True:
                            data = await quart.websocket.receive()
                            #print("*** receive data", data)
                            await ws.send_str(data)
                        print("*** end receive")
                    async def send():
                        print("*** start send")
                        while True:
                            data = await ws.receive()
                            if data.type==aiohttp.WSMsgType.TEXT:
                                await quart.websocket.send(data.data)
                            elif data.type==aiohttp.WSMsgType.CLOSED or data.tp==aiohttp.WSMsgType.ERROR:
                                print("***** closing!")
                                raise asyncio.CancelledError
                            else:
                                print("**** uh")
                        print("*** end send")

                    tasks = []
                    tasks.append(asyncio.create_task(recv()))
                    tasks.append(asyncio.create_task(send()))

                    try:
                        await asyncio.gather(*tasks)
                    except asyncio.CancelledError:
                        pass
                    except:
                        # Print traceback because Quart seems to be catching everything in this context.
                        traceback.print_exc() 
                    finally:
                        await ws.close()
            except aiohttp.client_exceptions.ClientConnectorError:
                print("**** ws error 0")
                pass



class VizyVisor(Vizy):

    def __init__(self, user="pi"):
        super().__init__()
        self.connections = 0
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
        self.app = PortProxy(5000)
        self.server.register_blueprint(self.app.server, url_prefix="/app")

        # Install connection counter
        #self.connection_counter()

        @self.callback_connect
        def func(client, connect):

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

    def interpolate_index(
        self,
        metas="",
        title="",
        css="",
        config="",
        scripts="",
        app_entry="",
        favicon="",
        renderer="",
    ):
        print("***************** interpolate_index", quart.request.base_url)
        index = super().interpolate_index(metas, title, css, config, scripts, app_entry, favicon,renderer)
        try:
            if request.headers['X-Forwarded-Proto']=='https':    
                i = index.find("<head>")
                return index[:i + 6] + '\n<meta http-equiv="Content-Security-Policy" content="upgrade-insecure-requests">' + index[i + 6:]
        except:
            pass
        return index

    # This installs code that counts websocket connections as they 
    # connect and disconnect, counting client connections to us (VisyVisor),
    # console, shell, and python instances.  It doesn't count connections to editor
    # or the app process itself.   
    def connection_counter(self):
        original_func = self.server.dispatch_websocket
        async def wrap(*args, **kwargs):
            self.connections += 1 
            await self.loop.run_in_executor(None, self.indicate)
            e = None
            try:
                res = await original_func(*args, **kwargs)
            except Exception as _e: 
                e = _e
            self.connections -= 1
            await self.loop.run_in_executor(None, self.indicate)
            if e:
                # Pass exception to Quart.
                raise e
            return res 
        self.server.dispatch_websocket = wrap


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
        elif self.connections:
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
