"""Current isolated Server/worker process fixture."""
import sys, os, json, time, threading, subprocess, tempfile, select, traceback, shutil, hashlib, base64
from pathlib import Path

def reply(v):
    print(json.dumps(v), flush=True)

def commands(handler):
    for line in sys.stdin:
        try:
            reply({'ok': True, 'result': handler(json.loads(line))})
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            reply({'ok': False, 'error': type(e).__name__ + ': ' + str(e)})

def dashboard(source, root, port='0'):
    sys.path.insert(0, source)
    from nodes import NodeRegistry, create_agent_server
    import node_health, wallet_preview as dashboard_preview, ast, inspect
    tree = ast.parse(inspect.getsource(dashboard_preview.validate))

    class RegtestNetwork(ast.NodeTransformer):

        def visit_Constant(self, node):
            return ast.copy_location(ast.Constant('regtest'), node) if node.value == 'main' else node
    exec(compile(ast.fix_missing_locations(RegtestNetwork().visit(tree)), 'regtest-only-preview-network', 'exec'), dashboard_preview.__dict__)
    clock = {'offset': 0}
    real_time = time.time
    time.time = lambda: real_time() + clock['offset']
    from vendor.embit.networks import NETWORKS
    NETWORKS['main'] = dict(NETWORKS['regtest'])
    original = node_health.classify
    node_health.classify = lambda info: original(dict(info, chain='main'))
    Path(root).mkdir(parents=True, exist_ok=True)
    registry = NodeRegistry(Path(root) / 'config.cfg')
    server = create_agent_server(registry, port=int(port), ipv4=False)
    server.start()
    original_exchange = registry.hub.exchange

    def measured_exchange(*args, **kwargs):
        started = time.monotonic()
        try:
            return original_exchange(*args, **kwargs)
        finally:
            elapsed = time.monotonic() - started
            if elapsed > 1:
                print('FIXTURE exchange elapsed_seconds=' + str(round(elapsed, 3)), file=sys.stderr, flush=True)
    registry.hub.exchange = measured_exchange

    def poll_nodes():
        while True:
            try:
                registry.ready_for_builders()
                (Path(root) / 'poll-evidence.json').write_text(json.dumps({'connections': len(registry.connections), 'health': len(registry.health.values), 'pending': len(registry.health.pending)}))
            except Exception:
                traceback.print_exc(file=sys.stderr)
            time.sleep(0.5)
    threading.Thread(target=poll_nodes, daemon=True).start()
    reply({'port': server.server_port, 'polling': 'production-health'})

    def control(c):
        if c['op'] == 'discover_identity':
            return registry.hub.wallet_builder.discover(foreground=True)
        if c['op'] == 'identity_status':
            data = registry.hub.wallet_builder.read()
            return {'eligible': len(registry.hub.wallet_builder.available()), 'identities': len(data['identities']), 'challenges': len(data['challenges']), 'connections': len(registry.connections), 'sessions': sorted((hashlib.sha256(t.encode()).hexdigest() for t in registry.connections))}
        if c['op'] == 'advance':
            clock['offset'] = c['seconds']
            return True
        if c['op'] == 'clear_profile':
            from profile_archive import ProfileArchive
            with registry.lock:
                ProfileArchive(registry.config).replace()
                registry.reset()
            return {'cleared': True}
        if c['op'] == 'status':
            state = registry.hub.read()
            result = {}
            for token, row in list(registry.connections.items()):
                node = row['node_id']
                entry = state['nodes'].get(node, {})
                summary = registry.hub.node_summary(node)
                result[row['hostname']] = {'id': node, 'permissions': summary['sync_permissions'], 'inventory': summary['inventory_ready'], 'inventory_error': summary['inventory_error'], 'wallets': len(registry.hub.inventories.get(node, {}).get('wallets', [])), 'queue': len(entry.get('sync_snapshot', [])), 'health': registry.health.status(row)}
            return {'nodes': result, 'requests': len(state['requests']), 'log': registry.log_text()[-6000:]}
        if c['op'] == 'stop':
            server.close()
            return True
        raise ValueError('Unknown fixture command')
    commands(control)
