// Exercise the shipped service controls without a browser, network, Core or services.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element{
 constructor(){this.value='';this.dataset={};this.parentElement=this;this.events={};this.attributes={};this.classList={toggle:(k,v)=>{this.attributes['class:'+k]=v;}};this.labels=[{textContent:'Fixture'}];}
 querySelector(s){this.children=this.children||{};return this.children[s]||(this.children[s]=new Element());}
 setAttribute(k,v){this.attributes[k]=v;}addEventListener(k,v){this.events[k]=v;}checkValidity(){return true;}append(...items){this.items=(this.items||[]).concat(items);}replaceChildren(){this.items=[];}
}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const rows=['ddns','dashboard','node'].map(id=>{const row=new Element();row.dataset={service:id};row.querySelector=s=>get(id+':'+s);return row;});
let requests=0;
let copied;const sandbox={navigator:{clipboard:{async writeText(text){copied=text;}}},console,URLSearchParams,location:{hash:'',search:'',pathname:'/'},history:{replaceState(){}},sessionStorage:{removeItem(){}},window:{},document:{querySelector:get,querySelectorAll:()=>rows,createElement:()=>new Element()},fetch:()=>{requests++;throw Error('Unexpected network request');},setTimeout(){},clearTimeout(){},setInterval(){}};
vm.createContext(sandbox);
const source=fs.readFileSync(require('path').join(__dirname,'../web/app.js'),'utf8').replace('refresh();setInterval(refresh,2000);','');vm.runInContext(source,sandbox);
const status=Object.fromEntries(['server','ddns','dashboard','node'].map(id=>[id,{color:'red',message:'Off'}]));
const state={config:{hostname:'server.example.com',ssh_user:'local',ssh_port:22,identity_file:'',cookie:'',rpc_port:8332,enabled:{ddns:false,dashboard:false,node:false}},status,workspace:{protected:{running:false,viewer:false}},node_support:{available:false,message:'Install optional viewer and configure Bitcoin Core RPC.'}};
sandbox.fixture=state;vm.runInContext('render(fixture)',sandbox);
assert.equal(get('node:.switch').attributes['aria-disabled'],'true');
assert.equal(get('node:.switch').attributes['aria-checked'],'false');
assert.equal(get('ddns:.switch').attributes['aria-disabled'],'false');
assert.equal(get('dashboard:.switch').attributes['aria-disabled'],'false');
assert.equal(get('#page-services').disabled,false);
get('node:.switch').events.click({currentTarget:get('node:.switch')});assert.equal(requests,0);assert.equal(get('node:.status-text').textContent,state.node_support.message);
state.config.enabled.node=true;vm.runInContext('render(fixture)',sandbox);assert.equal(get('node:.switch').attributes['aria-disabled'],'false');
console.log('Tunnel-only UI: node stays off with an actionable message; SSH controls stay usable; existing node can be switched off.');

const commandPanel=get('node:.service-copy').querySelector('.prerequisite-commands');
state.config.enabled.node=false;state.node_support.commands=['sudo apt install pkexec polkitd'];vm.runInContext('render(fixture)',sandbox);
const box=commandPanel.items[0];assert.equal(box.items[0].items[0].textContent,state.node_support.commands[0]);
(async()=>{await box.items[1].events.click();assert.equal(copied,state.node_support.commands[0]);assert.equal(box.items[2].textContent,'Copied');vm.runInContext('busy=true',sandbox);await vm.runInContext('refresh()',sandbox);assert.equal(requests,0);vm.runInContext('busy=false',sandbox);sandbox.window.workspaceChanging=true;await vm.runInContext('refresh()',sandbox);assert.equal(requests,0);console.log('Prerequisite command code box and Copy command button: passed.');
 sandbox.window.workspaceChanging=false;state.node_support={available:true};state.workspace={protected:{running:false,viewer:false}};state.config.enabled.node=false;
 let accept,reject;sandbox.testApi=(route)=>route==='state'?Promise.resolve(state):new Promise((resolve,fail)=>{accept=resolve;reject=fail;});vm.runInContext('api=(...args)=>testApi(...args);nodeFeedback=null;render(fixture)',sandbox);
 let pending=vm.runInContext("change('toggle',{service:'node',enabled:true},document.querySelector('[unused]'))",sandbox);await new Promise(setImmediate);
 assert.match(get('node:.status-text').textContent,/Starting protected workspace/);assert.equal(get('node:.dot').className,'dot amber');
 reject(Error('Protected workspace setup was cancelled.'));await pending;assert.equal(get('node:.dot').className,'dot red');assert.match(get('node:.status-text').textContent,/cancelled/);assert.equal(state.config.enabled.node,false);
 vm.runInContext('render(fixture)',sandbox);assert.match(get('node:.status-text').textContent,/cancelled/);
 pending=vm.runInContext("change('toggle',{service:'node',enabled:true},document.querySelector('[unused]'))",sandbox);await new Promise(setImmediate);state.config.enabled.node=true;state.status.node={color:'amber',message:'Checking Bitcoin Core RPC…'};accept({ok:true});await pending;
 assert.equal(get('node:.status-text').textContent,'Checking Bitcoin Core RPC…');assert.equal(get('node:.switch').attributes['aria-checked'],'true');console.log('Node toggle: preparation progress, retained local failure, retry and runtime diagnostics passed.');})().catch(e=>{console.error(e);process.exitCode=1;});
