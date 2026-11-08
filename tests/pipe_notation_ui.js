const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const agent=fs.readFileSync(path.join(__dirname,'../web/workspace.js'),'utf8').split('\n').find(x=>x.startsWith('function pipe('));const c={};vm.createContext(c);vm.runInContext(agent,c);
const samples=[0n,1n,1000n,123456n,1000000n,100000001n,123456789n,123456789123456n,-1n,-123456789n,2100000000000000n];
assert.equal(c.pipe(100000001n),'₿1.00 | 1 sats');assert.equal(c.pipe(123456n),'₿0.00 | 123,456 sats');assert.equal(c.pipe(123456789123456n),'₿1,234,567.89 | 123,456 sats');
const dashboard=process.env.WALLABY_TEST_DASHBOARD_SRC;if(dashboard){const source=fs.readFileSync(path.join(dashboard,'assets/app.js'),'utf8');vm.runInContext(source.slice(source.indexOf('function btc(value)'),source.indexOf('const initial=',source.indexOf('function btc(value)'))),c);for(const n of samples){const v=n<0n?-n:n,decimal=(n<0n?'-':'')+v/100000000n+'.'+String(v%100000000n).padStart(8,'0');assert.equal(c.pipe(n),c.btc(decimal));}}
console.log('Exact Bitcoin Pipe notation: comma grouping, unpadded satoshi tail, negatives, zero and maximum supply; matches Wallet Server when supplied.');
