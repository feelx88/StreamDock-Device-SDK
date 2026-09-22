from ydotool_handler import YDoToolHandler
from threading import Lock
from threading import Thread
from datetime import datetime, timezone
import json
import math
import os
import time


class EliteDangerousHandler(YDoToolHandler):
    # Flags bit positions
    FLAG_LANDING_GEAR = 1 << 2
    FLAG_HARDPOINTS = 1 << 6
    FLAG_LIGHTS = 1 << 8
    FLAG_CARGO_SCOOP = 1 << 9
    FLAG_ANALYSIS_MODE = 1 << 27
    FLAG_NIGHT_VISION = 1 << 28

    # Stock Elite Dangerous bindings (evdev key codes):
    # N (49) = Cycle Next Fire Group, B (48) = Cycle Previous Fire Group.
    NEXT_FIRE_GROUP_KEY = 49
    PREVIOUS_FIRE_GROUP_KEY = 48
    FIRE_GROUP_COUNT = 6
    # Keep an optimistically selected fire group highlighted for this long
    # after a button press. The worker extends the hold while a move is being
    # sent, so this is how long the deck takes to sync back to the real value
    # once the last move finishes; a fresh Status.json reading then replaces
    # the claim (~1 s), while a stale value never overrides the last pressed
    # group.
    FIRE_GROUP_OPTIMISTIC_HOLD = 1.0
    # Pause after one queued move finishes before the next move's keys start,
    # so the game has clearly registered the previous burst. Without this,
    # moves queued back-to-back hit ED so fast that cycles get dropped and
    # the fire group lands off-target.
    FIRE_GROUP_SEQUENCE_GAP = 0.4
    # Worker poll cadence while waiting for queued fire group requests.
    FIRE_GROUP_POLL_INTERVAL = 0.02

    def __init__(self, cmd_lock, status_path):
        super().__init__(cmd_lock)
        self.status_path = status_path
        self.status_flags = 0
        self.status_fire_group = None
        self._fire_group_optimistic_until = 0.0
        # Latest requested fire group, coalesced into one slot and drained by
        # the worker. Reads/writes are protected by `_fire_group_lock` so a
        # button press can never be dropped between the worker reading and
        # clearing the slot.
        self._fire_group_lock = Lock()
        self._fire_group_queued = None
        # Position the last sent sequence ends at. Deltas are computed against
        # this (not the optimistic claim) so queued moves build on each other.
        self._fire_group_position = None
        # True while the worker is sending keys or waiting out the settle gap.
        self._fire_group_busy = False
        # Time of the latest button press. A Status.json value whose
        # `timestamp` is newer than this reflects a post-press state and can be
        # trusted as the game's real position.
        self._fire_group_last_action = 0.0
        self._fire_group_worker = Thread(
            target=self._fire_group_worker_loop, daemon=True)
        self._fire_group_worker.start()

    def update(self):
        self.status_flags, real_fire_group, ts = self._get_status()
        # Status.json is the only window on the game's real fire group, but ED
        # only rewrites the file on some status events - fire group changes are
        # NOT among them on this setup - so the value is usually stale. Trust it
        # only when its timestamp is newer than the last press; a stale value
        # must never override the highlight or corrupt the delta base.
        fresh = (ts is not None and real_fire_group is not None
                 and ts >= math.floor(self._fire_group_last_action))
        idle = self._fire_group_idle()
        if fresh and idle:
            with self._fire_group_lock:
                self._fire_group_position = real_fire_group
        # Sync the highlight back to the real value only from a fresh reading
        # (or before the first press), and only when nothing is in flight - a
        # short hold must never cut a move that is still being sent.
        if (self._fire_group_position is None
                or (time.time() >= self._fire_group_optimistic_until
                    and fresh and idle)):
            self.status_fire_group = real_fire_group

    def _get_status(self):
        if not self.status_path or not os.path.exists(self.status_path):
            return 0, None, None
        try:
            with open(self.status_path, 'r') as f:
                data = json.load(f)
                fire_group = data.get('FireGroup')
                if isinstance(fire_group, dict):
                    fire_group = fire_group.get('InShip')
                if not isinstance(fire_group, int):
                    fire_group = None
                return (data.get('Flags', 0), fire_group,
                        self._parse_ts(data.get('timestamp')))
        except (json.JSONDecodeError, IOError):
            return 0, None, None

    @staticmethod
    def _parse_ts(raw):
        """Parse ED's ISO-8601 status timestamp into a UTC epoch (float)."""
        if not isinstance(raw, str):
            return None
        try:
            dt = datetime.fromisoformat(raw.strip())
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

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

    def fire_group(self, index):
        """Select fire group `index` (0..5 -> A..F).

        The press claims the target optimistically (the highlight moves
        immediately) and hands the actual key sending to the worker thread, so
        the SDK's reader thread never blocks. A press made while a previous
        switch is still in flight is therefore always captured - it is
        coalesced into the pending slot and executed once the current move has
        finished, after a short settle pause so the game registers every step.
        """
        letter = chr(ord('a') + index)

        def cmd():
            self.status_fire_group = index
            self._fire_group_optimistic_until = (
                time.time() + self.FIRE_GROUP_OPTIMISTIC_HOLD)
            self._fire_group_last_action = time.time()
            with self._fire_group_lock:
                self._fire_group_queued = index

        return (
            lambda: cmd(),
            lambda: 'images/firegroup_{}.active.png'.format(letter)
            if self.status_fire_group == index
            else 'images/firegroup_{}.png'.format(letter)
        )

    def _fire_group_worker_loop(self):
        while True:
            time.sleep(self.FIRE_GROUP_POLL_INTERVAL)
            with self._fire_group_lock:
                if self._fire_group_busy or self._fire_group_queued is None:
                    continue
                index = self._fire_group_queued
                self._fire_group_queued = None
                self._fire_group_busy = True

            try:
                current = self._fire_group_position
                if current is None:
                    current = 0
                current %= self.FIRE_GROUP_COUNT

                fwd = (index - current) % self.FIRE_GROUP_COUNT
                back = (current - index) % self.FIRE_GROUP_COUNT

                # Keep update() from syncing over a still-processing move.
                self._fire_group_optimistic_until = (
                    time.time() + self.FIRE_GROUP_OPTIMISTIC_HOLD)

                if fwd == 0:
                    # Already on (or predicted to be on) the target group.
                    with self._fire_group_lock:
                        self._fire_group_position = index
                    continue

                if fwd <= back:
                    key, presses = self.NEXT_FIRE_GROUP_KEY, fwd
                else:
                    key, presses = self.PREVIOUS_FIRE_GROUP_KEY, back

                # Insert an extra `wait` token between presses so each
                # fire-group cycle is separated by two key-delays and the game
                # registers every step.
                sequence = ' wait '.join(
                    '{}:1 wait {}:0'.format(key, key) for _ in range(presses))
                with self._acquire_timeout('cmd'):
                    os.system('ydotool key -d 50 {}'.format(sequence))

                with self._fire_group_lock:
                    self._fire_group_position = index

                # Let the game register this move before the next one starts.
                time.sleep(self.FIRE_GROUP_SEQUENCE_GAP)
            finally:
                with self._fire_group_lock:
                    self._fire_group_busy = False

    def _fire_group_idle(self):
        with self._fire_group_lock:
            return not self._fire_group_busy and self._fire_group_queued is None
