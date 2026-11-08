"""Light/dark theme that follows the Windows setting."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

LIGHT = dict(window="#F4F5F7", card="#FFFFFF", border="#E3E6EB", text="#1B1D21", sub="#6B7280",
             faint="#9AA1AC", accent="#2B6CFF", accent_hover="#1F5BE6", accent_soft="#E8EFFF",
             success="#16A34A", success_soft="#E6F6EC", warn="#C27803", warn_soft="#FDF3E1",
             danger="#DC2626", danger_soft="#FDECEC", track="#E6E8EC", hover="#F5F7FA",
             button="#FFFFFF", button_hover="#F1F3F6", selected="#EAF0FF", input="#E7EAEF")
DARK = dict(window="#151619", card="#1F2024", border="#2E3036", text="#F2F3F5", sub="#9CA3AF",
            faint="#6B7280", accent="#5B8CFF", accent_hover="#7AA2FF", accent_soft="#1E2A47",
            success="#4ADE80", success_soft="#163322", warn="#FBBF24", warn_soft="#3A2E12",
            danger="#F87171", danger_soft="#3D1C1C", track="#33363C", hover="#25272B",
            button="#2A2C31", button_hover="#33363C", selected="#24304D", input="#2A2C31")

C: dict = dict(LIGHT)


def is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def apply(app) -> None:
    C.clear()
    C.update(DARK if is_dark() else LIGHT)
    app.setStyle("Fusion")
    pal = QPalette()
    q = lambda k: QColor(C[k])
    pal.setColor(QPalette.Window, q("window"))
    pal.setColor(QPalette.Base, q("card"))
    pal.setColor(QPalette.AlternateBase, q("card"))
    pal.setColor(QPalette.Text, q("text"))
    pal.setColor(QPalette.WindowText, q("text"))
    pal.setColor(QPalette.ButtonText, q("text"))
    pal.setColor(QPalette.Button, q("button"))
    pal.setColor(QPalette.Highlight, q("selected"))
    pal.setColor(QPalette.HighlightedText, q("text"))
    pal.setColor(QPalette.PlaceholderText, q("faint"))
    pal.setColor(QPalette.ToolTipBase, q("card"))
    pal.setColor(QPalette.ToolTipText, q("text"))
    pal.setColor(QPalette.Mid, q("border"))
    app.setPalette(pal)
    app.setStyleSheet(f"""
    QMainWindow, QWidget#root {{ background: {C['window']}; }}
    QLabel {{ color: {C['text']}; }}
    QLabel#title {{ font-size: 17pt; font-weight: 600; }}
    QLabel#subtitle, QLabel#muted {{ color: {C['sub']}; }}
    QLabel#chip {{ background: {C['card']}; border: 1px solid {C['border']}; border-radius: 12px;
                   padding: 4px 12px; color: {C['sub']}; }}
    QFrame#card {{ background: {C['card']}; border: 1px solid {C['border']}; border-radius: 14px; }}
    QTableWidget {{ background: transparent; border: none; outline: 0; }}
    QTableWidget::item {{ border: none; padding: 0 10px; }}
    QTableWidget::item:selected {{ background: {C['selected']}; color: {C['text']}; }}
    QTableWidget::item:hover {{ background: {C['hover']}; }}
    QHeaderView {{ background: transparent; }}
    QHeaderView::section {{ background: transparent; color: {C['sub']}; border: none;
        border-bottom: 1px solid {C['border']}; padding: 10px 12px 8px 12px; font-size: 8.5pt;
        font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
    QPushButton {{ background: {C['button']}; color: {C['text']}; border: 1px solid {C['border']};
        border-radius: 8px; padding: 7px 16px; }}
    QPushButton:hover {{ background: {C['button_hover']}; }}
    QPushButton:disabled {{ color: {C['faint']}; }}
    QPushButton#primary {{ background: {C['accent']}; color: white; border: 1px solid {C['accent']};
        font-weight: 600; padding: 8px 22px; }}
    QPushButton#primary:hover {{ background: {C['accent_hover']}; border-color: {C['accent_hover']}; }}
    QPushButton#primary:disabled {{ background: {C['track']}; border-color: {C['track']}; color: {C['faint']}; }}
    QPushButton#danger {{ background: {C['danger_soft']}; color: {C['danger']}; border: 1px solid {C['danger_soft']};
        font-weight: 600; padding: 8px 22px; }}
    QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {C['sub']}; }}
    QPushButton#ghost:hover {{ background: {C['button_hover']}; color: {C['text']}; }}
    QPushButton#ghost:disabled {{ color: {C['faint']}; }}
    QFrame#segment {{ background: {C['input']}; border-radius: 9px; }}
    QPushButton#seg {{ background: transparent; border: none; border-radius: 7px; padding: 5px 12px;
        color: {C['sub']}; }}
    QPushButton#seg:checked {{ background: {C['card']}; color: {C['text']}; font-weight: 600; }}
    QMenu {{ background: {C['card']}; border: 1px solid {C['border']}; border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 6px; color: {C['text']}; }}
    QMenu::item:selected {{ background: {C['hover']}; }}
    QToolTip {{ background: {C['card']}; color: {C['text']}; border: 1px solid {C['border']};
        border-radius: 8px; padding: 8px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
    QScrollBar::handle:vertical {{ background: {C['track']}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {C['faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QMessageBox {{ background: {C['card']}; }}
    """)
