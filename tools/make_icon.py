"""Generate VibeFlow's PNG/ICO application icon."""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QPixmap,
)
from PySide6.QtWidgets import QApplication

SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(size: int) -> QImage:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = size

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#11161C"))
    painter.drawRoundedRect(QRectF(0.02 * s, 0.02 * s, 0.96 * s, 0.96 * s), 0.23 * s, 0.23 * s)

    # Three motion traces (roll / pitch / yaw), subtle.
    colors = ("#5FA8D3", "#6FBF8B", "#D3A15F")
    for i, color in enumerate(colors):
        pen = QPen(QColor(color), max(1.0, 0.025 * s))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        path = QPainterPath()
        y = 0.30 * s + i * 0.14 * s
        path.moveTo(0.16 * s, y)
        path.cubicTo(0.33 * s, y - 0.11 * s, 0.43 * s, y + 0.11 * s, 0.55 * s, y)
        path.cubicTo(0.67 * s, y - 0.11 * s, 0.78 * s, y + 0.10 * s, 0.84 * s, y)
        painter.drawPath(path)

    # V mark.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#E8EEF5"))
    v = QPolygonF(
        [
            QPointF(0.34 * s, 0.47 * s),
            QPointF(0.46 * s, 0.78 * s),
            QPointF(0.58 * s, 0.47 * s),
            QPointF(0.51 * s, 0.47 * s),
            QPointF(0.46 * s, 0.63 * s),
            QPointF(0.41 * s, 0.47 * s),
        ]
    )
    painter.drawPolygon(v)

    # Accent dot.
    painter.setBrush(QColor("#7FA7C9"))
    painter.drawEllipse(QRectF(0.69 * s, 0.18 * s, 0.11 * s, 0.11 * s))
    painter.end()
    return pixmap.toImage()


def main() -> None:
    app = QApplication([])
    resources = Path(__file__).resolve().parent.parent / "vibeflow" / "ui" / "resources"
    resources.mkdir(parents=True, exist_ok=True)
    images = {size: render(size) for size in SIZES}
    images[256].save(str(resources / "vibeflow.png"), "PNG")

    # Build a multi-size ICO (PNG-compressed entries are supported by Windows).
    blobs = []
    for size in SIZES:
        temp = resources / f".icon_{size}.png"
        images[size].save(str(temp), "PNG")
        blobs.append((size, temp.read_bytes()))
        temp.unlink()

    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = []
    payload = b""
    for size, data in blobs:
        width = 0 if size >= 256 else size
        entries.append(
            struct.pack("<BBBBHHII", width, width, 0, 0, 1, 32, len(data), offset)
        )
        offset += len(data)
        payload += data
    (resources / "vibeflow.ico").write_bytes(header + b"".join(entries) + payload)
    print("written", resources / "vibeflow.ico")
    app.quit()


if __name__ == "__main__":
    main()
