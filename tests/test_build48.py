"""Real xorriso output must advance progress before process completion."""
import tempfile,time,unittest
from pathlib import Path
from disc_backup import writer_bytes,write_stream,readback,WriterProgress

class WriterReports(unittest.TestCase):
 def test_actual_xorriso_and_legacy_prefix_and_decimal_reports(self):
  total=32*1024*1024
  for line,amount in [('xorriso : UPDATE :    8 of   32 MB written (fifo  0%) [buf  50%]   7.6x.',8*1024*1024),('1.5 of 32 MB written (fifo 99%)',1572864),('Track 01: 12 of 32 MB written (fifo 99%)',12*1024*1024)]:self.assertEqual(writer_bytes(line,total),amount)
  for line in ('Writing to pipe: 32 MB','Track 01: Total bytes read/written: 33554432/33554432','xorriso : UPDATE : Closing track/session.','Warning: 20 of 32 MB written','-5 of 32 MB written'):self.assertIsNone(writer_bytes(line,total))
 def test_pipe_acceptance_does_not_advance_physical_percentage(self):
  job={'written_bytes':0};p=WriterProgress(job);p.writer_report(writer_input_bytes=1000000)
  self.assertEqual(job['written_bytes'],0);self.assertEqual(job['writer_input_bytes'],1000000)
  p(500000);self.assertEqual(job['written_bytes'],500000);self.assertGreater(job['writer_last_progress_at'],0)
 def test_real_throttled_xorriso_reports_intermediate_progress_and_readback_passes(self):
  with tempfile.TemporaryDirectory() as tmp:
   target=Path(tmp)/'fixture';total=32*1024*1024;seen=[];job={'written_bytes':0}
   class Observe(WriterProgress):
    def __call__(self,count):super().__call__(count);seen.append(count)
   def source():
    for _ in range(32):yield bytes(1024*1024);time.sleep(.1)
   sha=write_stream('stdio:'+str(target),source(),total,Observe(job))
   self.assertTrue(any(0<n<total for n in seen),seen);self.assertEqual(seen[-1],total);self.assertEqual(job['writer_input_bytes'],total);self.assertTrue(job['writer_input_complete']);self.assertEqual(job['writer_status'],'finished');readback(str(target),total,sha)
