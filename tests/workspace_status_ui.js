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
 available=false;context.window.updateWorkspace(fixture());assert.equal(get('#workspace-dot').className,'dot red');assert.equal(get('#start-protected').disabled,false);assert.equal(get('#stop-protected').disabled,true);
 let pending=get('#start-protected').events.click();assert.equal(get('#workspace-dot').className,'dot amber');assert.equal(get('#start-protected').disabled,true);assert.equal(get('#stop-protected').disabled,true);
 available=true;release({});await pending;assert.equal(get('#workspace-dot').className,'dot green');assert.equal(get('#workspace-state').textContent,'Ready · protections verified');assert.equal(get('#start-protected').disabled,true);assert.equal(get('#stop-protected').disabled,false);
 pending=get('#stop-protected').events.click();assert.equal(get('#workspace-dot').className,'dot amber');available=false;release({message:'Closed.'});await pending;assert.equal(get('#workspace-dot').className,'dot red');assert.equal(get('#start-protected').disabled,false);
 pending=get('#start-protected').events.click();fail(Error('Local setup refused.'));await pending;assert.equal(get('#workspace-dot').className,'dot red');assert.equal(message,'Local setup refused.');assert.equal(get('#start-protected').disabled,false);assert.equal(get('#stop-protected').disabled,true);
 context.state.node_support.available=false;context.window.updateWorkspace(fixture());assert.equal(get('#start-protected').disabled,true);
 console.log('Workspace red/amber/green status, pending controls, cleanup and visible failure: passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
