from keys import Keys
import sys


class Layers:
    def __init__(self, ydotool, pulse, hass, mpd, playerctl, loginctl, elite):
        self.ydotool = ydotool
        self.pulse = pulse
        self.hass = hass
        self.mpd = mpd
        self.playerctl = playerctl
        self.loginctl = loginctl
        self.elite = elite

        self.layer = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        self.sub_layer = int(sys.argv[2]) if len(sys.argv) > 2 else 0

        self.keys_manager = Keys(
            self.ydotool,
            self.pulse,
            self.hass,
            self.mpd,
            self.playerctl,
            self.loginctl,
            self.elite,
            self
        )
        self.keys = self.keys_manager.get_mappings()
        self.device = None

    def set_device(self, device):
        self.device = device

    def set_layer(self, new_layer, new_sub_layer=None):
        if new_sub_layer is not None:
            new_sub = new_sub_layer
        elif self.layer == new_layer:
            new_sub = (
                self.sub_layer + 1) % len(self.keys['layers'][self.layer])
        else:
            new_sub = 0

        # Only clear + switch when the page really changes. Clearing icons on
        # an unchanged page (e.g. rotating on a single-page layer) blanks the
        # device while refresh() still thinks the display is current, so the
        # keys never get redrawn.
        if new_layer != self.layer or new_sub != self.sub_layer:
            if self.device is not None:
                self.device.clearAllIcon()
            self.layer = new_layer
            self.sub_layer = new_sub

    def set_layer_relative(self, layer_delta=None, sub_layer_delta=None):
        if layer_delta is not None:
            num_layers = len(self.keys['layers'])
            self.layer = (self.layer + layer_delta) % num_layers
            self.sub_layer = 0  # Reset sub-layer when switching layers

        if sub_layer_delta is not None:
            num_sub_layers = len(self.keys['layers'][self.layer])
            self.sub_layer = (
                self.sub_layer + sub_layer_delta) % num_sub_layers

        self.set_layer(self.layer, new_sub_layer=self.sub_layer)

    def current_sublayer_keys(self):
        return self.keys['layers'][self.layer][self.sub_layer]

    def current_sublayer_display_keys(self):
        # Filter for keys with displays (1-6) that have an image part
        return {k: v for k, v in self.current_sublayer_keys().items() if 1 <= k <= 6 and isinstance(v, tuple)}

    def handle_keys(self, key):
        sublayer_keys = self.current_sublayer_keys()

        if key in sublayer_keys:
            action = sublayer_keys[key]
            if isinstance(action, tuple):
                action[0]()
            else:
                action()
        elif key in self.keys['default']:
            self.keys['default'][key]()
