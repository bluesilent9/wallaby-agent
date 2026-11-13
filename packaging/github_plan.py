#!/usr/bin/python3
"""Prepare incremental Git tree changes without uploading old releases again."""
import argparse,base64,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output-prefix',type=Path,required=True);a=p.parse_args()
 base=json.loads(a.base.read_text());manifest=json.loads(a.manifest.read_text());known={r['path']:r for r in base['tree'] if r['type']=='blob'};shas={r['sha'] for r in known.values()};wanted={r['path'] for r in manifest};entries=[];binary=[];removed=[]
 # Build 88 is the sole previous installer retained in the current tree.
 for path,old in known.items():
  if path not in wanted and path!='dist/wallaby-agent_2.0.0~dev88_amd64.deb':entries.append({'path':path,'mode':old['mode'],'type':'blob','sha':None});removed.append(path)
 for row in manifest:
  if row['path'] in known and known[row['path']]['sha']==row['sha'] and known[row['path']]['mode']==row['mode']:continue
  entry={'path':row['path'],'mode':row['mode'],'type':'blob'}
  if row['sha'] in shas:entry['sha']=row['sha'];entries.append(entry)
  elif row['path'].endswith('.deb'):binary.append(row)
  else:entry['content']=(ROOT/row['path']).read_text();entries.append(entry)
 chunks=[];chunk=[];size=0
 for e in entries:
  amount=len(json.dumps(e))
  if chunk and size+amount>60000:chunks.append(chunk);chunk=[];size=0
  chunk.append(e);size+=amount
 if chunk:chunks.append(chunk)
 prefix=str(a.output_prefix)
 for i,c in enumerate(chunks):Path(prefix+'-'+str(i)+'.json').write_text(json.dumps(c))
 if len(binary)!=1:raise ValueError('Expected one current installer')
 content=base64.b64encode((ROOT/binary[0]['path']).read_bytes()).decode();parts=[content[i:i+50000] for i in range(0,len(content),50000)]
 for i,part in enumerate(parts):Path(prefix+'-binary-'+str(i)+'.txt').write_text(part)
 plan={'chunks':len(chunks),'entries':len(entries),'removed':removed,'binary':binary[0],'binary_parts':len(parts)};Path(prefix+'-plan.json').write_text(json.dumps(plan));print(json.dumps({k:v for k,v in plan.items() if k!='removed'}));print('Obsolete paths removed:',len(removed))
if __name__=='__main__':main()
