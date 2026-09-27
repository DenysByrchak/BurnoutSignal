import cv2
import threading
import time
from config import USER_CONFIG


class FacialExpressionTracker:
    """
    Watches the webcam and turns face presence into a multiplier that the
    burnout agent uses to nudge its score up or down a little.

    Important behavior:
      - The webcam is only opened while facial tracking is switched ON in
        settings. If it's off, the camera stays off (no light, no capture).
      - If the AI part fails for any reason (no webcam, or a broken OpenCV
        install missing the face-detection classes), we don't crash. We
        just fall back to the manual multiplier the user set in settings.
    """

    def __init__(self):
        # Multiplier the agent reads. 1.0 means "no effect".
        self.multiplier = 1.0

        # Thread bookkeeping.
        self._running = False
        self._thread = None

        # Camera / detector state. These start out empty and only get
        # filled in once facial tracking is actually turned on.
        self.camera_available = False
        self._capture = None
        self._face_detector = None
        self._cascade_load_failed = False

    def start(self):
        # Guard against starting a second background thread by accident.
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self._thread.start()

    def stop(self):
        # Ask the loop to stop, wait a moment for it to notice, then make
        # sure the webcam is definitely released.
        self._running = False

        if self._thread is not None:
            self._thread.join(timeout=1.0)

        self._release_camera()

    def _load_face_detector(self):
        # Build the Haar cascade classifier once. This is wrapped in a
        # try/except on purpose: on some machines, having both
        # opencv-python and opencv-python-headless (or opencv-contrib-python)
        # installed at the same time breaks the install in a way where
        # `import cv2` still works but `cv2.CascadeClassifier` is missing.
        # If that happens here, we log it once and fall back to the manual
        # multiplier instead of crashing the whole tracking thread.
        if self._face_detector is not None or self._cascade_load_failed:
            return

        try:
            cascade_file = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            detector = cv2.CascadeClassifier(cascade_file)

            if detector.empty():
                raise RuntimeError("cascade file loaded but classifier came back empty")

            self._face_detector = detector

        except Exception as error:
            print(f"Facial Tracker: could not set up face detection ({error}).")
            print("Facial Tracker: check for conflicting opencv packages "
                  "(e.g. opencv-python + opencv-python-headless installed together).")
            print("Facial Tracker: using the manual expression multiplier instead.")
            self._cascade_load_failed = True

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
        # This runs for the whole life of the app, but it only touches the
        # camera while facial_tracking_enabled is True in settings.
        while self._running:
            tracking_is_on = USER_CONFIG.get("facial_tracking_enabled", False)

            if not tracking_is_on:
                # Feature is off right now. Make sure the camera is off too.
                self._release_camera()
                time.sleep(1.0)
                continue

            # Feature is on. Make sure we have a camera and a detector
            # ready before we try to read a frame.
            self._open_camera()
            self._load_face_detector()

            if not self.camera_available or self._face_detector is None:
                # Nothing usable yet, try again in a bit.
                time.sleep(1.0)
                continue

            self._update_multiplier_from_camera()
            time.sleep(2.0)  # Poll every 2 seconds to save CPU.

        # Loop is exiting because _running was set to False.
        self._release_camera()

    def _update_multiplier_from_camera(self):
        # Grab a single frame and look for a face in it.
        was_read, frame = self._capture.read()

        if not was_read:
            return

        gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        detected_faces = self._face_detector.detectMultiScale(
            gray_frame, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )

        # Heuristic for the demo: a visible, stable face suggests the user
        # is sitting and focused, so we nudge the multiplier down a bit.
        # No face suggests they stepped away or looked off-screen, so we
        # nudge it up.
        if len(detected_faces) > 0:
            print("Focused")
            self.multiplier = 0.85
        else:
            print("Unfocused")
            self.multiplier = 1.20

    def get_multiplier(self):
        # Tracking is off entirely -> don't affect the score at all.
        if not USER_CONFIG.get("facial_tracking_enabled", False):
            return 1.0

        # We have a live camera reading available -> trust it.
        if self.camera_available and self._face_detector is not None:
            return self.multiplier

        # No working camera or detector right now (unplugged webcam, or
        # the cascade classifier failed to load) -> fall back to whatever
        # the user set manually in the settings popup.
        return USER_CONFIG.get("manual_facial_multiplier", 1.0)
