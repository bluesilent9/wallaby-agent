const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
class E{constructor(tag,props,...children){this.tag=tag;this.props=props;this.children=children.flat().filter(x=>x!=null);}append(...c){this.children.push(...c);}replaceChildren(...c){this.children=c;}addEventListener(){}}
const text=n=>n instanceof E?n.children.map(text).join(' '):String(n),nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new E('div',{}));return nodes.get(id);};
const c={window:{},$:get,initialPage:'services',document:{querySelector:get,querySelectorAll:()=>[]},notify(){},calls:[],api:async(action,data)=>{c.calls.push([action,data]);return{};}};
vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/workspace.js'),'utf8'),c);c.el=(...a)=>new E(...a);c.button=(label,klass,action)=>{const e=new E('button',{},label);e.action=action;return e;};
c.fixture={pending:[{id:'urgent',kind:'wallet_rename',wallet_name:'Pending vault',state:'pending'}],setups:[],exclusions:[{wallet_name:'Excluded wallet',policy_id:'excluded'}],obsolete_sync_denials:[{wallet_name:'Old extinct child'}],denied:[{id:'declined',wallet_name:'Declined wallet',proposal:{kind:'wallet_setup'}}]};
vm.runInContext('workspace=fixture;renderApprovals()',c);
assert(text(get('#approval-list')).includes('Pending vault'));for(const name of ['Excluded wallet','Old extinct child','Declined wallet'])assert(!text(get('#approval-list')).includes(name));
assert(text(get('#sync-denials')).includes('Excluded wallet'));assert(text(get('#sync-denials')).includes('Old extinct child'));assert(text(get('#denied-list')).includes('Declined wallet'));
const html=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8'),authorise=html.slice(html.indexOf('<section id="page-authorise"'),html.indexOf('<section id="page-burn"'));
const ids=['approval-list','approval-review','local-wallets-list','authorisation-denials','sync-denials','denied-list'].map(id=>authorise.indexOf('id="'+id+'"'));assert(ids.every(i=>i>=0));assert.deepEqual([...ids].sort((a,b)=>a-b),ids);
const buttons=(n)=>n instanceof E?[...(n.tag==='button'?[n]:[]),...n.children.flatMap(buttons)]:[];
(async()=>{for(const root of ['#sync-denials','#denied-list'])for(const b of buttons(get(root)))await b.action();assert.deepEqual(c.calls.map(x=>x[0]),['authorise/clear-extinct-denials','authorise/enable-sync','authorise/forget']);assert.equal(c.calls[1][1].id,'excluded');assert.equal(c.calls[2][1].id,'declined');
 c.fixture.pending=[];vm.runInContext('approvalSignature="";renderApprovals()',c);assert(text(get('#approval-list')).includes('No requests awaiting authorisation.'));assert(text(get('#sync-denials')).includes('Excluded wallet'));
 c.fixture.exclusions=[];c.fixture.obsolete_sync_denials=[];c.fixture.denied=[];vm.runInContext('renderApprovals()',c);assert.equal(get('#sync-denials').children.length,0);assert.equal(get('#denied-list').children.length,0);
 console.log('Authorise order: pending reviews and local wallets precede all denial sections; denial controls retained; cleared records do not linger. Passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
