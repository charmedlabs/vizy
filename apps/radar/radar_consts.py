#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

# Name of Google Photos album to store photos
ALBUM = "radar"
# Mimimum value before differences in pixel values are considered motion
NOISE_FLOOR = 30*3
# Maximum amount of time a vehicle can take to traverse the width of the image
DATA_TIMEOUT = 10 # seconds
# Number of seconds the speed is displayed on the video window after a vehicle's speed is measured
SPEED_DISPLAY_TIMEOUT = 3 # seconds
# Font size to overlay the speed on top of the video/image
FONT_SIZE = 60 
# Color to overlay speed
FONT_COLOR = (0, 255, 0)
# Color to overlay speed if speed limit is exceeded
FONT_COLOR_EXCEED = (0, 0, 255)
# Minimum number of data points for a valid vehicle detection
MINIMUM_DATA = 3
# Camera shutter speed (seconds)
SHUTTER_SPEED = 0.001
# Camera shutter speed in low light conditions (seconds)
LOW_LIGHT_SHUTTER_SPEED = 1/30
# Maximum least-squares fitting error per data point for a valid vehicle detection
MAX_RESIDUAL = 100
