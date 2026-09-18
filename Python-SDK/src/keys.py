class Keys:
    def __init__(self, ydotool, pulse, hass, mpd, playerctl, loginctl, elite, layers):
        self.ydotool = ydotool
        self.pulse = pulse
        self.hass = hass
        self.mpd = mpd
        self.playerctl = playerctl
        self.loginctl = loginctl
        self.elite = elite
        self.layers = layers

    def get_mappings(self):
        return {
            'default': {
                37: lambda: self.layers.set_layer(0),
                48: lambda: self.layers.set_layer(1),
                49: lambda: self.layers.set_layer(2),
                # pc audio
                53: lambda: self.pulse.toggle_default_source_mute(),
                80: lambda: self.pulse.change_default_source_volume(-5),
                81: lambda: self.pulse.change_default_source_volume(5),
                144: lambda: self.pulse.change_default_source_volume(-1),
                145: lambda: self.pulse.change_default_source_volume(1),
                # mpd audio
                96: lambda: self.mpd.guard(self.mpd.client().volume, -5),
                97: lambda: self.mpd.guard(self.mpd.client().volume, 5),
                52: lambda: self.mpd.toggle_mute(),
            },
            'layers': {
                0: [
                    {
                        1: self.hass.scene('meetingmodus_ohne_kamera'),
                        2: self.hass.scene('meetingmodus'),
                        3: self.hass.scene('vogelmodus'),
                        4: self.pulse.toggle_default_sink_mute(),
                        5: self.pulse.switch_default_source(),
                        6: self.ydotool.action('freeze', '56:1 42:1 33:1 wait 56:0 42:0 33:0'),
                    },
                    {
                        1: self.ydotool.action('thumbs_down', '56:1 3:1 wait 56:0 3:0'),
                        2: self.ydotool.action('vomit', '56:1 5:1 wait 56:0 5:0'),
                        3: self.ydotool.action('exploding_head', '56:1 4:1 wait 56:0 4:0'),
                        4: self.pulse.toggle_default_sink_mute(),
                        5: self.ydotool.action('thumbs_up', '56:1 2:1 wait 56:0 2:0'),
                        6: self.ydotool.action('freeze', '56:1 42:1 33:1 wait 56:0 42:0 33:0'),
                    }
                ],
                1: [
                    {
                        1: self.mpd.previous(),
                        2: self.mpd.toggle(),
                        3: self.mpd.next(),
                        5: self.playerctl.toggle(),
                        6: self.loginctl.toggle_lock(),
                    }
                ],
                2: [
                    {
                        1: self.hass.scene('vogelmodus'),
                        2: self.hass.scene('nachtmodus'),
                        3: (
                            lambda: self.layers.set_layer(3),
                            '../images/games.png'
                        ),
                        4: self.hass.trigger_service(
                            '../images/lightbulb_circle_green.png',
                            'light',
                            'turn_on',
                            entity_id='light.neopixel_light',
                            rgb_color=(0, 255, 63),
                            brightness=125,
                        ),
                        5: self.hass.trigger_service(
                            '../images/table_lamp.png',
                            'switch',
                            'toggle',
                            entity_id='switch.outlet003',
                        ),
                        6: self.hass.scene('pause'),
                    }
                ],
                3: [
                    {
                        1: self.hass.scene('vogelmodus'),
                        2: self.hass.scene('nachtmodus'),
                        4: self.hass.trigger_service(
                            '../images/table_lamp.png',
                            'switch',
                            'toggle',
                            entity_id='switch.outlet003',
                        ),
                        5: self.playerctl.toggle(),
                        6: self.pulse.switch_default_source(),
                        144: lambda: self.layers.set_layer_relative(sub_layer_delta=-1),
                        145: lambda: self.layers.set_layer_relative(sub_layer_delta=1),
                    },
                    {
                        1: self.ydotool.action('short_scan', '42:1 3:1 wait 42:0 3:0', toggle=False),
                        2: self.ydotool.action('long_scan', '42:1 4:1 wait 42:0 4:0', toggle=False),
                        3: self.ydotool.action('seta', '42:1 5:1 wait 42:0 5:0', toggle=False),
                        4: self.ydotool.action('comms', '46:1 wait 46:0', toggle=False),
                        144: lambda: self.layers.set_layer_relative(sub_layer_delta=-1),
                        145: lambda: self.layers.set_layer_relative(sub_layer_delta=1),
                    },
                    {
                        1: self.elite.cockpit_mode(),
                        2: self.elite.cargo_scoop(),
                        3: self.elite.hardpoints(),
                        4: self.elite.landing_gear(),
                        5: self.elite.night_vision(),
                        6: self.elite.lights(),
                        144: lambda: self.layers.set_layer_relative(sub_layer_delta=-1),
                        145: lambda: self.layers.set_layer_relative(sub_layer_delta=1),
                    }
                ],
            }
        }
