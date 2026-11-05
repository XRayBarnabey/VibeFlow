"""VibeFlow visual identity: restrained dark palette and Qt stylesheet."""

from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QFontDatabase

COLORS = {
    "bg": "#0E1114",
    "panel": "#151A20",
    "panel_alt": "#1A2028",
    "panel_high": "#202832",
    "border": "#242C36",
    "border_soft": "#1C232C",
    "text": "#D9E0E8",
    "text_dim": "#8B96A5",
    "text_faint": "#5F6B7A",
    "accent": "#7FA7C9",
    "accent_bright": "#A6C8E4",
    "accent_deep": "#31506A",
    "danger": "#D97A7A",
    "success": "#6FBF8B",
    "warning": "#E0B15C",
    "roll": "#5FA8D3",
    "pitch": "#6FBF8B",
    "yaw": "#D3A15F",
}
DARK_COLORS = dict(COLORS)
LIGHT_COLORS = {
    "bg": "#F3F5F8",
    "panel": "#FFFFFF",
    "panel_alt": "#F2F5F9",
    "panel_high": "#E8EDF3",
    "border": "#D6DEE7",
    "border_soft": "#E3E8EF",
    "text": "#24303C",
    "text_dim": "#5F6E7E",
    "text_faint": "#7A8796",
    "accent": "#376E99",
    "accent_bright": "#2C5F86",
    "accent_deep": "#C7DBEC",
    "danger": "#B44747",
    "success": "#2E8B57",
    "warning": "#A97712",
    "roll": "#2F7DAB",
    "pitch": "#2E8B57",
    "yaw": "#B27A28",
}
_MODE = "dark"


def is_light() -> bool:
    return _MODE == "light"

AXIS_COLORS = (COLORS["roll"], COLORS["pitch"], COLORS["yaw"])

