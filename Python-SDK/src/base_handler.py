from lockable import Lockable


class BaseHandler(Lockable):
    def __init__(self, locks):
        super().__init__(locks)

    def update(self):
        pass
