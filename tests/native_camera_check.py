import sys,threading,json
from http.server import HTTPServer,BaseHTTPRequestHandler
import socket
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from protected_viewer import install_camera_permissions
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PyQt6.QtCore import QUrl,QTimer
class Server(HTTPServer):address_family=socket.AF_INET6
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(b'''<script>window.result=null;navigator.mediaDevices.getUserMedia({video:true,audio:false}).then(s=>{window.result={video:s.getVideoTracks().length,audio:s.getAudioTracks().length};s.getTracks().forEach(t=>t.stop());window.result.stopped=s.getTracks().every(t=>t.readyState==='ended')}).catch(e=>window.result={error:e.name+': '+e.message});</script>''')
 def log_message(self,*a):pass
server=Server(('::1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();origin='http://[::1]:'+str(server.server_port)
app=QApplication(sys.argv);page=QWebEnginePage();asked=[]
page.profile().setPersistentPermissionsPolicy(QWebEngineProfile.PersistentPermissionsPolicy.AskEveryTime)
install_camera_permissions(page,origin,lambda:asked.append(True) or True)
finished=[]
def got(value):
 if value is None:return
 finished.append(value);print(json.dumps({'native_camera':value,'confirmations':len(asked)}),flush=True);app.quit()
def poll():page.runJavaScript('window.result',got)
timer=QTimer();timer.timeout.connect(poll);timer.start(200);QTimer.singleShot(20000,app.quit);page.load(QUrl(origin));app.exec();server.shutdown()
assert len(asked)==1 and finished and finished[0]=={'video':1,'audio':0,'stopped':True},(asked,finished)
print('PASS native Qt WebEngine permission signal, exact IPv6 loopback origin, local confirmation and video-only fake camera capture; tracks stopped.')
