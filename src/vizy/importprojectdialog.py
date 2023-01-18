import os
import kritter
import base64
import json
import time 
import gdown

IMPORT_FILE = "import.zip"

class ImportProjectDialog(kritter.Kdialog):

    def __init__(self, gdrive, project_dir, key_type):
        self.gdrive = gdrive
        self.project_dir = project_dir
        self.key_type = key_type
        self.callback_func = None
        self.key_c = kritter.KtextBox(placeholder="Paste share key here")
        self.import_button = kritter.Kbutton(name=[kritter.Kritter.icon("cloud-download"), "Import"], spinner=True, disabled=True)
        self.key_c.append(self.import_button)
        self.status = kritter.Ktext(style={"control_width": 12})
        self.confirm_text = kritter.Ktext(style={"control_width": 12})
        self.confirm_dialog = kritter.KyesNoDialog(title="Confirm", layout=self.confirm_text, shared=True)
        super().__init__(title=[kritter.Kritter.icon("cloud-download"), "Import project"], layout=[self.key_c, self.status, self.confirm_dialog], shared=True)

        @self.confirm_dialog.callback_response()
        def func(val):
            if val:
                self.kapp.push_mods(self.import_button.out_spinner_disp(True))
                mods = self.import_button.out_spinner_disp(False)
                self.project_name = self._next_project()
                self.kapp.push_mods(self.confirm_dialog.out_open(False))
                return mods + self._import()

        @self.callback_view()
        def func(state):
            if not state:
                return self.status.out_value("") + self.key_c.out_value("") + self.import_button.out_disabled(True)

        @self.key_c.callback()
        def func(key):
            return self.import_button.out_disabled(False)

        @self.import_button.callback(self.key_c.state_value())
        def func(key):
            self.kapp.push_mods(self.import_button.out_spinner_disp(True))
            mods = self.import_button.out_spinner_disp(False)
            key = key.strip()
            if key.startswith('V') and key.endswith('V'):
                try:
                    key = key[1:-1]
                    data = json.loads(base64.b64decode(key.encode()).decode())
                    if data[0]!=self.key_type:
                        raise RuntimeError("This is not the correct type of key.") 
                    self.project_name = data[1]
                    self.key = data[2]
                    # We could add a callback here for client code to verify and raise exception
                except Exception as e:
                    return mods +  self.status.out_value(f"This key appears to be invalid. ({e})") 
                if os.path.exists(os.path.join(self.project_dir, self.project_name)):
                    return mods + self.confirm_text.out_value(f'A project named "{self.project_name}" already exists.  Would you like to save it as "{self._next_project()}"?') + self.confirm_dialog.out_open(True)
                return mods + self._import()
            else:
                return mods + self.status.out_value('Share keys start and end with a "V" character.') 

    def _next_project(self):
        project_name = self.project_name+"_"
        while os.path.exists(os.path.join(self.project_dir, project_name)):
            project_name += "_"
        return project_name 

    def _update_status(self, percent):
        self.kapp.push_mods(self.status.out_value(f"Downloading {self.project_name} project ({percent}%)..."))

    def _import(self):
        try:
            new_project_dir = os.path.join(self.project_dir, self.project_name)
            os.makedirs(new_project_dir)
            import_file = os.path.join(new_project_dir, IMPORT_FILE) 
            # Use gdown code to download if we don't have Google Drive credentials
            if self.gdrive is None:
                self.kapp.push_mods(self.status.out_value(f"Downloading {self.project_name} project..."))
                gdown.download(id=self.key, output=import_file)
            else: # Otherwise use Google credentials, which gives us a some feedback.
                self.gdrive.download(self.key, import_file, self._update_status)
            self.kapp.push_mods(self.status.out_value("Unzipping project files..."))
            os.chdir(new_project_dir)
            os.system(f"unzip {IMPORT_FILE}")
            os.remove(import_file)
        except Exception as e:
            print("Unable to import project.", e)
            os.rmdir(new_project_dir)
            self.kapp.push_mods(self.status.out_value(f'Unable to import project. ({e})'))
            return []
        self.kapp.push_mods(self.status.out_value("Done!")) 
        time.sleep(1)
        mods = self.out_open(False)
        if self.callback_func:
            res = self.callback_func(self.project_name)
            if isinstance(res, list):
                mods += res
        return mods 

    def callback(self):
        def wrap_func(func):
            self.callback_func = func
        return wrap_func

