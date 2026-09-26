# Agent Memory — StreamDock Project

This file is the persistent memory for AI agents working on this repo. Last
updated: 2026-09-18 (after HA handler + single-page rotation fixes).

## Writing & comment style (IMPORTANT)

- Do NOT frame docs or code comments as "the previous version did X, now it does
  Y". History-diffing narration is not helpful. Describe what the code does and
  why, in the present tense, as if it always worked this way.
- Avoid references to removed files/scripts, old bugs, or "used to" phrasing
  unless the user explicitly asks for a migration/diff explanation.
- Keep comments about the current design and its rationale, not its lineage.

## Project Overview

`streamdock` is the home of the **StreamDock** device app (6 display keys +
3 knobs, StreamDock293 class device) plus several SDKs:

- `Python-SDK/` — upstream library (verbatim, tracked), rewritten by upstream at
  `b476fb1` ("full library rewrite"). **Never modify files under `Python-SDK/`.**
- `app/` — the user's device app, fully separated from the SDK so upstream can
  be updated freely (`git pull` upstream and merge; app untouched).
- `CPP-SDK/`, `WebSocket-SDK/`, `docs/` — other upstream artifacts, not ours.
- `LLM-linux-instructions.md` — upstream docs, not ours.

### Branch layout

- `main` — tracks `origin/main` (upstream, tip `b476fb1`).
- `feelx88` — CURRENT WORKING BRANCH: upstream `main` + ported app. Newest
  commits on top; NOT pushed to origin yet.
- `feelx88-old` — backup reference of the pre-rebase branch (tip `4760ddf`),
  kept for diffing/restoring old behavior if needed.
- `.venv` at `app/.venv` — real app venv (Python 3.14.7, pillow 12.3.0,
  pyudev 0.24.4, homeassistant-api 6.1.0, python-mpd2, dbus-python).
  `Python-SDK/src/.venv` is stale/unused.

### feelx88 commit history (newest first)

```
ac3f39f Fix blank screen when rotating/pressing on a single-page layer
04c1e06 Fix HomeAssistant handler: drop removed cache_session kwarg
809c4f5 Make app/requirements.txt self-contained (include SDK core deps)
09ad2b0 Move app out of Python-SDK into app/, restore SDK verbatim upstream
ae51beb Add requirements.txt for app python dependencies
c6e6180 Rebuild feelx88 on upstream main: port app to new SDK API
b476fb1 upstream main (SDK rewrite)
```

## App Architecture

### Directory layout (`app/`)

```
main.py                     entry point: sys.path bootstrap, chdir, device mgmt
sdk_patch.py                runtime monkeypatch (StreamDock293.set_key_image)
configuration.py            config loading
keys.py                     key mappings per layer/sub-layer + default layer
layers.py                   page/sub-page rotation logic
lockable.py                 locking helpers
base_handler.py             handler base (guard, _acquire_timeout)
ydotool_handler.py          keyboard emulation via ydotool
pulseaudio_handler.py       pulse volume/mute/device switch via pulsectl
homeassistant_handler.py    Home Assistant scenes/entities
mpd_handler.py              MPD client (python-mpd2)
playerctl_handler.py        media control via playerctl
loginctl_handler.py         session control via loginctl
elite_dangerous_handler.py  Elite Dangerous journal/status via submodule
modules/                    git submodules (elite-dangerous docs + icons,
                            x4-foundations modules also under here)
images/                     icon PNGs
config.json                 user config (GITIGNORED — do not commit secrets)
config.json.tpl             config template (committed)
requirements.txt            self-contained app deps
tox.ini, GEMINI.md
```

### Entry point (`app/main.py`)

- Bootstraps `sys.path` to `../Python-SDK/src` (relative to file, not CWD).
- `os.chdir(APP_DIR)` so `config.json` and `images/...` resolve from any launch
  directory.
- Imports `sdk_patch` and calls `sdk_patch.patch_streamdock293()` right after
  SDK imports, before handlers.
