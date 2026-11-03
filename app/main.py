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
sdk_patch.patch_enumerate_serialization()
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

# Raised while a device is being torn down. The reader callback drops input
# instead of waiting on device_lock, so close() can take the lock and tear the
# transport down without a parked reader blocking its reader-join.
_teardown = Event()

# Reader-wedge watchdog state. A wedged device spins its SDK reader thread in
# the C read call instead of blocking in poll; see _check_reader_wedge().
_reader_wedged = False
_reader_cpu = None  # (id(device), cpu ticks, monotonic time) of last sample
_reader_spin_streak = 0

_last_images = {}
_last_sublayer = None
# Monotonic time of the last forced full repaint; see FORCE_REPAINT_INTERVAL.
_last_repaint = 0.0

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

# How long the recovery path lets the USB stack settle after tearing a device
# down, before the outer loop enumerates and re-opens it. Re-opening the HID
# path instantly after a bus reset is what kept "No such device" recurring.
REOPEN_SETTLE_DELAY = 1.0

# Force a full repaint at least this often, even when no image changed.
# refresh() only writes keys whose desired image differs from the cache, so
# anything the device blanks on its own -- its inactivity/screensaver, a USB
# hiccup that survives recovery, or the clearAllIcon() run on every (re)open --
# would leave the panel dark until an app restart. Forgetting the cache on this
# interval makes the next tick redraw every key. It is a handful of writes on a
# 0.3 s tick, so keep it comfortably above the panel's own blanking to avoid
# needless USB traffic on a device that already resets under load.
FORCE_REPAINT_INTERVAL = 10.0

# A healthy reader thread blocks in the transport's poll() and burns ~no CPU.
# A wedged one (input endpoint dead after a USB failure) makes hid_read_timeout
# return at once, so the SDK reader loop spins one core forever and input goes
# dead -- without one draw ever failing, so the write-failure recovery cannot
# see it. The watchdog flags the device when the reader burns CPU above this
# fraction of wall time for READER_SPIN_MIN_TICKS consecutive refresh ticks.
READER_SPIN_FRACTION = 0.666
READER_SPIN_MIN_TICKS = 2

ydotool = YDoToolHandler(cmd_lock)
pulse = PulseAudioHandler(config)
hass = HomeAssistantHandler(config, hass_lock)
mpd = MPDHandler(config, mpd_lock)
playerctl = PlayerCtlHandler(cmd_lock)
loginctl = LoginCtlHandler(cmd_lock)
elite = EliteDangerousHandler(cmd_lock, config.elite_dangerous_status_path)

handlers = [ydotool, pulse, hass, mpd, playerctl, loginctl, elite]

layers = Layers(ydotool, pulse, hass, mpd, playerctl, loginctl, elite)


_CLK_TCK = os.sysconf("SC_CLK_TCK")


def _reader_cpu_ticks(thread):
    """CPU clock ticks (user+sys) a thread has burned, or None if unknown.

    On Linux the OS TID is thread.native_id (threading.Thread.ident is a
    Python-internal id since 3.13, NOT the TID), so /proc/self/task/<tid>/stat
    reveals the reader thread's CPU without touching the SDK. Fields after the
    comm field (everything past the last ')' ): [11]=utime, [12]=stime.
    """
    os_id = getattr(thread, "native_id", None) or getattr(thread, "ident", None)
    if not os_id:
        return None
    try:
        with open(f"/proc/self/task/{os_id}/stat", "rb") as f:
            _, rest = f.read().decode("utf-8", "replace").rsplit(")", 1)
    except (OSError, ValueError):
        return None
    fields = rest.split()
    try:
        return int(fields[11]) + int(fields[12])
    except (IndexError, ValueError):
        return None


def _check_reader_wedge(device):
    """Flag the device when its reader thread is spinning instead of waiting.

    The transport's read is a C call: when the input endpoint dies, poll()
    returns immediately and the SDK reader loop burns ~100% of a core. The
    panel still draws over the (working) out endpoint, so the write-failure
    streak never grows and nothing else would notice. A healthy reader stays
    parked in poll and burns ~no CPU. On platforms without /proc this stays a
    no-op.
    """
    global _reader_wedged, _reader_cpu, _reader_spin_streak

    thread = getattr(device, "read_thread", None)
    if thread is None:
        _reader_cpu = None
        _reader_spin_streak = 0
        return

    ticks = _reader_cpu_ticks(thread)
    now = time.monotonic()
    key = id(device)

    if ticks is None:
        return
    if _reader_cpu is None or _reader_cpu[0] != key:
        # First sample for this reader: arm, don't judge.
        _reader_cpu = (key, ticks, now)
        _reader_spin_streak = 0
        return

    _, prev_ticks, prev_time = _reader_cpu
    _reader_cpu = (key, ticks, now)

    dt = now - prev_time
    if dt <= 0:
        return
    dt_ticks = ticks - prev_ticks
    if dt_ticks < 0:
        _reader_spin_streak = 0
        return

    cpu_s = dt_ticks / _CLK_TCK
    if cpu_s >= READER_SPIN_FRACTION * dt:
        _reader_spin_streak += 1
        if _reader_spin_streak >= READER_SPIN_MIN_TICKS:
            _reader_wedged = True
    else:
        _reader_spin_streak = 0


