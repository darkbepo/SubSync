from __future__ import annotations

import os
import subprocess
import sys
import time

from PySide6.QtCore import (Property, QEasingCurve, QObject, QPropertyAnimation, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QIcon, QKeySequence, QPainter,
                           QPainterPath, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QButtonGroup,
                               QFrame, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QStyle, QStyledItemDelegate,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import paths, theme
from .pairing import expand, pair
from .theme import C

APP_NAME = "SubSync"
WAITING, INCOMPLETE, QUEUED, RUNNING, DONE, WARNING, ERROR, CANCELLED = (
    "waiting", "incomplete", "queued", "running", "done", "warning", "error", "cancelled")
ACTIVE = {QUEUED, RUNNING}
ROW_H = 54


from .settings import load as load_settings  # noqa: E402
from .settings import save as save_settings  # noqa: E402


def make_icon(size=256) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = size * 0.06
    path = QPainterPath()
    path.addRoundedRect(r, r, size - 2 * r, size - 2 * r, size * 0.22, size * 0.22)
    from PySide6.QtGui import QLinearGradient

    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#4C84FF"))
    g.setColorAt(1, QColor("#1F4FD8"))
    p.fillPath(path, g)
    p.setPen(QPen(QColor("white"), size * 0.05, Qt.SolidLine, Qt.RoundCap))
    for k, h in enumerate([0.12, 0.26, 0.4, 0.22, 0.32, 0.14]):
        x = size * (0.24 + k * 0.105)
        y = size * 0.38
        p.drawLine(int(x), int(y - size * h / 2), int(x), int(y + size * h / 2))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 240))
    p.drawRoundedRect(QRectF(size * .2, size * .64, size * .6, size * .07), size * .035, size * .035)
    p.setBrush(QColor(255, 255, 255, 160))
    p.drawRoundedRect(QRectF(size * .3, size * .76, size * .4, size * .07), size * .035, size * .035)
    p.end()
    return pm


def qc(key, alpha=None) -> QColor:
    c = QColor(C[key])
    if alpha is not None:
        c.setAlpha(alpha)
    return c


class Bridge(QObject):
    event = Signal(object, str, object)


class Job:
    _next = 1

    def __init__(self, video, sub):
        self.id = Job._next
        Job._next += 1
        self.video, self.sub = video, sub
        self.state = WAITING if (video and sub) else INCOMPLETE
        self.text = ""
        self.detail = ""
        self.progress = 0.0
        self.tooltip = ""
        self.out = None
        self.reset_text()

    def reset_text(self):
        if self.state == WAITING:
            self.text, self.detail = "Ready", ""
        else:
            self.text = "Needs a video" if self.sub else "Needs a subtitle"
            self.detail = "Drop it onto this row"


# ---------------------------------------------------------------- widgets
class ToggleSwitch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 0.0
        self.anim = QPropertyAnimation(self, b"knob", self)
        self.anim.setDuration(140)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(40, 22)

    def _animate(self, on):
        self.anim.stop()
        self.anim.setStartValue(self._pos)
        self.anim.setEndValue(1.0 if on else 0.0)
        self.anim.start()

    def setChecked(self, on):
        super().setChecked(on)
        self._pos = 1.0 if on else 0.0
        self.update()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)  # (not "pos": that would shadow QWidget.pos)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off, on = qc("track"), qc("accent")
        t = self._pos
        track = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * t
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class SessionBar(QWidget):
    def __init__(self):
        super().__init__()
        self.value = 0.0
        self.setFixedHeight(3)

    def set(self, v):
        self.value = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        if self.value > 0:
            p.setBrush(qc("accent"))
            p.drawRoundedRect(QRectF(0, 0, self.width() * self.value, self.height()), 1.5, 1.5)


def _rounded(p, rect, radius, color):
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(rect, radius, radius)


