import os

# --- HUD defaults ---
DEFAULT_HUD_SIZE = 100
DEFAULT_THEME = "Neon Violet"

# --- Agent polling ---
# How often (in seconds) the agent checks the focused window.
POLLING_RATE_SECONDS = 2

# Window titles are matched against these lists (case-insensitive, partial
# match) to decide whether the current app counts as productive time or
# distraction time.
PRODUCTIVITY_APPS = ['Visual Studio Code', 'PowerShell', 'Word', 'Excel', 'Chrome', 'Edge']
DISTRACTION_APPS = ['Spotify', 'Discord', 'Twitter', 'Instagram', 'Steam', 'YouTube', 'Reddit', 'Netflix']

# Used to stretch a short real-world testing session into a plausible
# "simulated day" of activity, so the model sees numbers in the range it
# was trained on instead of a couple of minutes' worth of seconds.
TIME_MULTIPLIER = 120

# All the user-adjustable settings live in one dictionary so they can be
# saved/loaded together and passed around easily.
USER_CONFIG = {
    'hud_size': DEFAULT_HUD_SIZE,
    'theme_preset': DEFAULT_THEME,

    # Per-feature sensitivity sliders (settings popup, "Telemetry" tab).
    'daily_screen_time': 5.0,
    'deep_work_hours': 5.0,
    'doomscrolling_duration': 5.0,
    'app_switch_frequency': 5.0,

    # Last dragged position of the floating HUD. -1 means "not set yet",
    # so the HUD falls back to its default corner position.
    'pos_x': -1,
    'pos_y': -1,

    # Facial tracking is OFF by default. The webcam is only ever opened
    # while this is True - see facial_tracker.py.
    'facial_tracking_enabled': False,

    # Fallback multiplier used when facial tracking is on but the webcam
    # (or the face-detection model) isn't actually available.
    'manual_facial_multiplier': 1.0
}

MODEL_PATH = "halt_model.pkl"
SETTINGS_FILE = "settings.txt"

# Color themes used to tint the HUD ring as the score climbs from
# low -> mid -> high.
THEMES = {
    'Neon Violet': {'low': (60, 215, 120), 'mid': (230, 190, 90), 'high': (240, 110, 120)},
    'Cyberpunk Cyan': {'low': (0, 220, 255), 'mid': (255, 230, 0), 'high': (255, 40, 130)},
    'Solar Amber': {'low': (100, 220, 100), 'mid': (255, 165, 0), 'high': (255, 60, 60)},
    'Matrix Green': {'low': (50, 255, 50), 'mid': (150, 255, 50), 'high': (255, 50, 50)}
}


def _parse_setting_value(key, raw_value):
    # Converts the raw text from settings.txt into the right type for a
    # given key. Returns None if the value can't be parsed, so the caller
    # can skip it instead of crashing on a corrupted settings file.
    try:
        if key in ('hud_size', 'pos_x', 'pos_y'):
            return int(raw_value)
        if key == 'theme_preset':
            return str(raw_value)
        if key == 'facial_tracking_enabled':
            return raw_value.lower() == 'true'
        return float(raw_value)
    except ValueError:
        return None


def load_settings():
    # If there's no settings file yet, write out the defaults and stop -
    # there's nothing to load.
    if not os.path.exists(SETTINGS_FILE):
        save_settings()
        return

    try:
        with open(SETTINGS_FILE, "r") as settings_file:
            lines = settings_file.readlines()
    except Exception as error:
        print(f"Error reading settings: {error}")
        return

    # Each line looks like "key=value". Unknown keys and malformed lines
    # are skipped rather than crashing the app.
    for line in lines:
        if "=" not in line:
            continue

        key, raw_value = line.strip().split("=", 1)

        if key not in USER_CONFIG:
            continue

        parsed_value = _parse_setting_value(key, raw_value)

        if parsed_value is None:
            print(f"Skipping malformed setting: {line.strip()!r}")
            continue

        USER_CONFIG[key] = parsed_value


def save_settings():
    # Writes every key/value pair in USER_CONFIG out to disk, one per line.
    try:
        with open(SETTINGS_FILE, "w") as settings_file:
            for key, value in USER_CONFIG.items():
                settings_file.write(f"{key}={value}\n")
    except Exception as error:
        print(f"Error writing settings: {error}")
