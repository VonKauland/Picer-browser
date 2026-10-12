"""The default charcoal palette, with accent confined to actionable states."""

COLORS = {
    "background": "#171719",
    "title": "#242426",
    "text": "#F3F3F0",
    "menu": "#303032",
    "control": "#38383B",
    "border": "#454549",
    "hover": "#414145",
    "muted": "#A2A2A6",
    "accent": "#E8FF59",
}

CONTROLS = """
QPushButton, QToolButton { background: #38383B; color: #F3F3F0;
border: none; border-radius: 16px; padding: 8px 16px; min-height: 16px; }
QPushButton:hover, QToolButton:hover { background: #414145; }
QPushButton:pressed, QToolButton:pressed { background: #454549; }
QPushButton:disabled, QToolButton:disabled { background: #303032; color: #67676D; }
QPushButton:focus, QToolButton:focus { border: 1px solid #A2A2A6; }
QPushButton#primaryButton { background: #E8FF59; color: #242426; font-weight: 600;
border-radius: 18px; padding: 10px 20px; }
QPushButton#primaryButton:hover { background: #F0FF8A; }
QPushButton#dangerButton { background: transparent; color: #E98282; }
QPushButton#dangerButton:hover { background: #453238; }
QPushButton#quietButton { background: transparent; color: #A2A2A6; }
QPushButton#quietButton:hover { background: #38383B; color: #F3F3F0; }
QPushButton#circleButton { border-radius: 16px; padding: 0; }
QLineEdit, QSpinBox, QComboBox, QKeySequenceEdit { background: #38383B;
border: 1px solid #454549; border-radius: 12px; padding: 7px 12px;
min-height: 20px; color: #F3F3F0; selection-background-color: #E8FF59;
selection-color: #242426; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {
border: 1px solid #A2A2A6; }
QComboBox { combobox-popup: 0; }
QComboBox::drop-down { border: none; width: 22px; }
QSpinBox::up-button, QSpinBox::down-button { width: 18px; border: none; }
QAbstractItemView { background: transparent; border: none; outline: none; }
QFrame#picerComboPopup { background: transparent; border: none; }
QComboBox QAbstractItemView { background: #303032; border: none;
border-radius: 12px; padding: 6px; outline: none;
selection-background-color: #414145; selection-color: #F3F3F0; }
QComboBox QAbstractItemView QWidget { background: transparent; }
QComboBox QAbstractItemView::item { min-height: 22px; padding: 6px 12px; border-radius: 6px; }
QComboBox QAbstractItemView::item:selected { background: #414145; color: #F3F3F0; }
QTreeView::item, QListWidget::item { padding: 6px; border-radius: 8px; }
QTreeView::item:selected, QListWidget::item:selected {
background: #414145; color: #F3F3F0; border-left: 3px solid #E8FF59; }
QHeaderView::section { background: #303032; color: #A2A2A6; border: none; padding: 8px; }
QGroupBox { border: none; border-radius: 12px; margin-top: 20px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 0; color: #A2A2A6; }
QTextEdit, QScrollArea { background: transparent; border: none; }
QSlider { background: transparent; border: none; padding: 0; }
QSlider::groove:horizontal { background: #454549; border: none;
height: 4px; border-radius: 2px; }
QSlider::handle:horizontal { background: #E8FF59; width: 14px;
border: none; margin: -5px 0; border-radius: 7px; }
QSlider::groove:vertical { background: #454549; border: none;
width: 4px; border-radius: 2px; }
QSlider::handle:vertical { background: #E8FF59; height: 14px;
border: none; margin: 0 -5px; border-radius: 7px; }
QSlider::handle:disabled { background: #67676D; }
QScrollBar { background: transparent; width: 8px; height: 8px; }
QScrollBar::handle { background: #454549; border-radius: 4px;
min-height: 24px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QWidget#bindingPage, QWidget#touchMap, QTabWidget#inputTabs QStackedWidget {
background: transparent; border: none; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { background: transparent; color: #A2A2A6; padding: 10px 18px;
border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #F3F3F0; border-bottom: 2px solid #E8FF59; }
QTabBar::tab:hover { background: #38383B; border-radius: 8px; }
QTabWidget#inputTabs QTabBar::tab { padding: 8px 12px; }
QToolTip { color: #F3F3F0; background: #38383B; border: 1px solid #454549; padding: 6px; }
QMenu { background: #303032; color: #F3F3F0; border: none;
border-radius: 12px; padding: 6px; }
QMenu::item { padding: 9px 32px 9px 16px; border-radius: 6px; }
QMenu::item:selected { background: #414145; }
QMenu::item:disabled { color: #67676D; }
QMenu::separator { height: 1px; background: #454549; margin: 6px 10px; }
"""

STYLE = (
    """
QWidget { background: #242426; color: #F3F3F0; font-size: 13px;
font-family: 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif; }
QWidget#titleBar { background: #242426; }
QWidget#titleLeft, QWidget#titleRight, QWidget#windowControls, QLabel {
background: transparent; }
QDialog, QWidget#dialogHeader { background: transparent; }
QLabel#brand { font-size: 15px; font-weight: 600; }
QLabel#dialogHeading { font-size: 24px; font-weight: 600; }
QLabel#sectionHeading { font-size: 15px; font-weight: 600; }
QLabel#muted { color: #A2A2A6; }
QFrame#dialogSurface { background: #242426; border: 1px solid #454549; border-radius: 18px; }
QFrame#card { background: #303032; border: none; border-radius: 14px; }
QWidget#cardContent { background: #303032; border-radius: 14px; }
QLabel#typePill { color: #A2A2A6; background: #38383B; border-radius: 10px; padding: 3px 8px; }
QWidget#componentRow { background: transparent; }
QMenuBar { background: transparent; padding: 0; }
QMenuBar::item { padding: 8px 10px; background: transparent; }
QMenuBar::item:selected { background: #38383B; border-radius: 8px; }
QGraphicsView { border: none; background: #171719; }
QToolButton#quickSlot { border: none; border-radius: 14px; padding: 0;
background: transparent; color: #A2A2A6; font-size: 16px; }
QToolButton#quickSlot:hover { background: #38383B; }
QToolButton#quickSlot:disabled { color: #67676D; }
QMainWindow::separator { background: transparent; width: 0px; height: 0px; }
QLabel#empty { color: #A2A2A6; font-size: 15px; background: transparent; }
"""
    + CONTROLS
)


def accent_style(style, original, custom):
    """Replace only theme accent tokens; unrelated skin/plugin colors stay intact."""
    if not custom:
        return style
    import re

    from PySide6.QtGui import QColor

    hover = QColor(custom).lighter(120).name()
    replacements = {original.lower(): custom, "#f0ff8a": hover}
    style = re.sub(r"#[0-9a-fA-F]{6}", lambda m: replacements.get(m[0].lower(), m[0]), style)
    foreground = "#242426" if QColor(custom).lightnessF() > 0.5 else "#F3F3F0"
    return style + f"\nQPushButton#primaryButton {{ color: {foreground}; }}"
