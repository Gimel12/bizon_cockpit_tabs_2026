/* Browser-only fixture for UI tests and previews. Never included in release packages. */
window.fixtureCalls=[];
const makeDrive=(name,model,serial,extra={})=>({name,path:'/dev/'+name,type:'disk',size:2e12,serial,model,transport:'nvme',wwn:'fixture-'+serial,mountpoints:[],reasons:[],is_os:false,system_roles:[],test_allowed:true,available:true,health:{status:'passed',temperature:37,percentage_used:2,media_errors:0,error_log_entries:0,firmware:'DEMO',power_on_hours:400,raw:{}},...extra});
window.fixtureInventory={host:'UI preview · sample data',time:0,tools:{fio:true,smartctl:true,mdadm:true},arrays:[],devices:[
 makeDrive('nvme0n1','Samsung SSD 990 PRO 1TB','DEMO-OS',{size:1e12,is_os:true,test_allowed:false,available:false,system_roles:['/'],mountpoints:['/','/boot/efi'],reasons:['System drive'],test_block_reason:'OS / system drive protected'}),
 makeDrive('nvme1n1','Samsung SSD 990 PRO 2TB','DEMO-DATA',{mountpoints:['/mnt/projects'],available:false,reasons:['Mounted data volume']}),
 makeDrive('sdb','Samsung SSD 870 EVO 2TB','DEMO-002',{transport:'sata'}),
 makeDrive('sdc','Samsung SSD 870 EVO 2TB','DEMO-003',{transport:'sata',health:{status:'warning',temperature:48,percentage_used:null,media_errors:3,alerts:['Media errors: 3'],raw:{}}}),
 makeDrive('sdd','Solidigm P44 Pro 2TB','DEMO-004',{health:{status:'partial',temperature:null,percentage_used:null,raw:{}}}),
 makeDrive('sde','Solidigm P44 Pro 2TB','DEMO-005')
]};
window.fixtureJobs=[];
window.cockpit={spawn(args){const action=args[3],req=JSON.parse(args[4]);window.fixtureCalls.push({action,req});let data;
 switch(action){
 case 'inventory':data=window.fixtureInventory;break;
 case 'arrays':data=window.fixtureInventory.arrays;break;
 case 'jobs':data=window.fixtureJobs;break;
 case 'status':data=window.fixtureJobs.find(j=>j.id===req.id);break;
 case 'start':{const id='a'.repeat(32);data={id,status:'running',created:Date.now()/1000,elapsed:12,config:{...req,devices:req.devices.map(path=>{const d=window.fixtureInventory.devices.find(d=>d.path===path);return {path,model:d.model,drive:d};})},samples:req.devices.map(path=>({path,bandwidth:[[0,0],[3,2500],[6,3200],[9,3100],[12,3300]]})),results:req.devices.map(path=>({path,metrics:[{read:{mib_s:3300,iops:3300,latency_p99_ms:1.5},write:{mib_s:0,iops:0,latency_p99_ms:0}}]})),before:{},after:{},temperature_samples:[]};window.fixtureJobs.unshift(data);break;}
 case 'stop':window.fixtureJobs[0].status='cancelled';data={message:'Fixture test stopped.'};break;
 case 'report':data={html:'<!doctype html><title>UI fixture report</title><h1>Sample report — not hardware results</h1>'};break;
 case 'raid-plan':data={token:'b'.repeat(32),confirmation:'CREATE '+req.name,capacity:2e12,warning:'Creates RAID metadata on the selected blank drives.',config:{action:'create',level:req.level,name:req.name,devices:req.devices.map(path=>window.fixtureInventory.devices.find(d=>d.path===path))}};break;
 case 'raid-apply':data={message:'Fixture array created.'};break;
 default:data={message:'Fixture action'};
 }
 const result=JSON.stringify({ok:true,data:JSON.parse(JSON.stringify(data))});let onData;
 const promise=Promise.resolve().then(()=>{if(onData)onData(result);return result;});promise.stream=f=>{onData=f;};return promise;
}};
