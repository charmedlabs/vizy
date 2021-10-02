import os
import time
from datetime import datetime
import cv2
import dash_html_components as html
import dash_core_components as dcc
from kritter import Kritter, KtextBox, Ktext, Kdropdown, Kbutton, Kdialog, KsideMenuItem
from dash_devices.dependencies import Input, Output
import dash_bootstrap_components as dbc
from kritter import Gcloud, Kritter, GPstoreMedia
from .vizy import BASE_DIR

AUTH_FILE = "gcloud.auth"

UNAUTHORIZED = 0
CODE_INPUT = 1
AUTHORIZED = 2

class GcloudDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        self.state = UNAUTHORIZED
        self.gcloud = Gcloud(os.path.join(kapp.etcdir, AUTH_FILE))
        
        style = {"label_width": 3, "control_width": 6}
        bstyle = {"vertical_padding": 0}

        self.authenticate = Kbutton(name="Authenticate", style=style, service=None)    
        self.code = KtextBox(name="Enter code", style=style, service=None)
        self.submit = Kbutton(name="Submit", style=bstyle, service=None)
        self.code.append(self.submit) 
        self.test = Kbutton(name="Test", spinner=True, service=None)
        self.remove = Kbutton(name="Remove authentication", service=None)
        self.status = dbc.PopoverBody(id=Kritter.new_id())
        self.po = dbc.Popover(self.status, id=Kritter.new_id(), is_open=False, target=self.test.id)

        self.store_url = dcc.Store(id=Kritter.new_id())
        layout = [self.authenticate, self.code, self.test, self.remove, self.store_url, self.po]

        dialog = Kdialog(title="Google cloud configuration", layout=layout)
        self.layout = KsideMenuItem("Google cloud", dialog, "google")

        @self.authenticate.callback()
        def func():
            url = self.gcloud.get_url()
            self.state = CODE_INPUT
            return [Output(self.store_url.id, "data", url)] + self.update()

        @self.remove.callback()
        def func():
            self.gcloud.remove_creds()
            self.state = UNAUTHORIZED
            return self.update()

        @self.submit.callback(self.code.state_value())
        def func(code):
            self.gcloud.set_code(code)
            self.state = AUTHORIZED
            return self.update()

        @self.test.callback()
        def func():
            # Enable spinner, showing we're busy
            self.kapp.push_mods(self.test.out_spinner_disp(True) + self.out_status(None))
            # Generate test image
            image =  cv2.imread(os.path.join(BASE_DIR, "test.jpg"))
            date = datetime.now().strftime("%m-%d-%Y %H:%M:%S")
            image = cv2.putText(image, "VIZY TEST IMAGE",  (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (25, 25, 25), 3)
            image = cv2.putText(image, date,  (50, 140), cv2.FONT_HERSHEY_SIMPLEX, 1, (25, 25, 25), 3)
            cv2.imwrite("/tmp/test.jpg", image) 
            # Upload                                                   
            gpsm = GPstoreMedia(self.gcloud)
            result = self.test.out_spinner_disp(False)
            if gpsm.save("/tmp/test.jpg"):
                result += self.out_status([html.P("Success!"), html.P("(Check your Google Photos account.)")]) 
            else:
                result += self.out_status("An unknown error occurred.")
            return result

        @dialog.callback_view()
        def func(open):
            if open:
                return self.update()
            else:
                return self.out_status(None)

        script = f"""
            function(url) {{
                window.open(url, "_blank");
                return null;
            }}
            """
        kapp.clientside_callback(script,
            Output("_none", Kritter.new_id()), [Input(self.store_url.id, "data")]
        )
 
    def out_status(self, status):
        if status is None:
            return [Output(self.po.id, "is_open", False)]
        return [Output(self.status.id, "children", status), Output(self.po.id, "is_open", True)]

    def update(self):
        if self.state!=CODE_INPUT:
            self.state = UNAUTHORIZED if self.gcloud.creds() is None else AUTHORIZED

        if self.state==UNAUTHORIZED:
            return self.authenticate.out_disp(True) + self.code.out_disp(False) + self.test.out_disp(False) + self.remove.out_disp(False) + self.out_status(None)
        elif self.state==CODE_INPUT:
            return self.authenticate.out_disp(False) + self.code.out_disp(True) + self.test.out_disp(False) + self.remove.out_disp(False) + self.out_status(None)
        else:
            return self.authenticate.out_disp(False) + self.code.out_disp(False) + self.test.out_disp(True) + self.remove.out_disp(True) + self.out_status(None)


