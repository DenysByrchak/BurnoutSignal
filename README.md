# Burnout Signal

Burnout Signal is a desktop telemetry tracker and floating HUD that monitors cognitive fatigue and helps prevent digital burnout. Built with Python, PyQt6, and XGBoost, it runs in the background, analyzes your workflow and facial expression, and shows a real-time burnout risk score.

When the score reaches critical levels, the app triggers a full-screen intervention overlay to force a cognitive reset.

## Features

* **Machine Learning Core:** An XGBoost regression model predicts burnout risk on a 0-100 scale, calibrated so the score can actually reach both ends of that range.
* **Context-Aware Window Tracking:** Uses `pywin32` to classify active windows as "Deep Work" or "Distractions," tracking app switch frequency and total screen time.
* **Facial Expression Tracking:** Uses MediaPipe's Face Landmarker to read brow tension, smiling, closed eyes, and yawning from the webcam, then nudges the fatigue score up (tense, drowsy, yawning) or down (relaxed, smiling). Off by default. The webcam only opens once you enable it in settings. Falls back to a manual multiplier if the webcam or model isn't available.
* **Customizable Floating HUD:** A frameless, draggable widget with SVG neon rendering. Every 5 seconds it alternates between the numeric score and a short keyboard-character mood readout (`o_o` looking, `:D` smiling, `-_-` eyes closed, `zzz` tired). Saves its position automatically and supports multiple color themes (Neon Violet, Cyberpunk Cyan, Solar Amber, Matrix Green).
* **Live Configuration:** Adjust tracking multipliers, toggle facial tracking, and change HUD size or theme through PyQt6 popup menus. Settings persist to `settings.txt`.
* **Intervention Overlay:** A full-screen darkening effect with a glowing card that locks focus when the score hits 100.

## Project Structure

* **`main.py`**: The HUD widget, SVG ring rendering, score/mood toggle, dragging, and the right-click menu.
* **`agent.py`**: Background `QThread` that runs the window tracking loop, builds features, and runs model inference.
* **`facial_tracker.py`**: Background thread that owns the webcam and MediaPipe's Face Landmarker. Produces the fatigue multiplier and the mood label the HUD shows.
* **`ui_components.py`**: The Telemetry Settings, Customization menu, and Intervention Overlay popups.
* **`config.py`**: Configuration and settings persistence (`settings.txt`).
* **`train_model.py`**: Trains the XGBoost model and calibrates it, exporting `halt_model.pkl`.

## Requirements

* Python 3.12+
* Windows OS (for `pywin32` window tracking)
* A webcam (optional, off by default)
* An internet connection the first time facial tracking is enabled, to download MediaPipe's face landmark model (cached afterward)

Install dependencies:
```bash
pip install -r requirements.txt
```

Dependencies are pinned to exact versions. Both OpenCV and MediaPipe have shipped breaking changes between minor versions, so re-test webcam capture and app shutdown before bumping either.
