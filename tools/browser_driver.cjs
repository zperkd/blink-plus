/* Validation only: drive a temporary Edge profile through CDP; no packages required. */
const {spawn}=require('node:child_process');const fs=require('node:fs');const path=require('node:path');
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const root=path.join(process.env.LOCALAPPDATA,'BlinkPlusValidation');fs.mkdirSync(root,{recursive:true});
const profile=path.join(root,'edge-'+Date.now());
const tunnel=spawn('ssh',['-N','-L','127.0.0.1:18129:127.0.0.1:8129',...(process.env.BLINK_PLUS_SSH_KEY?['-i',process.env.BLINK_PLUS_SSH_KEY]:[]),'-o','BatchMode=yes','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=15',process.env.BLINK_PLUS_SSH_HOST||'pi'],{windowsHide:true,stdio:'ignore'});
const browser=spawn(path.join(process.env['ProgramFiles(x86)'],'Microsoft','Edge','Application','msedge.exe'),['--headless=new','--disable-gpu','--autoplay-policy=no-user-gesture-required','--remote-debugging-port=9227','--user-data-dir='+profile,'--no-first-run','--no-default-browser-check','--disable-features=msImplicitSignin','--window-size=1280,800','about:blank'],{windowsHide:true,stdio:'ignore'});
browser.on('error',e=>console.error('BROWSER_LAUNCH_ERROR '+e.code));
let ws;const pending=new Map();let id=0;
async function send(method,params={}){const next=++id;return new Promise((resolve,reject)=>{pending.set(next,{resolve,reject});ws.send(JSON.stringify({id:next,method,params}));setTimeout(()=>{if(pending.has(next)){pending.delete(next);reject(new Error('CDP timeout '+method));}},15000).unref();});}
(async()=>{let targets;
 for(let i=0;i<60;i++){try{targets=await(await fetch('http://127.0.0.1:9227/json/list')).json();if(targets.length)break;}catch{}await wait(500);}
 if(!targets)throw new Error('Browser did not start');
 ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
 ws.onmessage=e=>{const value=JSON.parse(e.data);if(value.id&&pending.has(value.id)){const p=pending.get(value.id);pending.delete(value.id);value.error?p.reject(new Error(value.error.message)):p.resolve(value.result);}};
 await send('Page.enable');await send('Runtime.enable');
 let previous=null;const results=[];const deadline=Date.now()+650000;
 const expected=Number(process.env.BLINK_PLUS_BROWSER_COUNT||7);
 while(results.length<expected&&Date.now()<deadline){let ready;
  try{ready=await(await fetch('http://127.0.0.1:18129/blink-plus-ready',{signal:AbortSignal.timeout(2000)})).json();}catch{await wait(1000);continue;}
  if(ready.camera_id===previous){await wait(1000);continue;}
  previous=ready.camera_id;console.log('BROWSER_ATTACH '+ready.camera);
  await send('Page.navigate',{url:'http://127.0.0.1:18129/blink-plus-test?t='+Date.now()});
  let metric=null;
  for(let i=0;i<90;i++){await wait(1000);const r=await send('Runtime.evaluate',{expression:'JSON.stringify(window.__blinkResult||null)',returnByValue:true});if(r.result?.value){metric=JSON.parse(r.result.value);if(metric)break;}}
  if(!metric)metric={camera:ready.camera,error:'browser_driver_timeout'};
  console.log('BROWSER_METRICS '+JSON.stringify(metric));results.push(metric);
  await send('Page.navigate',{url:'about:blank'});
 }
 fs.writeFileSync(path.join(root,'browser-results.json'),JSON.stringify(results,null,2));
 console.log('BROWSER_COMPLETED '+results.length);
 await send('Browser.close').catch(()=>{});
})().catch(e=>{console.error('VALIDATION_ERROR '+e.message);process.exitCode=1;}).finally(()=>{try{ws?.close();}catch{}browser.kill();tunnel.kill();});
