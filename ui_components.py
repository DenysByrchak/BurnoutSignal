import functools
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QPushButton,
                             QFormLayout, QDoubleSpinBox, QSpinBox,
                             QComboBox, QHBoxLayout, QFrame, QCheckBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor
from config import USER_CONFIG, THEMES, save_settings


class TelemetrySettingsPopup(QWidget):
    """
    Popup where the user tunes how sensitive the score is to each tracked
    signal, and turns facial tracking on/off.
    """

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(315, 360)

        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame#MainContainer {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #252244, stop:1 #1a1733);
                border: 1px solid #48417c;
                border-radius: 12px;
            }
            QLabel {
                color: #d1cbdc; font-family: Helvetica, sans-serif;
                font-size: 12px; font-weight: bold; background: transparent;
            }
            QDoubleSpinBox {
                background-color: rgba(0, 0, 0, 0.4); color: #ffffff;
                border: 1px solid #48417c; border-radius: 4px; padding: 4px; font-weight: bold;
            }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; border: none; }
            QCheckBox { color: #d1cbdc; font-family: Helvetica, sans-serif; font-size: 12px; font-weight: bold; }
            QPushButton.step-btn {
                background-color: rgba(80, 75, 130, 100); color: white; font-weight: bold;
                border: 1px solid #48417c; border-radius: 4px;
                min-width: 25px; max-width: 25px; min-height: 25px; max-height: 25px;
            }
            QPushButton.step-btn:hover { background-color: rgba(110, 105, 170, 200); }
            QPushButton.action-btn {
                background-color: transparent; color: #d1cbdc; font-family: Helvetica, sans-serif;
                font-size: 13px; font-weight: bold; border: 1px solid #48417c; border-radius: 6px; padding: 8px 15px;
            }
            QPushButton.action-btn:hover { background-color: rgba(90, 85, 150, 150); }
        """)
        self.container.setObjectName("MainContainer")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        title = QLabel("Telemetry & Expression Settings")
        title.setStyleSheet("color: #7ef59b; margin-bottom: 5px; font-size: 14px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        form_layout = QFormLayout()
        form_layout.setSpacing(6)

        # Keeps track of the spinbox for each setting key, so save_and_close
        # can read them back out later.
        self.inputs = {}

        # Turns the webcam-based facial tracking on/off. The webcam is only
        # ever opened while this box is checked - see facial_tracker.py.
        self.facial_checkbox = QCheckBox("Enable Facial AI Tracking")
        self.facial_checkbox.setChecked(USER_CONFIG.get('facial_tracking_enabled', False))
        form_layout.addRow(self.facial_checkbox)

        note_label = QLabel(
            "Expression Mult. is a fallback used only if the\n"
            "webcam or face detection isn't available."
        )
        note_label.setStyleSheet("color: #9a93b0; font-size: 10px; font-weight: normal;")
        form_layout.addRow(note_label)

        labels = {
            'daily_screen_time': "Screen Time (x):",
            'deep_work_hours': "Deep Work (x):",
            'doomscrolling_duration': "Distractions (x):",
            'app_switch_frequency': "App Switches (x):",
            'manual_facial_multiplier': "Expression Mult:"
        }

        for key, display_name in labels.items():
            self._add_spinbox_row(form_layout, key, display_name)

        layout.addLayout(form_layout)

        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("class", "action-btn")
        cancel_btn.clicked.connect(self.close)

        save_btn = QPushButton("Save")
        save_btn.setProperty("class", "action-btn")
        save_btn.setStyleSheet("color: #7ef59b; border: 1px solid #7ef59b;")
        save_btn.clicked.connect(self.save_and_close)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _add_spinbox_row(self, form_layout, key, display_name):
        # Builds one "label | spinbox [-] [+]" row and wires up the step
        # buttons. Pulled out into its own method (instead of a lambda per
        # button) so each button calls a normal, debuggable method.
        spinbox = QDoubleSpinBox()
        spinbox.setRange(0.1, 5.0)
        spinbox.setSingleStep(0.1)
        spinbox.setValue(USER_CONFIG[key])
        spinbox.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)

        minus_btn = QPushButton("-")
        minus_btn.setProperty("class", "step-btn")
        minus_btn.clicked.connect(functools.partial(self._step_spinbox, spinbox, -0.1))

        plus_btn = QPushButton("+")
        plus_btn.setProperty("class", "step-btn")
        plus_btn.clicked.connect(functools.partial(self._step_spinbox, spinbox, 0.1))

        row_layout = QHBoxLayout()
        row_layout.addWidget(spinbox)
        row_layout.addWidget(minus_btn)
        row_layout.addWidget(plus_btn)

        self.inputs[key] = spinbox
        form_layout.addRow(display_name, row_layout)

    def _step_spinbox(self, spinbox, delta):
        # Nudges a spinbox up or down by delta, rounded to avoid floating
        # point noise like 0.7000000000000001.
        new_value = round(spinbox.value() + delta, 2)
        spinbox.setValue(new_value)

    def save_and_close(self):
        # Pull every value back out of the widgets and persist it.
        USER_CONFIG['facial_tracking_enabled'] = self.facial_checkbox.isChecked()

        for key, spinbox in self.inputs.items():
            USER_CONFIG[key] = spinbox.value()

        save_settings()
        self.close()


class CustomizePopup(QWidget):
    """Popup for changing how the floating HUD looks (size + color theme)."""

    def __init__(self, hud_reference):
        super().__init__()
        self.hud = hud_reference

        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(300, 200)

        self.container = QFrame(self)
        self.container.setStyleSheet("""
            QFrame#MainContainer {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #252244, stop:1 #1a1733);
                border: 1px solid #48417c;
                border-radius: 12px;
            }
            QLabel {
                color: #d1cbdc; font-family: Helvetica, sans-serif;
                font-size: 12px; font-weight: bold; background: transparent;
            }
            QSpinBox, QComboBox {
                background-color: rgba(0, 0, 0, 0.4); color: #ffffff;
                border: 1px solid #48417c; border-radius: 4px; padding: 4px; font-weight: bold;
            }
            QComboBox::drop-down { border: none; }
            QSpinBox::up-button, QSpinBox::down-button { width: 0px; border: none; }
            QPushButton.action-btn {
                background-color: transparent; color: #d1cbdc; font-family: Helvetica, sans-serif;
                font-size: 13px; font-weight: bold; border: 1px solid #48417c; border-radius: 6px; padding: 8px 15px;
            }
            QPushButton.action-btn:hover { background-color: rgba(90, 85, 150, 150); }
        """)
        self.container.setObjectName("MainContainer")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        title = QLabel("HUD Customization")
        title.setStyleSheet("color: #7ef59b; margin-bottom: 5px; font-size: 14px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        form_layout = QFormLayout()
        form_layout.setSpacing(8)

        self.size_spinbox = QSpinBox()
        self.size_spinbox.setRange(60, 250)
        self.size_spinbox.setValue(USER_CONFIG['hud_size'])
        form_layout.addRow("HUD Size (px):", self.size_spinbox)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(list(THEMES.keys()))
        self.theme_combo.setCurrentText(USER_CONFIG['theme_preset'])
        form_layout.addRow("Color Theme:", self.theme_combo)

        layout.addLayout(form_layout)

        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setProperty("class", "action-btn")
        cancel_btn.clicked.connect(self.close)

        save_btn = QPushButton("Save")
        save_btn.setProperty("class", "action-btn")
        save_btn.setStyleSheet("color: #7ef59b; border: 1px solid #7ef59b;")
        save_btn.clicked.connect(self.save_and_close)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def save_and_close(self):
        USER_CONFIG['hud_size'] = self.size_spinbox.value()
        USER_CONFIG['theme_preset'] = self.theme_combo.currentText()
        save_settings()

        if self.hud:
            self.hud.apply_dynamic_settings()

        self.close()


class InterventionWindow(QWidget):
    """Full-screen "take a break" overlay shown when the score hits 100."""

    def __init__(self, agent, close_callback):
        super().__init__()
        self.agent = agent
        self.close_callback = close_callback

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.container = QFrame(self)
        self.container.setFixedSize(500, 300)
        self.container.setStyleSheet("""
            QFrame#CardContainer {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #28244d, stop:1 #1a1733);
                border: 1px solid #5a5096;
                border-radius: 18px;
            }
            QLabel { font-family: Helvetica, sans-serif; background: transparent; }
            QPushButton {
                background-color: rgba(70, 65, 120, 100);
                color: #d1cbdc; font-family: Helvetica, sans-serif;
                font-size: 14px; font-weight: bold;
                border: 1px solid #5a5096; border-radius: 8px; padding: 12px 28px;
            }
            QPushButton:hover { background-color: rgba(90, 85, 150, 180); border-color: #7ef59b; color: #7ef59b; }
        """)
        self.container.setObjectName("CardContainer")

        card_layout = QVBoxLayout(self.container)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setContentsMargins(30, 30, 30, 30)
        card_layout.setSpacing(15)

        title = QLabel("BURNOUT SIGNAL ALERT")
        title.setStyleSheet("color: #f07182; font-size: 18pt; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("Elevated cognitive fatigue detected.\nTake a brief moment to reset.")
        subtitle.setStyleSheet("color: #b8b2c8; font-size: 11pt; line-height: 14px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn = QPushButton("Resume Workflow")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.close_ui)

        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        card_layout.addSpacing(15)
        card_layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        main_layout.addWidget(self.container)
        self.showFullScreen()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(12, 10, 18, 225))

    def close_ui(self):
        self.agent.reset_metrics()
        self.agent.is_paused = False
        self.close_callback()
        self.hide()
