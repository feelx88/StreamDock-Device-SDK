from base_handler import BaseHandler
import os

CMD = 'cmd'


class YDoToolHandler(BaseHandler):

    def __init__(self, cmd_lock):
        super().__init__({
            CMD: cmd_lock,
        })
        self._states = {}

    def action(self, name, key_sequence, timeout=50, toggle=True):
        if toggle and (name not in self._states):
            self._states[name] = False

        def cmd():
            with self._acquire_timeout(CMD):
                os.system(
                    'ydotool key -d {} {}'.format(timeout, key_sequence))
                if toggle:
                    self._states[name] = not self._states[name]

        return (
            lambda: cmd(),
            lambda: 'images/{}.active.png'.format(
                name) if toggle and self._states.get(name, False) else 'images/{}.png'.format(name)
        )
