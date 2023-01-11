import kritter

class NewProjectDialog(kritter.Kdialog):
    def __init__(self, get_projects, title=[kritter.Kritter.icon("folder"), "New project"], overwritable=False):
        self.get_projects = get_projects
        self.name = ''
        self.callback_func = None
        name = kritter.KtextBox(placeholder="Enter project name")
        save_button = kritter.Kbutton(name=[kritter.Kritter.icon("save"), "Save"], disabled=True)
        dialog_text = kritter.Ktext(style={"control_width": 12})
        if overwritable:
            dialog = kritter.KyesNoDialog(title="Overwrite project?", layout=dialog_text, shared=True)
        else:
            dialog = kritter.KokDialog(title="Project exists", layout=dialog_text, shared=True)

        name.append(save_button)
        super().__init__(title=title, close_button=[kritter.Kritter.icon("close"), "Cancel"], layout=[name, dialog], shared=True)

        @self.callback_view()
        def func(state):
            if not state:
                return name.out_value("")

        @name.callback()
        def func(val):
            if val:
                self.name = val
            return save_button.out_disabled(not bool(val))

        @save_button.callback()
        def func():
            projects = self.get_projects()
            if self.name in projects:
                if overwritable:
                    return dialog_text.out_value(f'"{self.name}" exists. Do you want to overwrite?') + dialog.out_open(True)
                else:
                    return dialog_text.out_value(f'"{self.name}" already exists.') + dialog.out_open(True)

            mods = []
            if self.callback_func:
                res = self.callback_func(self.name)
                if isinstance(res, list):
                    mods += res
            return self.out_open(False) + mods 

        if overwritable:
            @dialog.callback_response()
            def func(val):
                if val:
                    self.kapp.push_mods(self.out_open(False))
                    if self.callback_func:
                        self.callback_func(self.name)
 
    def callback_project(self):
        def wrap_func(func):
            self.callback_func = func
        return wrap_func
