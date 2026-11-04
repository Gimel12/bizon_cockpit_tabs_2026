import RFB from './noVNC/core/rfb.js';
let proc, rfb, generation=0;
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
            this._finishClose(options);
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
function stop(closeRfb=true) { generation++; const oldRfb=rfb, oldProc=proc; rfb=null; proc=null; if(closeRfb!==false)oldRfb?.disconnect(); oldProc?.close(); document.getElementById('connect').disabled=false; document.getElementById('disconnect').disabled=true; }
document.getElementById('connect').addEventListener('click', () => {
    const run=++generation;
    status.textContent='Starting desktop…'; document.getElementById('connect').disabled=true;document.getElementById('disconnect').disabled=false;
    let buffer='', connected=false;
    proc=cockpit.spawn(['/usr/bin/python3','-I','/usr/local/share/dlbt_os/cockpit_vnc/py_backend/start_vnc.py'],{err:'message'});
    proc.stream(data => {
        if(run!==generation)return;
        buffer+=data;
        if (connected || !buffer.includes('\n')) return;
        try {
            const config=JSON.parse(buffer.split('\n')[0]);
            if (!Number.isInteger(config.port) || config.port<5910 || config.port>5929) throw Error('Invalid desktop port');
            connected=true;
            rfb=new RFB(document.getElementById('screen'),new CockpitSocket(config.port),{credentials:{password:config.password}});
            rfb.scaleViewport=true; rfb.resizeSession=true;
            rfb.addEventListener('connect',()=>{if(run!==generation)return;status.textContent='Connected securely through Cockpit';document.getElementById('disconnect').disabled=false;});
            rfb.addEventListener('disconnect',()=>{if(run!==generation)return;status.textContent='Disconnected';stop(false);});
            rfb.addEventListener('securityfailure',()=>{if(run!==generation)return;status.textContent='Desktop authentication failed';stop();});
        } catch(e) {status.textContent=e.message;stop();}
    }).then(()=>{if(run===generation){status.textContent='Desktop session ended';stop();}}).catch(err=>{if(run!==generation)return;status.textContent=err.message || String(err);stop();});
});
document.getElementById('disconnect').addEventListener('click',()=>{status.textContent='Disconnected';stop();});
window.addEventListener('beforeunload',stop);
