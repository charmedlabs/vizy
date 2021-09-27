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

    def __init__(self, kapp, pmask):
        self.kapp = kapp

        check_button = Kbutton(name="Check for updates at vizycam.com", id=Kritter.new_id(), spinner=True)
        check_response = html.Div(id=Kritter.new_id())
        install_button = Kbutton(name="Install", id=Kritter.new_id(), spinner=True)
        @install_button.callback()
        def func():
            # Block unauthorized attempts
            if not callback_context.client.authentication&pmask:
                return
            # Start spinner
            self.kapp.push_mods(install_button.out_spinner_disp(True))
            # Close dialog, start install/open install dialog.  Note, execterm.exec takes a few seconds to 
            # run because it waits, so this func will take a few more seconds to return the result.  
            return self.update_dialog.out_open(False) + install_button.out_spinner_disp(False) + self.kapp.execterm.exec(command=f"python3 {os.path.join(self.kapp.homedir, SCRIPTSDIR_NAME, INSTALL_UPDATE_SCRIPT)}", size="lg", backdrop="static", close_button=False, logfile=os.path.join(self.kapp.homedir, SCRIPTSDIR_NAME, "install.log"))

        upload = dcc.Upload(id=Kritter.new_id(), children=html.Div([
                html.Div('Drag and drop Vizy software package here.'),
                html.Div('Or click here to select local file.'),
            ]), style={
                'width': '100%',
                'height': '100px',
                'lineHeight': '20px',
                'padding-top': '30px',
                'borderWidth': '1px',
                'borderStyle': 'dashed',
                'borderRadius': '5px',
                'textAlign': 'center',
            },
            multiple=False
        )

        update_url = dbc.Input(id=Kritter.new_id(), placeholder="Copy URL of Vizy software package here and press Install.", type="text")
        install_button2 = Kbutton(name="Install", id=Kritter.new_id())

        update_layout = [
            html.Div("You are currently running Vizy version "+__version__+".", style={"padding-bottom": "10px"}),
            check_button, check_response, html.Div("--OR--",style={"padding": "10px 0px 10px 0px"}),
            html.Div(upload),
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

        @self.kapp.callback_shared(None,
            [Input(upload.id, 'contents')], [State(upload.id, 'filename')]
        )
        def func(contents, filename):
            # Block unauthorized attempts
            if not callback_context.client.authentication&pmask or not contents or not filename:
                return
            # Contents are type and contents separated by comma, so we grab 2nd item.
            # See https://dash.plotly.com/dash-core-components/upload
            bin_contents = base64.b64decode(contents.split(",")[1])
            # Make temp directory 
            install_dir = os.path.join(self.kapp.homedir, "tmp")
            os.system("mkdir " + install_dir)
            filename = os.path.join(install_dir, filename)
            # Write file
            file = open(filename, "wb")
            file.write(bin_contents)
            file.close()
            # Return contents to reset so we can set again
            return [Output(self.update_dialog.id, "is_open", False), self.kapp.execterm.exec(command=f"python3 {os.path.join(self.kapp.homedir, SCRIPTSDIR_NAME, INSTALL_UPDATE_SCRIPT)} {filename} -r", size="lg", backdrop="static", close_button=False, logfile=os.path.joinself)]

        @install_button2.callback([State(update_url.id, 'value')])
        def func(url):
            # Block unauthorized attempts
            if not callback_context.client.authentication&pmask or not url:
                return
            return [Output(self.update_dialog.id, "is_open", False), self.kapp.execterm.exec(command="python3 " + os.path.join(self.kapp.homedir, SCRIPTSDIR_NAME, INSTALL_UPDATE_SCRIPT) + " " + url + " -r", size="lg", backdrop="static", close_button=False)]

        @self.update_dialog.callback_view()
        def func(enable):
            if not enable:
                return check_button.out_spinner_disp(False) + [Output(check_response.id, "children", None), Output(update_url.id, 'value', None), Output(upload.id, 'contents', None)]

        self.layout = KsideMenuItem("Update", self.update_dialog, "chevron-circle-up", kapp=self.kapp)

