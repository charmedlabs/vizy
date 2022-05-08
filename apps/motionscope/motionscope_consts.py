#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

# Width of video window in pixels
WIDTH = 736
# Padding between video in pixels, controls and sides of browser
PADDING = 10
# Number of graphs to show
GRAPHS = 6
# Maximum number of seconds to record before stopping
MAX_RECORDING_DURATION = 10 
# Start shift recording range in seconds
START_SHIFT = 2
# Minimum range of object in pixels for it to be a valid object
MIN_RANGE = 30
# When playing back recordings, number of frames/second
PLAY_RATE = 30
# When updating time and spacing in Analyze tab, how many updates 
# per second 
UPDATE_RATE = 15
# Background frame attenuation factor 
BG_AVG_RATIO = 0.1
# Number of frames to feed into filter for background frame 
BG_CNT_FINAL = 10 
# External button I/O channel (can be 0, 1, 2, or 3)
EXT_BUTTON_CHANNEL = 0

DEFAULT_CAMERA_SETTINGS = {"mode": "768x432x10bpp", "brightness": 50, "framerate": 50, "autoshutter": False, "shutter": 0.0085, "awb": True, "red_gain": 1, "blue_gain": 1}

DEFAULT_CAPTURE_SETTINGS = {"start_shift": 0, "duration": MAX_RECORDING_DURATION, "trigger_mode": "button press", "trigger_sensitivity": 50} 

DEFAULT_PROCESS_SETTINGS = {"motion_threshold": 25}

DEFAULT_ANALYZE_SETTINGS = {"show_options": "objects, points, lines"}