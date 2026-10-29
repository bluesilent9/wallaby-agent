"""Public address-book facts read from Core, included in the signed wallet review."""
import re
from build8_policy import descriptors
from wallet_ops import rpc
from vendor.embit.script import address_to_scriptpubkey


def fixed_address(desc):
    body=desc.split('#')[0];match=re.fullmatch(r'addr\(([^()]{1,128})\)',body)
    if not match:return None
    try:address_to_scriptpubkey(match[1])
    except Exception:raise ValueError('Invalid fixed address.') from None
    return match[1]


def address_only(raw):return all(fixed_address(r['desc']) for r in raw['descriptors'])


def validate_labels(rows):
    if not isinstance(rows,list) or len(rows)>10000:raise ValueError('Too many address labels.')
    seen=set()
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'address','label','is_change'} or type(row['is_change']) is not bool:raise ValueError('Invalid public address label.')
        address=row['address'];label=row['label']
        if not isinstance(address,str) or len(address)>128 or address in seen:raise ValueError('Duplicate or invalid labelled address.')
        try:address_to_scriptpubkey(address)
        except Exception:raise ValueError('Invalid labelled address.') from None
        seen.add(address)
        if not isinstance(label,str) or len(label)>256 or any(ord(c)<32 for c in label):raise ValueError('Invalid public label.')
    return rows


def read_labels(core,name,raw,outputs):
    wanted=descriptors(raw);addresses={r['address'] for r in outputs}
    fixed={fixed_address(row['desc']) for row in raw['descriptors']};fixed.discard(None);addresses|=fixed
    for label in rpc(core,'listlabels',[],name):
        if len(addresses)>10000:raise ValueError('Wallet has too many labelled addresses.')
        for address in rpc(core,'getaddressesbylabel',[label],name):
            info=rpc(core,'getaddressinfo',[address],name)
            if not (info.get('ismine') or info.get('iswatchonly')):continue
            if address in fixed:addresses.add(address);continue
            parent=info.get('parent_desc')
            if parent:
                try:
                    if descriptors({'wallet_name':name,'descriptors':[{'desc':parent}]})<=wanted:addresses.add(address)
                except ValueError:continue
    result=[]
    for address in sorted(addresses):
        info=rpc(core,'getaddressinfo',[address],name)
        if not (info.get('ismine') or info.get('iswatchonly')):continue
        labels=info.get('labels',[])
        if not isinstance(labels,list) or len(labels)>1 or any(not isinstance(label,str) for label in labels):raise ValueError('Core returned ambiguous address labels.')
        result.append({'address':address,'label':labels[0] if labels else '','is_change':bool(info.get('ischange'))})
    validate_labels(result);return result


def apply_labels(core,name,rows,write):
    validate_labels(rows)
    for row in rows:
        info=rpc(core,'getaddressinfo',[row['address']],name)
        if not (info.get('ismine') or info.get('iswatchonly')):raise ValueError('A labelled address is not controlled or monitored by the imported wallet.')
        if write and not row['is_change']:rpc(core,'setlabel',[row['address'],row['label']],name)
        labels=rpc(core,'getaddressinfo',[row['address']],name).get('labels',[])
        if (labels[0] if labels else '')!=row['label']:raise ValueError('Address label for '+row['address']+' differs from the approved preview. Expected '+repr(row['label'])+'; Core reports '+repr(labels)+'.')
