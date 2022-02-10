
class Motion:

    # Extract motion from split BGR input frame (frame_split) 
    # and split BGR background frame (bg_split) 
    def extract(self, frame_split, bg_split):
        pass

    # Threshold property, varies between 1 and 100
    @property
    def threshold(self):
        return self._threshold 

    @threshold.setter
    def threshold(self, _threshold):
        self._threshold = _threshold

