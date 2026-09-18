from base_handler import BaseHandler
import mpd

MPD = 'mpd'


class MPDHandler(BaseHandler):
    def __init__(self, config, mpd_lock):
        super().__init__({
            MPD: mpd_lock,
        })

        self._mpd_ip = config['mpd_ip']
        self._mpd_port = config['mpd_port']

        self.connect()

    def update(self):
        self.ping()

    def connect(self):
        try:
            self._client = mpd.MPDClient()
            self._client.timeout = 0.1
            self._client.connect(
                self._mpd_ip,
                self._mpd_port
            )
        except Exception:
            pass

    def client(self):
        return self._client

    def guard(self, command, *args):
        with self._acquire_timeout(MPD):
            try:
                return command(*args)
            except Exception:
                return None

    def toggle_mute(self):
        with self._acquire_timeout(MPD):
            try:
                status = self._client.status()
                current_volume = int(status.get('volume', 0))
                if current_volume > 0:
                    with open('mpd_volume.state', 'w') as statefile:
                        statefile.write(str(current_volume))
                    self._client.setvol(0)
                else:
                    try:
                        with open('mpd_volume.state', 'r') as statefile:
                            last_volume = int(statefile.read())
                            self._client.setvol(last_volume)
                    except (FileNotFoundError, ValueError):
                        self._client.setvol(50)
            except Exception:
                pass

    def ping(self):
        with self._acquire_timeout(MPD):
            try:
                self._client.ping()
            except Exception:
                self.connect()

    def toggle(self):
        def cmd():
            with self._acquire_timeout(MPD):
                try:
                    if self._client.status()['state'] == 'pause':
                        self._client.play()
                    else:
                        self._client.pause()
                except Exception:
                    pass

        def img():
            with self._acquire_timeout(MPD):
                try:
                    if self._client.status()['state'] == 'pause':
                        return 'images/media_play.png'
                    else:
                        return 'images/media_pause.png'
                except Exception:
                    return 'images/error.png'

        return (
            lambda: cmd(),
            lambda: img(),
        )

    def previous(self):
        return (
            lambda: self.guard(self._client.previous),
            'images/media_previous.png',
        )

    def next(self):
        return (
            lambda: self.guard(self._client.next),
            'images/media_next.png',
        )
