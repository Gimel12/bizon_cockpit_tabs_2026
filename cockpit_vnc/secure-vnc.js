import RFB from './noVNC/core/rfb.js';
let proc, rfb, startupTimer, generation=0;
const element = id => document.getElementById(id);
const STARTUP_TIMEOUT = 45000;
const status = document.getElementById('status');
class CockpitSocket {
    constructor(port) {
        this.readyState=0; this.bufferedAmount=0; this.protocol=''; this.binaryType='arraybuffer';
        this._onopen=null; this._onmessage=null; this.onclose=null; this.onerror=null;
        this._queue=[]; this._ready=false; this._opened=false;
        this.channel=cockpit.channel({payload:'stream',address:'127.0.0.1',port,binary:true});
        this.channel.addEventListener('control',(event,options)=>{
            if(options.command==='ready'){this._ready=true;this._pump();}
        });
        this.channel.addEventListener('message',(event,data)=>{
            const bytes=data instanceof Uint8Array?data:new Uint8Array(data);
            this._queue.push(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength));
            this._ready=true;this._pump();
        });
        this.channel.addEventListener('close',(event,options)=>{
            // Match WebSocket: close events must arrive after close() returns.
            queueMicrotask(()=>this._finishClose(options));
        });
    }
    get onopen(){return this._onopen;}
    set onopen(fn){this._onopen=fn;queueMicrotask(()=>this._pump());}
    get onmessage(){return this._onmessage;}
    set onmessage(fn){this._onmessage=fn;queueMicrotask(()=>this._pump());}
    _pump(){
        if(this.readyState>=2 || !this._ready || !this._onopen || !this._onmessage)return;
        if(!this._opened){this._opened=true;this.readyState=1;this._onopen({});}
        while(this._queue.length && this.readyState===1)this._onmessage({data:this._queue.shift()});
    }
    send(data){this.channel.send(new Uint8Array(data.buffer||data,data.byteOffset||0,data.byteLength));}
    _finishClose(options={}){if(this.readyState===3)return;this.readyState=3;this.onclose?.({wasClean:!options.problem,code:options.problem?1006:1000,reason:options.problem||''});}
    close(){if(this.readyState>=2)return;this.readyState=2;this.channel.close();queueMicrotask(()=>this._finishClose());}
}
function stop(closeRfb=true) {
    generation++;
    clearTimeout(startupTimer);
    const oldRfb=rfb, oldProc=proc;
    rfb=null; proc=null;
    if(closeRfb!==false) oldRfb?.disconnect();
    oldProc?.close();
    element('screen').replaceChildren();
    window.dispatchEvent(new Event('desktop-ended'));
}
function showState(state, title, description) {
    document.body.dataset.state=state;
    const busy=state==='starting' || state==='connecting';
    const active=state==='connected';
    element('welcome').hidden=active;
    element('toolbar').hidden=!active;
    element('connection-progress').hidden=!busy;
    element('connect').hidden=busy;
    element('connect').disabled=busy || active;
    element('cancel').hidden=!busy;
    element('disconnect').disabled=!active;
    element('fullscreen').disabled=!active;
    element('welcome-title').textContent=title;
    element('welcome-description').textContent=description;
    element('state-badge').textContent=({ready:'Ready to connect',starting:'Starting desktop',connecting:'Connecting',connected:'Connected',error:'Connection needs attention',disconnected:'Session closed'})[state];
    element('connect').textContent=state==='error' ? 'Try again →' : state==='disconnected' ? 'Connect again →' : 'Connect to desktop →';
    element('progress-label').textContent=state==='connecting' ? 'Opening your secure connection…' : 'Starting your desktop…';
    element('notice').hidden=true;
    status.textContent=active ? 'Connected securely through Cockpit' : title+'. '+description;
}
function fail(description) {
    stop();
    showState('error','We couldn’t open your desktop',description);
    element('connect').focus();
}
function connect() {
    if(proc || rfb) return;
    const run=++generation;
    showState('starting','Getting your workspace ready','Starting a private Ubuntu session. This usually takes a few seconds.');
    let buffer='', configured=false;
    startupTimer=setTimeout(()=>{
        if(run===generation) fail('The desktop took too long to respond. Try again. If it keeps happening, sign out of Cockpit and sign back in.');
    },STARTUP_TIMEOUT);
    try {
        proc=cockpit.spawn(['/usr/bin/python3','-I','/usr/local/share/dlbt_os/cockpit_vnc/py_backend/start_vnc.py'],{err:'message'});
        proc.stream(data => {
            if(run!==generation || configured)return;
            buffer+=data;
            if(buffer.length>8192){fail('The desktop returned an unexpected response. Please try again.');return;}
            if(!buffer.includes('\n'))return;
            try {
                const config=JSON.parse(buffer.split('\n')[0]);
                if(!Number.isInteger(config.port) || config.port<5910 || config.port>5929 || typeof config.password!=='string' || config.password.length!==8) throw Error('Invalid desktop configuration');
                configured=true; buffer='';
                showState('connecting','Opening your desktop','Your session is ready. Establishing the secure display connection.');
                rfb=new RFB(element('screen'),new CockpitSocket(config.port),{credentials:{password:config.password}});
                rfb.scaleViewport=true; rfb.resizeSession=true;
                rfb.addEventListener('connect',()=>{
                    if(run!==generation)return;
                    clearTimeout(startupTimer);
                    showState('connected','Desktop connected','');
                    element('screen').focus();
                });
                rfb.addEventListener('desktopname',event=>{
                    if(run===generation)element('screen').setAttribute('aria-label','Remote desktop: '+event.detail.name);
                });
                rfb.addEventListener('disconnect',event=>{
                    if(run!==generation)return;
                    if(document.body.dataset.state!=='connected' || !event.detail.clean){
                        fail('The desktop connection was interrupted. Check your network and try again.');
                    }else{
                        stop(false);
                        showState('disconnected','Your desktop session has ended','Connect again to open a new workspace.');
                    }
                });
                rfb.addEventListener('securityfailure',()=>{
                    if(run===generation)fail('The desktop could not authenticate this session. Try again to create a new secure connection.');
                });
            }catch(_){fail('The desktop returned an unexpected response. Please try again.');}
        }).then(()=>{
            if(run!==generation)return;
            if(document.body.dataset.state!=='connected'){fail('The desktop closed before it was ready. Please try again.');return;}
            stop();showState('disconnected','Your desktop session has ended','Connect again to open a new workspace.');
        }).catch(()=>{
            if(run===generation)fail('The desktop service could not start. Please try again. If it keeps happening, contact your system administrator.');
        });
    }catch(_){fail('Cockpit could not start the desktop. Refresh this page and try again.');}
}
element('connect').addEventListener('click',connect);
function disconnect() {
    const wasStarting=document.body.dataset.state!=='connected';
    stop();
    showState('disconnected',wasStarting?'Connection cancelled':'You’re disconnected','Connect again whenever you’re ready to open a new workspace.');
    element('connect').focus();
}
element('disconnect').addEventListener('click',disconnect);
element('cancel').addEventListener('click',disconnect);
// Display dimensions are read from the rendered canvas, never guessed from the window.
const dimensions=new MutationObserver(()=>{
    const canvas=element('screen').querySelector('canvas');
    element('display-size').textContent=canvas?.width && canvas?.height ? canvas.width+' × '+canvas.height+' · Auto fit' : 'Connected · Auto fit';
});
dimensions.observe(element('screen'),{subtree:true,childList:true,attributes:true,attributeFilter:['width','height']});
window.addEventListener('beforeunload',()=>{dimensions.disconnect();stop();});

// Enable the entry action only once the module and connection handlers are ready.
element('connect').disabled=false;
element('state-badge').textContent='Ready to connect';
status.textContent='Ready to connect';
