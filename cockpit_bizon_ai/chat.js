/* BIZON AI: model planning and per-request computer execution over Cockpit stdio. */
(() => {
    'use strict';
    const BASE = '/usr/local/share/dlbt_os/cockpit_bizon_ai/agent/';
    const MAX_LINE = 8 * 1024 * 1024, MAX_OUTPUT = 256 * 1024;
    const paths = {panel:'M4 4h16v16H4zM9 4v16',plus:'M12 5v14M5 12h14',settings:'M4 7h16M4 17h16M8 4v6M16 14v6',refresh:'M20 7v5h-5M4 17v-5h5M5 7a8 8 0 0 1 13-2l2 3M4 16l2 3a8 8 0 0 0 13-2',close:'M6 6l12 12M6 18 18 6',spark:'m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z',heart:'M20 5c-3-3-7 0-8 2-1-2-5-5-8-2s-1 7 8 14c9-7 11-11 8-14Z',search:'M15 15l6 6M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0',code:'m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18',clip:'m8 12 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l9-9',stop:'M5 5h14v14H5z',send:'m3 3 18 9-18 9 4-9Zm4 9h14',trash:'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v7m4-7v7',terminal:'m5 6 5 6-5 6m8 0h6',file:'M5 3h9l5 5v13H5zM14 3v5h5',check:'m5 12 4 4L20 5'};
    Object.assign(paths, {copy:'M9 9h11v11H9zM15 5V3H3v12h2',edit:'m15 4 5 5M4 20l5-1L21 7l-5-5L4 14z',more:'M5 12h.01M12 12h.01M19 12h.01',down:'m6 9 6 6 6-6'});
    const LAYOUT_KEY = 'bizon.ai.sidebar.v1';
    const renderedText = new WeakMap();
    let historyItems = [], renameId = null, stickToBottom = true, mobileLayout = window.innerWidth < 760;
    let historyMutation = false, attachmentEpoch = 0;
    const el = id => document.getElementById(id);
    const make = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; };
    const icon = name => { const svg = document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.setAttribute('viewBox','0 0 24 24'); svg.setAttribute('aria-hidden','true'); svg.classList.add('ai-icon'); const p = document.createElementNS(svg.namespaceURI,'path'); p.setAttribute('d',paths[name] || paths.terminal); svg.append(p); return svg; };
    let active = null, conversation = null, settings = null, pendingFiles = [], settingsBusy = false, historyEpoch = 0, destroyed = false, permission;
    const requests = new Set();
    function uuid() { return crypto.randomUUID ? crypto.randomUUID() : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const v=crypto.getRandomValues(new Uint8Array(1))[0]&15;return (c==='x'?v:(v&3)|8).toString(16);}); }
    function nonce() { return [...crypto.getRandomValues(new Uint8Array(32))].map(x=>x.toString(16).padStart(2,'0')).join(''); }
    function close(proc) { try { proc?.close('terminated'); } catch (_) {} }
    function live(run) { return !destroyed && active === run && !run.ended; }
    function redact(value) {
        return String(value)
            .replace(/-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)/g,'[redacted private key]')
            .replace(/\b(?:sk-ant-|sk-proj-|sk-)[A-Za-z0-9_-]{8,}/g,'[redacted]')
            .replace(/\b(Bearer\s+)[A-Za-z0-9._~+/=-]+/gi,'$1[redacted]')
            .replace(/(["']?(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret|token)["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)/gi,'$1[redacted]')
            .replace(/(https?:\/\/)[^/@\s]+:[^/@\s]+@/g,'$1[redacted]@');
    }
    function status(message, error = false) { el('run-status').textContent = redact(message); el('run-status').classList.toggle('error',error); }
    function controls() {
        document.querySelectorAll('[data-run-lock],.history-open,.history-delete,.history-more,.rename-chat,.reuse-prompt').forEach(node => { node.disabled = Boolean(active) || settingsBusy || historyMutation; });
        el('send').disabled = !settings || Boolean(active) || settingsBusy || historyMutation || (!el('chat-input').value.trim() && !pendingFiles.length);
        el('stop').hidden = !active;
        el('send').hidden = Boolean(active);
        el('chat-input').disabled = Boolean(active) || historyMutation;
        el('new-chat').disabled = historyMutation || settingsBusy;
        el('admin-choice').hidden = !el('computer-control').checked;
        el('control-description').textContent = el('computer-control').checked
            ? 'Computer control runs commands with your account permissions. Administrator mode can change the entire system. Enable only for tasks you trust.'
            : 'Chat only. No commands or file changes.';
    }
    function invoke(action, data = {}) {
        return new Promise((resolve,reject) => {
            let proc;
            try {
                proc = cockpit.spawn(['/usr/bin/python3','-I',BASE+'backend.py',action],{err:'message'});
                requests.add(proc);
                proc.then(output => {
                    requests.delete(proc);
                    try { const value = JSON.parse(output); if (value.error) throw Error(String(value.error)); resolve(value); } catch (error) { reject(error); }
                }, () => { requests.delete(proc); reject(Error('The workstation helper could not complete this request.')); });
                proc.input(JSON.stringify(data)+'\n');
            } catch (error) { requests.delete(proc); close(proc); reject(error); }
        });
    }
    function readEvents(proc, run, receive) {
        let buffer = '';
        proc.stream(chunk => {
            if (!live(run)) return;
            buffer += String(chunk);
            if (buffer.length > MAX_LINE) return finish(run,'The response exceeded the safe size limit.',true);
            let newline;
            while (live(run) && (newline = buffer.indexOf('\n')) >= 0) {
                const line = buffer.slice(0,newline); buffer = buffer.slice(newline+1);
                if (!line.trim()) continue;
                try { const event=JSON.parse(line); if (!event || typeof event!=='object' || Array.isArray(event)) throw Error(); receive(event); }
                catch (_) { finish(run,'The workstation sent an invalid response. This request was stopped.',true); }
            }
        });
    }
    function safeUrl(raw) {
        try { const url = new URL(raw); return ['https:','http:'].includes(url.protocol) ? url.href : null; } catch (_) { return null; }
    }
    function inline(node, text) {
        const regex = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^\s)]+\))/g; let index=0, match;
        while ((match=regex.exec(text))) {
            node.append(document.createTextNode(text.slice(index,match.index)));
            const token=match[0];
            if (token.startsWith('`')) node.append(make('code','',token.slice(1,-1)));
            else if (token.startsWith('**')) node.append(make('strong','',token.slice(2,-2)));
            else { const cut=token.indexOf(']('), url=safeUrl(token.slice(cut+2,-1)); if (url) { const a=make('a','',token.slice(1,cut)); a.href=url; a.target='_blank'; a.rel='noopener noreferrer'; node.append(a); } else node.append(document.createTextNode(token)); }
            index=regex.lastIndex;
        }
        node.append(document.createTextNode(text.slice(index)));
    }
    function markdown(target, text) {
        target.replaceChildren();
        const clean = redact(text);
        renderedText.set(target, clean);
        const copy = target.closest('.message')?.querySelector('.copy-response');
        if (copy) copy.hidden = !clean.trim();
        const lines=clean.split('\n'); let index=0;
        while (index<lines.length) {
            const line=lines[index];
            if (line.startsWith('```')) {
                const language=line.slice(3).trim().slice(0,40); let code=''; index++;
                while(index<lines.length&&!lines[index].startsWith('```')) { code+=lines[index]+(index+1<lines.length?'\n':''); index++; }
                if(index<lines.length)index++;
                const wrap=make('div','code-block'), head=make('div','code-header'), copy=make('button','', 'Copy code'), pre=make('pre'); copy.type='button';
                head.append(make('span','',language||'Code'),copy); pre.append(make('code','',code)); wrap.append(head,pre);target.append(wrap);
                copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(code);copy.textContent='Copied';}catch(_){copy.textContent='Select code to copy';}});continue;
            }
            if(!line.trim()){index++;continue;}
            const heading=/^(#{1,3})\s+(.+)$/.exec(line);
            if(heading){const h=make(heading[1].length===1?'h2':'h3');inline(h,heading[2]);target.append(h);index++;continue;}
            if(line.includes('|') && /^\s*\|?\s*:?-{3,}/.test(lines[index+1]||'')) {
                const wrap=make('div','table-wrap'),table=make('table'),head=make('thead'),body=make('tbody');
                const cells=value=>value.trim().replace(/^\||\|$/g,'').split('|').map(cell=>cell.trim());
                const header=make('tr');for(const cell of cells(line)){const th=make('th');inline(th,cell);header.append(th);}head.append(header);index+=2;
                while(index<lines.length&&lines[index].includes('|')&&lines[index].trim()){const row=make('tr');for(const cell of cells(lines[index++])){const td=make('td');inline(td,cell);row.append(td);}body.append(row);}
                table.append(head,body);wrap.append(table);target.append(wrap);continue;
            }
            const list=/^\s*(?:[-*]|\d+\.)\s+/.test(line);
            if(list){const ordered=/^\s*\d+\./.test(line),ul=make(ordered?'ol':'ul');while(index<lines.length&&/^\s*(?:[-*]|\d+\.)\s+/.test(lines[index])){const li=make('li');inline(li,lines[index].replace(/^\s*(?:[-*]|\d+\.)\s+/,''));ul.append(li);index++;}target.append(ul);continue;}
            const p=make('p'); inline(p,line);target.append(p);index++;
        }
    }
    function growComposer() {
        const input = el('chat-input');
        input.style.height = 'auto';
        input.style.height = Math.min(200, Math.max(52, input.scrollHeight)) + 'px';
    }
    function fillComposer(text) {
        el('chat-input').value = text.slice(0, 16384);
        growComposer(); controls(); el('chat-input').focus();
    }
    function updateScrollState() {
        const area = el('chat-area');
        stickToBottom = area.scrollHeight - area.scrollTop - area.clientHeight < 80;
        el('scroll-bottom').hidden = stickToBottom || !el('messages').children.length;
    }
    function scrollChat(force = false) {
        if (force) stickToBottom = true;
        if (stickToBottom) el('chat-area').scrollTop = el('chat-area').scrollHeight;
        el('scroll-bottom').hidden = stickToBottom || !el('messages').children.length;
    }
    function setHistoryOpen(open, persist = false, focus = false) {
        const panel = el('history-panel');
        const restoreFocus = !open && panel.contains(document.activeElement);
        panel.hidden = !open;
        el('history-toggle').setAttribute('aria-expanded', String(open));
        el('history-toggle').setAttribute('aria-label', open ? 'Hide recent chats' : 'Show recent chats');
        el('history-toggle').title = open ? 'Hide recent chats' : 'Show recent chats';
        el('history-toggle-label').textContent = open ? 'Hide chats' : 'Show chats';
        el('history-backdrop').hidden = !open || !mobileLayout;
        if (persist && !mobileLayout) {
            try { localStorage.setItem(LAYOUT_KEY, open ? 'open' : 'closed'); } catch (_) {}
        }
        if (restoreFocus) el('history-toggle').focus();
        if (open && focus) el('history-search').focus();
    }
    function preferredHistoryOpen() {
        if (mobileLayout) return false;
        try { return localStorage.getItem(LAYOUT_KEY) !== 'closed'; } catch (_) { return true; }
    }
    function message(role, text = '') {
        el('welcome').hidden = true;
        const article = make('article', 'message ' + (role === 'user' ? 'user' : 'assistant'));
        const body = make('div', 'message-body'), actions = make('div', 'message-actions');
        const copy = make('button', 'copy-response', 'Copy');
        copy.type = 'button'; copy.title = role === 'user' ? 'Copy message' : 'Copy response';
        copy.setAttribute('aria-label', copy.title); copy.prepend(icon('copy'));
        copy.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(renderedText.get(body) || '');
                copy.replaceChildren(icon('check'), document.createTextNode('Copied'));
                setTimeout(() => { if (copy.isConnected) copy.replaceChildren(icon('copy'), document.createTextNode('Copy')); }, 1800);
            } catch (_) { status('Clipboard access is unavailable. Select the message text to copy it.', true); }
        });
        actions.append(copy);
        if (role === 'user') {
            const reuse = make('button', 'reuse-prompt', 'Use as draft');
            reuse.type = 'button'; reuse.title = 'Edit this message as a new draft'; reuse.prepend(icon('edit'));
            reuse.addEventListener('click', () => {
                if (active || settingsBusy || historyMutation) return;
                el('computer-control').checked = false; el('administrator').checked = false;
                attachmentEpoch++; pendingFiles = []; renderAttachments();
                fillComposer(renderedText.get(body) || '');
                status('Message copied to your draft. Review it before sending; computer control is off.');
            });
            actions.append(reuse);
        }
        article.append(make('div', 'message-label', role === 'user' ? 'You' : 'Bizon AI'), body, actions);
        el('messages').append(article);
        if (role === 'user') { body.textContent = redact(text); renderedText.set(body, redact(text)); }
        else markdown(body, text);
        scrollChat(); return {article, body};
    }
    function activity(parent,request) {
        const card=make('details','activity'),head=make('summary'),meta=make('span','activity-meta','Starting…'),output=make('pre','activity-output');
        const labels={run_command:'Running command',read_file:'Reading file',write_file:'Writing file'};
        const title=redact(request.name==='run_command'?String(request.arguments.command||''):String(request.arguments.path||''));
        const titleNode=make('span','activity-title',labels[request.name]+(title?' · '+title:'')); titleNode.title=title;
        head.append(icon(request.name==='run_command'?'terminal':'file'),titleNode,meta);card.append(head,output);card.dataset.state='running';parent.insertBefore(card,parent.querySelector('.message-actions'));scrollChat();
        return {card,meta,output,started:Date.now(),text:'',fragment:'',droppingLine:false,privateKey:false};
    }
    function appendOutput(action,text) { action.text=(action.text+redact(text)).slice(-MAX_OUTPUT);action.output.textContent=action.text; }
    function streamOutput(action,text) {
        action.fragment += String(text);
        let end;
        while ((end=action.fragment.indexOf('\n'))>=0) {
            const line=action.fragment.slice(0,end+1);action.fragment=action.fragment.slice(end+1);
            if(action.droppingLine){appendOutput(action,'[Long output line omitted]\n');action.droppingLine=false;continue;}
            if(/-----BEGIN [^-]*PRIVATE KEY-----/.test(line)){action.privateKey=true;appendOutput(action,'[redacted private key]\n');}
            if(action.privateKey){if(/-----END [^-]*PRIVATE KEY-----/.test(line))action.privateKey=false;continue;}
            appendOutput(action,line);
        }
        if(action.fragment.length>MAX_OUTPUT){action.fragment='';action.droppingLine=true;}
    }
    function finish(run, reason='',error=false) {
        if (!live(run)) return;
        run.ended=true;active=null;clearTimeout(run.timeout);clearTimeout(run.startTimeout);
        close(run.planner);close(run.executor);run.secret='';
        el('messages').setAttribute('aria-busy', 'false');
        for(const action of run.actions.values())if(action.card.dataset.state==='running'){action.card.dataset.state='error';action.meta.textContent='Stopped';}
        el('administrator').checked=false;status(reason,error);controls();void loadHistory();
    }
    function startPlanner(run) {
        if(!live(run))return;
        try {
            run.planner=cockpit.spawn(['/usr/bin/python3','-I',BASE+'backend.py','chat'],{err:'message'});
            readEvents(run.planner,run,event=>{
                if(event.type==='conversation'){conversation=event.id;run.conversationId=event.id;el('current-chat-title').textContent=redact(event.title||'New chat');}
                else if(event.type==='status')status(String(event.message||'Working…'));
                else if(event.type==='text_delta') { run.text=(run.text+String(event.text||'')).slice(-1024*1024);markdown(run.reply.body,run.text);scrollChat(); }
                else if(event.type==='tool_request')executeTool(run,event);
                else if(event.type==='done'){if(typeof event.content==='string')markdown(run.reply.body,event.content);conversation=event.conversation_id||conversation;scrollChat();finish(run,'Request complete.');}
                else if(event.type==='error')finish(run,String(event.message||'The AI request failed.'),true);
                else finish(run,'The AI sent an unsupported response. This request was stopped.',true);
            });
            run.planner.then(()=>{if(live(run))finish(run,'The connection ended before the request completed.',true);},()=>{if(live(run))finish(run,'The AI request could not finish. Check AI settings and try again.',true);});
            run.planner.input(JSON.stringify({conversation_id:conversation||undefined,message:run.prompt,provider:settings.provider,model:settings.provider==='claude'?(settings.claude_model||''):settings.model,mode:run.mode,attachments:run.attachments})+'\n',true);
        } catch(_){finish(run,'Could not start the AI request. Check that the workstation helper is installed.',true);}
    }
    function executeTool(run,request) {
        if(!live(run))return;
        if(run.mode!=='agent'||!run.executor||!run.ready)return finish(run,'Computer control is off. No command was run.',true);
        if(typeof request.id!=='string'||!request.id||request.id.length>200||!['run_command','read_file','write_file'].includes(request.name)||!request.arguments||typeof request.arguments!=='object'||Array.isArray(request.arguments)||run.seen.has(request.id)||run.pending||run.seen.size>=16)return finish(run,'An invalid or repeated computer action was blocked.',true);
        run.seen.add(request.id);run.pending=request.id;run.actions.set(request.id,activity(run.reply.article,request));
        run.executor.input(JSON.stringify({type:'execute',run_id:run.id,nonce:run.secret,id:request.id,name:request.name,arguments:request.arguments})+'\n',true);
    }
    function startExecutor(run) {
        try {
            const options={err:'message'};if(run.admin)options.superuser='require';
            run.executor=cockpit.spawn(['/usr/bin/python3','-I',BASE+'executor.py'],options);
            readEvents(run.executor,run,event=>{
                if(event.type==='ready'){
                    if(event.run_id!==run.id||run.ready)return finish(run,'The computer-control session was not verified.',true);
                    run.ready=true;clearTimeout(run.startTimeout);startPlanner(run);return;
                }
                if(event.type==='error')return finish(run,String(event.message||'Computer control stopped.'),true);
                if(!run.ready||!run.pending||event.id!==run.pending)return finish(run,'An unexpected computer-control response was blocked.',true);
                const action=run.actions.get(event.id);
                if(event.type==='tool_start')action.meta.textContent='Running…';
                else if(event.type==='output')streamOutput(action,event.text||'');
                else if(event.type==='tool_done'){
                    if(!event.result||typeof event.result!=='object')return finish(run,'The command result was invalid.',true);
                    if(typeof event.result.output==='string'){action.text='';appendOutput(action,event.result.output);}
                    if(event.result.error)appendOutput(action,'\n'+String(event.result.error));
                    const code=event.result.exit_code;action.card.dataset.state=code===0&&!event.result.error?'complete':'error';action.meta.textContent=((Date.now()-action.started)/1000).toFixed(1)+'s · Exit '+String(code??'unknown');
                    run.pending=null;run.planner.input(JSON.stringify({type:'tool_result',id:event.id,result:event.result})+'\n',true);status('Reviewing the result…');
                } else finish(run,'The computer-control response was invalid.',true);
            });
            run.executor.then(()=>{if(live(run))finish(run,'Computer control ended before the request completed.',true);},()=>{if(live(run))finish(run,run.admin?'Administrator access is unavailable. Enable Administrative access in Cockpit, then try again.':'Could not start computer control.',true);});
            run.startTimeout=setTimeout(()=>finish(run,'Computer control did not start in time. Try again.',true),60000);
            run.executor.input(JSON.stringify({type:'init',run_id:run.id,nonce:run.secret,ttl_seconds:1800,mode:run.admin?'administrator':'user'})+'\n',true);
        } catch(_){finish(run,'Could not start computer control.',true);}
    }
    function send(event) {
        event?.preventDefault();if(active||!settings||settingsBusy||historyMutation)return;
        const prompt=el('chat-input').value.trim();if(!prompt&&!pendingFiles.length)return;
        const attachments=pendingFiles;attachmentEpoch++;pendingFiles=[];renderAttachments();el('chat-input').value='';growComposer();stickToBottom=true;
        el('messages').setAttribute('aria-busy', 'true');
        if(mobileLayout)setHistoryOpen(false);
        message('user',prompt+(attachments.length?'\n\nAttached: '+attachments.map(f=>f.name).join(', '):''));
        const run={id:uuid(),secret:nonce(),mode:el('computer-control').checked?'agent':'chat',admin:el('computer-control').checked&&el('administrator').checked,prompt:prompt||'Please review the attached files.',attachments,reply:message('assistant'),text:'',seen:new Set(),actions:new Map(),pending:null,ready:false,ended:false};
        active=run;run.timeout=setTimeout(()=>finish(run,'The request reached its 30-minute limit.',true),1800000);controls();status(run.admin?'Starting administrator access through Cockpit…':'Thinking…');
        if(run.mode==='agent')startExecutor(run);else startPlanner(run);
    }
    function closeHistoryMenus() {
        document.querySelectorAll('.history-menu').forEach(menu => { menu.hidden = true; });
        document.querySelectorAll('.history-more').forEach(button => button.setAttribute('aria-expanded', 'false'));
    }
    function historyGroup(value) {
        const date = new Date(typeof value === 'number' ? value * 1000 : value);
        const today = new Date(); today.setHours(0, 0, 0, 0);
        const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
        const week = new Date(today); week.setDate(week.getDate() - 7);
        if (date >= today) return 'Today';
        if (date >= yesterday) return 'Yesterday';
        if (date >= week) return 'Previous 7 days';
        return 'Earlier';
    }
    function openRename(item) {
        if (active || settingsBusy || historyMutation) return;
        closeHistoryMenus(); renameId = item.id;
        el('rename-title').value = String(item.title || '').slice(0, 80);
        el('rename-status').textContent = '';
        if (el('rename-dialog').showModal) el('rename-dialog').showModal();
        else el('rename-dialog').setAttribute('open', '');
        el('rename-title').focus(); el('rename-title').select();
    }
    function closeRename() {
        if (el('rename-dialog').close) el('rename-dialog').close();
        else el('rename-dialog').removeAttribute('open');
        renameId = null;
        if (!el('history-panel').hidden) el('history-search').focus();
        else el('history-toggle').focus();
    }
    async function renameHistory(event) {
        event.preventDefault();
        const title = el('rename-title').value.trim(), id = renameId;
        if (!id || active || settingsBusy || historyMutation) return;
        if (!title) { el('rename-status').textContent = 'Enter a name for this chat.'; return; }
        const buttons = el('rename-form').querySelectorAll('button,input');
        buttons.forEach(button => { button.disabled = true; });
        historyMutation = true; historyEpoch++; controls();
        try {
            const result = await invoke('history_rename', {id, title});
            historyItems = historyItems.map(item => item.id === id ? {...item, title: result.title || title} : item);
            if (conversation === id) el('current-chat-title').textContent = redact(result.title || title);
            renderHistory(); closeRename(); status('Chat renamed.');
        } catch (_) { el('rename-status').textContent = 'The chat could not be renamed. Try again.'; }
        finally { historyMutation = false; buttons.forEach(button => { button.disabled = false; }); controls(); }
    }
    function renderHistory() {
        const list = el('history-list'), query = el('history-search').value.trim().toLocaleLowerCase();
        list.replaceChildren(); let group = '';
        const matches = historyItems.filter(item => String(item.title || 'Untitled chat').toLocaleLowerCase().includes(query));
        el('history-empty').hidden = Boolean(matches.length);
        el('history-empty').textContent = query ? 'No chats match your search.' : 'Your conversations will appear here.';
        for (const item of matches) {
            const label = historyGroup(item.updated_at);
            if (label !== group) { list.append(make('h3', 'history-group-heading', label)); group = label; }
            const row = make('div', 'history-item' + (item.id === conversation ? ' current' : ''));
            const open = make('button', 'history-open'), more = make('button', 'history-more');
            const menu = make('div', 'history-menu'), rename = make('button', 'rename-chat', 'Rename');
            const remove = make('button', 'history-delete', 'Delete chat'), title = redact(item.title || 'Untitled chat');
            [open, more, rename, remove].forEach(button => { button.type = 'button'; });
            open.append(make('strong', '', title)); open.title = title;
            if (item.id === conversation) open.setAttribute('aria-current', 'true');
            more.append(icon('more')); more.title = 'Chat options'; more.setAttribute('aria-label', 'Options for ' + title);
            more.setAttribute('aria-expanded', 'false'); menu.hidden = true;
            rename.prepend(icon('edit')); remove.prepend(icon('trash'));
            let confirmed = false;
            more.addEventListener('click', () => {
                const show = menu.hidden; closeHistoryMenus(); confirmed = false;
                remove.replaceChildren(icon('trash'), document.createTextNode('Delete chat')); remove.classList.remove('confirm-delete');
                menu.hidden = !show; more.setAttribute('aria-expanded', String(show));
            });
            rename.addEventListener('click', () => openRename(item));
            open.addEventListener('click', () => { if (!active) void readHistory(item.id); });
            remove.addEventListener('click', async () => {
                if (active || historyMutation) return;
                if (!confirmed) { confirmed = true; remove.classList.add('confirm-delete'); remove.replaceChildren(icon('trash'), document.createTextNode('Confirm delete')); return; }
                historyMutation = true; historyEpoch++; controls();
                let deleted = false;
                try {
                    await invoke('history_delete', {id: item.id});
                    historyItems = historyItems.filter(chat => chat.id !== item.id); deleted = true;
                } catch (_) { status('Could not delete this chat.', true); }
                finally { historyMutation = false; controls(); }
                if (deleted) { if (conversation === item.id) newChat(); else renderHistory(); }
            });
            menu.append(rename, remove); row.append(open, more, menu); list.append(row);
        }
        controls();
    }
    async function loadHistory() {
        const epoch = ++historyEpoch;
        try {
            const data = await invoke('history_list');
            if (destroyed || epoch !== historyEpoch) return;
            historyItems = (data.conversations || []).filter(item => item && typeof item.id === 'string');
            renderHistory();
        } catch (_) {
            if (epoch === historyEpoch && !destroyed) {
                el('history-list').replaceChildren(); el('history-empty').hidden = false;
                el('history-empty').textContent = 'Chat history is unavailable. Use refresh to try again.';
            }
        }
    }
    async function readHistory(id) {
        if (active || historyMutation) return;
        const epoch = ++historyEpoch;
        try {
            const data = await invoke('history_read', {id});
            if (active || destroyed || epoch !== historyEpoch) return;
            conversation = data.id; el('current-chat-title').textContent = redact(data.title || 'Conversation');
            el('messages').replaceChildren(); el('welcome').hidden = false; stickToBottom = true;
            for (const item of data.messages || []) {
                if (!['user', 'assistant'].includes(item.role)) continue;
                const shown = message(item.role, String(item.content || ''));
                for (const saved of item.actions || []) {
                    if (!saved || !['run_command', 'read_file', 'write_file'].includes(saved.name) || !saved.arguments) continue;
                    const card = activity(shown.article, saved), result = saved.result || {};
                    appendOutput(card, result.output || '');
                    if (result.error) appendOutput(card, '\n' + String(result.error));
                    card.card.dataset.state = result.exit_code === 0 && !result.error ? 'complete' : 'error';
                    card.meta.textContent = 'Saved · Exit ' + String(result.exit_code ?? 'unknown');
                }
            }
            el('computer-control').checked = false; el('administrator').checked = false;
            if (mobileLayout) setHistoryOpen(false);
            controls(); scrollChat(true); status('Conversation loaded. Computer control is off.'); void loadHistory();
        } catch (_) { status('Could not open this chat.', true); }
    }
    function newChat() {
        if (historyMutation) return;
        if (active) finish(active, 'Request stopped.');
        conversation = null; historyEpoch++; el('current-chat-title').textContent = 'New chat';
        el('messages').replaceChildren(); el('welcome').hidden = false;
        attachmentEpoch++; pendingFiles = []; renderAttachments(); el('chat-input').value = ''; growComposer();
        el('computer-control').checked = false; el('administrator').checked = false;
        if (mobileLayout) setHistoryOpen(false);
        status(''); controls(); scrollChat(true); void loadHistory(); el('chat-input').focus();
    }
    function applySettings(data) {
        settings={...data,provider:data.provider||'ollama',model:data.model||''};
        el('connection-status').textContent=data.local_error&&settings.provider!=='claude'?'Local AI unavailable':settings.provider==='claude'&&!settings.claude_configured?'Claude setup needed':'Connected to workstation';
        el('model-label').textContent=(settings.provider==='claude'?'Claude · ':'Local · ')+(settings.provider==='claude'?(settings.claude_model||'Automatic model'):settings.model||'Choose a model');
        el('provider').value=settings.provider;el('local-url').value=settings.local_url||'http://127.0.0.1:11434';el('settings-model').value=settings.provider==='claude'?(settings.claude_model||''):settings.model;
        el('key-status').textContent=settings.claude_configured?'A Claude key is saved on this workstation.':'No Claude key saved.';el('delete-key').disabled=!settings.claude_configured;el('claude-key').value='';providerFields();modelOptions(settings.provider==='claude'?[]:settings.local_models||[]);controls();
    }
    function providerFields(){const cloud=el('provider').value==='claude';el('claude-settings').hidden=!cloud;el('local-settings').hidden=cloud;}
    function modelOptions(models){el('available-models').replaceChildren();for(const model of models){const id=typeof model==='string'?model:model.id||model.name;if(!id)continue;const option=make('option');option.value=id;option.label=typeof model==='object'?(model.name||id):id;el('available-models').append(option);}}
    function setSettingsBusy(value){settingsBusy=value;el('settings-form').querySelectorAll('input,select,button').forEach(node=>{node.disabled=value;});if(!value)el('delete-key').disabled=!settings?.claude_configured;controls();}
    function configPayload(){const provider=el('provider').value;return {provider,model:provider==='claude'?(settings?.model||''):el('settings-model').value.trim(),local_url:el('local-url').value.trim(),claude_model:provider==='claude'?el('settings-model').value.trim():(settings?.claude_model||'')};}
    async function saveSettings(event){event.preventDefault();if(active||settingsBusy)return;const data=configPayload();if(el('claude-key').value)data.claude_api_key=el('claude-key').value;el('claude-key').value='';setSettingsBusy(true);el('settings-status').textContent='Saving…';try{const result=await invoke('configure',data);applySettings(result);el('settings-status').textContent='Settings saved. Test the connection to check model availability.';}catch(_){el('settings-status').textContent='Settings could not be saved. Check the local address, model and provider configuration.';}finally{delete data.claude_api_key;setSettingsBusy(false);}}
    async function discover(){if(active||settingsBusy)return;if(el('provider').value==='claude'&&el('claude-key').value){el('settings-status').textContent='Save the new Claude key before testing it.';return;}setSettingsBusy(true);el('settings-status').textContent='Checking the connection…';try{const result=await invoke('models',{provider:el('provider').value,local_url:el('local-url').value.trim()});modelOptions(result.models||[]);el('settings-status').textContent=result.models?.length?'Connected. '+result.models.length+' models available; choose one in the Model field.':'Connected, but no models were found.';}catch(_){el('settings-status').textContent='Could not list models. Check that the local server is running, or that a valid Claude key is saved.';}finally{setSettingsBusy(false);}}
    async function deleteKey(){if(active||settingsBusy)return;el('claude-key').value='';setSettingsBusy(true);try{const result=await invoke('configure',{...configPayload(),delete_claude_key:true});applySettings(result);el('settings-status').textContent='Saved Claude key removed.';}catch(_){el('settings-status').textContent='Could not remove the saved key.';}finally{setSettingsBusy(false);}}
    function renderAttachments(){el('attachments').replaceChildren();pendingFiles.forEach((file,index)=>{const chip=make('span','attachment',file.name),remove=make('button');remove.type='button';remove.setAttribute('aria-label','Remove '+file.name);remove.append(icon('close'));remove.addEventListener('click',()=>{if(!active){pendingFiles.splice(index,1);renderAttachments();controls();}});chip.append(remove);el('attachments').append(chip);});controls();}
    async function attachFiles(){const epoch=historyEpoch,generation=attachmentEpoch;const files=[...el('file-input').files];el('file-input').value='';for(const file of files){if(active||destroyed||epoch!==historyEpoch||generation!==attachmentEpoch)return;if(pendingFiles.length>=4){status('Attach up to four files per request.',true);break;}const image=['image/png','image/jpeg','image/webp'].includes(file.type);if(file.size>(image?2*1024*1024:32*1024)){status(file.name+' is too large. Use images under 2 MB and text files under 32 KB.',true);continue;}try{let data;if(image){const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));data={name:file.name,media_type:file.type,data:btoa(binary)};}else{const text=await file.text();if(text.includes('\0'))throw Error();data={name:file.name,text};}if(active||destroyed||epoch!==historyEpoch||generation!==attachmentEpoch)return;if(pendingFiles.reduce((n,f)=>n+(f.text?.length||0),0)+(data.text?.length||0)>60000||pendingFiles.reduce((n,f)=>n+(f.data?.length||f.text?.length||0),0)+(data.data?.length||data.text?.length||0)>7*1024*1024){status('The attachments exceed the total limit. Use fewer or smaller files.',true);continue;}pendingFiles.push(data);renderAttachments();}catch(_){status('Could not read '+file.name+'. Attach a supported image or plain-text file.',true);}}}
    function init(){
        document.querySelectorAll('[data-icon]').forEach(node=>node.prepend(icon(node.dataset.icon)));
        setHistoryOpen(preferredHistoryOpen()); growComposer();
        el('chat-area').addEventListener('scroll', updateScrollState, {passive:true});
        el('scroll-bottom').addEventListener('click', () => scrollChat(true));
        window.addEventListener('resize', () => {
            const mobile = window.innerWidth < 760;
            if (mobile !== mobileLayout) { mobileLayout = mobile; setHistoryOpen(preferredHistoryOpen()); }
            growComposer(); scrollChat();
        });
        el('composer').addEventListener('submit',send);el('chat-input').addEventListener('input',()=>{growComposer();controls();});el('chat-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();send();}});
        el('stop').addEventListener('click',()=>{if(active)finish(active,'Request stopped. Computer access for this request has ended.');});el('new-chat').addEventListener('click',newChat);
        el('computer-control').addEventListener('change',()=>{if(!el('computer-control').checked)el('administrator').checked=false;controls();});
        el('history-toggle').addEventListener('click', () => setHistoryOpen(el('history-panel').hidden, true, mobileLayout));
        el('history-close').addEventListener('click', () => setHistoryOpen(false, true));
        el('history-backdrop').addEventListener('click', () => setHistoryOpen(false));
        el('history-search').addEventListener('input', renderHistory);
        el('history-refresh').addEventListener('click',()=>void loadHistory());
        el('rename-form').addEventListener('submit', renameHistory);
        el('rename-cancel').addEventListener('click', closeRename);
        el('rename-dialog').addEventListener('cancel', () => { renameId = null; });
        document.addEventListener('click', event => { if (!event.target.closest('.history-item')) closeHistoryMenus(); });
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape') { closeHistoryMenus(); if (mobileLayout && !el('history-panel').hidden) setHistoryOpen(false); }
            if (document.querySelector('dialog[open]')) return;
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setHistoryOpen(true, true, true); }
            if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'o' && !active) { event.preventDefault(); newChat(); }
        });
        el('settings-open').addEventListener('click',()=>{if(active||historyMutation)return;el('claude-key').value='';el('settings-status').textContent='';if(el('settings-dialog').showModal)el('settings-dialog').showModal();else el('settings-dialog').setAttribute('open','');});
        el('model-label').addEventListener('click',()=>el('settings-open').click());
        const clearKey=()=>{el('claude-key').value='';};el('settings-dialog').addEventListener('close',clearKey);el('settings-dialog').addEventListener('cancel',clearKey);el('settings-close').addEventListener('click',()=>{clearKey();if(el('settings-dialog').close)el('settings-dialog').close();else el('settings-dialog').removeAttribute('open');});
        el('provider').addEventListener('change',()=>{providerFields();const cloud=el('provider').value==='claude';modelOptions(!cloud&&el('provider').value===settings?.provider?(settings.local_models||[]):[]);el('settings-model').value=cloud?(settings?.claude_model||''):(settings?.model||'');if(el('provider').value==='openai_local'&&el('local-url').value==='http://127.0.0.1:11434')el('local-url').value='http://127.0.0.1:8000/v1';});
        el('settings-form').addEventListener('submit',saveSettings);el('discover-models').addEventListener('click',discover);el('delete-key').addEventListener('click',deleteKey);el('attach').addEventListener('click',()=>el('file-input').click());el('file-input').addEventListener('change',attachFiles);
        document.querySelectorAll('[data-prompt]').forEach(button=>button.addEventListener('click',()=>{if(active||historyMutation)return;fillComposer(button.dataset.prompt);}));
        try{permission=cockpit.permission({admin:true});permission.addEventListener('changed',()=>{if(active?.admin&&permission.allowed===false)finish(active,'Administrator access was revoked. The request was stopped.',true);});}catch(_){}
        invoke('status').then(data=>{if(!destroyed)applySettings(data);}).catch(()=>{el('connection-status').textContent='Setup needed';status('The AI helper is unavailable. Install the workstation AI components, then reload this tab.',true);});void loadHistory();controls();
        window.addEventListener('beforeunload',()=>{if(active)finish(active);destroyed=true;for(const request of requests)close(request);permission?.close();clearKey();});
    }
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
