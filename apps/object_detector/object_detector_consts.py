#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

# Number of images to keep in the media directory
IMAGES_KEEP = 100
# Number of images to display in the media queue
IMAGES_DISPLAY = 25
# How long to wait (seconds) before picking best detection image for media queue
PICKER_TIMEOUT = 10
# Width of media queue images
MEDIA_QUEUE_IMAGE_WIDTH = 300
# Folder within Google Photos to save media
GPHOTO_ALBUM = "Vizy Object Detector"

# Maximum distance between detections before assuming they are different
# detections (birds)
TRACKER_DISAPPEARED_DISTANCE = 300
# Numbers of frames that a detection has disappeared before assuming it's gone
TRACKER_MAX_DISAPPEARED = 1
