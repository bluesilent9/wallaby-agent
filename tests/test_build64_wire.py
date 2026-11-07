"""Signed public history over the actual authorised receiving socket."""
import copy,io,socket,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_build64 import NativeHistory
from test_build8 import paired,signed
from wallet_ops import rpc
from approval_store import Store,digest
from peer_wallet import wallet_details,frame_read,frame_write,socket_path
from wallet_preview import receive,fingerprint
from sync_queue import apply_snapshot,choose
from batch_transfer import BatchTransfer
from chain_sync import send
from history_wire import export
from local_extinction import prepare,complete
from retirement_phases import imports
from wallet_recovery import staging_timestamp
from regtest_support import Regtest

class SignedHistory(NativeHistory):
 def transfer(self,allow):
  # Preserve the original history into the sender's Core archive first.
  rows=self.rows();imports(self.core,self.p,timestamp=staging_timestamp(self.core),only_missing=True)
  from core_history import install
  install(self.core,self.store,'Wallaby Extinct',rows,self.p['manifest'])
  node=Regtest();self.addCleanup(node.close)
  receiver=Store(self.store.root/'receiving')
  p=paired('Wallaby Extinct');p['source_has_private_keys']=False;p['public_wallet']=rpc(self.core,'listdescriptors',[False],'Wallaby Extinct')
  # The live receiver's keys are pinned to the independently signed sender preview.
  facts=wallet_details(self.core,{**p,'direction':'send'},self.store);apply_snapshot(receiver,1,[p]);key=digest(p);choose(receiver,key,True,True)
  proof=signed(self.store,p,facts);receive(receiver,proof)
  if allow:
   retired={**self.p,'public_wallet':p['public_wallet']};ident=prepare(receiver,retired,['Old']);complete(receiver,ident)
  t=BatchTransfer(node.core,receiver);self.addCleanup(t.close)
  with patch('batch_transfer.readiness',return_value={'listening':True}),patch('peer_wallet.readiness',return_value={'listening':True}):t.authorise_batch({key:fingerprint(proof['public_key'])})
  with tempfile.TemporaryDirectory() as folder:
   file,header=export(self.core,self.store,p,facts,folder)
   with socket.socket(socket.AF_UNIX) as sock:
    sock.settimeout(60);sock.connect(str(socket_path(receiver)));stream=sock.makefile('rwb',buffering=0)
    frame_write(stream,{'operation':'manifest','transfer_id':p['transfer_id'],'peer_ipv6':p['peer']['ipv6'],'details':facts,'watch_only':True})
    self.assertEqual(frame_read(stream)['status'],'review_required');self.assertIn('core_history_v1',frame_read(stream)['features'])
    send(self.core,stream,frame_read,frame_write);frame_write(stream,header);stream.write(file.read_bytes());stream.flush();result=frame_read(stream);frame_write(stream,{'status':'confirmed'})
  t.thread.join(10);self.assertFalse(t.thread.is_alive(),t.error)
  self.assertTrue(rpc(node.core,'getnetworkinfo')['networkactive'])
  if allow:
   self.assertEqual(result['status'],'loaded',result);self.assertEqual(rpc(node.core,'getwalletinfo',[],'Wallaby Extinct')['txcount'],2)
   from retirement_phases import readback
   readback(node.core,self.p);self.assertIn(key,receiver.read()['completed'])
  else:
   self.assertEqual(result['status'],'history_deferred');self.assertNotIn('Wallaby Extinct',rpc(node.core,'listwallets'));self.assertNotIn(key,receiver.read()['completed'])
 def test_signed_native_history_transfers_after_local_extinction(self):self.transfer(True)
 def test_signed_history_is_deferred_without_local_extinction(self):self.transfer(False)
 def test_extinct_original_restores_only_after_verified_direct_private_transfer(self):
  from local_extinction import restoration,eligible
  rpc(self.core,'encryptwallet',['fixture-only-password'],'Old')
  node=Regtest();self.addCleanup(node.close);receiver=Store(self.store.root/'restore-receiver')
  p=paired('Old');p['public_wallet']=rpc(self.core,'listdescriptors',[False],'Old');p['source_has_private_keys']=True
  ident=prepare(receiver,{**self.p,'public_wallet':p['public_wallet']},['Old']);complete(receiver,ident);self.assertTrue(restoration(receiver,p['public_wallet']))
  facts=wallet_details(self.core,{**p,'direction':'send'},self.store);apply_snapshot(receiver,1,[p]);key=digest(p);choose(receiver,key,True,False);proof=signed(self.store,p,facts);receive(receiver,proof)
  t=BatchTransfer(node.core,receiver);self.addCleanup(t.close)
  with patch('batch_transfer.readiness',return_value={'listening':True}),patch('peer_wallet.readiness',return_value={'listening':True}):t.authorise_batch({key:fingerprint(proof['public_key'])})
  with tempfile.TemporaryDirectory() as folder:
   file=Path(folder)/'encrypted.dat';rpc(self.core,'backupwallet',[str(file)],'Old');raw=file.read_bytes()
   import hashlib
   with socket.socket(socket.AF_UNIX) as sock:
    sock.settimeout(60);sock.connect(str(socket_path(receiver)));stream=sock.makefile('rwb',buffering=0)
    frame_write(stream,{'operation':'manifest','transfer_id':p['transfer_id'],'peer_ipv6':p['peer']['ipv6'],'details':facts,'watch_only':False});self.assertEqual(frame_read(stream)['status'],'review_required');self.assertFalse(frame_read(stream)['watch_only'])
    send(self.core,stream,frame_read,frame_write);frame_write(stream,{'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()});stream.write(raw);stream.flush();result=frame_read(stream);self.assertEqual(result['status'],'loaded',result);frame_write(stream,{'status':'confirmed'})
  t.thread.join(10);self.assertEqual(receiver.read()['local_retirements'][ident]['state'],'restored');self.assertFalse(restoration(receiver,p['public_wallet']))
  info=rpc(node.core,'getwalletinfo',[],'Wallaby Sync '+p['transfer_id'][:24]);self.assertTrue(info['private_keys_enabled']);self.assertEqual(info['unlocked_until'],0);self.assertEqual(info['txcount'],2)
  from vendor.embit.descriptor.checksum import checksum
  fixed={'wallet_name':'Wallaby Extinct','descriptors':[{'desc':(body:='addr('+row['address']+')')+'#'+checksum(body)} for row in self.p['manifest']['addresses']]}
  with self.assertRaisesRegex(ValueError,'completed extinction'):eligible(node.core,receiver,fixed)
