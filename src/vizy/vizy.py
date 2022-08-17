#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

import os
from kritter import Kritter, ConfigFile, Klogin, MEDIA_DIR
from .vizypowerboard import VizyPowerBoard
from .users import Users 

BASE_DIR = os.path.dirname(os.path.realpath(__file__))
VIZY_HOME = "VIZY_HOME"
ETCDIR_NAME = 'etc'
APPSDIR_NAME = 'apps'
EXAMPLESDIR_NAME = 'examples'
SCRIPTSDIR_NAME = 'scripts'

VIZY_STYLE = '''
.side-button {
    min-width: 160px;
    text-align: left; 
    margin: 2px 2px 0px 2px;
    padding: 4px 0px 4px 10px;
    /*color: #ffffff;
    font: verdana;
    border-radius: 0; */
    border: 0px;
    background-color: #909090; 
}

.button-div {
    /* background-color: blue; */ 
    margin: 0px;
    padding: 0px;   
}

html, body, #react-entry-point, #_main {
    height: 100%;
}
'''

CONFIG_FILE = "vizy_main.json"
DEFAULT_CONFIG = {
    "software": {
        "update server": "https://vizycam.com/sd",
        "channel": "vizy_main",
        "start-up app": None,
        "start-up example": "video",
        "maximum logins": 3
    }, 
    "hardware": {
        "power board": {
            "PCB type": "rpi_main",
            "firmware type": "main"
        },
        "camera": {
            "type": "Sony IMX477 12.3 megapixel",
            "IR-cut": "switchable",
            "version": "1.0"
        },
        "coprocessor": None 
    }
}


def dirs(num):
    homedir = os.getenv(VIZY_HOME)
    if homedir is None:
        raise RuntimeError("VIZY_HOME environment variable should be set to the directory where Vizy software is installed.")
    if not os.path.exists(homedir):
        raise RuntimeError("VIZY_HOME directory doesn't exist!")
    uid = os.stat(homedir).st_uid
    gid = os.stat(homedir).st_gid
    etcdir = os.path.join(homedir, ETCDIR_NAME)
    if not os.path.exists(etcdir):
        os.mkdir(etcdir)
        os.chown(etcdir, uid, gid)
    appsdir = os.path.join(homedir, APPSDIR_NAME)
    if not os.path.exists(appsdir):
        os.mkdir(appsdir)
        os.chown(appsdir, uid, gid)
    examplesdir = os.path.join(homedir, EXAMPLESDIR_NAME)
    if not os.path.exists(examplesdir):
        os.mkdir(examplesdir)
        os.chown(examplesdir, uid, gid)

    result = homedir, etcdir, appsdir, examplesdir
    return result[0:num]


class VizyConfig(ConfigFile):

    def __init__(self, etcdir):
        config_filename = os.path.join(etcdir, CONFIG_FILE)
        super().__init__(config_filename, DEFAULT_CONFIG)


class VizyLogin(Klogin):

    def __init__(self, kapp):
        super().__init__(kapp, os.path.join(BASE_DIR, "login"), kapp.users.config['secret'])

        # Override authorize function with ours
        self.authorize_func = kapp.users.authorize


class Vizy(Kritter):
    def __init__(self):

        super().__init__()

        self.title = "Vizy"
        self.homedir, self.etcdir, self.appsdir, self.examplesdir = dirs(4)
        self.vizy_config = VizyConfig(self.etcdir)
        self.users = Users(self.etcdir)

        # Add our own media path
        self.media_path.insert(0, os.path.join(BASE_DIR, MEDIA_DIR))

        # Instantiate power board
        self.power_board = VizyPowerBoard()
        self.uuid = self.power_board.uuid()

        # Create login
        self.login = VizyLogin(self)

    @property
    def style(self):
        return self.__style
    
    @style.setter
    def style(self, _style):
        self.__style = _style
        _style = VIZY_STYLE + _style
        Kritter.style.fset(self, _style)




