#!/usr/bin/python3
"""Native passphrase entry; no secrets in browser, arguments, logs or disk."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import json,os


def dialogue_type():
    from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,QDialogButtonBox
    from PyQt6.QtCore import Qt
    class PassphraseDialog(QDialog):
        def __init__(self,prompt,confirm=False):
            super().__init__();self.confirm=confirm
            self.setWindowTitle('Wallaby Agent · protected local authorisation')
            self.setMinimumWidth(560);layout=QVBoxLayout(self)
            label=QLabel(prompt);label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);layout.addWidget(label)
            self.fields=[];self.visibility=[]
            for title in (('Passphrase','Retype passphrase to confirm') if confirm else ('Passphrase',)):
                layout.addWidget(QLabel(title));row=QHBoxLayout();field=QLineEdit();field.setMaxLength(1025);field.setEchoMode(QLineEdit.EchoMode.Password)
                toggle=QPushButton('Show');toggle.setCheckable(True);toggle.setAutoDefault(False);toggle.setAccessibleName('Show or hide '+title.lower())
                def reveal(checked,field=field,toggle=toggle):
                    field.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password);toggle.setText('Hide' if checked else 'Show')
                toggle.toggled.connect(reveal);row.addWidget(field);row.addWidget(toggle);layout.addLayout(row);self.fields.append(field);self.visibility.append(toggle)
            self.error=QLabel('');self.error.setTextFormat(Qt.TextFormat.PlainText);self.error.setWordWrap(True);layout.addWidget(self.error)
            if confirm:layout.addWidget(QLabel('Use at least 12 characters. Both entries must match.'))
            self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
            self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);layout.addWidget(self.buttons)
            self.fields[0].setFocus()
        def accept(self):
            value=self.fields[0].text()
            if not value or len(value)>1024:
                self.error.setText('Enter a non-empty passphrase, up to 1024 characters.');self.fields[0].setFocus();return
            if self.confirm and len(value)<12:
                self.error.setText('Use at least 12 characters. You can edit both entries and try again.');self.fields[0].setFocus();return
            if self.confirm and value!=self.fields[1].text():
                self.error.setText('Passphrases did not match. Retype the confirmation and try again.');self.fields[1].clear();self.fields[1].setFocus();return
            super().accept()
        def secret(self):return self.fields[0].text()
        def clear(self):
            for toggle,field in zip(self.visibility,self.fields):toggle.setChecked(False);field.clear()
    return PassphraseDialog


def main():
    from protected_memory import enforce,root
    enforce()
    settings=json.loads(sys.stdin.buffer.readline(32768))
    if not isinstance(settings,dict) or set(settings)!={'prompt','confirm'} or not isinstance(settings['prompt'],str) or len(settings['prompt'])>8192 or type(settings['confirm']) is not bool:raise ValueError('Invalid native passphrase request.')
    for name in ('XDG_CACHE_HOME','XDG_DATA_HOME','XDG_CONFIG_HOME'):os.environ[name]=str(root()/'native-dialog')
    from PyQt6.QtWidgets import QApplication,QDialog
    app=QApplication([]);dialog=dialogue_type()(settings['prompt'],settings['confirm'])
    try:
        if dialog.exec()!=QDialog.DialogCode.Accepted:return 1
        # JSON framing preserves newlines/Unicode in the actual passphrase.
        sys.stdout.write(json.dumps(dialog.secret(),ensure_ascii=True));sys.stdout.flush();return 0
    finally:dialog.clear()

if __name__=='__main__':
    try:sys.exit(main())
    except Exception:sys.exit(2) # Never emit raw GUI/protection exceptions or secret data.
