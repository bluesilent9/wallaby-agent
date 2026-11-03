"""Bounded RAM-only child output; export only fixed public failure explanations."""
from collections import deque
import threading
from diagnostics import LocalActionFailure

class StartupOutput:
    def __init__(self,stream):
        self.parts=deque(maxlen=16);self.stream=stream;self.recording=True
        self.thread=threading.Thread(target=self.drain,daemon=True);self.thread.start()
    def drain(self):
        try:
            while True:
                part=self.stream.read(2048)
                if not part:break
                if self.recording:self.parts.append(part)
        finally:self.stream.close()
    def text(self):
        return b''.join(tuple(self.parts)).decode(errors='replace').lower()
    def clear(self):
        self.recording=False;self.parts.clear()
    def failure(self,exit_code):
        self.thread.join(1)
        raw=self.text()
        cases=[
          (('error while loading shared libraries','symbol lookup error'),'core_runtime_libraries','The selected Bitcoin Core executable cannot load its runtime libraries. Install a compatible native Bitcoin Core executable; no disk fallback was used.'),
          (('permission denied','read-only file system','operation not permitted'),'core_startup_permissions','The offline Core process was denied access under workspace restrictions. Inspect the protected startup configuration; do not disable RAM or storage protection.'),
          (('cannot allocate memory','bad_alloc','out of memory'),'core_startup_memory','The offline Core process could not allocate memory within the protected workspace.'),
          (('unable to bind','address already in use','unable to start http server'),'core_startup_rpc_bind','The offline Core process could not bind its temporary loopback RPC port.'),
          (('unknown command line','unrecognized option','invalid parameter'),'core_startup_options','The selected Core executable rejected an offline-node startup option.'),
        ]
        code='core_startup_exit';message='The offline Core process exited before its local RPC became ready. No wallet passphrase was requested and no disk fallback was used.'
        for needles,category,explanation in cases:
            if any(n in raw for n in needles):code=category;message=explanation;break
        self.clear()
        return LocalActionFailure(code,message+' Exit status: '+str(exit_code)+'.')