- Device discovery: `DeviceManager().listen(auto_open=False, auto_init=False)`
  (app opens/initializes devices itself).
- New-API input handling: `set_key_callback` → `read_callback(device, event)`
  translates `InputEvent` back to legacy hardware key codes and calls
  `layers.handle_keys(key)`. Trigger on `event.state == 0` to mirror the old
  `status == 0` read filter.
- `refresh(device)` loop every 0.3 s: calls `handler.update()` for all handlers,
  renders keys 1–6, `set_key_image`/`clearIcon`, `device.refresh()`.
- Signal handler (SIGABRT/INT/TERM/QUIT/HUP): `clearAllIcon()` + `close()` all
  enumeration devices, then exit.
- Launch: `cd app && ./.venv/bin/python main.py [layer [sub_layer]]`

### Event → legacy key code mapping (N3)

- BUTTON `KEY_1..6` = legacy codes `1..6` (top six display keys)
- BUTTON `KEY_7/8/9` = `37 / 48 / 49` (bottom three page buttons)
- KNOB rotate, `KNOB_1` L/R = `144 / 145` (0x90 / 0x91) — page rotation on
  layer 3, volume elsewhere (default mapping)
- KNOB rotate, `KNOB_2` L/R = `96 / 97` (0x60 / 0x61) — MPD volume
- KNOB rotate, `KNOB_3` L/R = `80 / 81` (0x50 / 0x51) — pulse source volume
- KNOB press `KNOB_1/2/3` = `51 / 52 / 53` (mute / mpd mute / source mute)

### Layers / rotation logic (`app/layers.py`)

- `self.layer` = top-level page index, `self.sub_layer` = page within layer.
- Layers config: layer 0 → 2 pages, layers 1+2 → 1 page each, layer 3 → 4 pages.
- `set_layer(new_layer, new_sub_layer=None)`: computes target page; only calls
  `device.clearAllIcon()` and commits state **when the page actually changes**
  (single-page layers used to blank the screen — fixed in `ac3f39f`).
- `set_layer_relative(layer_delta, sub_layer_delta)`: modular rotation; called
  by knob bindings `set_layer_relative(sub_layer_delta=±1)` on layer 3.
- `current_sublayer_keys()` / `current_sublayer_display_keys()` (keys 1–6 with
  an image tuple).
- `handle_keys(key)`: sublayer mapping wins, else `default` mapping.

### Handlers

- All handlers share `BaseHandler.__init__` taking dict of named locks;
  `guard()` runs an action under the handler lock (used as `lambda: self.guard(...)`).
- `HomeAssistantHandler`: `self._client = homeassistant_api.Client(url, token)`
  (positional only — the old `cache_session=False` kwarg was removed in
  homeassistant-api >= 6.x and silently killed the whole handler; fixed in
  `04c1e06`; `connect()` now prints failures and leaves `_client = None`).
  Reads `input_text.aktuelle_szene` → `_active_scene`; `scene(name)` renders
  `images/{name}.png` vs `.active.png`; `trigger_service(icon, domain, service,
  **data)` binds keys; error state → `images/error.png`.
- `MPDHandler`: `client()` helper (method) returns `self._client`; keys call
  `self.mpd.guard(self.mpd.client().volume, -5)` etc.
- Runtime system deps (not pip): `ydotool`, `playerctl`, `loginctl`
  (systemd), and `libpulse.so` (for `pulsectl`). Headset/speakers device names
  are configured in `config.json` under `"audio"` (`.tpl` has placeholders) and
  applied by `PulseAudioHandler._switch_profile`.
- Elite Dangerous submodules: `app/modules/elite-dangerous/`
  (`elite-api-docs` @ `753ef2f1…`, `elite-dangerous-stream-deck-icons` @
  `0d0af15a…`); x4-foundations modules under `app/modules/x4-foundations/`.
  Submodules are NOT initialized locally — populate with
  `git submodule update --init --recursive`. `git submodule status` is empty
  and working tree shows ` D` entries for them (cosmetic, expected).

