"""Exact Dashboard Build20 receipt method snapshot; globals supplied by the test."""
def receipt(self, node, payload):
    if not isinstance(payload, dict) or set(payload) != {'version', 'cancellation_id', 'request_hash', 'status'} or type(payload['version']) is not int or (payload['version'] != 1) or (payload['status'] != 'received'):
        raise ValueError('Invalid cancellation delivery receipt.')
    with storage_lock(self.config):
        s = self.read()
        batch = s['cancellations'].get(payload['cancellation_id'])
        t = batch.get('targets', {}).get(node) if batch else None
        if not t or t['request_hash'] != payload['request_hash'] or (not t.get('sent_utc')):
            raise ValueError('Cancellation receipt does not match a request delivered to this Agent.')
        t.setdefault('received_utc', stamp())
        batch['complete'] = all((v.get('received_utc') for v in batch['targets'].values()))
        row = s['workspaces'].get(batch['kind'])
        if batch['complete'] and row and (row.get('cancellation_id') == payload['cancellation_id']):
            s['workspaces'].pop(batch['kind'])
        self.write(s)