def refresh(device):
    global _last_images, _last_sublayer, _write_failures, _last_repaint

    _check_reader_wedge(device)

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

        # Periodically forget what is on screen so every key is redrawn even
        # when nothing changed. The cache above turns refresh() into "only
        # write what differs", which is normally what we want, but it also
        # means anything the device blanks behind our back -- its own
        # inactivity/screensaver, a USB hiccup that survived recovery, or the
        # clearAllIcon() run on every (re)open -- would leave the panel dark
        # forever, because the cache still claims the icons are drawn.
        # Dropping the cache makes this tick redraw all of them.
        now = time.monotonic()
        if now - _last_repaint >= FORCE_REPAINT_INTERVAL:
            _last_images.clear()
            _last_repaint = now

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
    # While the device is being torn down, drop events instead of waiting for
    # device_lock: the recovery path holds that lock while it closes the
    # transport, and a reader parked on the lock could not be joined by
    # close().
    if _teardown.is_set():
        return

    key = _event_to_legacy_key(event)
    if key is None:
        return

    # Bounded wait: a refresh() stuck in the C transport must not park the
    # reader here forever, or it would outlive close()'s reader-join and leak
    # the transport handle.
    if not device_lock.acquire(timeout=1.0):
        return
    try:
        if _teardown.is_set():
            return
        layers.handle_keys(key)
    finally:
        device_lock.release()


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

    _teardown.set()
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
    # The SDK's own hotplug listener is intentionally not started. It polls the
    # HID bus on its own thread in parallel with the enumerate() below and
    # closes device objects the main loop is still drawing to; that concurrent
    # use of the vendor transport is what aborted the process inside
    # libtransport. This loop already detects (re)attach through enumerate()
    # and a failed open/write, so the listener adds nothing but the race.
    device_manager = DeviceManager()
    init_signal_handler(device_manager)

    while True:
        try:
            refresh_event.clear()
            _teardown.clear()
            _reader_wedged = False
            _reader_cpu = None
            _reader_spin_streak = 0

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

                # clearAllIcon() just blanked the panel, but the image cache
                # below is a module global that survives a recovery: without
                # this, the first refresh() after a (re)open sees every icon as
                # "already drawn" and skips it, leaving the dock dark until the
                # app is restarted. Forget what was on screen and start the
                # forced-repaint clock from now.
                _last_images.clear()
                _last_repaint = time.monotonic()

                layers.set_device(device)
                device.set_key_callback(read_callback)

                refresh_thread = start_thread(refresh_callback, (device, ))

                while True:
                    refresh_thread.join(1)

                    # Either the refresh thread died, the transport has been
                    # failing on every tick for a while (see _write_failures),
                    # or the reader thread is spinning on a dead input pipe
                    # (see _check_reader_wedge). All three mean this device
                    # object is no longer usable, so drop it and let the outer
                    # loop re-enumerate and re-open a fresh one.
                    # This is what makes the dock recover on its own instead of
                    # staying mute until someone restarts the app.
                    if (not refresh_thread.is_alive()
                            or _write_failures >= WRITE_FAILURE_LIMIT
                            or _reader_wedged):
                        if _reader_wedged:
                            reason = "input reader spinning"
                        elif not refresh_thread.is_alive():
                            reason = "refresh thread dead"
                        else:
                            reason = "write failures"
                        print(f"[recover] {reason}: closing {device.path} and re-opening",
                              flush=True)

                        refresh_event.set()

                        # Let an in-flight refresh tick finish. refresh()
                        # touches the transport while holding device_lock, so
                        # this keeps the close below from racing a draw.
                        refresh_thread.join(2)

                        # Drop further input, then close the device under the
                        # same lock refresh()/read_callback use so no draw or
                        # key event touches the transport while it is torn
                        # down. The lock is taken with a timeout because a
                        # refresh() wedged in the C transport can hold it past
                        # the join above; recovery must not block on that.
                        _teardown.set()
                        locked = device_lock.acquire(timeout=2)
                        try:
                            device.close()
                        finally:
                            if locked:
                                device_lock.release()

                        _write_failures = 0
                        _reader_wedged = False
                        _reader_cpu = None
                        _reader_spin_streak = 0

                        # Give the USB stack a moment to finish the
                        # re-enumeration before the outer loop enumerates and
                        # re-opens; an instant reopen is what kept "No such
                        # device" coming back.
                        time.sleep(REOPEN_SETTLE_DELAY)

                        break

        except KeyboardInterrupt:
            signal_handler(signal.SIGINT)