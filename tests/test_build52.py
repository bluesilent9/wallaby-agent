"""Drive-level verification must not trust a stale 2 KB Linux block capacity."""
import hashlib,os,stat,tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from disc_backup import image,optical_readback,readback
from disc_archive import plan,chunks

class DriveReadback(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);p=Path(tmp.name);d=p/'disc';d.mkdir();(d/'README').write_text('Disposable ISO prefix');iso=p/'iso';image(d,iso);package=p/'package';package.write_bytes(os.urandom(10000));self.layout=plan(iso,package,4*1024*1024);self.track=p/'track';sha=hashlib.sha256()
  with self.track.open('wb') as out:
   for part in chunks(iso,package,self.layout):out.write(part);sha.update(part)
  self.sha=sha.hexdigest();self.total=self.layout['total_bytes']
 def test_real_drive_reader_hashes_whole_raw_track_beyond_small_iso(self):
  progress=[];optical_readback('stdio:'+str(self.track),self.total,self.sha,progress.append);self.assertEqual(progress[-1],self.total);self.assertGreater(self.total,1024*1024)
 def test_stale_two_kb_kernel_capacity_does_not_limit_drive_read(self):
  original=optical_readback;progress=[];open_real=os.open;close_real=os.close;stat_real=os.stat
  with patch('disc_backup.os.stat',side_effect=lambda path,*a,**k:SimpleNamespace(st_mode=stat.S_IFBLK) if str(path)=='/dev/sr0' else stat_real(path,*a,**k)),patch('disc_backup.os.open',side_effect=lambda path,*a,**k:98 if str(path)=='/dev/sr0' else open_real(path,*a,**k)),patch('disc_backup.os.close',side_effect=lambda fd:None if fd==98 else close_real(fd)),patch('fcntl.ioctl',return_value=(2048).to_bytes(8,'little')),patch('disc_backup.optical_readback',side_effect=lambda d,n,s,p:original('stdio:'+str(self.track),n,s,p)),patch('disc_backup.os.readv',side_effect=AssertionError('Must not use stale block reads')):
   readback('/dev/sr0',self.total,self.sha,progress.append)
  self.assertEqual(progress[-1],self.total)
 def test_complete_checksum_mismatch_is_still_refused(self):
  with self.assertRaisesRegex(ValueError,'checksum differs'):optical_readback('stdio:'+str(self.track),self.total,'0'*64)
 def test_oversized_requested_read_is_never_accepted_as_complete(self):
  with self.assertRaises(ValueError):optical_readback('stdio:'+str(self.track),self.total+1024*1024,self.sha)
 def test_reader_error_refuses_even_matching_complete_bytes(self):
  original=subprocess.Popen
  def failed(command,**kwargs):
   self.assertIn('-indev',command);self.assertNotIn('-outdev',command);self.assertNotIn('-as',command);self.assertIn('what=disc',command);self.assertIn('max_lba='+str(self.total//2048-1),command)
   return original(['/usr/bin/python3','-c','import sys;sys.stdout.buffer.write(open(sys.argv[1],"rb").read());sys.exit(32)',str(self.track)],**kwargs)
  with patch('disc_backup.subprocess.Popen',side_effect=failed),self.assertRaisesRegex(ValueError,'reader exit 32'):optical_readback('/dev/sr0',self.total,self.sha)
 def test_rejected_nonsector_initial_read_does_not_pollute_checksum(self):
  original=os.readv;calls=0
  def transient(fd,views):
   nonlocal calls
   calls+=1
   if calls==1:return 512
   return original(fd,views)
  with patch('disc_backup.os.readv',side_effect=transient),patch('disc_backup.time.sleep'):readback(str(self.track),self.total,self.sha)
