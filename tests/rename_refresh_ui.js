// Execute the shipped rename handlers and wallet-card renderer together.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
class Element{
 constructor(tag='div',props={},...children){this.tag=tag;this.props={...props};this.children=children.flat().filter(x=>x!=null);this.events={};this.checked=false;this.disabled=false;}
 append(...items){this.children.push(...items.flat().filter(x=>x!=null));}replaceChildren(...items){this.children=items;}
 setAttribute(k,v){this.props[k]=v;}addEventListener(k,v){this.events[k]=v;}showModal(){this.open=true;}close(){this.open=false;}remove(){this.removed=true;}focus(){}
}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},el=(...a)=>new Element(...a),all=n=>[n,...n.children.filter(x=>x instanceof Element).flatMap(all)],text=n=>n instanceof Element?n.children.map(text).join(' '):String(n);
let wallet='treasury',next='Treasury (2022 - 2026)',watch=false,fail=false,blockedRead=null,calls=[],page='authorise';
const wallets=()=>[{wallet,sats:'123450000',private_keys_enabled:!watch,deletable:true},{wallet:'SMSF',sats:'500',private_keys_enabled:true,deletable:true}];
const c={window:{},$:get,el,approvalSignature:'',pipe:n=>'pipe '+n,notify(){},showPage:p=>page=p,denyButton:()=>el('button',{},'Deny'),run:async f=>f(),button:(label,klass,action)=>{const b=el('button',{class:klass},label);b.action=action;return b;},document:{body:el('body'),createElementNS:(ns,tag)=>el(tag),querySelectorAll:()=>[]},api:async(route,args)=>{
 calls.push({route,args});if(route==='authorise/local-wallets'){if(blockedRead){const fn=blockedRead;blockedRead=null;return fn();}return {wallets:wallets()};}
 if(route==='authorise/rename'||route==='authorise/reconcile-rename'){if(fail)throw Error('Rename refused');if(args.id!=='disc')wallet=next;return {message:'Verified',burn_authorised:args.id==='disc'};}
 if(route==='authorise/delete-wallet-review')return {wallet:args.wallet,sats:'123450000',private_keys_enabled:!watch,token:'review-only'};
 throw Error('Unexpected API '+route);
}};
vm.createContext(c);for(const file of ['local_wallets.js','rename.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../web',file),'utf8'),c);
function review(id='rename',extra={}){const box=el('section');c.window.renderRenameApproval({id,kind:'wallet_rename',rename:{wallet,new_wallet:next,storage:'node',private_keys_enabled:!watch,chain:'regtest',policy_identity:'local policy',public_wallet:{},...extra}},box);return box;}
const approve=box=>all(box).find(e=>e.tag==='button'&&text(e)==='Approve wallet rename');
(async()=>{
 await c.window.loadLocalWallets();assert.match(text(get('#local-wallets-list')),/treasury/);
 await approve(review()).action();let list=get('#local-wallets-list');assert.match(text(list),/Treasury \(2022 - 2026\)/);assert(!/treasury/.test(text(list)));assert.match(text(list),/SMSF/);assert.match(text(list),/pipe 123450000/);
 let bin=all(list).find(e=>e.props['aria-label']==='Delete local wallet '+wallet);assert(bin);await bin.action();assert.equal(calls.at(-1).args.wallet,'Treasury (2022 - 2026)');assert(!calls.some(x=>x.route==='authorise/delete-wallet'));
 // An earlier inventory request must not reinsert the old name after approval.
 const old=wallets();let release;blockedRead=()=>new Promise(resolve=>release=resolve);const pending=c.window.loadLocalWallets();next='Treasury newer';await approve(review()).action();
 const renders=[],replace=list.replaceChildren.bind(list);list.replaceChildren=(...items)=>{renders.push(items.map(text).join(' '));replace(...items);};release({wallets:old});await pending;assert.equal(renders.length,1);assert(renders[0].includes('Treasury newer'));assert(!renders[0].includes('Treasury (2022 - 2026)'));assert.match(text(list),/SMSF/);
 // The same refresh applies to watch copies and preserves the watch-only eye.
 watch=true;next='Treasury old_watch';await approve(review()).action();assert.match(text(list),/Treasury old_watch/);assert.equal(all(list.children[0]).filter(e=>e.props['aria-label']==='Watch-only wallet').length,1);
 // A refused rename does not pretend that its new name has been applied.
 fail=true;next='Must not appear';const count=calls.filter(x=>x.route==='authorise/local-wallets').length;await assert.rejects(approve(review()).action(),/Rename refused/);assert.equal(calls.filter(x=>x.route==='authorise/local-wallets').length,count);assert(!text(list).includes(next));fail=false;
 next='Reconciled Treasury_watch';const box=review('reconcile',{reconciliation:true,actual_wallet:next,applied:true,loaded:true,stage:'reload',error_code:'core_or_verification'});all(box).find(e=>e.tag==='input').checked=true;await all(box).find(e=>e.tag==='button'&&text(e)==='Load, verify and resolve').action();assert(text(list).includes(next));
 const before=calls.filter(x=>x.route==='authorise/local-wallets').length;const disc=review('disc',{storage:'disc',archive_skip_allowed:true});await all(disc).find(e=>e.tag==='button'&&text(e)==='Approve rename and archive choice').action();assert.equal(page,'burn');assert.equal(calls.filter(x=>x.route==='authorise/local-wallets').length,before);
 console.log('Rename-to-card integration: private/watch names, unchanged balances/sibling cards, current delete-review target, stale in-flight inventory, refusal, reconciliation and disc routing passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
