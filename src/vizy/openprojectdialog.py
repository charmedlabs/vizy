import kritter

class OpenProjectDialog(kritter.Kdialog):
    def __init__(self, get_projects, title=[kritter.Kritter.icon("folder-open"), "Open project"]):
        self.get_projects = get_projects
        self.selection = ''
        self.callback_func = None
        open_button = kritter.Kbutton(name=[kritter.Kritter.icon("folder-open"), "Open"], disabled=True)
        delete_button = kritter.Kbutton(name=[kritter.Kritter.icon("trash"), "Delete"], disabled=True)
        delete_text = kritter.Ktext(style={"control_width": 12})
        yesno = kritter.KyesNoDialog(title="Delete project?", layout=delete_text, shared=True)
        select = kritter.Kdropdown(value=None, placeholder="Select project...")
        select.append(open_button)
        select.append(delete_button)
        super().__init__(title=title, layout=[select, yesno], shared=True)

        @self.callback_view()
        def func(state):
            if state:
                return select.out_options(self.get_projects(True))
            else:
                return select.out_value(None)

        @select.callback()
        def func(selection):
            self.selection = selection
            disabled = not bool(selection)
            return open_button.out_disabled(disabled) + delete_button.out_disabled(disabled)

        @open_button.callback()
        def func():
            mods = []
            if self.callback_func:
                res = self.callback_func(self.selection, False)
                if isinstance(res, list):
                    mods += res
            return self.out_open(False) + mods

        @delete_button.callback()
        def func():
            return delete_text.out_value(f'Are you sure you want to delete "{self.selection}" project?') + yesno.out_open(True)

        @yesno.callback_response()
        def func(val):
            if val:
                mods = []
                if self.callback_func:
                    res = self.callback_func(self.selection, True)
                    if isinstance(res, list):
                        mods += res
                projects = self.get_projects(True)
                return select.out_options(projects) + select.out_value(None)

    def callback_project(self):
        def wrap_func(func):
            self.callback_func = func
        return wrap_func
