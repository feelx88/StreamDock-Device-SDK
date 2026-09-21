from base_handler import BaseHandler
import threading
import pulsectl


class PulseAudioHandler(BaseHandler):

    def __init__(self, config):
        super().__init__({})
        audio = config['audio']
        self.headset_source = audio['headset_source']
        self.speakers_source = audio['speakers_source']
        self.headset_sink = audio['headset_sink']
        self.speakers_sink = audio['speakers_sink']
        self._pulse = None
        self._pulse_lock = threading.Lock()

    def _ensure(self):
        """Connect lazily, returning the live client or None (lock held)."""
        if self._pulse is None:
            try:
                self._pulse = pulsectl.Pulse('streamdock', threading_lock=True)
            except pulsectl.PulseError:
                self._pulse = None
        return self._pulse

    def _close(self):
        """Drop the current connection so the next call reconnects (lock held)."""
        if self._pulse is not None:
            try:
                self._pulse.close()
            except Exception:
                pass
            self._pulse = None

    def _call(self, operation):
        """Run operation(client) on a live connection, serialized.

        Returns None when the audio server is unreachable, a device is absent,
        or the connection drops mid-call; a dropped connection is closed so the
        next call reconnects.
        """
        with self._pulse_lock:
            pulse = self._ensure()
            if pulse is None:
                return None
            try:
                return operation(pulse)
            except pulsectl.PulseIndexError:
                return None
            except pulsectl.PulseError:
                self._close()
                return None

    def _current_source(self):
        return self._call(lambda pulse: pulse.server_info().default_source_name)

    def _source_muted(self):
        def operation(pulse):
            source = pulse.get_source_by_name(pulse.server_info().default_source_name)
            return bool(source.mute)
        return self._call(operation)

    def _switch_profile(self, speakers=False):
        source_name = self.speakers_source if speakers else self.headset_source
        sink_name = self.speakers_sink if speakers else self.headset_sink

        def operation(pulse):
            pulse.source_default_set(source_name)
            source = pulse.get_source_by_name(source_name)
            for output in pulse.source_output_list():
                pulse.source_output_move(output.index, source.index)

            pulse.sink_default_set(sink_name)
            sink = pulse.get_sink_by_name(sink_name)
            for stream in pulse.sink_input_list():
                pulse.sink_input_move(stream.index, sink.index)

        self._call(operation)

    def switch_default_source(self):
        def is_headset():
            return self._current_source() == self.headset_source

        return (
            lambda: self._switch_profile(speakers=is_headset()),
            lambda: 'images/headset.png' if is_headset() else 'images/speaker.png'
        )

    def toggle_default_sink_mute(self):
        def operation(pulse):
            source = pulse.get_source_by_name(pulse.server_info().default_source_name)
            pulse.source_mute(source.index, not source.mute)

        return (
            lambda: self._call(operation),
            lambda: 'images/mic_off.png' if self._source_muted() else 'images/mic.png'
        )

    def toggle_default_source_mute(self):
        def operation(pulse):
            sink = pulse.get_sink_by_name(pulse.server_info().default_sink_name)
            pulse.sink_mute(sink.index, not sink.mute)

        self._call(operation)

    def change_default_source_volume(self, amount):
        def operation(pulse):
            sink = pulse.get_sink_by_name(pulse.server_info().default_sink_name)
            pulse.volume_change_all_chans(sink, amount / 100.0)

        self._call(operation)
