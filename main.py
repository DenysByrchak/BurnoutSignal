import sys
import functools
from PyQt6.QtWidgets import QApplication, QWidget, QMenu
from PyQt6.QtCore import Qt, QRectF, QTimer
from PyQt6.QtGui import QPainter, QColor, QFont
from PyQt6.QtSvg import QSvgRenderer

from config import load_settings, save_settings, USER_CONFIG, THEMES, POLLING_RATE_SECONDS
from agent import BurnoutSignalAgent
from ui_components import TelemetrySettingsPopup, CustomizePopup, InterventionWindow

# How often the HUD flips between showing the numeric score and an emote,
# in milliseconds. Every time this fires we flip a boolean, so the actual
# on-screen cadence is "5 seconds of score, then 5 seconds of emote".
EMOTE_SWITCH_INTERVAL_MS = 5000

# Maps FacialExpressionTracker.expression_label -> what the HUD draws.
# Plain keyboard characters instead of emoji, so it renders consistently
# with any font (no need to hunt for a color-emoji font like Segoe UI
# Emoji). "looking" is also the fallback for any label we don't recognize.
EXPRESSION_TEXT = {
    "looking": "o_o",
    "smiling": ":D",
    "eyes_closed": "-_-",
    "tired": "zzz",
}


class FloatingHUD(QWidget):
    """
    The small always-on-top circular widget that shows the current burnout
    score. It also owns the right-click menu for settings/customize/quit.
    """

    def __init__(self, agent):
        super().__init__()
        self.agent = agent
        self.score = 0.0

        # Kept as attributes (rather than created fresh each time) so the
        # popups don't get rebuilt - and lose their state - every time
        # they're opened.
        self.intervention = None
        self.settings_popup = None
        self.customize_popup = None

        # Used while the user is dragging the HUD around the screen.
        self.drag_position = None

        # Whether the ring is currently showing an emote instead of the
        # numeric score. Flipped every EMOTE_SWITCH_INTERVAL_MS by
        # emote_timer below.
        self.showing_emote = False

        self.agent.score_updated.connect(self.update_score)
        self.agent.trigger_alert.connect(self.trigger_ui)

        # Periodically flips between the score and an emote. Reads
        # self.agent.facial_tracker directly rather than over a Qt signal -
        # it's just a plain string being read for display, so a little bit
        # of staleness between the tracker's own 2-second poll and this
        # 5-second flip doesn't matter.
        self.emote_timer = QTimer(self)
        self.emote_timer.setInterval(EMOTE_SWITCH_INTERVAL_MS)
        self.emote_timer.timeout.connect(self._toggle_emote_display)
        self.emote_timer.start()

        self.initUI()

    def initUI(self):
        # Frameless, always-on-top, click-through-safe circular widget.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.apply_dynamic_settings()

    def apply_dynamic_settings(self):
        # Called on startup and whenever the customize popup saves changes.
        size = USER_CONFIG['hud_size']
        self.resize(size, size)

        screen = QApplication.primaryScreen().availableGeometry()

        if USER_CONFIG['pos_x'] != -1 and USER_CONFIG['pos_y'] != -1:
            # User has dragged the HUD before - remember where they left it.
            self.move(USER_CONFIG['pos_x'], USER_CONFIG['pos_y'])
        else:
            # First run - park it in the bottom-left corner.
            x_pos = 25
            y_pos = screen.height() - size - 65
            self.move(x_pos, y_pos)

        self.update()

    def update_score(self, new_score):
        # Slot connected to the agent's score_updated signal.
        self.score = new_score
        self.update()

    def _toggle_emote_display(self):
        # Only bother switching to an emote if facial tracking is actually
        # producing live readings right now. Otherwise there's nothing real
        # to show, so just keep the numeric score up.
        facial_tracker = self.agent.facial_tracker

        if not facial_tracker.camera_available:
            self.showing_emote = False
        else:
            self.showing_emote = not self.showing_emote

        self.update()

    def _current_display_text(self):
        # What the center of the ring should show right now: the score, or
        # an emote for whatever the facial tracker is currently seeing.
        if not self.showing_emote:
            return f"{int(self.score)}"

        expression_label = self.agent.facial_tracker.expression_label
        return EXPRESSION_TEXT.get(expression_label, EXPRESSION_TEXT["looking"])

    def trigger_ui(self):
        # Slot connected to the agent's trigger_alert signal (score hit 100).
        if not self.agent.is_paused:
            self.agent.is_paused = True

            if not self.intervention:
                self.intervention = InterventionWindow(self.agent, self.intervention_closed)
            else:
                self.intervention.showFullScreen()

    def intervention_closed(self):
        # Placeholder hook in case something needs to run right when the
        # intervention window closes.
        pass

    def open_settings(self, pos):
        # Lazily create the popup once, then just reposition/show it.
        if not self.settings_popup:
            self.settings_popup = TelemetrySettingsPopup()

        self._show_popup_near(self.settings_popup, pos, width=315, height=290)

    def open_customize(self, pos):
        if not self.customize_popup:
            self.customize_popup = CustomizePopup(self)

        self._show_popup_near(self.customize_popup, pos, width=300, height=200)

    def _show_popup_near(self, popup, pos, width, height):
        # Positions a popup near the given point, nudging it back on-screen
        # if it would otherwise spill off the right or bottom edge.
        screen = QApplication.primaryScreen().availableGeometry()
        x, y = pos.x(), pos.y()

        if x + width > screen.right():
            x = screen.right() - width

        if y + height > screen.bottom():
            y = screen.bottom() - height

        popup.move(x, y)
        popup.show()
        popup.activateWindow()

    def get_neon_color(self):
        # Blends between the theme's low/mid/high colors based on the
        # current score, so the ring color shifts smoothly as burnout risk
        # climbs instead of jumping between fixed colors.
        theme_name = USER_CONFIG.get('theme_preset', 'Neon Violet')
        palette = THEMES.get(theme_name, THEMES['Neon Violet'])

        score = max(0.0, min(100.0, self.score))

        if score <= 50:
            percent = score / 50.0
            start_color, end_color = palette['low'], palette['mid']
        else:
            percent = (score - 50.0) / 50.0
            start_color, end_color = palette['mid'], palette['high']

        red = int(start_color[0] + (end_color[0] - start_color[0]) * percent)
        green = int(start_color[1] + (end_color[1] - start_color[1]) * percent)
        blue = int(start_color[2] + (end_color[2] - start_color[2]) * percent)

        return f"#{red:02x}{green:02x}{blue:02x}"

    def paintEvent(self, event):
        # Draws the glowing ring (as SVG) plus the score number on top.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hex_color = self.get_neon_color()

        svg_str = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="400" height="400">
          <defs>
            <filter id="neon-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur1"/>
              <feGaussianBlur in="SourceGraphic" stdDeviation="12" result="blur2"/>
              <feMerge>
                <feMergeNode in="blur2"/>
                <feMergeNode in="blur1"/>
                <feMergeNode in="SourceGraphic"/>
              </feMerge>
            </filter>
          </defs>
          <circle cx="200" cy="200" r="140" fill="#000"/>
          <circle cx="200" cy="200" r="150" fill="none" stroke="{hex_color}" stroke-width="16" filter="url(#neon-glow)"/>
        </svg>"""

        renderer = QSvgRenderer(svg_str.encode('utf-8'))
        renderer.render(painter, QRectF(self.rect()))

        font_size = max(10, int(self.width() * 0.2))
        display_text = self._current_display_text()

        painter.setPen(QColor("#e8e4f0"))

        if self.showing_emote:
            # Text like "-_-" or "o_o" runs wider than a couple of digits
            # at the same point size, so it gets a smaller size to keep it
            # from crowding the edges of the ring.
            font = QFont("Helvetica", int(font_size * 0.7), QFont.Weight.Bold)
        else:
            font = QFont("Helvetica", font_size, QFont.Weight.Bold)

        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, display_text)

    def mousePressEvent(self, event):
        # Start of a drag - remember the offset between the click point and
        # the widget's top-left corner.
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        # While dragging, keep the widget under the cursor at the same offset.
        if event.buttons() == Qt.MouseButton.LeftButton and self.drag_position:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        # End of a drag - remember the new position so it survives a restart.
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = None
            USER_CONFIG['pos_x'] = self.x()
            USER_CONFIG['pos_y'] = self.y()
            save_settings()
            event.accept()

    def contextMenuEvent(self, event):
        # Right-click menu: Settings / Customize / Force Test Break / Quit.
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setWindowFlags(
            menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)

        menu.setStyleSheet("""
            QMenu {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #28244d, stop:1 #1a1733);
                color: #d1cbdc; font-family: Helvetica, sans-serif;
                font-size: 14px; font-weight: bold; padding: 10px;
                border: 1px solid #48417c; border-radius: 12px; min-width: 180px;
            }
            QMenu::item { padding: 12px 25px; background-color: transparent; border-radius: 6px; margin: 2px 5px; }
            QMenu::item:selected { background-color: rgba(90, 85, 150, 150); }
            QMenu::separator { height: 1px; background: #48417c; margin: 8px 15px; }
        """)

        settings_action = menu.addAction("Settings")
        customize_action = menu.addAction("Customize")
        test_action = menu.addAction("Force Test Break")
        menu.addSeparator()
        quit_action = menu.addAction("Quit Burnout Signal")

        global_pos = self.mapToGlobal(event.pos())
        action = menu.exec(global_pos)

        if action == settings_action:
            self.open_settings(global_pos)
        elif action == customize_action:
            self.open_customize(global_pos)
        elif action == test_action:
            self.trigger_ui()
        elif action == quit_action:
            QApplication.quit()


def shutdown_agent(agent):
    # Gives the agent thread a chance to stop cleanly (which also releases
    # the webcam via the facial tracker) before the app exits.
    agent.stop()
    agent.wait(POLLING_RATE_SECONDS * 1000 + 500)


if __name__ == "__main__":
    load_settings()

    app = QApplication(sys.argv)
    agent = BurnoutSignalAgent()
    agent.start()

    hud = FloatingHUD(agent)
    hud.show()

    app.aboutToQuit.connect(functools.partial(shutdown_agent, agent))

    sys.exit(app.exec())