'use strict';
/* Chat UX regressions. Uses mocked Cockpit processes; no commands or network. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {JSDOM, VirtualConsole} = require('jsdom');
const html = fs.readFileSync('cockpit_bizon_ai/index.html', 'utf8');
const source = fs.readFileSync('cockpit_bizon_ai/chat.js', 'utf8');
const LAYOUT = 'bizon.ai.sidebar.v1';
const NOW = new Date('2026-11-04T12:00:00').getTime();
const day = 86400000;
const chats = [
    {id:'11111111-1111-4111-8111-111111111111', title:'Today diagnostics', updated_at:NOW / 1000},
    {id:'22222222-2222-4222-8222-222222222222', title:'Yesterday GPU', updated_at:(NOW-day) / 1000},
    {id:'33333333-3333-4333-8333-333333333333', title:'<img src=x onerror=alert(1)> token=history-private-value', updated_at:(NOW-3*day) / 1000},
    {id:'44444444-4444-4444-8444-444444444444', title:'Earlier storage', updated_at:(NOW-20*day) / 1000},
];
let passed = 0;
const tick = async () => { for (let i=0; i<6; i++) await Promise.resolve(); };
async function check(name, fn) { await fn(); passed++; console.log('PASS '+name); }

function setup({width=1100, stored, blocked=false, history=chats}={}) {
    const errors=[], virtualConsole=new VirtualConsole();
    virtualConsole.on('jsdomError', error=>errors.push(error));
    const dom=new JSDOM(html, {url:'https://workstation.test/cockpit/cockpit_bizon_ai/', runScripts:'outside-only', virtualConsole});
    const w=dom.window, d=w.document, storage=stored || new Map(), writes=[], sessionWrites=[], processes=[], copies=[];
    Object.defineProperty(w, 'innerWidth', {value:width, writable:true, configurable:true});
    const NativeDate=w.Date;
    w.Date=class extends NativeDate { constructor(...args){super(...(args.length?args:[NOW]));} static now(){return NOW;} };
    const storageMock={getItem:key=>storage.get(key)??null, setItem:(key,value)=>{writes.push({key,value:String(value)});storage.set(key,String(value));}, removeItem:key=>{writes.push({key,value:null});storage.delete(key);}};
    Object.defineProperty(w, 'localStorage', blocked?{get(){throw new w.DOMException('Blocked','SecurityError');}}:{value:storageMock});
    Object.defineProperty(w, 'sessionStorage', {value:{getItem:()=>null, setItem:(key,value)=>sessionWrites.push({key,value})}});
    Object.defineProperty(w.navigator, 'clipboard', {value:{writeText:async text=>{copies.push(text);}}});
    w.HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
    w.HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');this.dispatchEvent(new w.Event('close'));};
    let timerId=0;
    const timers=new Map();
    w.setTimeout=(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;};
    w.clearTimeout=id=>timers.delete(id);
    const permission={allowed:true,addEventListener(name,fn){this.changed=fn;},close(){}};
    w.cockpit={permission:()=>permission,spawn(args,options){
        const process={args,options,inputs:[],closed:0,
            stream(fn){this.ondata=fn;return this;},
            then(ok,fail){this.ok=ok;this.fail=fail;return this;},
            input(text,keep){this.inputs.push({data:JSON.parse(text),keep});return this;},
            close(){this.closed++;this.fail?.(Error('closed'));},
            emit(event){this.ondata?.(JSON.stringify(event)+'\n');},
            resolve(data){this.ok?.(JSON.stringify(data));},
            reject(){this.fail?.(Error('fixture backend failure'));}
        };processes.push(process);return process;
    }};
    const el=id=>d.getElementById(id), click=id=>el(id).click();
    const byAction=action=>processes.filter(p=>p.args.at(-1)===action);
    const executors=()=>processes.filter(p=>p.args.at(-1).endsWith('executor.py'));
    const input=(id,value)=>{el(id).value=value;el(id).dispatchEvent(new w.Event('input'));};
    const key=(key,options={})=>{const event=new w.KeyboardEvent('keydown',{key,bubbles:true,cancelable:true,...options});d.dispatchEvent(event);return event;};
    const submit=text=>{input('chat-input',text);el('composer').dispatchEvent(new w.Event('submit',{cancelable:true}));return byAction('chat').at(-1);};
    const finish=(process,content='Done')=>process.emit({type:'done',content});
    function dispose(){w.dispatchEvent(new w.Event('beforeunload'));dom.window.close();assert.deepEqual(errors.map(e=>e.message),[]);}
    w.eval(source);d.dispatchEvent(new w.Event('DOMContentLoaded'));
    byAction('status')[0].resolve({provider:'ollama',model:'local-fixture',local_url:'http://127.0.0.1:11434',claude_configured:false,claude_model:'',local_models:[{id:'local-fixture'}]});
    byAction('history_list')[0].resolve({conversations:history});
    return {dom,w,d,el,click,input,key,submit,finish,byAction,executors,processes,storage,writes,sessionWrites,copies,errors,timers,dispose};
}

(async()=>{
    let t=setup();await tick();
    await check('history groups conversations by local calendar age',()=>{
        assert.deepEqual([...t.d.querySelectorAll('.history-group-heading')].map(n=>n.textContent),['Today','Yesterday','Previous 7 days','Earlier']);
        assert.equal(t.d.querySelectorAll('.history-open').length,4);
    });
    await check('untrusted history titles remain text and redact credentials',()=>{
        const row=t.d.querySelectorAll('.history-item')[2];
        assert.equal(row.querySelectorAll('img,script').length,0);
        assert.match(row.textContent,/<img src=x/);
        assert(!row.textContent.includes('history-private-value'));
        assert(!row.querySelector('.history-open').title.includes('history-private-value'));
        assert(!row.querySelector('.history-more').getAttribute('aria-label').includes('history-private-value'));
    });
    await check('search filters titles without backend requests and shows no-results feedback',()=>{
        const count=t.processes.length;
        t.input('history-search','gpu');
        assert.equal(t.d.querySelectorAll('.history-open').length,1);
        assert.match(t.el('history-list').textContent,/Yesterday GPU/);
        assert(t.el('history-empty').hidden);
        t.input('history-search','missing-title');
        assert.equal(t.d.querySelectorAll('.history-open,.history-group-heading').length,0);
        assert(!t.el('history-empty').hidden);
        assert.match(t.el('history-empty').textContent,/No chats match/);
        assert.equal(t.processes.length,count);
        t.input('history-search','');
    });
    await check('desktop collapse persists only layout state and restores accessible toggle',()=>{
        t.click('history-toggle');
        assert(t.el('history-panel').hidden);
        assert.equal(t.el('history-toggle').getAttribute('aria-expanded'),'false');
        assert.equal(t.el('history-toggle-label').textContent,'Show chats');
        assert.equal(t.storage.get(LAYOUT),'closed');
        assert.deepEqual(t.writes,[{key:LAYOUT,value:'closed'}]);
        assert.deepEqual(t.sessionWrites,[]);
    });
    const remembered=t.storage;t.dispose();
    t=setup({stored:remembered});await tick();
    await check('a new page remembers collapse and keyboard search reopens it',()=>{
        assert(t.el('history-panel').hidden);
        const event=t.key('k',{metaKey:true});
        assert(event.defaultPrevented);
        assert(!t.el('history-panel').hidden);
        assert.equal(t.d.activeElement,t.el('history-search'));
        assert.equal(t.el('history-toggle').getAttribute('aria-expanded'),'true');
        assert.equal(t.storage.get(LAYOUT),'open');
    });
    t.d.querySelector('.history-open').click();
    t.byAction('history_read').at(-1).resolve({id:chats[0].id,title:chats[0].title,messages:[]});await tick();
    t.byAction('history_list').at(-1).resolve({conversations:chats});await tick();
    t.d.querySelector('.history-more').click();t.d.querySelector('.rename-chat').click();
    await check('rename targets the selected existing conversation',()=>{
        assert(t.el('rename-dialog').open);
        assert.equal(t.el('rename-title').value,chats[0].title);
        assert.equal(t.d.activeElement,t.el('rename-title'));
    });
    const renamed='Quoted "title" $(not-a-command) <img src=x>';
    t.el('rename-title').value=renamed;
    t.el('rename-form').dispatchEvent(new t.w.Event('submit',{cancelable:true}));
    let rename=t.byAction('history_rename').at(-1);
    await check('rename sends only id and title over JSON stdin, never command arguments or storage',()=>{
        assert.deepEqual(rename.inputs[0].data,{id:chats[0].id,title:renamed});
        assert.equal(rename.args.at(-1),'history_rename');
        assert(!JSON.stringify(rename.args).includes(renamed));
        assert(t.el('rename-title').disabled);
        assert(t.writes.every(write=>write.key===LAYOUT));
        assert.deepEqual(t.sessionWrites,[]);
    });
    rename.resolve({id:chats[0].id,title:renamed});await tick();
    await check('successful rename updates current title and sidebar safely',()=>{
        assert(!t.el('rename-dialog').open);
        assert.equal(t.el('current-chat-title').textContent,renamed);
        assert.equal(t.d.querySelector('.history-open strong').textContent,renamed);
        assert.equal(t.d.querySelector('.history-open strong').children.length,0);
        assert.equal(t.d.activeElement,t.el('history-search'));
    });
    t.d.querySelector('.history-more').click();t.d.querySelector('.rename-chat').click();
    t.el('rename-title').value='Retry name';t.el('rename-form').dispatchEvent(new t.w.Event('submit',{cancelable:true}));
    t.byAction('history_rename').at(-1).reject();await tick();
    await check('rename failure retains the editable dialog and useful retry feedback',()=>{
        assert(t.el('rename-dialog').open);assert(!t.el('rename-title').disabled);
        assert.equal(t.el('rename-title').value,'Retry name');assert.match(t.el('rename-status').textContent,/Try again/);
    });
    await check('cancelling rename sends no mutation and keyboard search respects open dialogs',()=>{
        const count=t.byAction('history_rename').length;
        const event=t.key('k',{ctrlKey:true});assert(!event.defaultPrevented);
        assert.equal(t.d.activeElement,t.el('rename-title'));
        t.click('rename-cancel');assert.equal(t.byAction('history_rename').length,count);assert(!t.el('rename-dialog').open);
    });
    await check('history deletion requires a fresh second click after reopening its menu',async()=>{
        const row=t.d.querySelectorAll('.history-item')[1];
        const more=row.querySelector('.history-more'), remove=row.querySelector('.history-delete');
        more.click();assert(!row.querySelector('.history-menu').hidden);
        remove.click();assert.match(remove.textContent,/Confirm delete/);
        assert.equal(t.byAction('history_delete').length,0);
        more.click();more.click();
        assert.equal(remove.textContent,'Delete chat');assert(!remove.classList.contains('confirm-delete'));
        remove.click();assert.equal(t.byAction('history_delete').length,0);
        remove.click();
        const deletion=t.byAction('history_delete').at(-1);
        assert.equal(t.byAction('history_delete').length,1);
        assert.deepEqual(deletion.inputs[0].data,{id:chats[1].id});assert(remove.disabled);
        deletion.resolve({deleted:true});await tick();
        assert.equal(t.d.querySelectorAll('.history-item').length,3);
        assert(!t.el('history-list').textContent.includes('Yesterday GPU'));
        assert.equal(t.el('current-chat-title').textContent,renamed);
    });
    t.dispose();

    t=setup();await tick();
    t.d.querySelector('.history-open').click();
    t.byAction('history_read').at(-1).resolve({id:chats[0].id,title:chats[0].title,messages:[{role:'user',content:'Saved request'}]});await tick();
    t.byAction('history_list').at(-1).resolve({conversations:chats});await tick();
    await check('pending current-chat deletion blocks new work until the mutation completes',async()=>{
        const row=t.d.querySelector('.history-item.current');
        row.querySelector('.history-more').click();
        row.querySelector('.history-delete').click();row.querySelector('.history-delete').click();
        const deletion=t.byAction('history_delete').at(-1), readCount=t.byAction('history_read').length;
        t.input('chat-input','A new request while deletion is pending');
        assert(t.el('send').disabled);assert(t.el('new-chat').disabled);
        assert([...t.d.querySelectorAll('.history-open,.history-more,.reuse-prompt')].every(node=>node.disabled));
        // Dispatch explicitly as well: disabled controls alone cannot guard keyboard or stale callbacks.
        t.el('composer').dispatchEvent(new t.w.Event('submit',{cancelable:true}));
        t.el('new-chat').dispatchEvent(new t.w.MouseEvent('click',{bubbles:true}));
        t.key('O',{ctrlKey:true,shiftKey:true});
        t.d.querySelectorAll('.history-open')[1].dispatchEvent(new t.w.MouseEvent('click',{bubbles:true}));
        assert.equal(t.byAction('chat').length,0);assert.equal(t.executors().length,0);
        assert.equal(t.byAction('history_read').length,readCount);
        assert.equal(t.el('current-chat-title').textContent,chats[0].title);
        assert.equal(t.d.querySelector('.message.user .message-body').textContent,'Saved request');
        deletion.resolve({deleted:true});await tick();
        assert.equal(t.el('current-chat-title').textContent,'New chat');
        assert.equal(t.el('messages').children.length,0);assert(!t.el('new-chat').disabled);
        const next=t.submit('A request after deletion');
        assert(next);assert.equal(t.byAction('chat').length,1);assert.equal(next.closed,0);
        t.finish(next);await tick();
    });
    t.dispose();

    t=setup({history:[]});await tick();
    const savedDraft=t.submit('Use this earlier request');t.finish(savedDraft);await tick();
    await check('Use as draft discards an attachment read that completes after the draft changes',async()=>{
        let resolveFile, reads=0;
        const fileText=new Promise(resolve=>{resolveFile=resolve;});
        Object.defineProperty(t.el('file-input'),'files',{value:[{name:'outdated.txt',size:10,type:'text/plain',text:()=>{reads++;return fileText;}}],configurable:true});
        t.el('file-input').dispatchEvent(new t.w.Event('change'));await tick();assert.equal(reads,1);
        t.d.querySelector('.message.user .reuse-prompt').click();
        assert.equal(t.el('chat-input').value,'Use this earlier request');
        resolveFile('Old attachment content');await tick();
        assert.equal(t.el('attachments').children.length,0);
        assert.equal(t.byAction('chat').length,1);assert.equal(t.executors().length,0);
        const next=t.submit(t.el('chat-input').value);
        assert.deepEqual(next.inputs[0].data.attachments,[]);
        t.finish(next);await tick();
    });
    t.dispose();

    t=setup({blocked:true});await tick();
    await check('blocked browser storage does not prevent loading, toggling or keyboard search',()=>{
        assert.equal(t.d.querySelectorAll('.history-open').length,4);
        t.click('history-toggle');assert(t.el('history-panel').hidden);
        t.key('k',{ctrlKey:true});assert(!t.el('history-panel').hidden);
        assert.equal(t.d.activeElement,t.el('history-search'));assert.deepEqual(t.errors,[]);
    });
    t.dispose();

    t=setup({history:[]});await tick();
    await check('empty history explains where future chats will appear',()=>{
        assert(!t.el('history-empty').hidden);assert.match(t.el('history-empty').textContent,/conversations will appear/);
    });
    let height=20;Object.defineProperty(t.el('chat-input'),'scrollHeight',{get:()=>height,configurable:true});
    await check('composer grows with content, caps height and shrinks again',()=>{
        t.input('chat-input','short');assert.equal(t.el('chat-input').style.height,'52px');
        height=124;t.input('chat-input','several\nlines');assert.equal(t.el('chat-input').style.height,'124px');
        height=900;t.input('chat-input','large draft');assert.equal(t.el('chat-input').style.height,'200px');
        height=24;t.input('chat-input','small');assert.equal(t.el('chat-input').style.height,'52px');
    });
    let planner=t.submit('Please inspect password="draft-secret"');
    planner.emit({type:'text_delta',text:'**Result**\napi_key=sk-ant-response-secret-123456789\nAuthorization: Bearer response-private-token'});
    t.finish(planner,'**Result**\napi_key=sk-ant-response-secret-123456789\nAuthorization: Bearer response-private-token');await tick();
    t.d.querySelector('.message.assistant .copy-response').click();await tick();
    await check('copy response uses the redacted rendered text, never the raw provider response',()=>{
        assert.equal(t.copies.length,1);assert.match(t.copies[0],/\*\*Result\*\*/);assert.match(t.copies[0],/\[redacted\]/);
        assert(!t.copies[0].includes('response-secret'));assert(!t.copies[0].includes('response-private-token'));
    });
    t.el('computer-control').checked=true;t.el('computer-control').dispatchEvent(new t.w.Event('change'));t.el('administrator').checked=true;
    Object.defineProperty(t.el('file-input'),'files',{value:[{name:'fixture.txt',size:4,type:'text/plain',text:async()=>'safe'}],configurable:true});
    t.el('file-input').dispatchEvent(new t.w.Event('change'));await tick();
    const requestsBefore=t.byAction('chat').length;
    t.d.querySelector('.message.user .reuse-prompt').click();
    await check('Use as draft clears attachments and permissions without executing anything',()=>{
        assert.match(t.el('chat-input').value,/Please inspect/);assert(!t.el('chat-input').value.includes('draft-secret'));
        assert(!t.el('computer-control').checked);assert(!t.el('administrator').checked);assert(t.el('admin-choice').hidden);
        assert.equal(t.el('attachments').children.length,0);assert.equal(t.d.activeElement,t.el('chat-input'));
        assert.equal(t.byAction('chat').length,requestsBefore);assert.equal(t.executors().length,0);
    });
    await check('chat content and credentials never enter browser layout storage',()=>{
        assert(t.writes.every(write=>write.key===LAYOUT&&['open','closed'].includes(write.value)));
        assert.deepEqual(t.sessionWrites,[]);assert.equal(t.storage.size,0);
    });
    let scrollHeight=1400, scrollTop=0;
    const area=t.el('chat-area');
    Object.defineProperties(area,{scrollHeight:{get:()=>scrollHeight,configurable:true},clientHeight:{value:400,configurable:true},scrollTop:{get:()=>scrollTop,set:value=>{scrollTop=Math.max(0,Math.min(value,scrollHeight-400));},configurable:true}});
    planner=t.submit('A longer response');
    area.scrollTop=120;area.dispatchEvent(new t.w.Event('scroll'));
    scrollHeight=1800;planner.emit({type:'text_delta',text:'The response continues while you read earlier content.'});
    await check('streaming preserves the reader position and reveals Latest message',()=>{
        assert.equal(area.scrollTop,120);assert(!t.el('scroll-bottom').hidden);
        assert(t.d.querySelector('.reuse-prompt').disabled);
    });
    await check('Latest message restores following and future text stays at the bottom',()=>{
        t.click('scroll-bottom');assert.equal(area.scrollTop,1400);assert(t.el('scroll-bottom').hidden);
        scrollHeight=2100;planner.emit({type:'text_delta',text:' More content.'});assert.equal(area.scrollTop,1700);
    });
    t.finish(planner);await tick();
    t.w.navigator.clipboard.writeText=async()=>{throw Error('clipboard blocked');};
    t.d.querySelector('.message.assistant .copy-response').click();await tick();
    await check('clipboard denial gives a visible manual-copy fallback',()=>assert.match(t.el('run-status').textContent,/Select the message text/));
    t.dispose();

    t=setup({width:500,stored:new Map([[LAYOUT,'open']])});await tick();
    await check('mobile history starts closed and opens with a backdrop and focused search',()=>{
        assert(t.el('history-panel').hidden);assert(t.el('history-backdrop').hidden);
        t.click('history-toggle');assert(!t.el('history-panel').hidden);assert(!t.el('history-backdrop').hidden);
        assert.equal(t.d.activeElement,t.el('history-search'));assert.deepEqual(t.writes,[]);
    });
    await check('mobile backdrop and Escape close history and restore toggle focus',()=>{
        t.click('history-backdrop');assert(t.el('history-panel').hidden);assert(t.el('history-backdrop').hidden);assert.equal(t.d.activeElement,t.el('history-toggle'));
        t.key('k',{metaKey:true});assert(!t.el('history-panel').hidden);
        t.key('Escape');assert(t.el('history-panel').hidden);assert.equal(t.d.activeElement,t.el('history-toggle'));
        assert.deepEqual(t.writes,[]);
    });
    await check('crossing mobile breakpoint preserves the desktop preference',()=>{
        t.w.innerWidth=1100;t.w.dispatchEvent(new t.w.Event('resize'));assert(!t.el('history-panel').hidden);assert(t.el('history-backdrop').hidden);
        t.click('history-toggle');assert.equal(t.storage.get(LAYOUT),'closed');
        t.w.innerWidth=500;t.w.dispatchEvent(new t.w.Event('resize'));t.click('history-toggle');assert(!t.el('history-panel').hidden);
        t.w.innerWidth=1100;t.w.dispatchEvent(new t.w.Event('resize'));assert(t.el('history-panel').hidden);assert.equal(t.storage.get(LAYOUT),'closed');
    });
    t.dispose();
    console.log(`${passed}/${passed} AI chat UX checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
