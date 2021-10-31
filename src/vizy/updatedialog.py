import os 
import json
import subprocess
import base64
from vizy import __version__, SCRIPTSDIR_NAME
from dash_devices.dependencies import Input, Output, State
from dash_devices import callback_context
import dash_bootstrap_components as dbc
import dash_html_components as html
import dash_core_components as dcc 
from kritter import Kritter, KsideMenuItem, Kdialog, Kbutton
from urllib.request import Request, urlopen
from distutils.version import LooseVersion

LATEST_SOFTWARE = "_latest.json"
INSTALL_UPDATE_SCRIPT = "install_update"

def get_latest(config, tries=3):
    for i in range(tries):
        try:
            url = os.path.join(config['software']['update server'], config['software']['channel']+LATEST_SOFTWARE)
            request = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            latest = urlopen(request).read()
            latest = json.loads(latest)
            return latest, LooseVersion(latest['version']) > LooseVersion(__version__) 
        except Exception as _e: 
            e = _e
    raise e

class UpdateDialog:

    # Note, we removed drag-drop file functionality, because as the build packages
    # became bigger (20MB), it became unreliable, so it has been removed for now.
    # There are size limits in the Quart configuration, but this doesn't seem to 
    # be the whole story.  

    def __init__(self, kapp, exit_app, pmask):
        self.kapp = kapp

        check_button = Kbutton(name="Check for updates at vizycam.com", spinner=True)
        check_response = html.Div(id=Kritter.new_id())
        install_button = Kbutton(name="Install", spinner=True)
        @install_button.callback()
        def func():
            # Block unauthorized attempts
            if not callback_context.client.authentication&pmask:
                return
            # Start spinner
            self.kapp.push_mods(install_button.out_spinner_disp(True))
            # Kill app
            exit_app()
            # Close dialog, start install/open install dialog.  Note, execterm.exec takes a few seconds to 
            # run because it waits, so this func will take a few more seconds to return the result.  
            return self.update_dialog.out_open(False) + install_button.out_spinner_disp(False) + self.kapp.execterm.exec(command=f"python3 {os.path.join(self.kapp.homedir, SCRIPTSDIR_NAME, INSTALL_UPDATE_SCRIPT)}", size="lg", backdrop="static", close_button=False, logfile=os.path.join(self.kapp.homedir, SCRIPTSDIR_NAME, "install.log"))

        update_url = dbc.Input(id=Kritter.new_id(), placeholder="Copy URL of Vizy software package here and press Install.", type="text")
        install_button2 = Kbutton(name="Install", spinner=True)

        update_layout = [
            html.Div("You are currently running Vizy version "+__version__+".", style={"padding-bottom": "10px"}),
            check_button, check_response, 
            html.Div("--OR--",style={"padding": "10px 0px 10px 0px"}), 
            html.Div([update_url, install_button2]),
        ]

        self.update_dialog = Kdialog(title="Update your Vizy software and firmware", layout=update_layout, kapp=self.kapp, shared=True)

        @check_button.callback()
        def func():
            self.kapp.push_mods(check_button.out_spinner_disp(True) + [Output(check_response.id, "children", "")])
            try:
                latest, newer = get_latest(self.kapp.vizy_config.config) 
                if newer:
                    check_layout = [html.Div("Version "+latest['version']+" is available."), install_button.layout]
                    return [Output(check_response.id, "children", check_layout)] + check_button.out_spinner_disp(False)
            except Exception as e:
                return [Output(check_response.id, "children", "Error: " + str(e))] + check_button.out_spinner_disp(False)
            return [Output(check_response.id, "children", "You are running the latest version.")] + check_button.out_spinner_disp(False)

        @install_button2.callback([State(update_url.id, 'value')])
        def func(url):
            # Block unauthorized attempts
            if not callback_context.client.authentication&pmask or not url:
                return
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "http://" + url
            self.kapp.push_mods(install_button2.out_spinner_disp(True))
            # Kill app
            exit_app()
            return self.update_dialog.out_open(False) + install_button2.out_spinner_disp(False) + self.kapp.execterm.exec(command=f"python3 {os.path.join(self.kapp.homedir, SCRIPTSDIR_NAME, INSTALL_UPDATE_SCRIPT)} {url}", size="lg", backdrop="static", close_button=False, logfile=os.path.join(self.kapp.homedir, SCRIPTSDIR_NAME, "install.log"))

        @self.update_dialog.callback_view()
        def func(enable):
            if not enable:
                return check_button.out_spinner_disp(False) + [Output(check_response.id, "children", None), Output(update_url.id, 'value', None)]

        self.layout = KsideMenuItem("Update", self.update_dialog, "chevron-circle-up", kapp=self.kapp)

