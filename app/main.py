from threading import Thread
from threading import Lock
from threading import Event
import os
import sys
import signal
import time

# The app lives in app/ and imports the upstream SDK from ../Python-SDK/src.
# Compute the SDK path relative to this file so the app works regardless of
# the current working directory it is launched from.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SDK_SRC_DIR = os.path.normpath(os.path.join(APP_DIR, '..', 'Python-SDK', 'src'))
if SDK_SRC_DIR not in sys.path:
    sys.path.insert(0, SDK_SRC_DIR)

# Resolve config.json and the relative 'images/...' paths against the app
# directory instead of the launch directory.
os.chdir(APP_DIR)

from configuration import Configuration
from layers import Layers
from StreamDock.DeviceManager import DeviceManager
from StreamDock.InputTypes import EventType, ButtonKey, KnobId, Direction
import sdk_patch
sdk_patch.patch_streamdock293()
from ydotool_handler import YDoToolHandler
from pulseaudio_handler import PulseAudioHandler
from homeassistant_handler import HomeAssistantHandler
from mpd_handler import MPDHandler
from playerctl_handler import PlayerCtlHandler
from loginctl_handler import LoginCtlHandler
from elite_dangerous_handler import EliteDangerousHandler

config = Configuration()

cmd_lock = Lock()
hass_lock = Lock()
mpd_lock = Lock()
device_lock = Lock()

refresh_event = Event()

_last_images = {}
_last_sublayer = None

# Sentinel for "we have no record of what this key is currently showing".
# It must NOT be None: a key with no icon has a desired state of None, and
# dict.get() also returns None for a missing key, so a plain
# `_last_images.get(key) == image` test would treat "unknown" and "correctly
# blank" as the same thing and skip the clearIcon(). See the comment in
# refresh() for the stale-icon symptom that caused.
_UNKNOWN = object()

# Number of consecutive refresh ticks in which at least one key failed to
# draw. The transport is a vendor C library: once a USB reset / re-enumeration
# kills the handle it keeps failing (e.g. "hid_write FAILED, res=-1 error:
# Protocol error") and the app would otherwise keep hammering a dead device
# forever. The main loop watches this streak and re-initialises the device once
# it crosses WRITE_FAILURE_LIMIT, so a wedged transport heals without an app
# restart.
_write_failures = 0
WRITE_FAILURE_LIMIT = 10

ydotool = YDoToolHandler(cmd_lock)
pulse = PulseAudioHandler(config)
hass = HomeAssistantHandler(config, hass_lock)
mpd = MPDHandler(config, mpd_lock)
playerctl = PlayerCtlHandler(cmd_lock)
loginctl = LoginCtlHandler(cmd_lock)
elite = EliteDangerousHandler(cmd_lock, config.elite_dangerous_status_path)

handlers = [ydotool, pulse, hass, mpd, playerctl, loginctl, elite]

layers = Layers(ydotool, pulse, hass, mpd, playerctl, loginctl, elite)


def refresh(device):
    global _last_images, _last_sublayer, _write_failures

    for handler in handlers:
        handler.update()

    keys = layers.current_sublayer_display_keys()
    entries = {}
    for key in range(1, 7):
        entry = keys.get(key)
        if entry and entry[1]:
            entries[key] = entry[1]() if callable(entry[1]) else entry[1]
        else:
            entries[key] = None

    with device_lock:
        sublayer = (layers.layer, layers.sub_layer)
        if sublayer != _last_sublayer:
            _last_images.clear()
            _last_sublayer = sublayer

        failed = 0
        for key in range(1, 7):
            image = entries.get(key)

            # A missing cache entry must not compare equal to a desired state of
            # None, otherwise a key with no icon on the current page looks
            # "already correct" and is never cleared. That is exactly what
            # happened after a wheel-driven page change: set_layer_relative()
            # mutates sub_layer before calling set_layer(), so set_layer()'s
            # "did the page really change" guard is already false and
            # clearAllIcon() never runs; the cache is then wiped just above, and
            # the None == None test made every icon-less key skip its
            # clearIcon(), leaving the previous page's icon on screen.
            if _last_images.get(key, _UNKNOWN) == image:
                continue

            if image is None:
                # clearIcon() reports no status at all in the current SDK, so
                # there is nothing to verify here; cache it so the clear is
                # not re-issued on every tick.
                device.clearIcon(key)
                _last_images[key] = None
                continue

            # Only cache a key as drawn when the call actually succeeded.
            #
            # The SDK declares transport_set_key_image_stream with
            # restype=c_uint32, so a C-level failure of -1 surfaces in Python
            # as 4294967295 -- a POSITIVE number that sails through a
            # `result >= 0` test. Caching one of those makes refresh() skip
            # the key forever: the panel freezes on a stale image and the
            # device only comes back after an app restart. The SDK's own
            # success value is 0 (TRANSPORT_SUCCESS) and a dead handle
            # returns None, so only `== 0` counts as drawn.
            if device.set_key_image(key, image) == 0:
                _last_images[key] = image
            else:
                failed += 1

        device.refresh()

    # A tick that drew everything resets the streak; any failure extends it.
    _write_failures = 0 if failed == 0 else _write_failures + 1