## SDK Notes (do NOT modify — upstream verbatim)

- `StreamDock.py`: `set_key_callback`, `open`/`close`, `clearIcon`,
  `clearAllIcon`, internal reader thread started by `open()`.
- `StreamDockN3.py`: `decode_input_event`, key maps.
- `InputTypes.py`: `InputEvent`, `EventType`, `ButtonKey`, `KnobId`, `Direction`.
- `DeviceManager.py`: `listen(auto_open/auto_init)`.
- **CRITICAL (SIGSEGV):** never reintroduce transport close during a parked
  blocking read — the C `.so` cannot be modified. New API `close()` shuts the
  reader + heartbeat and defers transport close; there is no separate `stop()`.

## Known Fixes & Gotchas

- `Temporary.jpg` / StreamDock293 tempfile bug: fixed at runtime via
  `sdk_patch.patch_streamdock293()` monkeypatch (NOT by editing upstream
  `StreamDock293.py`).
- homeassistant-api 6.1.0 `Client.__init__(api_url, token)` — no
  `cache_session`, no kwarg-based session; `get_state(entity_id=...)`,
  `trigger_service(domain, service, **service_data)` signatures confirmed.
- Single-page layer blank-screen bug (see layers logic above).
- Git output is German (e.g. `KONFLIKT`, `Zu Branch ... gewechselt`).
- `git status` should be clean except cosmetic ` D` submodule entries.
- Unverified on hardware: exact press/release byte semantics
  (`state == 0` vs `state == 1` for the release filter) — flagged in
  `app/main.py` comments; confirm on device.

## 2026-09-22 — Elite Dangerous fire group page

- Layer 3 gained a 4th page (index 3): six fire group buttons (A–F).
- Elite Dangerous has no "select group X" binding, so `fire_group(index)` in
  `elite_dangerous_handler.py` cycles from the current group to the target with
  the stock N (49 = next) / B (48 = previous) bindings, choosing the shorter
  direction (`fwd = (target-current) % 6` vs `back`) and building a multi-press
  `ydotool` sequence with an extra `wait` token between presses so the game
  registers every cycle. Pressing the already-active group sends nothing.
- Fire group selection is **optimistic**: a press immediately claims the target
  group (highlight); `update()` only syncs the highlight back from Status.json
  when the file's `timestamp` is *newer* than the last press (a "fresh"
  reading), or before the first press ever. A stale status value is never
  applied — the highlight keeps the last pressed group instead of snapping
  back to an outdated file value.
- Fire group presses are **queued and sent by a daemon worker**
  (`_fire_group_worker_loop`): `cmd()` only claims the target optimistically
  and stores it in a lock-protected, coalescing slot (`_fire_group_queued`
  under `_fire_group_lock`), so the SDK's reader thread never blocks and a
  press made while a previous switch is still in flight is always captured
  (never lost to a read/clear race). The worker drains the slot, computes the
  delta against `_fire_group_position` (the position the last *sent* sequence
  ends at, not the optimistic claim), sends the `ydotool` sequence, then waits
  `FIRE_GROUP_SEQUENCE_GAP` (0.4 s) before accepting the next queued request
  so ED registers each burst before the next starts. This "in-flight press +
  settle gap" design is what makes fast consecutive group changes reliable;
  a first async attempt (no gap) and a synchronous-revert (blocking the reader
  thread, losing presses made mid-move) both showed intermittent dropped
  switches and were replaced by this version.
