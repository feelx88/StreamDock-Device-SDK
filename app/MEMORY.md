# Agent Memory — StreamDock Project

This file is the persistent memory for AI agents working on this repo. Last
updated: 2026-09-18 (after HA handler + single-page rotation fixes).

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
pulseaudio_handler.py       pulse volume/mute via pactl
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
- Layers config: layer 0 → 2 pages, layers 1+2 → 1 page each, layer 3 → 3 pages.
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
- Runtime system deps (not pip): `ydotool`, `pactl` (pulseaudio-utils),
  `playerctl`, `loginctl` (systemd), `~/.change_audio.sh` helper script.
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