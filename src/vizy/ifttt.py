# imports
import requests
from json import dumps


class IFTTT_Wrapper:
    def __init__(self, key):
        self.key = key if key else ''
        self.url_base = 'https://maker.ifttt.com/trigger/'

    def ping_event(self, event_name, event_type, data):
        if self.key:
            url = self.build_url(event_name, event_type, data)
            try:
                r = requests.post(url, data)
            except Exception as e:
                print ('Failed: ', e)
        else:
            print('no key')

    def build_url(self, event_name, event_type, data):
        url = f"{self.url_base}{event_name}/"
        if event_type=='json':         # elif event_type=='parameter': 
            url += 'json/'
        url += f"with/key/{self.key}"
        return url
        # match event_type:
        #   case 'json': 
        #   case 'parameter': 
        #   case _: return # default