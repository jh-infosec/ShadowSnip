"""Check that video clips can be recorded on this computer (0.14.0).

    python clipcheck.py

Records three seconds of a moving square with each video codec this
computer's encoder offers, and prints for each: how long the encoder took to
start, how many frames it accepted, the size of the file, and how many
pictures can be read back from it. Nothing is kept; the files go to a
temporary folder that is deleted afterwards.

ShadowSnip's recorder is tested on Linux, where the encoder is software. On
Windows the encoder is whatever the graphics driver and Media Foundation
provide, which no test on another machine can stand in for. If clips come
out empty or will not play, the output of this script says where it goes
wrong.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import QEventLoop, QRect, QTimer
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
    from PySide6.QtMultimedia import QMediaFormat
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("ShadowSnip clip check")
    import clips
    import recorder

    print(f"Python {sys.version.split()[0]} on {sys.platform}, PySide6 {pyside_version}")
    media = QMediaFormat(QMediaFormat.FileFormat.MPEG4)
    offered = media.supportedVideoCodecs(QMediaFormat.ConversionMode.Encode)
    print("MP4 video codecs offered:", ", ".join(c.name for c in offered) or "none")
    wanted = [c for c in (QMediaFormat.VideoCodec.H264, QMediaFormat.VideoCodec.MPEG4,
                          QMediaFormat.VideoCodec.H265) if c in offered]
    if not wanted:
        print("RESULT: no usable codec; video clips cannot work here.")
        return 1

    counter = [0]

    def square(_screen, rect: QRect) -> QImage:
        image = QImage(rect.width(), rect.height(), QImage.Format.Format_RGB32)
        image.fill(QColor("#101018"))
        painter = QPainter(image)
        painter.fillRect(QRect(4 + (counter[0] * 6) % max(1, rect.width() - 40), 30, 32, 32), QColor("#e81123"))
        painter.end()
        counter[0] += 1
        return image

    geometry = QGuiApplication.primaryScreen().geometry()
    area = QRect(geometry.x(), geometry.y(), min(640, geometry.width()), min(360, geometry.height()))
    good = []
    with tempfile.TemporaryDirectory() as folder:
        for codec in wanted:
            path = Path(folder) / f"check_{codec.name}.mp4"
            original = recorder._codec_and_format

            def chosen(codec=codec):
                fmt = QMediaFormat(QMediaFormat.FileFormat.MPEG4)
                fmt.setVideoCodec(codec)
                return fmt

            recorder._codec_and_format = chosen
            rec = recorder.Recorder(area, path, fps=15, grab=square)
            result, times = [], {}
            loop = QEventLoop()
            rec.started.connect(lambda: times.setdefault("started", time.monotonic()))
            rec.finished.connect(lambda p: (result.append(("finished", p)), loop.quit()))
            rec.failed.connect(lambda m: (result.append(("failed", m)), loop.quit()))
            begin = time.monotonic()
            try:
                rec.start()
            except Exception as exc:  # noqa: BLE001 - this is a diagnostic
                print(f"  {codec.name}: could not start: {exc!r}")
                recorder._codec_and_format = original
                continue
            returned = time.monotonic() - begin
            if rec.is_started:
                times.setdefault("started", time.monotonic())
            QTimer.singleShot(3000 + int(recorder.WARMUP_SECONDS * 1000), rec.stop)
            started_check = QTimer()
            started_check.setInterval(50)

            def stop_three_seconds_in():
                if "started" in times and time.monotonic() - times["started"] >= 3.0:
                    started_check.stop()
                    rec.stop()

            started_check.timeout.connect(stop_three_seconds_in)
            started_check.start()
            QTimer.singleShot(40000, loop.quit)
            loop.exec()
            started_check.stop()
            recorder._codec_and_format = original
            warm = f"{times['started'] - begin:.2f} s" if "started" in times else "never"
            size = path.stat().st_size if path.is_file() else 0
            line = (f"  {codec.name}: start() returned in {returned:.2f} s, encoder started after {warm}, "
                    f"{rec.frames_sent} frames accepted, {rec.frames_dropped} dropped, "
                    f"{result[0][0] if result else 'no answer'}"
                    f"{' (' + result[0][1] + ')' if result and result[0][0] == 'failed' else ''}, "
                    f"file {size} bytes")
            readable = 0
            if size:
                try:
                    readable = len(clips.frames_of(path, fps=10, max_seconds=10))
                except Exception as exc:  # noqa: BLE001
                    line += f", reading back failed: {exc}"
            print(line + f", {readable} pictures read back")
            if result and result[0][0] == "finished" and rec.frames_sent >= 20 and readable >= 10:
                good.append(codec.name)
    if good:
        print(f"RESULT: video clips work here with {', '.join(good)}.")
        return 0
    print("RESULT: no codec produced a playable clip. Please send this output.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
