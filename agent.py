import time
import win32gui
import joblib
import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal
from config import (POLLING_RATE_SECONDS, PRODUCTIVITY_APPS, DISTRACTION_APPS,
                    TIME_MULTIPLIER, USER_CONFIG, MODEL_PATH)
from facial_tracker import FacialExpressionTracker


class BurnoutSignalAgent(QThread):
    """
    Background thread that watches what window is focused, keeps a running
    tally of screen time / deep work / doomscrolling / app switching, feeds
    those numbers into the trained model, and emits a 0-100 burnout score.
    """

    # Signals the UI listens to.
    score_updated = pyqtSignal(float)
    trigger_alert = pyqtSignal()

    def __init__(self):
        super().__init__()

        # Load the trained model bundle (model + the info needed to turn
        # its raw output into a 0-100 score).
        bundle = joblib.load(MODEL_PATH)
        self.model = bundle['model']
        self.features = bundle['features']
        self.score_min = bundle['score_min']
        self.score_max = bundle['score_max']
        self.score_range = max(self.score_max - self.score_min, 1e-6)
        self.feature_bounds = bundle['feature_bounds']

        # The facial tracker runs its own background thread. It only turns
        # the webcam on once the user enables facial tracking in settings,
        # so it's safe to start it here even if the feature is off.
        self.facial_tracker = FacialExpressionTracker()
        self.facial_tracker.start()

        # Raw counters we build up over time from window-focus polling.
        self.total_time_logged = 0
        self.deep_work_time = 0
        self.doomscrolling_time = 0
        self.app_switches = 0
        self.last_app = ""

        # Current score shown on the HUD.
        self.current_score = 0.0

        # is_paused is set while the intervention popup is on screen, so we
        # stop accumulating time during a break.
        self.is_paused = False
        self._running = True

    def stop(self):
        # Called on app shutdown.
        self._running = False
        self.facial_tracker.stop()

    def get_active_window_title(self):
        # Ask Windows which window currently has focus, and read its title.
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return ""
            return win32gui.GetWindowText(hwnd)
        except Exception:
            return ""

    def reset_metrics(self):
        # Called after an intervention closes, so the next stretch of work
        # starts from a clean slate.
        self.total_time_logged = 0
        self.deep_work_time = 0
        self.doomscrolling_time = 0
        self.app_switches = 0
        self.current_score = 0.0
        self.score_updated.emit(self.current_score)

    def _clip(self, value, key):
        # Keeps a simulated feature value inside the range the model was
        # calibrated on, so a single wild reading can't send the score
        # somewhere the model was never trained to interpret.
        lower_bound, upper_bound = self.feature_bounds[key]
        return max(lower_bound, min(upper_bound, value))

    def _current_app_is_a_distraction(self, window_title):
        # Checks the focused window title against the configured list of
        # distraction apps (case-insensitive, partial match).
        window_title_lower = window_title.lower()
        for app_name in DISTRACTION_APPS:
            if app_name.lower() in window_title_lower:
                return True
        return False

    def _current_app_is_productive(self, window_title):
        # Same idea as above, but for the productivity app list.
        window_title_lower = window_title.lower()
        for app_name in PRODUCTIVITY_APPS:
            if app_name.lower() in window_title_lower:
                return True
        return False

    def _build_feature_row(self):
        # Converts the raw counters (seconds of real polling time) into the
        # simulated daily numbers the model expects, using TIME_MULTIPLIER
        # to compress "a few minutes of testing" into "a plausible day".
        # USER_CONFIG's per-feature sensitivity sliders scale each one
        # further, so the settings popup can make the score more or less
        # reactive.
        simulated_screen_time = ((self.total_time_logged * TIME_MULTIPLIER) / 3600) * USER_CONFIG['daily_screen_time']
        simulated_deep_work = ((self.deep_work_time * TIME_MULTIPLIER) / 3600) * USER_CONFIG['deep_work_hours']
        simulated_doomscrolling = ((self.doomscrolling_time * TIME_MULTIPLIER) / 3600) * USER_CONFIG['doomscrolling_duration']
        simulated_app_switches = (self.app_switches * (TIME_MULTIPLIER / 10)) * USER_CONFIG['app_switch_frequency']

        feature_row = pd.DataFrame([{
            'daily_screen_time': self._clip(simulated_screen_time, 'daily_screen_time'),
            'deep_work_hours': self._clip(simulated_deep_work, 'deep_work_hours'),
            'doomscrolling_duration': self._clip(simulated_doomscrolling, 'doomscrolling_duration'),
            'app_switch_frequency': self._clip(simulated_app_switches, 'app_switch_frequency'),
        }])

        # Make sure the columns are in the exact order the model was
        # trained on.
        return feature_row[self.features]

    def _score_from_model(self, feature_row):
        # Runs the model and rescales its raw output into a 0-100 score
        # using the calibration anchors saved alongside the model.
        raw_score = self.model.predict(feature_row)[0]
        normalized_score = (raw_score - self.score_min) / self.score_range
        return max(0.0, min(100.0, normalized_score * 100.0))

    def run(self):
        # Main polling loop. Runs on its own thread for the life of the app.
        print("Burnout Signal Tracker Started...")

        while self._running:
            time.sleep(POLLING_RATE_SECONDS)

            if self.is_paused:
                # An intervention is showing right now, don't accumulate time.
                continue

            # The facial tracker gives back a multiplier: below 1.0 if the
            # webcam sees a focused face, above 1.0 if it doesn't (or 1.0
            # if the feature is off / unavailable).
            facial_multiplier = self.facial_tracker.get_multiplier()
            effective_poll_time = POLLING_RATE_SECONDS * facial_multiplier

            self.total_time_logged += effective_poll_time
            current_window_title = self.get_active_window_title()

            # Track how often the focused window actually changes.
            if current_window_title != self.last_app and current_window_title != "":
                self.app_switches += 1
                self.last_app = current_window_title

            # Bucket the current window into productive / distracting time.
            if self._current_app_is_a_distraction(current_window_title):
                self.doomscrolling_time += effective_poll_time
            elif self._current_app_is_productive(current_window_title):
                self.deep_work_time += effective_poll_time

            feature_row = self._build_feature_row()

            try:
                self.current_score = self._score_from_model(feature_row)
                self.score_updated.emit(self.current_score)

                if self.current_score >= 100:
                    self.trigger_alert.emit()

            except Exception as error:
                print(f"Prediction error: {error}")
