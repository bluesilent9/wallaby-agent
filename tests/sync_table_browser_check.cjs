const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{const browser=await chromium.launch({headless:true,args:['--no-sandbox']});try{
 const page=await browser.newPage({viewport:{width:1680,height:1100}}),errors=[],calls=[];page.on('pageerror',e=>errors.push(e.message));const root=path.join(__dirname,'../web');let offline=false,denied=true;
 const receive=(id,sender,locked=false)=>({id,peer_id:id,direction:'receive',wallet_name:'Beta wallet',sender,receiver:'This Agent',direct_ready:!offline,state:'pending',watch_only:locked,watch_only_locked:locked,encrypted_relay:true,selected:false});
 const a={...receive('a','Treasury Australia'),selected:true},b={...receive('b','wallet-laptop',true),selected:true},send={...receive('s','This Agent'),direction:'send',receiver:'Treasury Russia',wallet_name:'Zebra local'};
 function wallets(){return [
  {policy_id:'z',multisig:true,signers:[{label:'Australia signer',account:'Zebra local'}],wallet_name:'Zebra local',local_wallets:['Zebra local'],local_private:true,send:[{...send,direct_ready:!offline}],receive:[],offers:[],pending:true},
  {policy_id:'d',wallet_name:'Delta disabled',local_wallets:[],send:[],receive:[],offers:[],denied,deny_id:denied?null:'d',pending:!denied},
  {policy_id:'b',wallet_name:'Beta wallet',local_wallets:[],send:[],receive:[{...a,direct_ready:!offline},{...b,direct_ready:!offline}],offers:[],deny_id:'a',pending:true},
  {policy_id:'a',wallet_name:'Alpha local',local_wallets:['Alpha local'],send:[],receive:[],offers:[],pending:false}];}
 await page.route('http://wallaby.test/**',async route=>{const name=new URL(route.request().url()).pathname;let body={};if(name.startsWith('/api/')){
  if(name==='/api/session')body={token:'fixture'};
  else if(name==='/api/state')body={config:{hostname:'example.test',ssh_user:'fixture',ssh_port:22,rpc_port:8332,cookie:'',enabled:{ddns:false,dashboard:false,node:true}},version:'2.0.0~dev71',status:{server:{color:'green',message:'Connected'},node:{color:'green',message:'Connected'},dashboard:{color:'red',message:'Off'},ddns:{color:'red',message:'Off'}},workspace:{connected:true,protected:{running:true,viewer:true},pending:[],denied:[],setups:[],archives:{},burn:{},transfer:{wallets:wallets(),pending_count:denied?2:3,rows:[a,b,send],offers_received:true},sync:'Connected',outbox_count:0,identity:{fingerprint:'fixture'}}};
  else if(name==='/api/authorise/local-wallets')body={wallets:[]};
  else if(name==='/api/peers/block-status')body={pairs:[],chain:{}};
  else if(name==='/api/synchronisation/route'){const q=JSON.parse(route.request().postData());calls.push(q);const r=[a,b,send].find(r=>r.id===q.id);for(const other of [a,b,send])if(other.direction===r.direction)other.selected=false;Object.assign(r,{selected:q.selected,watch_only:q.watch_only});body={message:'Selected'};}
  else if(name==='/api/authorise/enable-sync'){denied=false;body={message:'Enabled'};}
  else if(name==='/api/authorise/disable-sync'){denied=true;body={message:'Disabled'};}
  return route.fulfill({json:body});
 }const file=path.join(root,name==='/'?'index.html':name);return route.fulfill({path:file,contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':name.endsWith('.svg')?'image/svg+xml':'text/html'});});
 await page.goto('http://wallaby.test/?page=synchronisation');await page.getByRole('heading',{name:'Wallet synchronisation',exact:true}).waitFor();const names=await page.locator('#sync-wallet-table tbody tr td:first-child strong').allTextContents();assert.deepEqual(names,['Alpha local','Beta wallet','Delta disabled','Zebra local']);assert.equal(await page.locator('#sync-count').textContent(),'2');assert.equal(await page.getByRole('columnheader',{name:'Signer',exact:true}).count(),1);await page.getByText('Australia signer',{exact:true}).waitFor();assert.equal(await page.locator('#sync-denial-list').count(),0);assert.equal(await page.locator('#public-sync-offers').count(),0);
 assert.equal(await page.getByRole('heading',{name:'Authorise 1 receiving wallet(s)',exact:true}).count(),1);
 const sources=page.getByLabel('Receive from Beta wallet',{exact:true});assert.deepEqual(await sources.locator('option').allTextContents(),['Treasury Australia','wallet-laptop']);assert.equal(await page.getByLabel('Watch only receive Beta wallet',{exact:true}).isDisabled(),false);
 await sources.selectOption('b');await page.waitForFunction(()=>document.querySelector('[aria-label="Watch only receive Beta wallet"]')?.disabled);assert.equal(await page.getByLabel('Watch only receive Beta wallet',{exact:true}).isChecked(),true);
 await page.getByLabel('Receive Beta wallet',{exact:true}).check();await page.waitForFunction(()=>document.querySelector('#peer-authorise-form'));assert.equal(calls.at(-1).id,'b');assert.equal(calls.at(-1).watch_only,true);
 await page.getByRole('button',{name:'Enable receiving',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#sync-count').textContent==='3');assert.deepEqual(await page.locator('#sync-wallet-table tbody tr td:first-child strong').allTextContents(),names);
 await page.screenshot({path:process.env.WALLABY_UI_SCREENSHOT,fullPage:true});offline=true;
 await page.evaluate(()=>{document.activeElement?.blur();transferSignature='';refresh(true);});await page.waitForFunction(()=>document.querySelector('[aria-label="Receive from Beta wallet"]')?.disabled);assert.equal(await sources.textContent(),'No Agent Detected');assert.equal(await sources.evaluate(n=>getComputedStyle(n).color),'rgb(177, 40, 40)');assert.equal(await page.getByLabel('Send to Zebra local',{exact:true}).isDisabled(),true);assert.equal(await page.locator('#peer-authorise-form').count(),0);assert.deepEqual(errors,[]);
 console.log('PASS unified alphabetic local/offered/disabled wallets, one table, deduplicated badge, eligible send/receive peers, atomic peer change, locked watch-only source, enable preserves ordering and offline red disabled controls.');
 }finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
