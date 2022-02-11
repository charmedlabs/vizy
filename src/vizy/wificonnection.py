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
import NetworkManager
import uuid
import time
from dbus.mainloop.glib import DBusGMainLoop

DBusGMainLoop(set_as_default=True)

WIFI_SSID = 1
WIFI_AP = 2

def get_wifi_device():
    devs = list([
        dev for dev in NetworkManager.NetworkManager.GetDevices()
        if dev.DeviceType == NetworkManager.NM_DEVICE_TYPE_WIFI
    ])
    assert(len(devs) == 1)
    device = devs[0]
    return device

def get_strength(ssid, device=None):
    if device is None:
        device = get_wifi_device()
    aps = [ap for ap in device.AccessPoints if ap.Ssid == ssid]
    strength = [ap.Strength for ap in aps]
    return max(strength)


def get_active_connection(ssid):
    active = NetworkManager.NetworkManager.ActiveConnections
    active = [x for x in active if x.Connection.GetSettings()['connection']['id'] == ssid]
    assert(len(active) <= 1)
    if len(active)==1 and active[0].State==NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATED:
        return active[0]
    else:
        return None


class WifiConnection(object):

    def __init__(self, ssid, password, mode=WIFI_SSID):
        self.mode = mode
        self.ssid = ssid
        self.password = password

    def remove_old_connections(self):
        try:
            active = get_active_connection(self.ssid)
            if active:
                NetworkManager.NetworkManager.DeactivateConnection(active)
                self.waitForDisconnection(active)
        except:
            pass
            
        for connection in NetworkManager.Settings.ListConnections():
            settings = connection.GetSettings()
            if settings['connection']['id'] == self.ssid:
                connection.Delete()
    
    def get_connection(self):
        if self.mode == WIFI_AP:
            return {
                 'connection': {'id': self.ssid,
                                'type': '802-11-wireless',
                                'uuid': str(uuid.uuid4())},
                 'ipv4': {'method': 'shared'},
                 'ipv6': {'method': 'ignore'},
                 '802-11-wireless-security': {'key-mgmt': 'wpa-psk', 'psk': self.password},
                 '802-11-wireless': {'mode': 'ap', 'ssid': self.ssid},
            }
        else:
            return {
                'connection': {'id': self.ssid,
                            'type': '802-11-wireless',
                            'uuid': str(uuid.uuid4())},
                'ipv4': {'method': 'auto'},
                'ipv6': {'method': 'auto'},
                '802-11-wireless-security': {
                    'auth-alg': 'open',
                    'key-mgmt': 'wpa-psk',
                    'psk': self.password
                },
                '802-11-wireless': {'mode': 'infrastructure', 'ssid': self.ssid},
            }
    
    def activate(self):
        
        self.remove_old_connections()
        connection = self.get_connection() 
        try:
            con = NetworkManager.Settings.AddConnection(connection)
            device = get_wifi_device()
            activeConnection = NetworkManager.NetworkManager.ActivateConnection(
                con, device, "/")
            self.waitForConnection(activeConnection)
        except:
            return None
        # Add MDNS multicast route -- only needs to be added for AP mode. 
        if self.mode==WIFI_AP:
            os.system("ip route add 224.0.0.0/4 dev wlan0")
        return activeConnection

    def deactivate(self, activeConnection):
        NetworkManager.NetworkManager.DeactivateConnection(activeConnection)
        self.waitForDisconnection(activeConnection)
        
    def waitForConnection(self, conn):
        while conn.State != NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATED:
            time.sleep(0.5)

    def waitForDisconnection(self, conn):
        try:
            while conn.State == NetworkManager.NM_ACTIVE_CONNECTION_STATE_ACTIVATED:
                time.sleep(0.5)
        except NetworkManager.ObjectVanished(_):
            pass