# The new SDK decodes raw HID packets into unified InputEvent objects instead of
# exposing the raw 5-tuple read() loop. Every handler below translates those
# events back into the exact key codes the keys.py/layers.py mappings expect, so
# the user's layer/action configuration stays unchanged.
#
#   BUTTON KEY_1..KEY_6  -> 1..6      (display keys)
#   BUTTON KEY_7/8/9     -> 37/48/49  (0x25/0x30/0x31 bottom buttons)
#   KNOB_3 rotate        -> 80/81     (0x50/0x51)
#   KNOB_2 rotate        -> 96/97     (0x60/0x61)
#   KNOB_1 rotate        -> 144/145   (0x90/0x91)
#   KNOB_1/2/3 press     -> 51/52/53  (0x33/0x34/0x35)
_BUTTON_CODES = {
    ButtonKey.KEY_7: 37,
    ButtonKey.KEY_8: 48,
    ButtonKey.KEY_9: 49,
}

_KNOB_ROTATE_CODES = {
    (KnobId.KNOB_1, Direction.LEFT): 144,
    (KnobId.KNOB_1, Direction.RIGHT): 145,
    (KnobId.KNOB_2, Direction.LEFT): 96,
    (KnobId.KNOB_2, Direction.RIGHT): 97,
    (KnobId.KNOB_3, Direction.LEFT): 80,
    (KnobId.KNOB_3, Direction.RIGHT): 81,
}

_KNOB_PRESS_CODES = {
    KnobId.KNOB_1: 51,
    KnobId.KNOB_2: 52,
    KnobId.KNOB_3: 53,
}


def _event_to_legacy_key(event):
    """Translate a new-API InputEvent into the legacy key code used by keys.py."""
    if event.event_type == EventType.BUTTON:
        # The old app triggered on raw status byte 0 (result_bytes[10] == 0),
        # which the new N3 decoder normalizes to state == 0. Acting on
        # state == 0 reproduces the old one-action-per-press behaviour on every
        # plausible N3 byte model (single packet per action, 0x00-press, or
        # case where the old whileread convention 0x01-press/0x00-release
        # applied).
        if event.state != 0:
            return None
        # KEY_1..KEY_6 already equal the legacy codes 1..6
        return _BUTTON_CODES.get(event.key, event.key.value)
    if event.event_type == EventType.KNOB_ROTATE:
        return _KNOB_ROTATE_CODES.get((event.knob_id, event.direction))
    if event.event_type == EventType.KNOB_PRESS:
        if event.state != 0:  # see BUTTON comment above
            return None
        return _KNOB_PRESS_CODES.get(event.knob_id)
    return None


def read_callback(device, event):
    """New-API input callback: callback(device, event: InputEvent).

    Runs on the SDK's internal reader thread (started by device.open()).
    """
    key = _event_to_legacy_key(event)
    if key is None:
        return

    with device_lock:
        layers.handle_keys(key)


def refresh_callback(device):
    while not refresh_event.wait(0.3):
        refresh(device)


def start_thread(callback, args=()):
    thread = Thread(target=callback, args=args)
    thread.daemon = True
    thread.start()
    return thread


def signal_handler(signum, frame):
    signame = signal.Signals(signum).name
    print(f'Signal handler called with signal {signame} ({signum})')

    for device in device_manager.enumerate():
        device.clearAllIcon()
        device.close()

    sys.exit()


def init_signal_handler(device_manger):
    signal.signal(signal.SIGABRT, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGQUIT, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)


if __name__ == "__main__":
    device_manager = DeviceManager()
    listen_thread = start_thread(
        # auto_open=False: the app opens/initializes devices itself below
        lambda: device_manager.listen(auto_open=False, auto_init=False)
    )
    init_signal_handler(device_manager)

    while True:
        try:
            refresh_event.clear()

            devices = device_manager.enumerate()

            if len(devices) < 1:
                print('Waiting for devices...')
                time.sleep(1)
                continue

            for device in devices:
                device.open()
                device.init()
                device.set_brightness(10)
                device.clearAllIcon()

                layers.set_device(device)
                device.set_key_callback(read_callback)

                refresh_thread = start_thread(refresh_callback, (device, ))

                while True:
                    refresh_thread.join(1)

                    # Either the refresh thread died, or the transport has been
                    # failing on every tick for a while (see _write_failures).
                    # Both mean this device object is no longer usable, so drop
                    # it and let the outer loop re-enumerate and re-open a fresh
                    # one -- the same path a dead refresh thread already took.
                    # This is what makes the dock recover on its own instead of
                    # staying mute until someone restarts the app.
                    if not refresh_thread.is_alive() or _write_failures >= WRITE_FAILURE_LIMIT:
                        refresh_event.set()

                        # The new close() shuts down the internal reader,
                        # heartbeat and transport gracefully (no separate
                        # stop() call exists anymore)
                        device.close()

                        refresh_thread.join(2)

                        _write_failures = 0

                        break

        except KeyboardInterrupt:
            signal_handler(signal.SIGINT)