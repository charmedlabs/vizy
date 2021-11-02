import os
import time
import dash_html_components as html
from kritter import Kritter, KtextBox, Ktext, Kdropdown, Kbutton, Kdialog, KsideMenuItem, PMASK_MAX, PMASK_MIN
from dash_devices.dependencies import Input, Output
from dash_devices import callback_context
import dash_bootstrap_components as dbc

DUMMY_PASSWORD = "98446753"
CHANGE = "Change"
ADD = "Add"
REMOVE = "Remove"
ACTIONS = [CHANGE, ADD, REMOVE]
MIN_USERNAME_LENGTH = 4
MIN_PASSWORD_LENGTH = 4

class UserDialog:

    def __init__(self, kapp, pmask, types=None):
        if os.geteuid()!=0:
            raise RuntimeError("You need to run with root permissions (psst, use sudo).")

        if types is None:
            from .vizyvisor import PMASK_APPS, PMASK_CONSOLE, PMASK_SYSTEM
            self.types = {
                "Guest": PMASK_MIN, 
                "User": PMASK_APPS + PMASK_CONSOLE + PMASK_SYSTEM, 
                "Admin": PMASK_MAX
            }
        else:
            self.types = types

        style = {"label_width": 4, "control_width": 5}
        self.kapp = kapp
        self.action_c = Kdropdown(name='Action', options=ACTIONS, style=style, service=None)
        self.usernames_c = Kdropdown(name='Username', style=style, service=None)
        self.username_c = KtextBox(name="Username", style=style, service=None)
        self.type_c = Kdropdown(name='Type', options=[k for k, v in self.types.items()], style=style, service=None)
        self.password_c = KtextBox(name="Password", type="password", style=style, service=None)
        self.c_password_c = KtextBox(name="Confirm password", type="password", style=style, service=None)
        self.a_password_c = KtextBox(name="Admin password", type="password", style=style, service=None)
        self.status_c = dbc.PopoverBody(id=Kritter.new_id())
        self.save = Kbutton(name=[Kritter.icon("angle-double-down"), "Save"], service=None)
        self.po = dbc.Popover(self.status_c, id=Kritter.new_id(), is_open=False, target=self.save.id)

        layout = [self.action_c, self.usernames_c, self.username_c, self.type_c, self.password_c, self.c_password_c, self.a_password_c, self.po]

        dialog = Kdialog(title=[Kritter.icon("user"), "User Configuration"], left_footer=self.save, layout=layout)
        self.layout = KsideMenuItem("Users", dialog, "user")

        @dialog.callback_view()
        def func(open):
            if open:
                return self.action_c.out_value(CHANGE)
            else:
                return self.out_status(None)

        @self.action_c.callback()
        def func(action):
            return self.update(action)

        @self.usernames_c.callback(self.action_c.state_value())
        def func(username, action):
            if username is None:
                return
            p = self.kapp.users.config['users'][username]['permissions']
            for name, val in self.types.items():
                if p==val:
                    break

            mods = self.out_status(None) + self.a_password_c.out_disp(True) + self.a_password_c.out_value("")
            if action==CHANGE:
                # We don't know the password or password length so we insert a dummy password to indicate 
                # that there's a password.
                mods += self.type_c.out_disp(True) + self.type_c.out_value(name) + self.password_c.out_disp(True) + self.password_c.out_value(DUMMY_PASSWORD) + self.c_password_c.out_disp(True) + self.c_password_c.out_value(DUMMY_PASSWORD)
            return mods 

        @self.username_c.callback()
        def func(username):
            if len(username)>=MIN_USERNAME_LENGTH:
                return self.out_status(None) + self.type_c.out_disp(True) + self.password_c.out_disp(True) + self.a_password_c.out_disp(True) + self.type_c.out_value(None) + self.password_c.out_value("") + self.c_password_c.out_disp(True) + self.c_password_c.out_value("") + self.a_password_c.out_value("")

        @self.save.callback(self.action_c.state_value() + self.username_c.state_value() + self.usernames_c.state_value() + self.type_c.state_value() + self.password_c.state_value() + self.c_password_c.state_value() + self.a_password_c.state_value())
        def func(action, username, usernames, _type, password, c_password, a_password):
            if not self.kapp.users.authorize(callback_context.client.username, a_password):
                return self.out_status("Sorry, admin password is incorrect.")
            if action==ADD and username in self.kapp.users.config['users']:
                return self.out_status(f"Sorry, username {username} already exists.")
            if action==ADD and _type is None:
                return self.out_status("Sorry, you need to specify type.")
            if action==REMOVE and callback_context.client.username==usernames:
                return self.out_status("Sorry, you cannot remove yourself.")
            if action==CHANGE and _type!="Admin" and callback_context.client.username==usernames:
                return self.out_status("Sorry, you cannot remove your own admin privileges.")
            if action==CHANGE or action==ADD:
                if password!=c_password:
                    return self.out_status("Sorry, passwords do not match.")
                if len(password)<MIN_PASSWORD_LENGTH:
                    return self.out_status(f"Sorry, passwords must be at least {MIN_PASSWORD_LENGTH} characters long.")

            if action==CHANGE:
                if password==DUMMY_PASSWORD:
                    # Password hasn't changed, send None for password to signal to kapp.users.
                    password = None
                kapp.users.add_change_user(usernames, self.types[_type], password)
            elif action==ADD:
                kapp.users.add_change_user(username, self.types[_type], password)
            elif action==REMOVE:
                kapp.users.remove_user(usernames)

            self.kapp.push_mods(self.update(action))
            time.sleep(1) # wait for gui to update so status message (below) winds up in the right place 
            return self.out_status("Saved!") 


    def out_status(self, status):
        if status is None:
            return [Output(self.po.id, "is_open", False)]
        return [Output(self.status_c.id, "children", status), Output(self.po.id, "is_open", True)]

    def update(self, action):
        # Reset values
        mods = self.out_status(None) + self.type_c.out_disp(False) + self.password_c.out_disp(False) + self.c_password_c.out_disp(False) + self.a_password_c.out_disp(False)
        if action==CHANGE or action==REMOVE:
            users = [user for user, info in self.kapp.users.config['users'].items()]
            users.sort(key=lambda n: n.lower()) # sort ignoring upper/lowercase
            mods += self.usernames_c.out_disp(True) + self.username_c.out_disp(False) + self.usernames_c.out_options(users) + self.usernames_c.out_value(None) 
        elif action==ADD:
            mods += self.usernames_c.out_disp(False) + self.username_c.out_disp(True) + self.username_c.out_value("") + self.type_c.out_value(None)  

        return mods 

