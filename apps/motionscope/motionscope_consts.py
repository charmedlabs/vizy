#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

# External trigger button I/O channel (can be 0, 1, 2, or 3)
EXT_BUTTON_CHANNEL = 0
# Maximum number of seconds to record before stopping
MAX_RECORDING_DURATION = 10 
# Maximum width of video window in browser pixels
WIDTH = 736
# Padding between video in browser pixels, controls and sides of browser
PADDING = 10
# Number of graphs to show
GRAPHS = 6
# Start shift recording range in seconds
START_SHIFT = 2
# Minimum total range of object in camera pixels for it to be a valid object
MIN_RANGE = 30
# Default Camera Tab settings
DEFAULT_CAMERA_SETTINGS = {"mode": "768x432x10bpp", "brightness": 50, "framerate": 50, "autoshutter": True, "shutter": 0.0085, "awb": True, "red_gain": 1, "blue_gain": 1}
# Default Capture Tab settings
DEFAULT_CAPTURE_SETTINGS = {"start_shift": 0, "duration": MAX_RECORDING_DURATION, "trigger_mode": "button press", "trigger_sensitivity": 75}
# Default Process settings 
DEFAULT_PROCESS_SETTINGS = {"motion_threshold": 25}

# Don't change the values below unless you know what you're doing or don't mind potentially
# breaking something!

# Focal length of lens measured in physical camera sensor pixels (unscaled).  The focal length
# is needed to make the perspective change (pitch, yaw) accurate.
# The focal length of 2260 assumes the default Vizy wide-angle lens and Sony IMX477 sensor.
FOCAL_LENGTH = 2260
# When playing back recordings, number of frames/second
PLAY_RATE = 30
# When updating time and spacing in Analyze tab, how many updates per second 
UPDATE_RATE = 10
# Background frame attenuation factor 
BG_AVG_RATIO = 0.1
# Number of frames to feed into filter for background frame 
BG_CNT_FINAL = 10 
# Default Analyze settings
DEFAULT_ANALYZE_SETTINGS = {"show_options": "objects, points, lines"}

