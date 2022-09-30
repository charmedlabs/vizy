#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

from kritter.ktextvisor import KtextVisor, KtextVisorTable, Image, Video

def handle_event(self, event):
    print(f"handle_event: {event}")

def handle_text(self, words, sender, context):
    print(f"handle_text from {sender}: {words}, context: {context}")