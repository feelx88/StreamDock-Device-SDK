# Project Overview

This project is a Python application that provides a flexible and configurable way to control StreamDock devices on Linux. It allows users to map actions to the keys of their StreamDock, organized in a system of layers and sub-layers.

The application is built with a modular architecture. Core components and handlers include:

*   **Configuration:** Managed by the `Configuration` class in `configuration.py`. It loads settings from `config.json` and provides typed access to configuration keys.
*   **Layers:** Managed by the `Layers` class in `layers.py`. It handles the logic for switching between layers and sub-layers. Supports `default` keys and layered mappings for all buttons.
*   **Keys:** Managed by the `Keys` class in `keys.py`. It centralizes the definition of all key mappings. Uses a structure with `default` and `layers`.
*   **ydotool:** For simulating keyboard and mouse events. Supports optional state management (toggling icons).
*   **pulseaudio:** For controlling audio volume and mute status.
*   **homeassistant:** For interacting with a Home Assistant instance.
*   **mpd:** For controlling the Music Player Daemon.
*   **playerctl:** For controlling media players that implement the MPRIS D-Bus interface.
*   **loginctl:** For locking the screen.

The application uses `pyudev` to detect StreamDock devices as they are connected and disconnected, and it uses `LibUSBHIDAPI` for low-level communication with the devices.

**Library Status:** The `StreamDock/` folder is treated as library code and should not be modified unless absolutely necessary.

# Hardware Mapping

The device features a 3x2 row of display keys, physical layer-switch buttons, and three clickable knobs.

### Display Keys
- **IDs 1 to 6:** These keys feature small displays and support icons. Mappings for these are defined in the `display` section of the `keys` dictionary.

### Layer Switch Keys
- **IDs 37, 48, 49:** Physical buttons located below the display row used to toggle between layers.

### Knobs
- **Large Knob:**
    - **53:** Click
    - **80:** Turn Left
    - **81:** Turn Right
- **Small Left Knob:**
    - **51:** Click
    - **144:** Turn Left
    - **145:** Turn Right
- **Small Right Knob:**
    - **52:** Click
    - **96:** Turn Left
    - **97:** Turn Right

# UI Structure

The application organizes key mappings into **Layers**. Each layer can contain multiple **Sub-layers**.
- **Default Keys:** Defined in the `default` section of the mappings. These are used if a key is not specifically mapped in the current sub-layer.
- **Switching Layers:** Physical keys or any mapped action can switch between layers using `set_layer` or `set_layer_relative`.
- **Switching Sub-layers:** By default, pressing the same layer key again cycles through the sub-layers available for that layer.
- **Relative Switching:** The `set_layer_relative(layer_delta, sub_layer_delta)` method allows relative navigation through layers and sub-layers.

### Layer 1 (Media & Games)
- **Sub-layer 1:** MPD and Playerctl media controls, Screen Lock.
- **Sub-layer 2:** X4 Foundations shortcuts:
    - Key 1: Short-range Scan (Shift+2)
    - Key 2: Long-range Scan (Shift+3)
    - Key 3: SETA (Shift+4)
    - Key 4: Comms (C) (Momentary)
- **Sub-layer 3:** Elite Dangerous shortcuts (Ctrl+1 to Ctrl+4):
    - Key 1: Cockpit Mode
    - Key 2: Cargo Scoop
    - Key 3: Hardpoints
    - Key 4: Landing Gear

# Building and Running

1.  **Installation:**
    This project is run directly from the source directory. A virtual environment (`.venv`) is recommended.

2.  **Dependencies:**
    Required Python dependencies:
    *   `pyudev`
    *   `pillow` (Pillow)
    *   `homeassistant-api` (implied by `homeassistant_handler.py`)
    *   `python-mpd2` (implied by `mpd_handler.py`)
    *   `autopep8` and `pycodestyle` (for development)

    External tools:
    *   `ydotool` (must be in system PATH)

3.  **Configuration:**
    The application uses `config.json`, which is managed by the `Configuration` class in `configuration.py`. A template is provided as `config.json.tpl`. Copy it to `config.json` and customize your settings.

    Supported keys:
    *   `homeassistant_url`: The URL of your Home Assistant instance.
    *   `homeassistant_token`: A Long-Lived Access Token for Home Assistant.
    *   `mpd_ip`: The IP address of your MPD server.
    *   `mpd_port`: The port of your MPD server (usually 6600).

4.  **Running:**
    ```bash
    .venv/bin/python3 main.py
    ```

# Development Conventions

*   **Code Style:**
    *   The project follows PEP 8.
    *   **Max Line Length:** 120 characters (configured in `tox.ini`).
    *   **Linting:** Use `pycodestyle` to check for compliance.
    *   **Formatting:** Use `autopep8` for automatic formatting.
    *   **Automation:** `pycodestyle`, `autopep8`, and other formatting/linting tools **MUST** be executed directly after every code modification without requiring user confirmation.
    *   **Virtual Environment:** Always use the project's virtual environment (`.venv`) for all Python-related tasks (running the app, formatting, linting, etc.) if it exists.
    *   **Virtual Environment:** Always use the project's virtual environment (`.venv`) for all Python-related tasks (running the app, formatting, linting, etc.) if it exists.

*   **Images:**
    *   Icons are stored in `../images/`.
    *   Standard format: 128x128 PNG, white icon, transparent background.
    *   Active state format: Green icon (or `.active.png` suffix).

*   **Testing:** There are no automated tests in this project.
*   **Contribution:** Ensure all code passes `pycodestyle` checks before committing.

# Interaction & Project Rules

*   **Library Code:** Do not modify files within the `StreamDock/` directory; it is treated as a library.
*   **Language:** All entries in `GEMINI.md` files must always be in English.
