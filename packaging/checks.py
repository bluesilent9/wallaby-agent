#!/usr/bin/python3
"""Current feature checks. Never build or run historical releases."""
import argparse,os,sys,subprocess,unittest,time,tempfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('tests',nargs='*');options=parser.parse_args()
 sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
 temporary=tempfile.TemporaryDirectory(prefix='wallaby-checks-',dir='/tmp');scratch=Path(temporary.name)
 for key,name in [('TMPDIR','tmp'),('XDG_CONFIG_HOME','config'),('XDG_RUNTIME_DIR','runtime')]:
  folder=scratch/name;folder.mkdir(parents=True,exist_ok=True,mode=0o700);folder.chmod(0o700);os.environ[key]=str(folder)
 from archive_swap import exchange
 from wallet_deletion import remove
 original=subprocess.run
 def run(command,*args,**kw):
  if isinstance(command,(list,tuple)) and command and (Path(command[0]).name in ('kdialog','zenity') or any(str(v).endswith('secret_prompt.py') for v in command)):raise AssertionError('Tests must mock native password prompts.')
  return original(command,*args,**kw)
 def swap(a,b):
  if not Path(a['path']).is_relative_to(scratch/'tmp') or not Path(b['path']).is_relative_to(scratch/'tmp'):raise AssertionError('Test escaped temporary wallet storage')
  return exchange(a,b,[Path(a['path']).parent])
 def cleanup(r):
  if not Path(r['path']).is_relative_to(scratch/'tmp'):raise AssertionError('Test escaped temporary wallet storage')
  return remove(r,[Path(r['path']).parent],allow_extinct=True)
 names=options.tests or ['test_current_release','test_wallet_history','test_release_identity','test_local_wallets']
 start=time.monotonic();suite=unittest.defaultTestLoader.loadTestsFromNames(names)
 with patch('subprocess.run',side_effect=run),patch('archive_swap.swap',side_effect=swap),patch('archive_swap.cleanup',side_effect=cleanup):result=unittest.TextTestRunner(verbosity=2).run(suite)
 print('Current feature checks: %.2f seconds'%(time.monotonic()-start),flush=True)
 temporary.cleanup()
 return not result.wasSuccessful()
if __name__=='__main__':raise SystemExit(main())
