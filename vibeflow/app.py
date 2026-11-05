"""Application bootstrap."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from . import APP_NAME, APP_TAGLINE, __version__
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def _app_icon() -> QIcon:
    icon_path = Path(__file__).parent / "ui" / "resources" / "vibeflow.ico"
    if icon_path.exists():
        return QIcon(str(icon_path))
    pixmap = QPixmap(256, 256)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#12171D"))
    painter.drawRoundedRect(8, 8, 240, 240, 52, 52)
    painter.setPen(QColor("#7FA7C9"))
    from PySide6.QtGui import QFont, QPolygonF
    from PySide6.QtCore import QPointF

    font = QFont("Segoe UI", 128)
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "V")
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#7FA7C9"))
    painter.drawPolygon(
        QPolygonF([QPointF(176, 66), QPointF(192, 82), QPointF(176, 98), QPointF(160, 82)])
    )
    painter.end()
    return QIcon(pixmap)


def _set_windows_icon(window) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        icon_path = Path(__file__).parent / "ui" / "resources" / "vibeflow.ico"
        if not icon_path.exists():
            return
        user32 = ctypes.windll.user32
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.SendMessageW.restype = wintypes.LPARAM
        user32.SetClassLongPtrW.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        user32.SetClassLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]

        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        WM_SETICON = 0x0080
        GCLP_HICON = -14
        GCLP_HICONSM = -34
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020

        hwnd = wintypes.HWND(int(window.winId()))
        big = user32.LoadImageW(
            None, str(icon_path), IMAGE_ICON, 32, 32, LR_LOADFROMFILE
        )
        small = user32.LoadImageW(
            None, str(icon_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE
        )
        if big:
            user32.SendMessageW(hwnd, WM_SETICON, 1, big)  # ICON_BIG
            user32.SetClassLongPtrW(hwnd, GCLP_HICON, big)
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, 0, small)  # ICON_SMALL
            user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, small)
        user32.SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    except Exception:
        pass


def main() -> int:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        for candidate in (base / "bin", Path(sys.executable).parent / "bin"):
            if candidate.is_dir():
                os.environ["PATH"] = (
                    f"{candidate}{os.pathsep}" + os.environ.get("PATH", "")
                )
                break
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    settings = QSettings("VibeFlow", "VibeFlow")
    try:
        scale = float(settings.value("ui/scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    if 0.8 <= scale <= 2.0:
        os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    app.setWindowIcon(_app_icon())
    apply_theme(app)

    window = MainWindow()
    window.setWindowIcon(_app_icon())
    window.show()
    _set_windows_icon(window)
    QTimer.singleShot(350, lambda: _set_windows_icon(window))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
