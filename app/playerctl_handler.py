from base_handler import BaseHandler
import os

CMD = 'cmd'


class PlayerCtlHandler(BaseHandler):
    def __init__(self, cmd_lock):
        super().__init__({
            CMD: cmd_lock
        })

    def toggle(self):
        def img():
            with self._acquire_timeout(CMD):
                status = os.popen(
                    'playerctl status 2> /dev/null').read().strip()
                if status == 'Playing':
                    return 'images/media_pause.png'
                elif status == 'Paused':
                    return 'images/media_play.png'
                else:
                    return 'images/music_off.png'

        def toggle():
            with self._acquire_timeout(CMD):
                os.system('playerctl play-pause -s'),

        return (
            lambda: toggle(),
            lambda: img(),
        )