- **Status.json is an unreliable fire-group signal here:** ED only rewrites
  the file on some status events (docking, gear, panel focus...) and fire-group
  changes alone may go unreported for long stretches (observed frozen ~1.5 h
  through a test window, yet it can update after other events and sometimes
  carries a newer group). The in-JSON `timestamp` is honored for freshness
  (trusted only when `ts >= floor(last_press)`), so the app degrades
  gracefully:
  - `update()` re-anchors `_fire_group_position` when a reading is fresh and
    nothing is in flight — the general drop-correction path for setups where
    the file *does* update.
  - When the file is stale (the common case here), the optimistic claim and
    the open-loop position are kept: a stale value can never override the
    highlight or corrupt the delta base. An earlier design polled Status.json
    mid-chain to confirm the real landing (`FIRE_GROUP_CONFIRM_TIMEOUT`); it
    was removed because on this setup the file never confirms, so the polls
    were pure latency (up to 0.8 s per queued press) with no benefit. The
    settle gap (`FIRE_GROUP_SEQUENCE_GAP`, 0.4 s) remains the only pause
    between chained moves.
- **Single app instance is mandatory.** `streamdock.desktop` (autostart)
  already launches `main.py`; launching a second copy makes both instances
  answer the same buttons and each send its own key bursts — symptoms ranged
  from "completely fucked" to random switching. Never run a second `main.py`.
- **Sync-back is quick (~1 s).** The optimistic claim is kept while moves are
  in flight (the worker extends `FIRE_GROUP_OPTIMISTIC_HOLD`, 1 s), and once
  the last move finishes a fresh Status.json reading replaces the highlight —
  gated on idle and fresh, so a stale file never overrides the pressed group
  and a short hold never cuts a move mid-send.
- ED does accept the fire-group cycle keys with the right-hand panel open
  (user's normal test setup, confirmed working) — the "works only every 4 s"
  thread was never a panel problem; it combined a stale re-anchor delay in the
  app with the dead file signal above, and is resolved by the queue + fresh
  sync + (critically) a single app instance.
- `update()` now parses `Flags`, `FireGroup` and `timestamp` from
  `Status.json` (`None` when the file is missing; `FireGroup` may be a plain
  int or a dict with `InShip`; `timestamp` is ED's ISO-8601 UTC time, parsed
  by `_parse_ts` and used to decide freshness). No highlight when unknown.
- Icons: `images/firegroup_{a..f}.png` ← `Group-*_OFF.png`,
  `.active.png` ← `Group-*_ON.png` from the stream-deck-icons submodule
  (1:1 byte copies, same as the other Elite buttons).

## Configuration & Secrets

- `app/config.json` is gitignored (user-local): contains
  `homeassistant_url`, `homeassistant_token`, `mpd_ip`, etc.
  Current values include HA URL `http://192.168.0.32:8123/api/` and
  `mpd_ip: 192.168.0.34` (user-edited; Nextcloud backup says `.76`).
- `app/config.json.tpl` (committed) is the template; `elite_dangerous_status_path`
  added for Steam/Proton Elite Dangerous `Status.json`.
- Safe backup of user config: `~/Nextcloud/devel/streamdock/config.json`.
- `app/.gitignore` ignores `config.json`, `volume.state`, `mpd_volume.state`,
  `__pycache__/`, `*.py[cod]`. Root `.gitignore` has `.DS_Store`, `.vscode`.

## Verification & Next Steps

1. On hardware: `cd app && git submodule update --init --recursive &&
   pip install -r requirements.txt && python main.py` with device attached.
2. Confirm press/release semantics (state == 0 vs state == 1) on device.
3. HA handler + single-page rotation fixes are committed locally and were
   verified via live HA state query + mock-device layer simulation; user
   confirmed HA clicks now work.
4. Optional once hardware-verified: `git push -u origin feelx88`.

## Top-level LLM instruction set (IMPORTANT)

There is an **LLM instruction set at the repo top level** with some useful
information: `LLM-linux-instructions.md` (repo root, next to `app/`). It
contains an instruction set written for LLM agents working on this repo.
Re-read it whenever beginning a fresh session or when told there is useful
context at the top level.

## 2026-09-26 — Dock goes mute until app restart (`hid_write ... Protocol error`)

Symptom: out of nowhere mid-session the dock stops responding entirely — panel
frozen, keys dead — and only restarting the app brings it back. The journal
shows a single line then silence:

    [send] hid_write FAILED, res=-1 error: Protocol error

That message is printed by the **vendor C transport** (`libtransport.so`, a
prebuilt binary under `Python-SDK/src/StreamDock/Transport/TransportDLL/`), not
by the Python SDK or the app. `EPROTO` means the USB endpoint/handle went bad,
typically after a bus reset or re-enumeration.

Root cause — the draw cache mistook the error for success:

- `transport_set_key_image_stream` is declared with **`restype = c_uint32`**
  (LibUSBHIDAPI.py:240). The C lib returns `-1` on failure, but ctypes reads it
  **unsigned**, so Python sees **4294967295**.
- The earlier 2026-09-19 fix tested `if result is None or result >= 0:` before
  caching `_last_images[key]`. `4294967295 >= 0` is **True**, so a *failed* draw
  was cached as "already drawn".
- From then on `if _last_images.get(key) == image: continue` skipped every key
  forever and the app never issued another write — which is why the log shows
  exactly **one** failure line and then nothing. Restarting resets the
  module-global and "fixes" it.
- The SDK's own success value is `0` (`TRANSPORT_SUCCESS`, the same convention it
  uses at LibUSBHIDAPI.py:544/987/1213); a dead handle returns `None`.

