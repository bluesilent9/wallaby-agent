#!/usr/bin/python3
"""HTML5 Bitcoin pages inside the same non-swapping, write-restricted service."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import json,os
from protected_memory import enforce,root

def close_allowed():
    from secure_bridge import call
    import time
    try:return call('ui.prepare_close',time.monotonic()+4,timeout=6).get('ok') is True
    except ValueError:return False

def main():
    enforce();settings=json.loads(sys.stdin.buffer.readline(8192));origin=settings['origin'];token=settings['token']
    if not origin.startswith('http://127.0.0.1:') or settings['page'] not in ('authorise','synchronisation','burn','message'):raise SystemExit('Invalid local view.')
    # Keep Chromium's sandbox enabled. Disable only caching, persistence and dumps.
    os.environ['QTWEBENGINE_CHROMIUM_FLAGS']='--disable-gpu --disable-breakpad --disable-crash-reporter --disable-logging --noerrdialogs'
    os.environ['XDG_CACHE_HOME']=str(root()/'viewer-cache');os.environ['XDG_DATA_HOME']=str(root()/'viewer-data');os.environ['XDG_CONFIG_HOME']=str(root()/'viewer-config')
    from PyQt6.QtCore import QUrl
    from PyQt6.QtWidgets import QApplication,QMainWindow,QMessageBox
    from PyQt6.QtWebEngineCore import QWebEngineProfile,QWebEnginePage,QWebEngineUrlRequestInterceptor,QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    class Interceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self,info):
            url=info.requestUrl()
            if url.scheme()+ '://'+url.host()+':'+str(url.port())!=origin:info.block(True);return
            info.setHttpHeader(b'X-Wallaby-Protected-View',token.encode())
    app=QApplication(sys.argv);profile=QWebEngineProfile(app);profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache);profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
    profile.setCachePath(str(root()/'viewer-cache'));profile.setPersistentStoragePath(str(root()/'viewer-data'));interceptor=Interceptor(profile);profile.setUrlRequestInterceptor(interceptor)
    class Page(QWebEnginePage):
        def acceptNavigationRequest(self,url,kind,main):return url.toString().startswith(origin+'/')
        def createWindow(self,kind):return None
    class Window(QMainWindow):
        def closeEvent(self,event):
            if not close_allowed():
                QMessageBox.information(self,'Protected work is unfinished','Finish active wallet operations, wait for queued Dashboard deliveries and unload archival wallets before closing. Closing this window disconnects the node and clears its protected workspace.');event.ignore();return
            event.accept()
    view=QWebEngineView();page=Page(profile,view);view.setPage(page)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard,False);page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows,False)
    profile.downloadRequested.connect(lambda download:download.cancel());window=Window();window.setWindowTitle('Wallaby Agent · Protected Bitcoin Workspace');window.resize(1240,850);window.setCentralWidget(view);view.load(QUrl(origin+'/?page='+settings['page']));window.show();window.raise_();window.activateWindow();app.exec()

if __name__=='__main__':main()