STYLESHEET = """
* {
    font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
    color: #D9E0E8;
}
QMainWindow, QWidget#Root {
    background-color: #0E1114;
}
QWidget {
    background-color: transparent;
}
QFrame#Header {
    background-color: #12161B;
    border-bottom: 1px solid #1F262F;
}
QFrame#Panel {
    background-color: #151A20;
    border: 1px solid #1F262F;
    border-radius: 6px;
}
QFrame#Card {
    background-color: #171D24;
    border: 1px solid #232B35;
    border-radius: 5px;
}
QFrame#Transport {
    background-color: #12161B;
    border-top: 1px solid #1F262F;
}
QLabel {
    background: transparent;
}
QLabel#Wordmark {
    font-size: 17px;
    font-weight: 600;
    letter-spacing: 1.2px;
    color: #E8EEF5;
}
QLabel#WordmarkAccent {
    font-size: 17px;
    font-weight: 600;
    letter-spacing: 1.2px;
    color: #7FA7C9;
}
QLabel#Tagline {
    font-size: 10px;
    letter-spacing: 1.6px;
    color: #5F6B7A;
}
QLabel#SectionTitle {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.4px;
    color: #7E8A99;
}
QLabel#Hint {
    color: #6F7B8B;
    font-size: 11px;
}
QLabel#StatusLabel {
    color: #7E8A99;
}
QFrame#HeaderSeparator {
    color: #242C36;
}
QLabel#Value {
    color: #A6C8E4;
    font-size: 11px;
    font-weight: 600;
}
QLabel#Timecode {
    color: #C9D3DE;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}
QLabel#TimecodeDim {
    color: #626E7D;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 11px;
}
QLabel#Error {
    color: #D97A7A;
}
QLabel#Warning {
    color: #E0B15C;
}
QLabel#Success {
    color: #6FBF8B;
}
QPushButton {
    background-color: #1B222B;
    border: 1px solid #2A333F;
    border-radius: 4px;
    padding: 6px 12px;
    color: #C9D3DE;
}
QPushButton:hover {
    background-color: #222B36;
    border-color: #384454;
}
QPushButton:pressed {
    background-color: #151B22;
}
QPushButton:disabled {
    color: #4C5664;
    border-color: #202730;
    background-color: #141920;
}
QPushButton#Primary {
    background-color: #2B455C;
    border: 1px solid #3D5D79;
    color: #E9F2FA;
    font-weight: 600;
}
QPushButton#Primary:hover {
    background-color: #33536E;
    border-color: #4C7294;
}
QPushButton#Ghost {
    background: transparent;
    border: 1px solid transparent;
    color: #8B96A5;
    padding: 4px 8px;
}
QPushButton#Ghost:hover {
    color: #D9E0E8;
    border-color: #2A333F;
}
QPushButton#Transport {
    background: transparent;
    border: none;
    color: #B7C3D0;
    padding: 0;
    font-size: 14px;
    min-width: 30px;
    min-height: 26px;
}
QPushButton#Transport:hover {
    color: #FFFFFF;
}
QPushButton#SourceToggle {
    background: transparent;
    border: 1px solid #2A333F;
    border-radius: 3px;
    padding: 2px 8px;
    color: #7E8A99;
    font-size: 10px;
}
QPushButton#SourceToggle:hover {
    border-color: #3A4655;
    color: #D9E0E8;
}
QPushButton#SourceToggle:checked {
    background-color: #2B455C;
    border-color: #5C82A1;
    color: #E9F2FA;
}
QPushButton#SourceToggle:disabled {
    color: #3F4955;
    border-color: #202730;
}
QPushButton#Transport:checked {
    color: #7FA7C9;
}
QPushButton#Play {
    background-color: #22374A;
    border: 1px solid #31506A;
    border-radius: 17px;
    min-width: 34px;
    min-height: 34px;
    max-width: 34px;
    max-height: 34px;
    padding: 0px;
    font-size: 13px;
    color: #DCEAF6;
}
QPushButton#Play:hover {
    background-color: #2B455C;
}
QSplitter::handle {
    background: #171D24;
    width: 8px;
    height: 8px;
}
QSplitter::handle:hover {
    background: #31506A;
}
QSlider::groove:horizontal {
    height: 3px;
    background: #2A323D;
    border-radius: 1px;
}
QSlider::sub-page:horizontal {
    background: #5C82A1;
    border-radius: 1px;
}
QSlider::handle:horizontal {
    background: #C6D5E3;
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
QSlider::handle:horizontal:hover {
    background: #FFFFFF;
}
QSlider::groove:vertical {
    width: 3px;
    background: #2A323D;
}
QSlider::sub-page:vertical {
    background: #5C82A1;
}
QSlider::handle:vertical {
    background: #C6D5E3;
    height: 12px;
    width: 12px;
    margin: 0 -5px;
    border-radius: 6px;
}
QTableWidget {
    background-color: transparent;
    border: none;
    gridline-color: transparent;
    selection-background-color: #212B36;
    selection-color: #E8EEF5;
    alternate-background-color: #171D24;
}
QTableWidget::item {
    padding: 4px 6px;
    border: none;
    border-bottom: 1px solid #1B222A;
}
QTableWidget::item:selected {
    background-color: #212B36;
}
QHeaderView::section {
    background-color: transparent;
    color: #6F7B8B;
    border: none;
    border-bottom: 1px solid #242C36;
    padding: 5px 6px;
    font-size: 10px;
    letter-spacing: 0.8px;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2C3541;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #3A4655;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: #2C3541;
    min-width: 24px;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit {
    background-color: #141A21;
    border: 1px solid #2A333F;
    border-radius: 4px;
    padding: 4px 7px;
    selection-background-color: #31506A;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #3A4655;
}
QComboBox::drop-down {
    border: none;
    width: 16px;
}
QComboBox::down-arrow {
    image: url("__CHEVRON__");
    width: 10px;
    height: 6px;
}
QComboBox QAbstractItemView {
    background-color: #1A2028;
    border: 1px solid #2A333F;
    selection-background-color: #2B455C;
    outline: none;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 14px;
    border: none;
    background: transparent;
}
QCheckBox {
    spacing: 7px;
}
QCheckBox::indicator {
    width: 13px;
    height: 13px;
    border: 1px solid #38434F;
    border-radius: 3px;
    background: #141A21;
}
QCheckBox::indicator:checked {
    background-color: #5C82A1;
    border-color: #7FA7C9;
}
QProgressBar {
    background-color: #1A2028;
    border: none;
    border-radius: 2px;
    height: 3px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background-color: #5C82A1;
    border-radius: 2px;
}
QToolTip {
    background-color: #1E252E;
    color: #D9E0E8;
    border: 1px solid #313B47;
    padding: 5px 7px;
}
QMenu {
    background-color: #171D24;
    border: 1px solid #2A333F;
    padding: 4px;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 3px;
}
QMenu::item:selected {
    background-color: #22303D;
}
QTabWidget::pane {
    border: none;
    background: transparent;
}
QTabBar::tab {
    background: transparent;
    color: #8B96A5;
    padding: 8px 14px;
    border-bottom: 2px solid transparent;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.6px;
}
QTabBar::tab:selected {
    color: #E8EEF5;
    border-bottom: 2px solid #7FA7C9;
}
QTabBar::tab:hover {
    color: #D9E0E8;
}
QStatusBar {
    background-color: #12161B;
    border-top: 1px solid #1F262F;
    color: #6F7B8B;
}
QStatusBar::item {
    border: none;
}
"""


