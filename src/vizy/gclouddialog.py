import os
import time
import dash_html_components as html
import dash_core_components as dcc
from kritter import Kritter, KtextBox, Ktext, Kdropdown, Kbutton, Kdialog, KsideMenuItem
from dash_devices.dependencies import Input, Output
import dash_bootstrap_components as dbc
from kritter import Gcloud, Kritter

AUTH_FILE = "gcloud.auth"

UNAUTHORIZED = 0
CODE_INPUT = 1
AUTHORIZED = 2

class GcloudDialog:

    def __init__(self, kapp, pmask):
        self.state = UNAUTHORIZED
        self.gcloud = Gcloud(os.path.join(kapp.etcdir, AUTH_FILE))
        
        style = {"label_width": 4, "control_width": 5}
        bstyle = {"vertical_padding": 0}

        self.authenticate = Kbutton(name="Authenticate", style=style, service=None)    
        self.code = Ktext(name="Code", style=style)
        self.submit = Kbutton(name="Submit", style=bstyle)
        self.code.append(self.submit) 
        self.test = Kbutton(name="Test")
        self.store_url = dcc.Store(id=Kritter.new_id())
        layout = [self.authenticate, self.code, self.test, self.store_url]

        dialog = Kdialog(title="Google cloud configuration", layout=layout)
        self.layout = KsideMenuItem("Google cloud", dialog, "google")

        @self.authenticate.callback()
        def func():
            print("authenticate")
            url = self.gcloud.get_url()
            return Output(self.store_url.id, "data", url)

        @dialog.callback_view()
        def func(open):
            if open:
                return self.update()

        script = f"""
            function(url) {{
                window.open(url, "_blank");
                return null;
            }}
            """
        kapp.clientside_callback(script,
            Output("_none", Kritter.new_id()), [Input(self.store_url.id, "data")]
        )
 

    def update(self):
        if self.state!=CODE_INPUT:
            self.state = UNAUTHORIZED if self.gcloud.creds() is None else AUTHORIZED

        if self.state==UNAUTHORIZED:
            return self.authenticate.out_disp(True) + self.code.out_disp(False) + self.test.out_disp(False)
        elif self.state==CODE_INPUT:
            return self.authenticate.out_disp(False) + self.code.out_disp(True) + self.test.out_disp(False)
        else:
            return self.authenticate.out_disp(False) + self.code.out_disp(False) + self.test.out_disp(True)


