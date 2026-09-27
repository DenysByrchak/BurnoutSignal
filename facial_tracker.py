import os
import time
import threading
from urllib.request import urlretrieve

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

from config import USER_CONFIG

# MediaPipe's face landmark model is a small (a few MB) pre-trained model
# file, not something we train ourselves. It ships "blendshape" scores -
# 0 to 1 numbers describing things like how raised an eyebrow is or how
# wide a mouth is smiling - which is really just geometry measured off the
# detected face mesh. We download it once and cache it next to the script.
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/latest/face_landmarker.task")
MODEL_PATH = "face_landmarker.task"

# Blendshape score thresholds used to turn raw numbers into yes/no reads.
# These are deliberately simple and easy to tune by hand.
BROW_TENSION_THRESHOLD = 0.4
SMILE_THRESHOLD = 0.3
RELAXED_BROW_THRESHOLD = 0.2
EYES_CLOSED_THRESHOLD = 0.5
YAWN_THRESHOLD = 0.5

MIN_MULTIPLIER = 0.7
MAX_MULTIPLIER = 1.5


class FacialExpressionTracker:
    """
    Watches the webcam and turns facial expression into a multiplier that
    the burnout agent uses to nudge its score up or down a little.

    How the expression reading works:
      - MediaPipe's Face Landmarker returns "blendshape" scores for the
        current frame: numbers describing brow position, mouth shape, eye
        openness, and so on. These come straight from the geometry of the
        detected face mesh, not from a trained "happy/sad/angry" emotion
        classifier.
      - We combine a handful of those scores ourselves (furrowed brow,
        smiling, closed eyes, open mouth) into one simple multiplier, using
        plain threshold rules instead of a black-box model.
      - The same scores also produce a one-word `expression_label`
        ("looking" / "smiling" / "eyes_closed" / "tired") that the HUD uses
        to occasionally show an emote instead of the numeric score.

    Other behavior:
      - The webcam is only opened while facial tracking is switched ON in
        settings. If it's off, the camera stays off (no light, no capture).
      - If anything about the model, its download, or the camera fails, we
        don't crash - we fall back to the manual multiplier from settings.
    """

    def __init__(self):
        # Multiplier the agent reads. 1.0 means "no effect".
        self.multiplier = 1.0

        # One-word summary of what the camera is seeing right now, for the
        # HUD to show as an emote. One of: "looking", "smiling",
        # "eyes_closed", "tired". The HUD (main.py) owns the actual emoji
        # each of these maps to - this class just reports what it sees.
        self.expression_label = "looking"

        # Thread bookkeeping.
        self._running = False
        self._thread = None

        # Camera / model state. These start out empty and only get filled
        # in once facial tracking is actually turned on.
        self.camera_available = False
        self._capture = None
        self._landmarker = None
        self._model_load_failed = False

    def start(self):
        # Guard against starting a second background thread by accident.
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self._thread.start()

    def stop(self):
        # Ask the loop to stop, then WAIT for it to actually finish.
        #
        # The tracking thread is the only thing allowed to touch the camera
        # and the MediaPipe model - it's the thread that created them, and
        # it may be in the middle of a detect() call right now. If we (the
        # caller, usually the main thread) closed those resources ourselves
        # here instead of waiting, we could free them out from under the
        # tracking thread while it's still using them. MediaPipe's native
        # code doesn't fail gracefully when that happens - it crashes the
        # whole process with an access violation. So: just wait.
        self._running = False

        if self._thread is None:
            return

        self._thread.join(timeout=5.0)

        if self._thread.is_alive():
            # Extremely unlikely (one loop iteration is a couple of seconds
            # at most) but if it ever happens, don't force-close resources
            # from here - that's the exact race that used to crash the app.
            print("Facial Tracker: background thread is taking longer than "
                  "expected to shut down.")

    def _ensure_model_downloaded(self):
        # The model file only needs to be fetched once, the first time the
        # app runs on a given machine. After that it's just read from disk.
        if os.path.exists(MODEL_PATH):
            return True

        try:
            print("Facial Tracker: downloading face landmark model (one-time, a few MB)...")
            urlretrieve(MODEL_URL, MODEL_PATH)
            print("Facial Tracker: model downloaded.")
            return True
        except Exception as error:
            print(f"Facial Tracker: could not download the face landmark model ({error}).")
            return False

    def _load_landmarker(self):
        # Build the Face Landmarker once. Wrapped in a try/except so a
        # missing model file, a bad download, or a broken mediapipe install
        # falls back to the manual multiplier instead of crashing the
        # tracking thread.
        if self._landmarker is not None or self._model_load_failed:
            return

        if not self._ensure_model_downloaded():
            print("Facial Tracker: using the manual expression multiplier instead.")
            self._model_load_failed = True
            return

        try:
            options = mp_vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
                running_mode=mp_vision.RunningMode.IMAGE,
                num_faces=1,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=False,
            )
            self._landmarker = mp_vision.FaceLandmarker.create_from_options(options)
        except Exception as error:
            print(f"Facial Tracker: could not set up the face landmark model ({error}).")
            print("Facial Tracker: using the manual expression multiplier instead.")
            self._model_load_failed = True

    def _release_landmarker(self):
        if self._landmarker is not None:
            self._landmarker.close()
        self._landmarker = None

    def _open_camera(self):
        # Only open the webcam if it isn't already open.
        if self._capture is not None:
            return

        capture = cv2.VideoCapture(0)

        if not capture.isOpened():
            print("Facial Tracker: no webcam detected.")
            self.camera_available = False
            self._capture = None
            return

        self._capture = capture
        self.camera_available = True

    def _release_camera(self):
        # Turn the camera off. This runs whenever tracking is disabled and
        # when the whole tracker shuts down, so the webcam light doesn't
        # stay on for no reason.
        if self._capture is not None:
            self._capture.release()

        self._capture = None
        self.camera_available = False

    def _tracking_loop(self):
        # Runs for the whole life of the app, but only touches the camera
        # and the model while facial_tracking_enabled is True in settings.
        #
        # The try/finally guarantees the camera and the model get released
        # on THIS thread - the one that created and used them - no matter
        # how the loop ends (normal shutdown, or an unexpected error). That
        # keeps cleanup single-threaded and avoids the close()-from-another-
        # thread race that used to crash the app on exit.
        try:
            while self._running:
                tracking_is_on = USER_CONFIG.get("facial_tracking_enabled", False)

                if not tracking_is_on:
                    self._release_camera()
                    self.expression_label = "looking"
                    time.sleep(1.0)
                    continue

                self._open_camera()
                self._load_landmarker()

                if not self.camera_available or self._landmarker is None:
                    # Nothing usable yet, try again in a bit.
                    time.sleep(1.0)
                    continue

                self._update_multiplier_from_camera()
                time.sleep(2.0)  # Poll every 2 seconds to save CPU.
        finally:
            self._release_camera()
            self._release_landmarker()

    def _update_multiplier_from_camera(self):
        # Grab a single frame and run the face landmark model on it.
        was_read, frame = self._capture.read()

        if not was_read:
            return

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        result = self._landmarker.detect(mp_image)

        if not result.face_blendshapes:
            # No face in the frame right now - treat it like looking away.
            self.multiplier = 1.20
            self.expression_label = "looking"
            return

        # face_blendshapes[0] is the list of scores for the first (only)
        # face we asked for. Turn it into a simple name -> score lookup.
        blendshape_scores = {}
        for shape in result.face_blendshapes[0]:
            blendshape_scores[shape.category_name] = shape.score

        self.multiplier = self._multiplier_from_blendshapes(blendshape_scores)
        self.expression_label = self._expression_label_from_blendshapes(blendshape_scores)

    def _multiplier_from_blendshapes(self, scores):
        # Pull out the handful of blendshape scores we care about, each
        # ranging from 0 (not happening at all) to 1 (fully happening).
        brow_tension = (scores.get('browDownLeft', 0.0) + scores.get('browDownRight', 0.0)) / 2
        smile = (scores.get('mouthSmileLeft', 0.0) + scores.get('mouthSmileRight', 0.0)) / 2
        eyes_closed = (scores.get('eyeBlinkLeft', 0.0) + scores.get('eyeBlinkRight', 0.0)) / 2
        yawning = scores.get('jawOpen', 0.0)

        multiplier = 1.0

        # A furrowed brow with no smile reads as tension or frustration.
        if brow_tension > BROW_TENSION_THRESHOLD and smile < RELAXED_BROW_THRESHOLD:
            multiplier += 0.15

        # Eyes mostly closed right when we happened to sample reads as
        # drowsy - a real blink is too quick to reliably catch on a
        # 2-second poll, so a "closed" reading here likely means more than
        # a blink.
        if eyes_closed > EYES_CLOSED_THRESHOLD:
            multiplier += 0.20

        # A wide open mouth reads as a yawn.
        if yawning > YAWN_THRESHOLD:
            multiplier += 0.15

        # A relaxed, smiling face with no brow tension nudges the other way.
        if smile > SMILE_THRESHOLD and brow_tension < RELAXED_BROW_THRESHOLD:
            multiplier -= 0.10

        return max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, multiplier))

    def _expression_label_from_blendshapes(self, scores):
        # Turns the same blendshape scores used for the multiplier into a
        # single label the HUD can show as an emote. Checked in this order
        # on purpose: a yawn is the clearest sign of being tired, even
        # though it also tends to squeeze the eyes shut for a moment.
        smile = (scores.get('mouthSmileLeft', 0.0) + scores.get('mouthSmileRight', 0.0)) / 2
        eyes_closed = (scores.get('eyeBlinkLeft', 0.0) + scores.get('eyeBlinkRight', 0.0)) / 2
        yawning = scores.get('jawOpen', 0.0)

        if yawning > YAWN_THRESHOLD:
            return "tired"

        if eyes_closed > EYES_CLOSED_THRESHOLD:
            return "eyes_closed"

        if smile > SMILE_THRESHOLD:
            return "smiling"

        return "looking"

    def get_multiplier(self):
        # Tracking is off entirely -> don't affect the score at all.
        if not USER_CONFIG.get("facial_tracking_enabled", False):
            return 1.0

        # We have a live camera + model reading available -> trust it.
        if self.camera_available and self._landmarker is not None:
            return self.multiplier

        # No working camera or model right now (unplugged webcam, model
        # download failed, etc.) -> fall back to whatever the user set
        # manually in the settings popup.
        return USER_CONFIG.get("manual_facial_multiplier", 1.0)
