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
 available=false;context.window.updateWorkspace(fixture());assert.equal(get('#workspace-dot').className,'dot red');assert.equal(get('#stop-protected').disabled,true);
 context.window.setWorkspaceAction('starting');assert.equal(get('#workspace-dot').className,'dot amber');
 available=true;context.window.updateWorkspace(fixture());context.window.setWorkspaceAction(null);assert.equal(get('#workspace-dot').className,'dot green');assert.equal(get('#stop-protected').disabled,false);
 context.state.config={enabled:{node:true}};context.window.updateWorkspace(fixture());assert.equal(get('#stop-protected').disabled,true);assert.match(get('#workspace-close-help').textContent,/Switch the node/);
 context.state.config.enabled.node=false;context.window.updateWorkspace(fixture());
 let pending=get('#stop-protected').events.click();assert.equal(get('#workspace-dot').className,'dot amber');available=false;release({message:'Closed.'});await pending;assert.equal(get('#workspace-dot').className,'dot red');
 available=true;context.window.updateWorkspace({...fixture(),viewer_open:true});assert.equal(get('main').inert,true);assert.equal(get('aside').inert,true);assert.equal(get('#protected-window-lock').hidden,false);
 pending=get('#close-protected-view').events.click();release({message:'Closed view.'});await pending;assert.equal(get('main').inert,false);assert.equal(get('#protected-window-lock').hidden,true);
 vm.runInContext("page='message'",context);context.window.updateWorkspace({...fixture(),protected:{running:true,viewer:true}});assert.equal(get('[data-page="services"]').disabled,true);assert.equal(get('#page-services').hidden,true);assert.equal(get('main').inert,false);
 console.log('Workspace status, node lifecycle help, inert regular window and protected-view closure: passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
