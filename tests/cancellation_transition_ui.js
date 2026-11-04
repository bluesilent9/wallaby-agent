// Actual shipped review/render/poll flow: cancellation replaces open creation controls.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
class E{constructor(tag,props={},...children){this.tag=tag;this.props=props;this.children=children.flat().filter(x=>x!=null);}append(...c){this.children.push(...c);}replaceChildren(...c){this.children=c;}addEventListener(){}}
const text=n=>n instanceof E?n.children.map(text).join(' '):String(n),all=n=>n instanceof E?[n,...n.children.flatMap(all)]:[],nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new E('div'));return nodes.get(id);};
let resolveReview;const calls=[];
const c={window:{},$:get,initialPage:'services',document:{querySelector:get,querySelectorAll:()=>[]},notify(){},api:async(route,body)=>{calls.push([route,body]);if(route==='authorise/review')return new Promise(resolve=>resolveReview=resolve);return{message:'Cancelled'};}};
vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/workspace.js'),'utf8'),c);c.el=(...a)=>new E(...a);c.button=(label,klass,action)=>{const b=new E('button',{},label);b.action=action;return b;};
c.window.renderWalletApproval=(r,box)=>{box.append(new E('p',{},'Old creation controls'),new E('button',{},'Deny'));get('#approval-review').replaceChildren(box);};vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/cancellation.js'),'utf8'),c);
const initial={id:'creation',kind:'wallet_setup',state:'pending'},cancel={id:'cancel',kind:'builder_cancel',state:'pending',replaces:['creation']},other={id:'other',kind:'wallet_rename',state:'pending'};
c.fixture={pending:[initial,other],denied:[],exclusions:[],setups:[]};vm.runInContext('workspace=fixture',c);
const setPending=rows=>{c.fixture.pending=rows;vm.runInContext('renderApprovals()',c);};
const review=id=>vm.runInContext('reviewApproval('+JSON.stringify(id)+')',c);
(async()=>{
 let request=review('creation');resolveReview({id:'creation',kind:'wallet_setup'});await request;assert(text(get('#approval-review')).includes('Old creation controls'));
 setPending([other,cancel]);let shown=text(get('#approval-review'));assert(shown.includes('This build was cancelled'));assert(!shown.includes('Old creation controls'));assert(!shown.includes('Deny'));assert(text(get('#approval-list').children[0]).includes('Builder cancellation'));
 let button=all(get('#approval-review')).find(x=>x.tag==='button'&&text(x)==='Review cancellation');assert(button);request=button.action();resolveReview({id:'cancel',kind:'builder_cancel',cancellation:{builder:'wallet',psbts:[],wallets:[],untracked_operations:[],untracked_exports:[],broadcasts:[],active_disc_write:false}});await request;
 shown=text(get('#approval-review'));assert(shown.includes('Delete and Cancel'));assert(shown.includes('Backup and Cancel'));assert(!shown.includes('Old creation controls'));
 let del=all(get('#approval-review')).find(x=>x.tag==='button'&&text(x)==='Delete and Cancel');assert(!all(get('#approval-review')).some(x=>x.tag==='input'&&x.props.type==='checkbox'));await del.action();assert.equal(calls.at(-1)[0],'authorise/cancel-build');assert.equal(calls.at(-1)[1].id,'cancel');assert.equal(calls.at(-1)[1].action,'delete');assert.equal(text(get('#approval-review')),'');
 // A creation response arriving after cancellation must never resurrect its controls.
 setPending([initial]);request=review('creation');const late=resolveReview;setPending([cancel]);late({id:'creation',kind:'wallet_setup'});await request;assert(!text(get('#approval-review')).includes('Old creation controls'));assert(text(get('#approval-review')).includes('Review cancellation'));
 // Removing a request for another reason clears it without guessing a cancellation.
 setPending([initial]);request=review('creation');resolveReview({id:'creation',kind:'wallet_setup'});await request;setPending([other]);assert.equal(text(get('#approval-review')),'');
 // A still-valid review survives unrelated arrivals; cancelled setup cards point to the same cancellation.
 setPending([initial]);request=review('creation');resolveReview({id:'creation',kind:'wallet_setup'});await request;setPending([initial,other]);assert(text(get('#approval-review')).includes('Old creation controls'));
 c.fixture.setups=[{id:'setup',name:'Unfinished vault',phase:'contributed',cancellation_id:'cancel'}];setPending([cancel]);assert(!text(get('#setup-list')).includes('Discard unfinished setup'));assert(text(get('#setup-list')).includes('Review cancellation'));
 c.fixture.setups=[{id:'setup',name:'Interrupted vault',phase:'installation_failed',cancellation_id:null}];setPending([]);assert(text(get('#setup-list')).includes('Installation failed'));assert(text(get('#setup-list')).includes('No automatic retry'));assert(!text(get('#setup-list')).includes('Work in progress'));assert(!text(get('#setup-list')).includes('Discard unfinished setup'));
 console.log('Cancellation transition: open creation replaced, cancellation priority/link, explicit cleanup consent, late-response rejection, unrelated review preservation and setup routing passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