class FileDelegate(QStyledItemDelegate):
    """Two lines: file name, then its folder."""

    def __init__(self, win, col):
        super().__init__(win)
        self.win, self.col = win, col

    def paint(self, p, option, index):
        job = self.win.job_at(index.row())
        if job is None:
            return
        self.win.paint_row_bg(p, option, index.row())
        path = job.video if self.col == 0 else job.sub
        r = option.rect.adjusted(16, 0, -10, 0)
        p.save()
        f = QFont(option.font)
        if not path:
            p.setPen(qc("faint"))
            p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, "—")
            p.restore()
            return
        name = os.path.basename(path)
        folder = os.path.dirname(path)
        fm = p.fontMetrics()
        top = r.top() + (r.height() - 2 * fm.height() - 2) / 2
        p.setPen(qc("text"))
        f.setWeight(QFont.Medium)
        p.setFont(f)
        p.drawText(QRectF(r.left(), top, r.width(), fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(name, Qt.ElideMiddle, r.width()))
        f.setWeight(QFont.Normal)
        f.setPointSizeF(f.pointSizeF() * 0.88)
        p.setFont(f)
        p.setPen(qc("sub"))
        p.drawText(QRectF(r.left(), top + fm.height() + 2, r.width(), fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(folder, Qt.ElideMiddle, r.width()))
        p.restore()


class ResultDelegate(QStyledItemDelegate):
    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def paint(self, p, option, index):
        job = self.win.job_at(index.row())
        if job is None:
            return
        self.win.paint_row_bg(p, option, index.row())
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = option.rect.adjusted(12, 0, -16, 0)
        f = QFont(option.font)
        small = QFont(option.font)
        small.setPointSizeF(small.pointSizeF() * 0.88)

        if job.state in (RUNNING, QUEUED):
            fm = p.fontMetrics()
            top = r.top() + (r.height() - fm.height() - 12) / 2
            p.setFont(f)
            p.setPen(qc("text") if job.state == RUNNING else qc("sub"))
            label = job.text if job.state == RUNNING else "Queued"
            p.drawText(QRectF(r.left(), top, r.width() - 50, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, label)
            if job.state == RUNNING:
                p.setPen(qc("sub"))
                p.setFont(small)
                p.drawText(QRectF(r.right() - 50, top, 50, fm.height()), Qt.AlignRight | Qt.AlignVCenter,
                           f"{int(job.progress * 100)}%")
            bar = QRectF(r.left(), top + fm.height() + 6, r.width(), 6)
            _rounded(p, bar, 3, qc("track"))
            if job.state == RUNNING and job.progress > 0:
                _rounded(p, QRectF(bar.left(), bar.top(), max(6.0, bar.width() * job.progress), 6), 3, qc("accent"))
            p.restore()
            return

        pill = {DONE: ("Synced", "success", "success_soft"), WARNING: ("Check", "warn", "warn_soft"),
                ERROR: ("Failed", "danger", "danger_soft"), CANCELLED: ("Stopped", "sub", "track"),
                WAITING: ("Ready", "accent", "accent_soft"), INCOMPLETE: ("Incomplete", "sub", "track")}[job.state]
        text, fg, bg = pill
        bf = QFont(small)
        bf.setWeight(QFont.DemiBold)
        p.setFont(bf)
        tw = p.fontMetrics().horizontalAdvance(text)
        ph = p.fontMetrics().height() + 6
        pr = QRectF(r.left(), r.center().y() - ph / 2 + 0.5, tw + 20, ph)
        _rounded(p, pr, ph / 2, qc(bg))
        p.setPen(qc(fg))
        p.drawText(pr, Qt.AlignCenter, text)
        tx = pr.right() + 12
        rest = QRectF(tx, r.top(), r.right() - tx, r.height())
        if job.state == DONE:
            fm = p.fontMetrics()
            top = r.top() + (r.height() - 2 * fm.height() - 4) / 2
            p.setFont(f)
            p.setPen(qc("text"))
            p.drawText(QRectF(tx, top, rest.width(), fm.height() + 2), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(job.text, Qt.ElideMiddle, int(rest.width())))
            p.setFont(small)
            p.setPen(qc("sub"))
            p.drawText(QRectF(tx, top + fm.height() + 4, rest.width(), fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(job.detail, Qt.ElideRight, int(rest.width())))
        else:
            p.setFont(small if job.state in (WAITING, INCOMPLETE) else f)
            p.setPen(qc("sub") if job.state in (WAITING, INCOMPLETE, CANCELLED) else qc("text"))
            msg = job.detail if job.state in (WAITING, INCOMPLETE) else job.text
            p.drawText(rest, Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(msg, Qt.ElideRight, int(rest.width())))
        p.restore()


class DropTable(QTableWidget):
    def __init__(self, win):
        super().__init__(0, 3)
        self.win = win
        self.drag_on = False
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setHorizontalHeaderLabels(["Reference video", "Reference subtitle", "Result"])
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(True)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setHighlightSections(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(ROW_H)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWordWrap(False)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.hover_row = -1

    def mouseMoveEvent(self, e):
        r = self.rowAt(int(e.position().y()))
        if r != self.hover_row:
            self.hover_row = r
            self.viewport().update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.hover_row = -1
        self.viewport().update()
        super().leaveEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self.drag_on = True
            self.viewport().update()
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            r = self.rowAt(int(e.position().y()))
            if r != self.hover_row:
                self.hover_row = r
                self.viewport().update()
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.drag_on = False
        self.viewport().update()

    def dropEvent(self, e):
        self.drag_on = False
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        row = self.rowAt(int(e.position().y()))
        self.win.add_paths(files, row if row >= 0 else None)
        e.acceptProposedAction()
        self.viewport().update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.rowCount() == 0 or self.drag_on:
            p = QPainter(self.viewport())
            p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(self.viewport().rect()).adjusted(18, 18, -18, -18)
            if self.rowCount():
                r = QRectF(r.left(), r.bottom() - 70, r.width(), 70)
            pen = QPen(qc("accent") if self.drag_on else qc("border"), 1.6, Qt.DashLine)
            pen.setDashPattern([5, 4])
            p.setPen(pen)
            p.setBrush(qc("accent_soft") if self.drag_on else Qt.NoBrush)
            p.drawRoundedRect(r, 12, 12)
            if self.rowCount():
                p.setPen(qc("accent"))
                p.drawText(r, Qt.AlignCenter, "Release to add")
                return
            cx, cy = r.center().x(), r.center().y() - 34
            # upload glyph
            _rounded(p, QRectF(cx - 30, cy - 30, 60, 60), 18, qc("accent_soft"))
            p.setPen(QPen(qc("accent"), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawLine(int(cx), int(cy + 11), int(cx), int(cy - 11))
            p.drawLine(int(cx - 9), int(cy - 3), int(cx), int(cy - 12))
            p.drawLine(int(cx + 9), int(cy - 3), int(cx), int(cy - 12))
            p.drawLine(int(cx - 13), int(cy + 14), int(cx + 13), int(cy + 14))
            f = QFont(self.font())
            f.setPointSizeF(f.pointSizeF() * 1.3)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            p.setPen(qc("text"))
            p.drawText(QRectF(r.left(), cy + 44, r.width(), 30), Qt.AlignCenter,
                       "Drop videos and subtitles here")
            f.setPointSizeF(self.font().pointSizeF())
            f.setWeight(QFont.Normal)
            p.setFont(f)
            p.setPen(qc("sub"))
            p.drawText(QRectF(r.left(), cy + 74, r.width(), 24), Qt.AlignCenter,
                       "Files or whole season folders · paired automatically by name or episode number")
            p.end()


# ---------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = load_settings()
        self.jobs: list[Job] = []
        self.running = False
        self.run_started = None
        self.run_done = 0
        self.run_total = 0
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(make_icon()))
        self.resize(1180, 680)
        self.setMinimumSize(860, 460)

        self.bridge = Bridge()
        self.bridge.event.connect(self.on_event)
        from .pipeline import Engine

        self.engine = Engine(lambda jid, kind, data: self.bridge.event.emit(jid, kind, data), lambda: self.settings)

        root = QWidget()
        root.setObjectName("root")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(14)

        # header
        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(make_icon(84).scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(icon)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel("SubSync")
        t.setObjectName("title")
        st = QLabel("Line-by-line subtitle sync from the video's own audio")
        st.setObjectName("subtitle")
        titles.addWidget(t)
        titles.addWidget(st)
        head.addSpacing(6)
        head.addLayout(titles)
        head.addStretch(1)
        self.chip = QLabel()
        self.chip.setObjectName("chip")
        self.set_chip("Loading speech model…", "warn")
        head.addWidget(self.chip, 0, Qt.AlignVCenter)
        lay.addLayout(head)

        # card with the table
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(4, 4, 4, 6)
        cl.setSpacing(0)
        self.table = DropTable(self)
        self.table.setItemDelegateForColumn(0, FileDelegate(self, 0))
        self.table.setItemDelegateForColumn(1, FileDelegate(self, 1))
        self.table.setItemDelegateForColumn(2, ResultDelegate(self))
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.context_menu)
        self.table.doubleClicked.connect(self.open_result)
        self.table.setColumnWidth(0, 330)
        self.table.setColumnWidth(1, 300)
        cl.addWidget(self.table, 1)
        self.session = SessionBar()
        cl.addWidget(self.session)
        lay.addWidget(card, 1)

        # footer
        foot = QHBoxLayout()
        foot.setSpacing(10)
        lbl = QLabel("Save as")
        lbl.setObjectName("muted")
        foot.addWidget(lbl)
        seg = QFrame()
        seg.setObjectName("segment")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.seg_group = QButtonGroup(self)
        for i, txt in enumerate((".en.srt", ".eng.srt")):
            b = QPushButton(txt)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.seg_group.addButton(b, i)
            sl.addWidget(b)
        self.seg_group.button(1 if self.settings.get("suffix") == ".eng" else 0).setChecked(True)
        self.seg_group.idClicked.connect(lambda _: self.settings_changed())
        foot.addWidget(seg)
        foot.addSpacing(14)
        self.overwrite = ToggleSwitch()
        self.overwrite.setChecked(bool(self.settings.get("overwrite", False)))
        self.overwrite.toggled.connect(lambda _: self.settings_changed())
        ow_lbl = QLabel("Overwrite existing")
        tip = ("On: replace a subtitle with the same name (waits until no other program is using it).\n"
               "Off: keep it and save the new one as  name.en.#1.srt")
        for wdg in (self.overwrite, ow_lbl):
            wdg.setToolTip(tip)
        ow_lbl.mousePressEvent = lambda e: self.overwrite.toggle()
        foot.addWidget(self.overwrite)
        foot.addWidget(ow_lbl)
        foot.addSpacing(14)
        self.tidy = ToggleSwitch()
        self.tidy.setChecked(bool(self.settings.get("tidy", True)))
        self.tidy.toggled.connect(lambda _: self.settings_changed())
        tidy_lbl = QLabel("Tidy up lines")
        tip = "One sentence per subtitle, at most 2 lines, capital letters repaired. Timing is fixed either way."
        for wdg in (self.tidy, tidy_lbl):
            wdg.setToolTip(tip)
        tidy_lbl.mousePressEvent = lambda e: self.tidy.toggle()
        foot.addWidget(self.tidy)
        foot.addWidget(tidy_lbl)
        foot.addStretch(1)
        self.overall = QLabel("")
        self.overall.setObjectName("muted")
        foot.addWidget(self.overall)
        foot.addSpacing(6)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setObjectName("ghost")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton("Clear finished")
        self.btn_clear.setObjectName("ghost")
        self.btn_clear.clicked.connect(self.clear_finished)
        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("primary")
        self.btn_start.setMinimumWidth(120)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.clicked.connect(self.start_stop)
        for b in (self.btn_remove, self.btn_clear, self.btn_start):
            foot.addWidget(b)
        lay.addLayout(foot)
        self.setCentralWidget(root)
        self.setAcceptDrops(True)

        QShortcut(QKeySequence.Delete, self, self.remove_selected)
        geo = self.settings.get("geometry")
        if geo:
            try:
                self.restoreGeometry(bytes.fromhex(geo))
            except Exception:
                pass
        self.refresh_buttons()
        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self.update_overall)
        self.ticker.start(1000)
        QTimer.singleShot(300, self.engine.warm_up)

    # ------------------------------------------------------------ painting helpers
    def paint_row_bg(self, p, option, row):
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            p.fillRect(option.rect, qc("selected"))
        elif row == self.table.hover_row:
            p.fillRect(option.rect, qc("hover"))
        p.save()
        p.setPen(QPen(qc("border"), 1))
        p.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        p.restore()

    def set_chip(self, text, color_key):
        self._chip = (text, color_key)
        self.chip.setText(f"<span style='color:{C[color_key]}'>●</span>&nbsp;&nbsp;{text}")

    # ------------------------------------------------------------ drops
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()], None)

    def add_paths(self, files, row):
        videos, subs = expand(files)
        if not videos and not subs:
            self.flash("Nothing usable there – videos (mkv, mp4, avi…) and subtitles (srt, ass, vtt) only")
            return
        if row is not None and len(videos) + len(subs) == 1 and row < len(self.jobs):
            j = self.jobs[row]
            if j.state not in ACTIVE:
                if videos:
                    j.video = videos[0]
                else:
                    j.sub = subs[0]
                self._reset(j)
                self.rebuild()
                self.after_change()
                return
        have_v = {j.video for j in self.jobs if j.video}
        have_s = {j.sub for j in self.jobs if j.sub}
        half = [j for j in self.jobs if j.state == INCOMPLETE]
        pool_v = [j.video for j in half if j.video] + [v for v in videos if v not in have_v]
        pool_s = [j.sub for j in half if j.sub] + [s for s in subs if s not in have_s]
        for j in half:
            self.jobs.remove(j)
        for v, s in pair(pool_v, pool_s):
            self.jobs.append(Job(v, s))
        self.rebuild()
        self.after_change()

    def _reset(self, j: Job):
        j.state = WAITING if (j.video and j.sub) else INCOMPLETE
        j.progress, j.tooltip, j.out = 0.0, "", None
        j.reset_text()

    def after_change(self):
        if self.running:
            for j in self.jobs:
                if j.state == WAITING:
                    self.submit(j)
        self.refresh_buttons()

    def flash(self, text):
        self.overall.setText(text)
        QTimer.singleShot(6000, self.update_overall)

    # ------------------------------------------------------------ table
    def job_at(self, row):
        return self.jobs[row] if 0 <= row < len(self.jobs) else None

    def rebuild(self):
        self.table.setRowCount(len(self.jobs))
        for r in range(len(self.jobs)):
            self.render_row(r)
        self.table.viewport().update()

    def render_row(self, r):
        j = self.jobs[r]
        for col, p in ((0, j.video), (1, j.sub)):
            it = QTableWidgetItem("")
            it.setToolTip(p or "")
            self.table.setItem(r, col, it)
        it = QTableWidgetItem("")
        it.setToolTip(j.tooltip or (j.text + ("\n" + j.detail if j.detail else "")))
        self.table.setItem(r, 2, it)

    def row_of(self, jid):
        for r, j in enumerate(self.jobs):
            if j.id == jid:
                return r, j
        return None, None

    # ------------------------------------------------------------ actions
    def settings_changed(self):
        self.settings["suffix"] = ".eng" if self.seg_group.checkedId() == 1 else ".en"
        self.settings["overwrite"] = self.overwrite.isChecked()
        self.settings["tidy"] = self.tidy.isChecked()
        save_settings(self.settings)

    def submit(self, j: Job):
        j.state, j.text, j.progress = QUEUED, "Queued", 0.0
        self.run_total += 1
        self.engine.submit(j.id, j.video, j.sub)

    def _begin_run(self):
        if not self.running:
            self.running = True
            self.run_started = time.time()
            self.run_done = 0
            self.run_total = 0

    def start_stop(self):
        if self.running:
            self.engine.stop()
            self.running = False
            self.refresh_buttons()
            return
        todo = [j for j in self.jobs if j.state in (WAITING, CANCELLED, ERROR, WARNING) and j.video and j.sub]
        if not todo:
            return
        self._begin_run()
        for j in todo:
            self.submit(j)
        self.rebuild()
        self.refresh_buttons()

    def refresh_buttons(self):
        self.btn_start.setText("Stop" if self.running else "Start")
        self.btn_start.setObjectName("danger" if self.running else "primary")
        self.btn_start.style().unpolish(self.btn_start)
        self.btn_start.style().polish(self.btn_start)
        ready = any(j.state in (WAITING, CANCELLED, ERROR, WARNING) and j.video and j.sub for j in self.jobs)
        self.btn_start.setEnabled(self.running or ready)
        self.btn_clear.setEnabled(any(j.state == DONE for j in self.jobs))
        self.btn_remove.setEnabled(bool(self.jobs))
        self.update_overall()

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            if self.jobs[r].state not in ACTIVE:
                del self.jobs[r]
        self.rebuild()
        self.refresh_buttons()

    def clear_finished(self):
        self.jobs = [j for j in self.jobs if j.state != DONE]
        self.rebuild()
        self.refresh_buttons()

    def context_menu(self, pos):
        r = self.table.rowAt(pos.y())
        j = self.job_at(r)
        if not j:
            return
        m = QMenu(self)
        if j.out:
            m.addAction("Show result in Explorer", lambda: self.reveal(j.out))
        folder = os.path.dirname(j.video or j.sub)
        m.addAction("Open folder", lambda: self.reveal(folder, folder=True))
        if j.state in (ERROR, WARNING, CANCELLED, DONE) and j.video and j.sub:
            m.addAction("Run again", lambda: self.retry(j))
        if j.state not in ACTIVE:
            m.addSeparator()
            m.addAction("Remove", self.remove_selected)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def retry(self, j):
        self._reset(j)
        self._begin_run()
        self.submit(j)
        self.rebuild()
        self.refresh_buttons()

    def open_result(self, index):
        j = self.job_at(index.row())
        if j and j.out:
            self.reveal(j.out)

    def reveal(self, path, folder=False):
        if sys.platform == "win32":
            if folder:
                os.startfile(path)
            else:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])

    # ------------------------------------------------------------ engine events
    def on_event(self, jid, kind, data):
        if jid is None:
            return self.on_global(kind, data)
        r, j = self.row_of(jid)
        if j is None:
            return
        if kind == "stage":
            if data == "Queued":
                j.state, j.text = QUEUED, "Queued"
            else:
                if data != j.text:
                    j.progress = 0.0 if "released" not in data else j.progress
                j.state, j.text = RUNNING, data
        elif kind == "progress":
            j.state = RUNNING
            j.progress = float(data)
        elif kind == "done":
            j.state = DONE
            j.out = data["out"]
            lo, hi = data["offsets"]
            shift = f"{lo:+.1f} s" if abs(hi - lo) < 0.05 else f"{lo:+.1f} → {hi:+.1f} s"
            n_runs = len(data["runs"])
            from .pipeline import tidy_details, tidy_summary

            tidy = data.get("tidy") or {}
            recut = tidy_summary(tidy)
            j.text = os.path.basename(data["out"])
            j.detail = (f"{data['matched']}/{data['total']} lines matched · shifts {shift}"
                        + (f" · {n_runs} timing sections" if n_runs > 1 else "")
                        + (f" · {sum(data['ends'][:2])} endings extended" if sum(data['ends'][:2]) else "")
                        + (f" · {recut}" if recut else "")
                        + f" · audio: {data['lang']}")
            st = data.get("stats", {})
            runs = "\n".join(f"   {self._ts(a)}–{self._ts(b)}:  {o:+.2f} s" for a, b, o in data["runs"])
            j.tooltip = (f"Saved: {data['out']}\nAudio language: {data['lang']}"
                         f"{' (cached transcript)' if st.get('cached') else ''}\n"
                         f"Lines matched to speech: {data['matched']} of {data['total']}\n"
                         f"Timing sections found:\n{runs}\n"
                         f"Endings extended so lines stay until spoken: {data['ends'][0]}\n"
                         f"Endings extended to a readable minimum: {data['ends'][1]}\n"
                         + (f"Lines with too little room before the next line: {data['ends'][2]}\n" if data['ends'][2] else "")
                         + (tidy_details(tidy) + "\n" if tidy else "") +
                         f"Time: {data['seconds']:.0f} s\n\nDouble-click to show the file")
            self.run_done += 1
        elif kind in ("warning", "error", "cancelled"):
            j.state = {"warning": WARNING, "error": ERROR, "cancelled": CANCELLED}[kind]
            j.text = data["text"] if isinstance(data, dict) else str(data)
            j.tooltip = j.text
            if kind != "cancelled":
                self.run_done += 1
        self.render_row(r)
        self.table.viewport().update()
        if self.running and not any(x.state in ACTIVE for x in self.jobs):
            self.running = False
            n_ok = sum(1 for x in self.jobs if x.state == DONE)
            self.flash(f"Finished · {n_ok} subtitle(s) synced")
            QApplication.alert(self)
        self.refresh_buttons()

    @staticmethod
    def _ts(t):
        t = int(t)
        return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"

    def on_global(self, kind, data):
        if kind == "device":
            st = data.get("state")
            if st == "loading":
                self.set_chip("Loading speech model…", "warn")
            elif st == "ready":
                print(f"{time.strftime('%H:%M:%S')} speech model ready on {data['device']}"
                      + (f" after {data['load_s']:.1f} s" if data.get("load_s") is not None else ""), flush=True)
                if data["device"] == "cuda":
                    name = (data["name"] or "NVIDIA GPU").replace("NVIDIA ", "").replace("GeForce ", "")
                    self.set_chip(f"{name} · ready", "success")
                else:
                    self.set_chip("CPU mode · slower (no usable NVIDIA GPU)", "warn")
                self.chip.setToolTip("")
            elif st == "error":
                self.set_chip(data.get("text", "Error"), "danger")
                if data.get("detail"):
                    self.chip.setToolTip("Details are in the logs folder")
                    with open(os.path.join(paths.LOGS, "worker-errors.log"), "a", encoding="utf-8") as f:
                        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + data["detail"] + "\n")
        elif kind == "batch":
            self.settings["gpu_batch"] = int(data)
            save_settings(self.settings)

    def update_overall(self):
        active = [j for j in self.jobs if j.state in ACTIVE]
        if not self.running or not active:
            self.session.set(0)
            done = sum(1 for j in self.jobs if j.state == DONE)
            self.overall.setText(f"{len(self.jobs)} items · {done} synced" if self.jobs else "")
            return
        total = max(self.run_total, self.run_done + len(active))
        cur = sum(j.progress for j in active if j.state == RUNNING) * 0.5
        self.session.set((self.run_done + min(cur, 0.9)) / total)
        el = time.time() - (self.run_started or time.time())
        if self.run_done:
            left = el / self.run_done * len(active)
            eta = f"about {int(left // 60) + 1} min left" if left >= 60 else "under a minute left"
        else:
            eta = "estimating time…"
        self.overall.setText(f"{self.run_done} of {total} done · {eta}")

    def closeEvent(self, e):
        if self.running:
            if QMessageBox.question(self, APP_NAME, "Syncing is still running. Stop and quit?") != QMessageBox.Yes:
                e.ignore()
                return
        self.settings["geometry"] = bytes(self.saveGeometry()).hex()
        save_settings(self.settings)
        self.engine.shutdown()
        e.accept()


