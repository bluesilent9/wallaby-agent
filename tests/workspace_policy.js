// Evaluate the exact shipped polkit rule with identity/unit/action boundary cases.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../packaging/build.py'),'utf8');
const rule=source.split("put('usr/share/polkit-1/rules.d/49-wallaby-agent-workspace.rules','''")[1].split("''')")[0];
let handler,uid='1000';const sandbox={polkit:{addRule:f=>handler=f,Result:{YES:'YES'},spawn:args=>{assert.deepEqual(Array.from(args),['/usr/bin/id','-u','--','dave']);return uid+'\n';}}};
vm.createContext(sandbox);vm.runInContext(rule,sandbox);
const own={user:'dave',system_unit:'wallaby-agent-secure@1000.service',no_new_privileges:true};
const evaluate=(id,subject=own,fields={})=>handler({id,lookup:key=>fields[key]},subject);
for(const id of ['org.freedesktop.login1.inhibit-block-sleep','org.freedesktop.login1.inhibit-block-shutdown']){
 assert.equal(evaluate(id),'YES');
 for(const change of [{system_unit:'other.service'},{system_unit:'user@1000.service'},{system_unit:'wallaby-agent-secure@1001.service'},{system_unit:undefined},{no_new_privileges:false},{no_new_privileges:undefined}])assert.equal(evaluate(id,{...own,...change}),undefined);
 uid='1001';assert.equal(evaluate(id),undefined);uid='0';assert.equal(evaluate(id,{...own,system_unit:'wallaby-agent-secure@0.service'}),undefined);uid='1000';
}
for(const id of ['org.freedesktop.login1.power-off','org.freedesktop.login1.reboot','org.freedesktop.login1.suspend','org.freedesktop.login1.power-off-ignore-inhibit','org.freedesktop.login1.inhibit-handle-lid-switch','org.freedesktop.policykit.exec','org.freedesktop.systemd1.manage-unit-files'])assert.equal(evaluate(id),undefined);
for(const verb of ['start','stop'])assert.equal(evaluate('org.freedesktop.systemd1.manage-units',own,{unit:'wallaby-agent-secure@1000.service',verb}),'YES');
for(const verb of ['restart','reload','kill'])assert.equal(evaluate('org.freedesktop.systemd1.manage-units',own,{unit:'wallaby-agent-secure@1000.service',verb}),undefined);
assert.equal(evaluate('org.freedesktop.systemd1.manage-units',own,{unit:'ssh.service',verb:'start'}),undefined);
console.log('Shipped polkit rule: only matching UID/system unit/NoNewPrivileges may acquire the two inhibitors; unrelated power/admin actions refused.');
