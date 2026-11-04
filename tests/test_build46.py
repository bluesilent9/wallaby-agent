"""Actual native Qt dialogue logic; offscreen only, with invented passwords."""
import os,unittest,json,subprocess
os.environ['QT_QPA_PLATFORM']='offscreen'
from unittest.mock import patch
from types import SimpleNamespace
from PyQt6.QtWidgets import QApplication,QDialog,QLineEdit
from secret_prompt import dialogue_type
from wallet_setup import secret_dialog
APP=QApplication.instance() or QApplication([])

class ConfirmationRetry(unittest.TestCase):
 def dialog(self,confirm=True):
  d=dialogue_type()('Wallet Treasury · Signer Australia',confirm);self.addCleanup(d.clear);self.addCleanup(d.close);d.show();return d
 def test_mismatch_keeps_dialogue_original_entry_and_setup_callback_waiting(self):
  d=self.dialog();accepted=[];d.accepted.connect(lambda:accepted.append(True));d.fields[0].setText('fixture-long-password');d.fields[1].setText('wrong-confirmation');d.accept()
  self.assertTrue(d.isVisible());self.assertFalse(accepted);self.assertIn('did not match',d.error.text());self.assertEqual(d.fields[0].text(),'fixture-long-password');self.assertEqual(d.fields[1].text(),'')
  d.fields[1].setText('fixture-long-password');d.accept();self.assertEqual(accepted,[True]);self.assertEqual(d.result(),QDialog.DialogCode.Accepted)
 def test_show_hide_each_field_defaults_masked_and_clear_resets(self):
  d=self.dialog()
  for field,toggle in zip(d.fields,d.visibility):
   field.setText('fixture-long-password');self.assertEqual(field.echoMode(),QLineEdit.EchoMode.Password);toggle.click();self.assertEqual(field.echoMode(),QLineEdit.EchoMode.Normal);self.assertEqual(toggle.text(),'Hide');toggle.click();self.assertEqual(field.echoMode(),QLineEdit.EchoMode.Password)
  d.clear();self.assertTrue(all(not field.text() for field in d.fields))
 def test_empty_short_and_oversized_creation_entries_can_be_corrected(self):
  d=self.dialog()
  for value in ('','short','a'*1025):
   for field in d.fields:field.setText(value)
   d.accept();self.assertTrue(d.isVisible());self.assertTrue(d.error.text())
  for field in d.fields:field.setText('valid-fixture-password')
  d.accept();self.assertEqual(d.result(),QDialog.DialogCode.Accepted)
 def test_existing_unlock_has_visibility_but_no_creation_length_rule(self):
  d=self.dialog(False);self.assertEqual(len(d.fields),1);d.fields[0].setText('old');d.accept();self.assertEqual(d.secret(),'old');self.assertEqual(d.result(),QDialog.DialogCode.Accepted)
 def test_parent_framing_preserves_actual_newlines_and_unicode(self):
  secret='fixture\\n literal\n Unicode é password'
  with patch('wallet_setup.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(secret).encode())):self.assertEqual(secret_dialog('Fixture',{},True),secret)
 def test_missing_or_failed_native_helper_never_falls_back_to_browser_or_logs(self):
  with patch('importlib.util.find_spec',return_value=None),patch('wallet_setup.subprocess.run') as run,self.assertRaisesRegex(ValueError,'python3-pyqt6'):secret_dialog('Fixture',{},True)
  run.assert_not_called()
  with patch('wallet_setup.subprocess.run',return_value=SimpleNamespace(returncode=2,stdout=b'',stderr=b'raw-sensitive-error')),self.assertRaisesRegex(ValueError,'could not open') as error:secret_dialog('Fixture',{})
  self.assertNotIn('raw-sensitive',str(error.exception))
