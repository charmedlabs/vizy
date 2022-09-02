#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

from kritter.ktextvisor import Image

def handle_event(obj, event):
    if event['event_type']=='trigger':
        if obj.tv:
            # Send message with timestamp and detected object class
            obj.tv.send(f"{event['timestamp']} {event['class']}")
            # Send image with detected object
            obj.tv.send(Image(event['image']))
