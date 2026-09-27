# Burnout Signal

Burnout Signal is a desktop telemetry tracker and floating HUD designed to monitor cognitive fatigue and prevent digital burnout. Built with Python, PyQt6, and XGBoost, the application runs seamlessly in the background to analyze your workflow context and facial focus, displaying a real-time burnout risk score. 

When your fatigue score reaches critical levels, the app triggers a full-screen, semi-transparent intervention overlay to force a cognitive reset.

## Features

* **Machine Learning Core:** Uses an XGBoost regression model trained on behavioral telemetry to predict burnout risk on a clean 0–100 scale.
* **Context-Aware Window Tracking:** Uses the Windows API (`pywin32`) to classify active applications into "Deep Work" or "Distractions" (Doomscrolling), tracking application switch frequency and total screen time.
* **Facial Focus Tracking:** Integrates OpenCV to monitor user presence and focus. If the user is focused, the fatigue multiplier slows down; if distracted or away, it accelerates.
* **Customizable Floating HUD:** A frameless, draggable UI widget with custom SVG neon rendering. It automatically saves its position and supports multiple color themes (Neon Violet, Cyberpunk Cyan, Solar Amber, Matrix Green).
* **Live Configuration:** Dynamically adjust tracking multipliers, HUD size, and themes via custom-styled PyQt6 popup menus. Settings are persistently saved to `settings.txt`.
* **Intervention Overlay:** A full-screen darkening effect with a glowing central card that temporarily locks focus when the burnout score hits 100.

## Project Structure

The codebase is modularized for clean architecture and easy extension:

* **`main.py`**: The master controller. Handles the floating HUD widget, SVG rendering, window dragging, and the right-click context menu.
* **`agent.py`**: The background `QThread`. Manages the OS window tracking loop, calculates feature states, and runs XGBoost model inference without blocking the UI.
* **`facial_tracker.py`**: The OpenCV webcam loop. Runs on a separate thread to detect user presence and calculate the dynamic focus multiplier.
* **`ui_components.py`**: Houses the custom-styled PyQt6 interfaces, including the Telemetry Settings, Customization menu, and the Full-Screen Intervention Overlay.
* **`config.py`**: Centralized configuration and state management. Handles parsing and saving user preferences to `settings.txt`.
* **`train.py`**: The machine learning script used to train the XGBoost model (`halt_model.pkl`) and calculate the bounds for continuous 0–100 scaling.

## Requirements

* **Python 3.12+**
* Windows OS (due to `pywin32` dependencies for active window tracking)
* A webcam (optional, for facial expression tracking)

Install dependencies via pip:
```bash
pip install -r requirements.txt
