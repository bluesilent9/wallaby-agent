// Exercise actual workspace button handlers and pending/success/failure rendering.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
class Element{
 constructor(){this.events={};this.attributes={};this.dataset={};this.classList={toggle:(key,value)=>this.attributes[key]=value};}
 addEventListener(key,action){this.events[key]=action;}
}
const elements=new Map(),get=key=>{if(!elements.has(key))elements.set(key,new Element());return elements.get(key);};
let result,error,message='',release,fail,available=true;
const fixture=()=>({connected:false,pending:[],denied:[],sync:'',outbox_count:0,transfer:{},protected:{running:available},busy:false});
const context={$:get,document:{querySelector:get,querySelectorAll:()=>[]},window:{},state:{node_support:{available:true}},initialPage:'services',busy:false,console,notify:e=>message=e?.message||'',api:()=>new Promise((resolve,reject)=>{release=resolve;fail=reject;}),refresh:async()=>context.window.updateWorkspace(fixture())};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/workspace.js'),'utf8'),context);
(async()=>{
 available=false;context.window.updateWorkspace(fixture());
 for(const name of ['authorise','synchronisation','burn','message'])assert.equal(get('[data-page="'+name+'"]').disabled,true);
 assert.equal(get('#protected-processing').hidden,true);
 vm.runInContext("showPage('authorise')",context);assert.equal(vm.runInContext('page',context),'services');assert.equal(get('#workspace-dot').className,'dot red');
 context.window.setWorkspaceAction('starting');assert.equal(get('#workspace-dot').className,'dot amber');
 available=true;context.window.updateWorkspace(fixture());context.window.setWorkspaceAction(null);assert.equal(get('#workspace-dot').className,'dot green');
 context.window.updateWorkspace({...fixture(),viewer_open:true});assert.equal(get('main').inert,true);assert.equal(get('aside').inert,true);assert.equal(get('#protected-window-lock').hidden,false);
 let pending=get('#close-protected-view').events.click();assert.match(get('#protected-lock-status').textContent,/disconnecting node/);release({message:'Closed view.'});await pending;assert.equal(get('main').inert,false);assert.equal(get('#protected-window-lock').hidden,true);
 context.window.updateWorkspace({...fixture(),viewer_open:true});pending=get('#close-protected-view').events.click();fail(Error('Finish active wallet work.'));await pending;assert.match(get('#protected-lock-status').textContent,/Finish active/);
 vm.runInContext("page='message'",context);context.window.updateWorkspace({...fixture(),protected:{running:true,viewer:true}});assert.equal(get('[data-page="services"]').disabled,true);assert.equal(get('#page-services').hidden,true);assert.equal(get('main').inert,false);
 for(const name of ['authorise','synchronisation','burn','message'])assert.equal(get('[data-page="'+name+'"]').disabled,false);
 assert.equal(get('#protected-processing').hidden,false);
 const html=fs.readFileSync(path.join(__dirname,'../web/index.html'),'utf8');assert.equal(html.includes('id="stop-protected"'),false);assert.equal(html.includes('id="start-protected"'),false);
 console.log('Workspace status, inert regular page, close feedback and absent manual workspace controls: passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
