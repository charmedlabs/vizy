import os
import kritter
import base64
import json
import dash_core_components as dcc
import dash_html_components as html
from dash_devices.dependencies import Input, Output, State

class ExportProjectDialog(kritter.Kdialog):

    def __init__(self, gdrive, key_type, file_info_func, key_func=None):
        self.gdrive = gdrive
        self.key_type = key_type
        self.file_info_func = file_info_func
        self.key_func = key_func
        self.export = kritter.Kbutton(name=[kritter.Kritter.icon("cloud-upload"), "Export"], spinner=True)
        self.status = kritter.Ktext(style={"control_width": 12})
        self.copy_key = kritter.Kbutton(name=[kritter.Kritter.icon("copy"), "Copy share key"], disp=False)
        self.key_store = dcc.Store(data="hello_there", id=kritter.Kritter.new_id())
        super().__init__(title=[kritter.Kritter.icon("cloud-upload"), "Export project"], layout=[self.export, self.status, self.copy_key, self.key_store], shared=True)

        # This code copies to the clipboard using the hacky method.  
        # (You need a secure page (https) to perform navigator.clipboard operations.)   
        script = """
            function(click, url) {
                var textArea = document.createElement("textarea");
                textArea.value = url;
                textArea.style.position = "fixed";  
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();
                document.execCommand('copy');
                textArea.remove();
            }
        """
        self.kapp.clientside_callback(script, Output("_none", kritter.Kritter.new_id()), [Input(self.copy_key.id, "n_clicks")], state=[State(self.key_store.id, "data")])

        def _update_status(percent):
            self.kapp.push_mods(self.status.out_value(f"Copying to Google Drive ({percent}%)..."))

        @self.callback_view()
        def func(state):
            if not state:
                return self.status.out_value("") + self.copy_key.out_disp(False)

        @self.export.callback()
        def func():
            self.kapp.push_mods(self.export.out_spinner_disp(True) + self.status.out_value("Zipping project files...") + self.copy_key.out_disp(False))
            file_info = self.file_info_func()
            os.chdir(file_info['project_dir'])
            files_string = ''
            for i in file_info['files']:
                files_string += f" '{i}'"
            files_string = files_string[1:]
            export_file = kritter.time_stamped_file("zip", f"{file_info['project_name']}_export_")
            os.system(f"zip -r '{export_file}' {files_string}")
            gdrive_file = os.path.join(file_info['gdrive_dir'], export_file)
            try:
                self.gdrive.copy_to(os.path.join(file_info['project_dir'], export_file), gdrive_file, True, _update_status)
            except Exception as e:
                print("Unable to upload project export file to Google Drive.", e)
                self.kapp.push_mods(self.status.out_value(f'Unable to upload project export file to Google Drive. ({e})'))
                return 
            url = self.gdrive.get_url(gdrive_file)
            pieces = url.split("/")
            # Remove obvous non-id pieces
            pieces = [i for i in pieces if i.find(".")<0 and i.find("?")<0]
            # sort by size
            pieces.sort(key=len, reverse=True)
            # The biggest piece is going to be the id.  Encode with the project name, surround by V's to 
            # prevent copy-paste errors (the key might be emailed, etc.)  
            key = f"V{base64.b64encode(json.dumps([self.key_type, file_info['project_name'], pieces[0]]).encode()).decode()}V"
            # Write key to file for safe keeping
            key_filename = os.path.join(file_info['project_dir'], kritter.time_stamped_file("key", "share_key_"))
            with open(key_filename, "w") as file:
                file.write(key)
            if self.key_func:
                self.key_func(key)
            return self.status.out_value(["Done!  Press ", html.B("Copy share key"), " button to copy to clipboard."]) + self.copy_key.out_disp(True) + self.export.out_spinner_disp(False) + [Output(self.key_store.id, "data", key)]
