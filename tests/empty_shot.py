import os as _os, sys as _sys
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import os, sys
os.environ["QT_QPA_PLATFORM"]="offscreen"; os.environ["SUBSYNC_ROOT"]="/tmp/ssroot2"; os.makedirs("/tmp/ssroot2", exist_ok=True)
sys.path.insert(0,_os.path.join(_REPO, "app"))
if __name__=="__main__":
    from PySide6.QtWidgets import QApplication
    import subsync.pipeline as P
    P.Engine.warm_up = lambda self: None
    app=QApplication([])
    from subsync import theme; theme.apply(app)
    from subsync.gui import MainWindow
    w=MainWindow(); w.resize(1100,600); w.show()
    for _ in range(20): app.processEvents()
    w.grab().save("/tmp/empty.png")
