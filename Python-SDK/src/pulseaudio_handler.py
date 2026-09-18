from base_handler import BaseHandler
import os

CMD = 'cmd'


class PulseAudioHandler(BaseHandler):

    def __init__(self, cmd_lock):
        super().__init__({
            CMD: cmd_lock,
        })

    def _current_source(self):
        with self._acquire_timeout(CMD):
            return os.popen('pactl get-default-source').read().strip()

    def switch_default_source(self):
        def is_headset():
            return self._current_source() == 'alsa_input.usb-Astro_Gaming_Astro_A50-00.mono-chat'

        def headset():
            with self._acquire_timeout(CMD):
                os.system('sh ~/.change_audio.sh headset')

        def speakers():
            with self._acquire_timeout(CMD):
                os.system('sh ~/.change_audio.sh speakers')

        return (
            lambda: speakers() if is_headset() else headset(),
            lambda: '../images/headset.png' if is_headset() else '../images/speaker.png'
        )

    def toggle_default_sink_mute(self):
        def is_current_source_mute():
            source = self._current_source()
            with self._acquire_timeout(CMD):
                return os.popen(
                    'LC_ALL=C pactl get-source-mute {}'.format(source)
                ).read().strip() == 'Mute: yes', source

        def mute():
            muted, source = is_current_source_mute()
            with self._acquire_timeout(CMD):
                return os.system('pactl set-source-mute {} {}'.format(source, '0' if muted else '1'))

        return (
            lambda: mute(),
            lambda: '../images/mic_off.png' if is_current_source_mute()[
                0] else '../images/mic.png'
        )

    def toggle_default_source_mute(self):
        with self._acquire_timeout('cmd'):
            os.system('pactl set-sink-mute @DEFAULT_SINK@ toggle')

    def change_default_source_volume(self, amount):
        with self._acquire_timeout('cmd'):
            os.system('pactl set-sink-volume @DEFAULT_SINK@ {}{}%'.format(
                '+' if amount > 0 else '-', abs(amount)))
