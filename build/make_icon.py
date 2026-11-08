import os as _os, sys as _sys
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import os, sys
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0,_os.path.join(_REPO, "app"))
from PySide6.QtWidgets import QApplication
app=QApplication([])
from subsync.gui import make_icon
make_icon(256).save(_os.path.join(_REPO, "build", "icon256.png"))
from PIL import Image
im=Image.open(_os.path.join(_REPO, "build", "icon256.png"))
im.save(_os.path.join(_REPO, "launcher", "app.ico"), sizes=[(16,16),(20,20),(24,24),(32,32),(40,40),(48,48),(64,64),(128,128),(256,256)])
print("icon ok")