def run(step=lambda m: None):
    from PySide6.QtCore import qInstallMessageHandler

    def qt_msg(mode, ctx, msg):  # Qt's own warnings/fatal errors are invisible without a console
        print(f"[qt] {msg}", flush=True)

    qInstallMessageHandler(qt_msg)
    app = QApplication(sys.argv)
    step("window library ready")
    app.setApplicationName(APP_NAME)
    f = QFont("Segoe UI Variable Text")
    if not f.exactMatch():
        f = QFont("Segoe UI")
    f.setPointSizeF(10)
    app.setFont(f)
    theme.apply(app)
    app.setWindowIcon(QIcon(make_icon()))
    w = MainWindow()

    def restyle(*_):
        theme.apply(app)
        if getattr(w, "_chip", None):
            w.set_chip(*w._chip)
        w.update()

    try:
        QGuiApplication.styleHints().colorSchemeChanged.connect(restyle)
    except Exception:
        pass
    w.show()
    # make sure the window really is on screen and in front, whatever
    # show-state the process was started with
    w.setWindowState((w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
    w.showNormal() if not w.isMaximized() else w.showMaximized()
    w.raise_()
    w.activateWindow()
    if sys.platform == "win32":
        # Windows may apply a "start hidden" flag from the launching program to
        # the first window shown; showing it again directly overrides that.
        import ctypes

        hwnd = int(w.winId())
        ctypes.windll.user32.ShowWindow(hwnd, 1)  # SW_SHOWNORMAL
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        step(f"window visible on screen: {bool(ctypes.windll.user32.IsWindowVisible(hwnd))}")
    step(f"window shown (visible={w.isVisible()}, {w.width()}x{w.height()} at {w.x()},{w.y()})")
    ready = os.environ.get("SUBSYNC_READY_FILE")
    if ready:
        try:
            open(ready, "w").write("ok")
        except OSError:
            pass
    return app.exec()
