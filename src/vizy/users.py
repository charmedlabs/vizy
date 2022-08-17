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
import hashlib
import binascii
from kritter import ConfigFile, PMASK_MAX, PMASK_MIN

def user(username, permissions, password=None):
    return {username: {"permissions": permissions, "password": password}}


CONFIG_FILE = "users.json"
DEFAULT_CONFIG = {
    "secret": None, 
    "users": {
    }
}

# Guest has minimum permission bits set.
DEFAULT_CONFIG['users'].update(user("guest", PMASK_MIN))
# Admin has all permission bits set.
DEFAULT_CONFIG['users'].update(user("admin", PMASK_MAX))

class Users(ConfigFile):

    def __init__(self, etcdir):
        self.auth_cache = {}
        config_filename = os.path.join(etcdir, CONFIG_FILE)
        super().__init__(config_filename, DEFAULT_CONFIG)

        save = False
        # Create random cookie secret. 
        if self.config['secret'] is None:
            self.config['secret'] = os.urandom(24).hex().upper()
            save = True

        # Create default passwords (password=username) if they're not set.
        for user, info in self.config['users'].items():
            if info['password'] is None:
                info['password'] = Users.hash_password(user)
                save = True

        if save:
            self.save()

    def authorize(self, username, password):
        res = 0
        up = username+password

        # Make sure the password file hasn't changed.
        if self.reload():
            # If it has changed, flush the cache.
            self.auth_cache = {}
            
        # Check auth_cache first and return if it's in there.
        try:
            res = self.auth_cache[up] 
        except:
            # Lazy way to bound cache size     
            if len(self.auth_cache)>10: 
                # BTW we're likely being attacked... 
                self.auth_cache = {}

            # Verify password
            try:
                info = self.config['users'][username]
                if Users.verify_password(password, info['password']):
                    res = info['permissions']
            except:
                pass

            # Cache result regardless
            self.auth_cache[up] = res

        return res

    def add_change_user(self, username, permissions, password):
        if password is None:
            try:
                password = self.config['users'][username]["password"]
            except:
                password = Users.hash_password(username)
        else:
            password = Users.hash_password(password)

        self.config['users'].update(user(username, permissions, password))
        self.save()

    def remove_user(self, username):
        try:
            del self.config['users'][username]
            self.save()
        except:
            pass

    @staticmethod
    def hash_password(password, salt=None):
        if salt is None:
            # Generate random salt to mix with password if it isn't supplied.
            salt = binascii.hexlify(os.urandom(8)).decode().upper()
        password += salt
        # Generating a secure and timely hash on a Raspberry Pi is difficult 
        # (dklen=10000), but this should be fine.
        hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 10000).hex().upper()
        return f"{hashed}:{salt}"

    @staticmethod
    def verify_password(password, hash_string):
        salt = hash_string.split(":")[1]
        return Users.hash_password(password, salt)==hash_string
