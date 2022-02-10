from dataupdate import DataUpdate

class Tab(DataUpdate):
    def __init__(self, name, kapp, data):
        super().__init__(data)
        self.name = name
        self.kapp = kapp

    def frame(self):
        return None

    def focus(self, state):
        return []