Fix in `app/main.py refresh()`:

- Cache a key **only** when `device.set_key_image(...) == 0`. Any other value
  (unsigned error code, or `None` from a dead handle) stays uncached and is
  retried on the next 0.3 s tick.
- `clearIcon()` returns **no status at all** in this SDK, so it is cached
  unconditionally (it cannot be half-verified; re-issuing it every tick would
  just spam the bus).
- Added bounded recovery: refresh ticks containing a failure extend a
  `_write_failures` streak (reset by any fully clean tick). Once it reaches
  `WRITE_FAILURE_LIMIT` (10 ticks ≈ 3 s) the main loop closes the device and
  lets the outer loop re-enumerate and `open()` it again — the same recovery
  path already used when the refresh thread dies. `open()` calls
  `transport.open(path)`, so a stale handle is genuinely re-acquired. This is
  what makes the dock heal by itself instead of needing a restart.

Ruled out (don't re-investigate): the vendor `.so` itself (binary, and
`Python-SDK/` must stay upstream-verbatim); `sdk_patch.py`'s tempfile lifecycle
(the transport reads the file synchronously inside the call); the cursor-only
display-wake in `loginctl_handler.py` (unlock path only, not on the refresh
loop).

## 2026-09-26 — Stale icon on keys that have no icon on the new page

Symptom: after a page change, a key that has **no icon** configured for the
current page keeps showing the icon from the *previous* page instead of an empty
button. Seen mainly in Elite Dangerous "space ship mode", where pages are changed
with the little wheel — hence "sometimes".

Two things combine to cause it:

1. `Layers.set_layer_relative()` (layers.py) **mutates `self.layer` /
   `self.sub_layer` first** and only then calls
   `set_layer(self.layer, new_sub_layer=self.sub_layer)`. Inside `set_layer()`
   the guard `if new_layer != self.layer or new_sub != self.sub_layer` is
   therefore already **False** (the values match, because they were pre-mutated),
   so **`clearAllIcon()` never runs** for wheel-driven page changes. The panel is
   not blanked. (Key-press page changes via `set_layer(0)` / `set_layer(1)` /
   `set_layer(2)` / `set_layer(3)` from keys.py *do* clear — that is why the bug
   only shows up on some page changes.)
2. `refresh()` in main.py reacts to a sublayer change by wiping the
   `_last_images` cache, then deduped with
   `if _last_images.get(key) == image: continue`. A key with no icon has
   `image is None`, and a **missing** dict entry also returns `None`, so
   `None == None` → `continue` → `clearIcon()` was **skipped** for every
   icon-less key. With no `clearAllIcon()` to fall back on, the previous page's
   icon stayed on screen. Because the key is never marked, it stayed wrong
   until some later page happened to give that key an icon again.

