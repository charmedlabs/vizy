import os 
import dash_html_components as html
from kritter import Kritter, Ktext, Kbutton, Kdialog, KsideMenuItem
from dash_devices.dependencies import Output

class AboutDialog:

    def __init__(self, kapp, pmask):
        self.kapp = kapp
        # pmask isn't used for now...

        style = {"label_width": 3, "control_width": 8}
        self.img = html.Img(id=self.kapp.new_id(), style={"display": "block", "max-width": "100%", "margin-left": "auto", "margin-right": "auto"})
        self.version = Ktext(name="Version", style=style)
        self.loc = Ktext(name="Location", style=style)
        self.author = Ktext(name="Author", style=style)
        self.desc = Ktext(name="Description", style=style)
        self.info_button = Kbutton(name=[Kritter.icon("info-circle"), "More info"], target="_blank")
        self.view_button = Kbutton(name=[Kritter.icon("edit"), "View/edit"], target="_blank")
        self.info_button.append(self.view_button)
        layout = [self.img, self.version, self.author, self.loc, self.desc]
        self.dialog = Kdialog(title="", layout=layout, left_footer=self.info_button)
        self.layout = KsideMenuItem("", self.dialog, "info-circle")

    def out_update(self, prog):
        mods = []
        title = f"About {prog['name']}"
        if prog['version']:
            version = f"{prog['version']}, installed or modified on {prog['mrfd']}"
        else:
            version = f"installed or modified on {prog['mrfd']}"

        email = html.A(prog['email'], href=f"mailto:{prog['email']}") if prog["email"] else None
        if prog["author"]:
            if email:
                author = [prog["author"] + ", ", email]
            else:
                author = prog["author"]
        elif email:
            author = email
        else:
            author = None

        mods += self.loc.out_value(os.path.join(self.kapp.homedir, prog['path']))
        mods += self.info_button.out_disp(bool(prog['url']))
        if prog['url']:
            mods += self.info_button.out_url(prog['url'])

        mods += self.author.out_disp(bool(author))
        if author:
            mods += self.author.out_value(author)

        mods += self.desc.out_disp(bool(prog['description']))
        if prog['description']:
            mods += self.desc.out_value(prog['description'])
        
        return mods + self.layout.out_name(title) + self.dialog.out_title([Kritter.icon("info-circle"), title]) + [Output(self.img.id, "src", prog['image_no_bg'])] + self.version.out_value(version) 