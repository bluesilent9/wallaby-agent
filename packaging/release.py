#!/usr/bin/python3
"""Build and verify one current installer and source bundle; no old release loop."""
import argparse,hashlib,io,json,shutil,stat,subprocess,tarfile,tempfile,zipfile
from pathlib import Path
from release_check import release_version
ROOT=Path(__file__).resolve().parents[1]

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
 version,number=release_version(ROOT)
 subprocess.run(['python3',str(ROOT/'packaging/build.py')],check=True)
 deb=next((ROOT/'dist').glob('wallaby-agent_'+version+'_*.deb'));sha=hashlib.sha256(deb.read_bytes()).hexdigest()
 sums=sha+'  '+deb.name+'\n';(ROOT/'dist/SHA256SUMS.txt').write_text(sums)
 with tempfile.TemporaryDirectory() as folder:
  extracted=Path(folder);subprocess.run(['dpkg-deb','-x',str(deb),folder],check=True);checked=0
  for tree in ('src','web'):
   for p in (ROOT/tree).rglob('*'):
    if not p.is_file() or '__pycache__' in p.parts or p.suffix=='.pyc':continue
    if p.read_bytes()!=(extracted/'usr/lib/wallaby-agent'/p.relative_to(ROOT)).read_bytes():raise ValueError('Package differs from current source: '+str(p))
    checked+=1
  for p in (extracted/'usr/share/doc/wallaby-agent').iterdir():
   if p.read_bytes()!=(ROOT/p.name).read_bytes():raise ValueError('Packaged document differs: '+p.name)
  for source,installed in [('packaging/secure_start.py','secure-start'),('packaging/secure_snap_ram.py','secure-snap-ram'),('packaging/configure_renames.py','configure-renames')]:
   if (ROOT/source).read_bytes()!=(extracted/'usr/lib/wallaby-agent'/installed).read_bytes():raise ValueError('Packaged helper differs')
 with tarfile.open(fileobj=io.BytesIO(subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(deb)]))) as tar:
  for member in tar:
   if member.uid or member.gid or member.mode&0o022:raise ValueError('Unsafe package ownership/mode: '+member.name)
 if subprocess.check_output(['dpkg-deb','-f',str(deb),'Version'],text=True).strip()!=version:raise ValueError('Package version differs')
 shutil.copy2(deb,out/deb.name);(out/('Wallaby_Agent_V2_Build'+str(number)+'_SHA256SUMS.txt')).write_text(sums)
 manifest=[]
 with zipfile.ZipFile(out/('Wallaby_Agent_V2_Build'+str(number)+'_Source.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
  for p in sorted(ROOT.rglob('*')):
   rel=p.relative_to(ROOT)
   if not p.is_file() or any(x in rel.parts for x in ('build','__pycache__','.git')) or p.suffix=='.pyc':continue
   raw=p.read_bytes();manifest.append({'path':str(rel),'mode':'100755' if p.stat().st_mode&stat.S_IXUSR else '100644','sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()});archive.write(p,ROOT.name+'/'+str(rel))
 (out/('Wallaby_Agent_V2_Build'+str(number)+'_Manifest.json')).write_text(json.dumps(manifest))
 result={'version':version,'sha256':sha,'bytes':deb.stat().st_size,'runtime_files_verified':checked,'manifest_files':len(manifest)}
 (out/('Wallaby_Agent_V2_Build'+str(number)+'_Verification.json')).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
