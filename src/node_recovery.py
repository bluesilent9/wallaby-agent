"""A single monotonic recovery budget; repeated failures never restart its clock."""
import math,threading,time
from diagnostics import describe

SECONDS=15

def notice(stage):
    return ('Connection issue between the agent and Bitcoin Core' if stage=='rpc'
            else 'Connection issue between agent and the Dashboard Server')

class Recovery:
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.lock=threading.RLock();self.reset()
    def reset(self):
        with self.lock:self.established=False;self.deadline=None;self.failure=None;self.expired=False;self.attempt=0
    def connected(self):
        with self.lock:
            if self.expired or self.deadline is not None and self.clock()>=self.deadline:return False
            self.established=True;self.deadline=None;self.failure=None;return True
    def lost(self,error):
        with self.lock:
            if not self.established or self.expired:return
            if self.deadline is None:self.deadline=self.clock()+SECONDS;self.failure=describe('dashboard',error)
    def tick(self):
        with self.lock:
            if self.deadline is not None and self.clock()>=self.deadline:self.expired=True
            return self.expired
    def snapshot(self):
        with self.lock:
            active=self.deadline is not None
            return {'active':active,'expired':self.expired,'remaining':max(0,math.ceil(self.deadline-self.clock())) if active else 0,'stage':self.failure.stage if self.failure else None,'code':self.failure.code if self.failure else None,'message':notice(self.failure.stage) if self.failure else '', 'attempt':self.attempt}