LIGHT_QSS_MAP = {
    "#0E1114": "#F3F5F8",
    "#12161B": "#FFFFFF",
    "#141920": "#F7F9FB",
    "#141A21": "#FFFFFF",
    "#151A20": "#FFFFFF",
    "#151B22": "#F0F3F7",
    "#171D24": "#F8FAFC",
    "#1A2028": "#F2F5F9",
    "#1B222A": "#EEF2F6",
    "#1B222B": "#FFFFFF",
    "#1C232C": "#E3E8EF",
    "#1E252E": "#FFFFFF",
    "#1F262F": "#E1E7EE",
    "#202730": "#DDE4EC",
    "#202832": "#E8EDF3",
    "#212B36": "#E8F0F8",
    "#222B36": "#F0F4F8",
    "#22303D": "#E5EDF5",
    "#22374A": "#DCEAF5",
    "#232B35": "#DCE4EC",
    "#242C36": "#D6DEE7",
    "#2A323D": "#D6DEE7",
    "#2A333F": "#D6DEE7",
    "#2B455C": "#DCEAF5",
    "#2C3541": "#D0D9E3",
    "#313B47": "#CBD5E1",
    "#31506A": "#C7DBEC",
    "#33536E": "#D3E4F2",
    "#38434F": "#CBD5E1",
    "#384454": "#C3CFDC",
    "#3A4655": "#BCC8D6",
    "#3D5D79": "#A9C6DE",
    "#3F4955": "#AAB6C4",
    "#4C5664": "#9AA7B7",
    "#4C7294": "#8FB6D4",
    "#5C82A1": "#4E7FA8",
    "#5F6B7A": "#6E7C8C",
    "#5FA8D3": "#2F7DAB",
    "#626E7D": "#6E7C8C",
    "#6F7B8B": "#5E6C7C",
    "#6FBF8B": "#2E8B57",
    "#7E8A99": "#5F6E7E",
    "#7FA7C9": "#376E99",
    "#8B96A5": "#5F6E7E",
    "#A6C8E4": "#2C5F86",
    "#B7C3D0": "#3E4C5C",
    "#C6D5E3": "#4A5A6B",
    "#C9D3DE": "#33404E",
    "#D3A15F": "#B27A28",
    "#D97A7A": "#B44747",
    "#D9E0E8": "#24303C",
    "#DCEAF6": "#1E3A52",
    "#E0B15C": "#A97712",
    "#E8EEF5": "#1B2530",
    "#E9F2FA": "#1E3A52",
    "#FFFFFF": "#16222E",
}


TIMELINE_DARK = {
    "bg": "#11151A",
    "border": "#1C232C",
    "ruler_text": "#66717F",
    "ruler_line": "#2A333F",
    "baseline": "#1F262F",
    "section_alt": "#1A222B",
    "section_peak": "#202A35",
    "section_label": "#758494",
    "section_line": "#24303C",
    "lane_center": "#1A222B",
    "axis_label": "#8B96A5",
    "hint": "#4E5A69",
    "beat": "#232E3A",
    "beat_bar": "#35445A",
    "playhead": "#E8EEF5",
    "tooltip_bg": "#202833",
    "tooltip_text": "#C9D3DE",
    "hover": (255, 255, 255, 26),
    "hover_soft": (255, 255, 255, 30),
}
TIMELINE_LIGHT = {
    "bg": "#FFFFFF",
    "border": "#D6DEE7",
    "ruler_text": "#647382",
    "ruler_line": "#D6DEE7",
    "baseline": "#E1E7EE",
    "section_alt": "#F7FAFD",
    "section_peak": "#EEF4FA",
    "section_label": "#5E6C7C",
    "section_line": "#DCE4EC",
    "lane_center": "#E8EDF3",
    "axis_label": "#7A8796",
    "hint": "#7A8796",
    "beat": "#D6DEE7",
    "beat_bar": "#AFC0D2",
    "playhead": "#1B2530",
    "tooltip_bg": "#FFFFFF",
    "tooltip_text": "#24303C",
    "hover": (0, 0, 0, 24),
    "hover_soft": (0, 0, 0, 28),
}
TIMELINE = dict(TIMELINE_DARK)


def apply_theme(app, mode: str = "dark") -> None:
    from pathlib import Path

    global _MODE
    _MODE = mode if mode in {"dark", "light"} else "dark"
    COLORS.clear()
    COLORS.update(LIGHT_COLORS if _MODE == "light" else DARK_COLORS)
    TIMELINE.clear()
    TIMELINE.update(TIMELINE_LIGHT if _MODE == "light" else TIMELINE_DARK)
    stylesheet = STYLESHEET
    if _MODE == "light":
        stylesheet = re.sub(
            r"#[0-9A-Fa-f]{6}",
            lambda match: LIGHT_QSS_MAP.get(match.group(0).upper(), match.group(0)),
            stylesheet,
        )
    chevron = (Path(__file__).parent / "resources" / "chevron-down.svg").as_posix()
    app.setStyleSheet(stylesheet.replace("__CHEVRON__", chevron))
    app.setStyle("Fusion")
    font = QFont(_preferred_font(), 9)
    app.setFont(font)


def _preferred_font() -> str:
    families = set(QFontDatabase.families())
    for candidate in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans"):
        if candidate in families:
            return candidate
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()


def color(key: str) -> QColor:
    return QColor(COLORS[key])