Fix: an unknown cache entry must never compare equal to a desired state of
`None`. Added a module-level `_UNKNOWN = object()` sentinel in main.py and
changed the test to `_last_images.get(key, _UNKNOWN) == image`. Now a wiped
cache makes icon-less keys issue their `clearIcon()` once and then settle, so
they correctly show an empty button.

Note: only the `refresh()` dedup was fixed. The `set_layer_relative()` →
`set_layer()` pre-mutation quirk (no `clearAllIcon()` on relative page changes)
was left alone deliberately — it is load-bearing for the single-page-rotation
blank fix below, and the sentinel makes the app correct without it. Don't "fix"
the pre-mutation without re-checking that section.

## 2026-09-19 — Icons vanish after ~3rd page change, only restart recovers

Symptom: after app restart, all 6 key icons are fine for ~2 page changes, then
after the third or so page change the whole panel is **completely blank** and
stays blank until the app is restarted.

Root cause (main.py `refresh()`, cache-written-unconditionally):

- Each real page change calls `layers.set_layer()` → `device.clearAllIcon()`
  which blanks the whole panel (hardware clear of all 6 keys).
- `refresh()` then redraws via the `_last_images`/`_last_sublayer` dedup
  cache. The line `_last_images[key] = image` ran UNCONDITIONALLY, even when
  `device.set_key_image()` / `clearIcon()` returned an error (`-1`, transient
  USB/transport failure).
- So if one draw fails at a page change, that key's image was cached as
  "current", and on every later tick `if _last_images.get(key) == image:
  continue` skipped it forever. Panel is already blank from `clearAllIcon()`
  and the key is never retried → whole page stays blank until restart (which
  resets the module-global `_last_images`).

Fix: in `app/main.py refresh()` only cache `_last_images[key] = image` when
the draw **succeeded** (`result >= 0` / `result is None`); on failure leave the
key uncached so it self-heals on the next 0.3 s refresh tick. Transient losses
no longer become permanent-until-restart.

> **SUPERSEDED 2026-09-26 — the success test above is wrong.** The SDK returns
> that status as `c_uint32`, so a real failure arrives as `4294967295`, which
> passes `result >= 0`. The cache therefore still poisoned itself on transport
> errors. The correct test is `== 0`. See the 2026-09-26 section above.

Also confirmed during this investigation (ruled out, don't re-investigate):
- The `sdk_patch.py` tempfile lifecycle is NOT the bug. The transport's
  `setKeyImg()` reads the file **synchronously** inside the call
  (LibUSBHIDAPI.py ~1368: `open(path,"rb").read()` -> `set_key_image_stream`),
  so its `finally: os.remove(temp_image_path)` is safe — no async race.
- The single-page rotation blank fix (`ac3f39f`) is intact — `set_layer()` only
  clears+switches on a real page change.

## 2026-09-19 — Single-page rotation blank fix (older, keep intact)

The single-page rotation blank fix (`ac3f39f`) is intact — `set_layer()` only
clears+switches on a real page change.

## 2026-09-19 — Display wake on unlock (`loginctl_handler.py`)

The unlock branch now also wakes a sleeping/blanked display. There is **no one
maintainable pip library** that wakes displays across X11+Wayland+macOS+Windows
(nothing like a universal `wake()`) — the ecosystem is fragmented (X11 DPMS
`xset`, wlroots `wlopm`, macOS `caffeinate -u`, Windows ES_DISPLAY_REQUIRED).
So `_wake_display()` (module-level, `loginctl_handler.py`) does a best-effort
platform dispatch wrapped in try/except, and relies on the one truly universal
primitive: a **tiny synthetic pointer nudge** (any input activity re-enables a
blanked panel on every OS). All calls are non-fatal no-ops if the display is
already awake; wired only into the unlock path (`locked()` true → unlock →
wake). Do NOT make this fatal or require a new dependency.