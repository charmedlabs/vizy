from kritter import Kritter

class VizyView:

    def __init__(self, name, layout=None, kapp=None):
        self.name = name
        self.layout = layout
        self.kapp = Kritter.kapp if kapp is None else kapp

    def view(self, enable):
        pass



