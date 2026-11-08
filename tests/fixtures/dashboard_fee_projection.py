"""Wallet Server Build20 public fee projection snapshot; no Wallet Server code changed."""
import heapq
from decimal import Decimal
def number(value):
    n = Decimal(str(value))
    if not n.is_finite() or n < 0:
        raise ValueError('Invalid fee quote')
    return format(n, 'f')

def project(entries, limit=4, capacity=999000):
    """Ancestor-package greedy block estimates. Dependencies precede children.

    This is an estimate of a node's local mempool, not Core's exact block
    assembler policy or a guarantee. Re-evaluate a package after an ancestor
    enters a block; don't count its size/fee twice.
    """
    if len(entries) > 50000:
        raise ValueError('Local mempool is too large for the bounded projection; fee recommendations remain available.')
    parents = {t: {p for p in e.get('depends', []) if p in entries} for t, e in entries.items()}
    anc = {}
    visiting = set()

    def ancestry(t):
        if t in anc:
            return anc[t]
        if t in visiting:
            raise ValueError('Cyclic mempool dependency')
        if len(visiting) > 500:
            raise ValueError('Mempool ancestry exceeds the projection complexity limit')
        visiting.add(t)
        value = {t}
        for p in parents[t]:
            value.update(ancestry(p))
        visiting.remove(t)
        if len(value) > 1000:
            raise ValueError('Mempool package exceeds projection complexity limit')
        anc[t] = value
        return value
    values = {t: (int(e['vsize']), satoshis(e['fees']['modified'])) for t, e in entries.items()}
    if any((s <= 0 for s, f in values.values())):
        raise ValueError('Invalid mempool virtual size')
    heap = []
    selected = set()
    blocks = []
    versions = {t: 0 for t in entries}
    children = {t: set() for t in entries}
    for t, ps in parents.items():
        for parent in ps:
            children[parent].add(t)

    def candidate(t):
        package = ancestry(t) - selected
        size = sum((values[p][0] for p in package))
        fee = sum((values[p][1] for p in package))
        return (-(Decimal(fee) / size) if size else Decimal(0), t, size, fee, package, versions[t])
    for t in sorted(entries):
        heapq.heappush(heap, candidate(t))
    for number_ in range(limit):
        used = 0
        fees = 0
        rates = []
        count = 0
        deferred = []
        while heap:
            old = heapq.heappop(heap)
            t = old[1]
            if t in selected or old[5] != versions[t]:
                continue
            value = candidate(t)
            if value[4] != old[4]:
                heapq.heappush(heap, value)
                continue
            rate, t, size, fee, package, version = value
            if used + size > capacity:
                deferred.append(value)
                continue
            selected.update(package)
            used += size
            fees += fee
            count += len(package)
            rates.append(-rate)
            affected = set()
            pending = list(package)
            while pending:
                parent = pending.pop()
                for child in children[parent]:
                    if child not in selected and child not in affected:
                        affected.add(child)
                        pending.append(child)
            for child in sorted(affected):
                versions[child] += 1
                heapq.heappush(heap, candidate(child))
        for value in deferred:
            heapq.heappush(heap, value)
        blocks.append({'index': number_, 'vsize': used, 'weight': used * 4, 'tx_count': count, 'fees_sats': fees, 'median_rate': number(sorted(rates)[len(rates) // 2]) if rates else '0', 'minimum_rate': number(min(rates)) if rates else '0', 'maximum_rate': number(max(rates)) if rates else '0', 'estimated_minutes': (number_ + 1) * 10})
        if not heap:
            break
    return blocks

def satoshis(value):
    n = Decimal(str(value)) * 100000000
    if not n.is_finite() or n != n.to_integral_value() or n < 0:
        raise ValueError('Invalid node Bitcoin amount')
    return int(n)
