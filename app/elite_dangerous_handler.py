from ydotool_handler import YDoToolHandler
import json
import os


class EliteDangerousHandler(YDoToolHandler):
    # Flags bit positions
    FLAG_LANDING_GEAR = 1 << 2
    FLAG_HARDPOINTS = 1 << 6
    FLAG_LIGHTS = 1 << 8
    FLAG_CARGO_SCOOP = 1 << 9
    FLAG_ANALYSIS_MODE = 1 << 27
    FLAG_NIGHT_VISION = 1 << 28

    def __init__(self, cmd_lock, status_path):
        super().__init__(cmd_lock)
        self.status_path = status_path
        self.status_flags = 0

    def update(self):
        self.status_flags = self._get_status_flags()

    def _get_status_flags(self):
        if not self.status_path or not os.path.exists(self.status_path):
            return 0
        try:
            with open(self.status_path, 'r') as f:
                data = json.load(f)
                return data.get('Flags', 0)
        except (json.JSONDecodeError, IOError):
            return 0

    def _is_flag_set(self, flag):
        return (self.status_flags & flag) != 0

    def action(self, name, key_sequence, flag, timeout=50):
        def cmd():
            with self._acquire_timeout('cmd'):
                os.system('ydotool key -d {} {}'.format(timeout, key_sequence))

        return (
            lambda: cmd(),
            lambda: 'images/{}.active.png'.format(name) if self._is_flag_set(
                flag) else 'images/{}.png'.format(name)
        )

    def cockpit_mode(self):
        return self.action('cockpit_mode', '29:1 2:1 wait 29:0 2:0', self.FLAG_ANALYSIS_MODE)

    def cargo_scoop(self):
        return self.action('cargo_scoop', '29:1 3:1 wait 29:0 3:0', self.FLAG_CARGO_SCOOP)

    def hardpoints(self):
        return self.action('hardpoints', '29:1 4:1 wait 29:0 4:0', self.FLAG_HARDPOINTS)

    def landing_gear(self):
        return self.action('landing_gear', '29:1 5:1 wait 29:0 5:0', self.FLAG_LANDING_GEAR)

    def night_vision(self):
        return self.action('night_vision', '29:1 6:1 wait 29:0 6:0', self.FLAG_NIGHT_VISION)

    def lights(self):
        return self.action('lights', '29:1 7:1 wait 29:0 7:0', self.FLAG_LIGHTS)
