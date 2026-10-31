# Build 21: native X close over the actual wire protocol

## Confirmed root cause

The protected viewer sent `time.monotonic()+4` to `ui.prepare_close`. The worker uses the shared `node_client.decode` JSON decoder, which preserves fractional numbers as `decimal.Decimal`. The admission guard accepted only exact `int` and `float` types. Consequently every normal fractional deadline was rejected as expired even when it was fresh. Build 20 changed the later timing check but did not fix this wire-type rejection. Its direct handler tests bypassed the decoder and missed the fault.

Build 21's viewer X and ordinary safe-stop helper use **ui.request_close with no arguments**. It contains no client-clock deadline or fractional value. The worker acquires its action lock without waiting behind another protected operation, verifies its protections, and applies the existing unfinished-work, archive and queued-result checks. It seals the workspace against new secret operations before acknowledging. The native QMainWindow close event accepts only an explicit `ok: true`; then the monitor disconnects the node, hands off sanitized logs and verifies RAM cleanup. This does not bypass protection or force-delete unfinished work.

For compatibility, an older viewer's `ui.prepare_close` request now accepts finite Decimal deadlines as well as int/float. Stale, nonnumeric, boolean, nonfinite and malformed requests still fail. The new native path does not use that compatibility branch.

A pre-Build21 worker reports the new action as unsupported. The ordinary stop helper can use its existing guarded `ui.close`, without sending another numeric deadline. Unknown old workers still require the existing protected idle inspection; unrelated errors are not bypassed.

## Getting unstuck on an older running installation

On the affected computer, the following invokes the same guarded backend action as the previously working ordinary-window button:

```
PYTHONPATH=/usr/lib/wallaby-agent/src python3 -c 'from secure_bridge import call; print(call("ui.close", timeout=60)["message"])'
```

It closes only tracked protected viewers after the local busy/delivery/archive gate passes. Normal monitor-driven node disconnection and cleanup follow. It does not kill the secure service or erase RAM past that gate. If it refuses, retain the workspace and finish/inspect the reported work instead of force-stopping it. The user confirmed this action closed the stuck wallet-laptop window.

The Build21 ordinary overlay additionally shows an escape button when the worker explicitly reports an open known-affected Build17–20 viewer. Its endpoint independently verifies the exact version/window state and runs the old guarded close before disabling the node and attempting safe cleanup. A refusal leaves the node untouched. Current/future/unknown open workers are not treated as affected legacy versions. For normal Build21 windows the X remains the normal close control and no ordinary close button is shown. The existing confirmed-window-loss/failed-cleanup recovery remains available.

## Verification and limits

Tests exercise the actual framed Unix socket, SO_PEERCRED check, JSON encoder and production Decimal-preserving decoder. They reproduce the original Build20 guard failure on a still-fresh deadline, verify the production viewer's argument-free call, exercise the exact native closeEvent body through that call, and check the worker's closing flag. Active work, queued signed results, malformed new arguments and stale legacy deadlines are refused. Fresh legacy Decimal deadlines work. Ordinary stop uses the same new argument-free gate. Legacy escape routing, ordering and busy refusal are tested independently.

An additional offscreen test uses the real PyQt6 QMainWindow and its actual close event, the shipped close-event source, and real framed worker IPC. Qt hides the window on success and keeps it visible on a busy refusal. OS protection evidence is substituted; the complete privileged Qt/systemd session on wallet-laptop still needs on-device confirmation after installation. No production wallet, installed service or pruning setting was modified during source/build testing. The user's manual guarded close was the only requested live recovery action.
