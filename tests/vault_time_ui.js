const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
class E{constructor(tag,props,...children){this.tag=tag;this.props=props;this.children=children.flat().filter(x=>x!=null);}append(...c){this.children.push(...c);}addEventListener(){} }
const text=n=>n instanceof E?n.children.map(text).join(' '):String(n),el=(...a)=>new E(...a),node={addEventListener(){}};
const c={window:{},$:()=>node,el,initialPage:'authorise',document:{querySelector:()=>node,querySelectorAll:()=>[]}};vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/workspace.js'),'utf8'),c);
c.el=el;
const row={height:100,first_spend_block:101,status:'estimated',utc:'2026-11-04T01:10+00:00',local:'2026-11-04T12:10+11:00',local_zone:'AEDT',source:'Local block-header timestamp average',seconds_per_block:590,sample_blocks:157788,sample_days:1077,notice:'Rough estimate only.'};
c.rows=[row];let result=text(vm.runInContext('vaultTimes(rows)',c));for(const s of ['Vault height 100','101','UTC:','AEDT','Rough estimate','Local block-header'])assert(result.includes(s));assert(!result.includes('99%'));
c.rows=[{height:100,status:'unavailable',notice:'No local headers'}];result=text(vm.runInContext('vaultTimes(rows)',c));assert(result.includes('No local headers'));assert(!result.includes('undefined'));console.log('Vault review: local header source, rough estimate, UTC/local zones, CLTV boundary and unavailable state passed.');
// Exercise the actual Wallet Builder approval renderers, not just the time card.
E.prototype.replaceChildren=function(...children){this.children=children;};
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new E('div',{}));return nodes.get(id);};
c.$=get;c.button=(label,klass,action)=>new E('button',{class:klass},label);c.denyButton=()=>new E('button',{},'Deny');
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/wallet_setup.js'),'utf8'),c);
const setup={name:'Proposed vault',threshold:1,total:1,chain:'regtest',height:100,requires_disc:false,roles:[{id:'A',name:'Local signer',local:true,storage:'node',fingerprint:'SHA256:local'}],proposal_hash:'proposal',policy_hash:'policy',samples:[],receive_descriptor:'public receive',change_descriptor:'public change'};
for(const kind of ['wallet_setup','wallet_setup_policy']){
 const box=new E('section',{});c.window.renderWalletApproval({kind,id:'setup',setup,unlock_estimates:[row]},box);const shown=text(box);
 for(const s of ['Vault unlock · local estimate','UTC:','2026-11-04T01:10','2026-11-04T12:10','AEDT','Rough estimate only','Local block-header'])assert(shown.includes(s),kind+' missing '+s);
 assert(!shown.includes('99%'));assert(shown.includes('Block 100'));
}
let box=new E('section',{});c.window.renderWalletApproval({kind:'wallet_setup',id:'plain',setup:{...setup,height:null},unlock_estimates:[]},box);assert(text(box).includes('No height lock'));assert(!text(box).includes('Vault unlock ·'));
box=new E('section',{});c.window.renderWalletApproval({kind:'wallet_setup',id:'unavailable',setup,unlock_estimates:[{height:100,status:'unavailable',notice:'Local headers unavailable'}]},box);assert(text(box).includes('Local headers unavailable'));assert(!text(box).includes('undefined'));
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/archives.js'),'utf8'),c);
box=new E('section',{});c.window.renderArchiveApproval({kind:'wallet_policy_refresh',id:'refresh',refresh:{wallet:'Vault',height:100,threshold:1,total:1,policy_hash:'local',samples:[],scan_range:[0,999],funded_outputs:[],previous_descriptors:[],receive_descriptor:'receive',change_descriptor:'change'},unlock_estimates:[row]},box);assert(text(box).includes('Vault unlock · local estimate'));assert(text(box).includes('AEDT'));
console.log('Wallet Builder initial/final approvals and policy refresh: visible UTC/local estimates, plain wallets and unavailable-header states passed.');
