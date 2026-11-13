"""Refuse an installer whose visible badge and runtime versions disagree."""
import ast,re


def release_version(root):
    worker=ast.parse((root/'src/worker_upgrade.py').read_text())
    versions=[n.value.value for n in worker.body if isinstance(n,ast.Assign)
              and any(isinstance(t,ast.Name) and t.id=='VERSION' for t in n.targets)
              and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)]
    if len(versions)!=1 or not (match:=re.fullmatch(r'2\.0\.0~dev([1-9][0-9]*)',versions[0])):
        raise ValueError('The worker must define one valid release version.')
    version=versions[0];build=match[1]
    badges=re.findall(r'\bBUILD\s+([0-9]+)\b',(root/'web/index.html').read_text())
    if badges!=[build]:raise ValueError('The shared window badge does not match the package/worker build.')
    for name in ('app.py','runtime.py','node_client.py'):
        module=ast.parse((root/'src'/name).read_text());labels=[n.value.value for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PROCESS_BUILD' for t in n.targets) and isinstance(n.value,ast.Constant)]
        if labels!=[version]:raise ValueError('The loaded-process build label does not match the installer.')
    for name,minimum in (('app.py',2),('runtime.py',1),('node_client.py',1)):
        found=[]
        for node in ast.walk(ast.parse((root/'src'/name).read_text())):
            if not isinstance(node,ast.Dict):continue
            for key,value in zip(node.keys,node.values):
                if isinstance(key,ast.Constant) and key.value in ('version','X-Wallaby-Agent-Version') and isinstance(value,ast.Constant) and isinstance(value.value,str):found.append(value.value)
        if len(found)<minimum or any(v!=version for v in found):
            raise ValueError('Runtime version metadata differs from the release: '+name)
    return version,int(build)
