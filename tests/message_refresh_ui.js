// Execute the real message refresh handler: progress, selections, empty/error, review invalidation.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
class Element{
 constructor(tag='div',props={},children=[]){this.tag=tag;this.props=props;this.children=children;this.events={};this.checked=false;this.value=props.value;}
 addEventListener(event,fn){this.events[event]=fn;}replaceChildren(...items){this.children=items;}append(...items){this.children.push(...items);}
 querySelectorAll(){return this.children.flatMap(item=>item.tag==='label'?item.children:[]).filter(item=>item.tag==='input'&&item.checked);}
}
const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
let release,fail;const context={$:get,el:(tag,props,...children)=>new Element(tag,props,children),api:()=>new Promise((resolve,reject)=>{release=resolve;fail=reject;}),run:fn=>fn(),console};
vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/message.js'),'utf8'),context);
(async()=>{
 let job=get('#message-refresh').events.click();assert.equal(get('#message-refresh').disabled,true);assert.match(get('#message-refresh').textContent,/Refreshing/);
 release([{name:'Signing account',disc:false}]);await job;let input=get('#message-wallets').children[0].children[0];input.checked=true;
 vm.runInContext("messageReview='obsolete-review'",context);job=get('#message-refresh').events.click();release([{name:'Signing account',disc:true}]);await job;
 assert.equal(get('#message-wallets').children[0].children[0].checked,true);assert.equal(vm.runInContext('messageReview',context),null);assert.equal(get('#message-refresh').disabled,false);
 job=get('#message-refresh').events.click();release([]);await job;assert.match(get('#message-wallets').children[0].children[0],/No signing accounts/);
 job=get('#message-refresh').events.click();fail(Error('Local Core is unavailable.'));await assert.rejects(job,/Local Core/);assert.equal(get('#message-wallets').children[0].props.role,'alert');assert.equal(get('#message-refresh').disabled,false);
 console.log('Signing-account refresh: progress, selection preservation, invalidated review, empty list and visible failure passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
