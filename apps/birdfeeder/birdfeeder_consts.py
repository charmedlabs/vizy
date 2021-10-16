# This file is for tweaking various values within the Birdfeeder application.
# Tweaking isn't typically necessary for most set-ups, but it's here 
# if needed! 

# The list of thresholds below corresponds to the species in the TensorFlow model.  
# The first number is the relative sensitivity for the specific species.  1.0 is 
# normal sensitivity.  Higher values are higher sensitivity, higher likelihood 
# of detection, lower values are lower likelihood of detection. 
# The 2nd value is where within the image you want to detect:
# [min_width, max_width, min_height, max_height]
# The origin is in the upper leftmost corner.  
# For example, if you only wanted to detect the species in the right half of
# the image, you'd use [0.5, 1.0, 0, 1.0], left half would be [0, 0.5, 0, 1.0].  
# If you only wanted to detect the species in the bottom half of he image you'd use 
# [0, 1.0, 0.5, 1.0], top half would be [0, 1.0, 0, 0.5], etc.
THRESHOLDS = [
    [1.0, [0, 1.0, 0, 1.0]], # 1 Common Pigeon  
    [1.0, [0, 1.0, 0, 1.0]], # 2 Baltimore Oriole
    [1.0, [0, 1.0, 0, 1.0]], # 3 Eastern Bluebird  
    [1.0, [0, 1.0, 0, 1.0]], # 4 Red-Bellied Woodpecker  
    [1.0, [0, 1.0, 0, 1.0]], # 5 White-breasted Nuthatch  
    [1.0, [0, 1.0, 0, 1.0]], # 6 Northern Mockingbird  
    [1.0, [0, 1.0, 0, 1.0]], # 7 Downy Woodpecker  
    [1.0, [0, 1.0, 0, 1.0]], # 8 Tufted Titmouse  
    [1.0, [0, 1.0, 0, 1.0]], # 9 Black-capped Chickadee  
    [1.0, [0, 1.0, 0, 1.0]], # 10 Song Sparrow  
    [1.0, [0, 1.0, 0, 1.0]], # 11 Northern Cardinal  
    [1.0, [0, 1.0, 0, 1.0]], # 12 Ruby-throated Hummingbird  
    [1.0, [0, 1.0, 0, 1.0]], # 13 American Robin  
    [1.0, [0, 1.0, 0, 1.0]], # 14 Blue Jay  
    [1.0, [0, 1.0, 0, 1.0]], # 15 Mourning Dove  
    [1.0, [0, 1.0, 0, 1.0]], # 16 American Goldfinch  
    [1.0, [0, 1.0, 0, 1.0]], # 17 Red-winged Blackbird  
    [1.0, [0, 1.0, 0, 1.0]], # 18 Common Grackle  
    [1.0, [0, 1.0, 0, 1.0]], # 19 American Crow  
    [1.0, [0, 1.0, 0, 1.0]], # 20 Cedar Waxwing  
    [1.0, [0, 1.0, 0, 1.0]], # 21 Virginia Opossum  
    [1.0, [0, 1.0, 0, 1.0]], # 22 Eastern Cottontail  
    [1.0, [0, 1.0, 0, 1.0]], # 23 Eastern Gray Squirrel  
    [1.0, [0, 1.0, 0, 1.0]], # 24 Western Gray Squirrel  
    [1.0, [0, 1.0, 0, 1.0]], # 25 Fox Squirrel  
    [1.0, [0, 1.0, 0, 1.0]], # 26 White Tailed Deer  
    [1.0, [0, 1.0, 0, 1.0]], # 27 Raccoon  
    [1.0, [0, 1.0, 0, 1.0]], # 28 Black Rat 
    [1.0, [0, 1.0, 0, 1.0]], # 29 Brown Rat  
    [1.0, [0, 1.0, 0, 1.0]]  # 30 Cat  
]

# List of pest species to defend against, by index.  Add or remove based on 
# which species you don't want at your birdfeeder.
PESTS = [21, 22, 23, 24, 25, 26, 27, 28, 29, 30]

# The name of the album in Google Photos that the pictures/videos are uploaded to.
ALBUM = "Birdfeeder"

# The I/O bit that's used to trigger the defense (e.g. sprinkler valve).  It can 
# range from 0 to 3.  See https://docs.vizycam.com/doku.php?id=wiki:pinouts  
DEFEND_BIT = 0 
