const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{constructor(tag,props={},children=[]){this.tag=tag;this.props=props;this.items=children.flat().filter(x=>x!==null);this.checked=false;}append(...xs){this.items.push(...xs);}replaceChildren(...xs){this.items=xs;}}
const target=new Element('div'),actions=[];
const sandbox={window:{},el:(tag,props,...xs)=>new Element(tag,props,xs),button:(label,klass,action)=>{const b=new Element('button',{class:klass},[label]);b.action=action;actions.push(b);return b;},$:()=>target,api:async()=>({message:'Cancelled'}),notify(){},approvalSignature:'fixture'};
vm.createContext(sandbox);vm.runInContext(fs.readFileSync(require('path').join(__dirname,'../web/cancellation.js'),'utf8'),sandbox);
function render(detected){actions.length=0;const box=new Element('section');sandbox.window.renderCancellation({id:'fixture',cancellation:{builder:'transaction',broadcast_detected:detected,broadcast_incomplete:!detected,broadcasts:[],wallets:[],psbts:[],untracked_operations:[],untracked_exports:[],active_disc_write:false}},box);return box;}
const first=render(true);assert(first.items.some(x=>x instanceof Element&&x.props.class==='warning broadcast-detected'&&x.items.includes('Broadcast PSBTs from this Transaction Build have been detected')));
assert.deepEqual(actions.map(b=>b.items[0]),['Delete and Cancel','Backup and Cancel']);assert.equal(actions[0].props.class,'cancel-delete');assert.equal(actions[1].props.class,'cancel-backup');
const second=render(false);assert(second.items.some(x=>x instanceof Element&&x.items.includes('No broadcast PSBTs from this Transaction Build have been detected')));
(async()=>{await actions[0].action();await actions[1].action();console.log('Cancellation UI: local choices, direct reviewed deletion and red broadcast warning passed.');})().catch(e=>{console.error(e);process.exitCode=1;});
