"""Real offscreen QMainWindow close event plus production framed worker IPC.

No Bitcoin material or live services are used. OS evidence is mocked by the
NativeWire fixture; Qt, event acceptance, JSON and Unix socket are real.
"""
import ast,os,unittest
from pathlib import Path
from unittest.mock import Mock,patch
os.environ['QT_QPA_PLATFORM']='offscreen'
from PyQt6.QtWidgets import QApplication,QMainWindow
from test_build21 import NativeWire
import protected_viewer

class QtNativeClose(NativeWire):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def test_real_qmainwindow_closes_on_success_and_stays_visible_for_busy_refusal(self):
  source=ast.parse((Path(__file__).resolve().parents[1]/'src/protected_viewer.py').read_text());window=next(n for n in ast.walk(source) if isinstance(n,ast.ClassDef) and n.name=='Window');module=ast.fix_missing_locations(ast.Module(body=[window],type_ignores=[]))
  with patch.object(protected_viewer,'QMainWindow',QMainWindow,create=True),patch.object(protected_viewer,'QMessageBox',Mock(),create=True):
   exec(compile(module,'shipped-native-window','exec'),protected_viewer.__dict__)
   actual=protected_viewer.Window();actual.show();self.app.processEvents();self.assertTrue(actual.isVisible());self.assertTrue(actual.close());self.app.processEvents();self.assertFalse(actual.isVisible());self.assertTrue(self.worker.closing)
   self.worker.closing=False;self.worker.busy.return_value=True;blocked=protected_viewer.Window();blocked.show();self.app.processEvents();self.assertFalse(blocked.close());self.assertTrue(blocked.isVisible());self.assertFalse(self.worker.closing);protected_viewer.QMessageBox.information.assert_called_once()
   self.worker.busy.return_value=False;self.assertTrue(blocked.close());actual.deleteLater();blocked.deleteLater();self.app.processEvents()

if __name__=='__main__':unittest.main(verbosity=2)
