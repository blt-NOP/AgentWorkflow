// 真正加载app.js；最小DOM与HTTP替身验证页面控制逻辑。真实浏览器证据另存。
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
class Element {
  constructor() { this.value = ''; this.children = []; this.hidden = false; this.disabled = false; this.checked = false; this.textContent = ''; }
  append(child) { this.children.push(child); }
  replaceChildren() { this.children = []; }
  addEventListener() {}
  setAttribute() {}
  closest() { return this; }
}
const nodes = {};
for (const match of fs.readFileSync(path.join(root, 'frontend/index.html'), 'utf8').matchAll(/id="([^"]+)"/g)) nodes[match[1]] = new Element();
const empty = id => ({session_id:id, facts:{}, messages:[], history:[], evidence:{rows:[],gaps:[]}, trace:[], skill:'research-dialogue', status:'WAITING_USER'});
const saved = {A:empty('A'), B:empty('B')};
let mode = 'success', calls = [], count = 0;
function completed(payload) {
  const state = {...empty(payload.session_id), request_id:payload.request_id, facts:payload.facts,
    messages:[{role:'assistant',content:'恢复成功'}]};
  saved[payload.session_id] = state;
  return {request_id:payload.request_id,state,status:'WAITING_USER'};
}
const context = vm.createContext({console, TextDecoder, TextEncoder, AbortController, Response, ReadableStream,
  setTimeout, clearTimeout, FormData, crypto:{randomUUID:()=>`request-${++count}`},
  localStorage:{getItem:()=> 'A',setItem(){}},
  document:{getElementById:id=>nodes[id],createElement:()=>new Element(),querySelectorAll:()=>[]},
  ResearchStream:require('../frontend/stream.js'),
  fetch:async (url, options={}) => {
    if (url === '/api/chat/stream') {
      const p = JSON.parse(options.body); calls.push(p);
      if (mode === 'stall' || mode === 'late') {
        if (mode === 'late') completed(p); // 后端已完成，客户端没有收到终态。
        return new Response(new ReadableStream({start(c) {
          options.signal.addEventListener('abort',()=>c.error(new Error('aborted')),{once:true});
        }}));
      }
      const types = mode === 'fail' ? [['started',{}],['failed',{message:'依赖超时，请恢复后重试',code:'TIMEOUT'}]] :
        [['started',{}],['completed',completed(p)]];
      return new Response(types.map(([type,data],i)=>'data: '+JSON.stringify({type,data,seq:i+1,session_id:p.session_id,request_id:p.request_id})+'\n\n').join(''));
    }
    const value = url === '/api/health' ? {model_enabled:false,model_configured:false} :
      url === '/api/skills' ? [{id:'research-dialogue',name:'research-dialogue'}] :
      url.startsWith('/api/sessions/') ? saved[decodeURIComponent(url.split('/').at(-1))] : [];
    return Response.json(value);
  }});
const execute = code => vm.runInContext(code, context);
const checks = [];
function check(value,label) { assert.ok(value,label); checks.push(label); console.log('PASS: '+label); }
(async()=>{
  execute(fs.readFileSync(path.join(root,'frontend/app.js'),'utf8'));
  await new Promise(resolve=>setTimeout(resolve,10));
  mode='fail'; nodes.compute.value='CPU'; nodes.message.value='继续';
  await execute("submitChat('继续')");
  check(nodes.status.textContent.includes('依赖超时') && !nodes['retry-chat'].hidden && !nodes['retry-chat'].disabled,'失败原因可见、停止等待、重试可用');
  const first = calls.at(-1);
  mode='success'; nodes.compute.value='GPU';
  await nodes['retry-chat'].onclick();
  check(calls.at(-1).session_id==='A' && calls.at(-1).request_id!==first.request_id && calls.at(-1).facts.compute==='CPU', '重试固定原会话和原输入，使用新请求编号');
  check(nodes['retry-chat'].hidden && nodes.messages.children.at(-1).textContent.includes('恢复成功'),'依赖恢复后原页面成功展示结果');
  mode='stall'; execute('chatTimeoutMs=20;streamIdleMs=100');
  await execute("submitChat('继续')");
  check(nodes.status.textContent.includes('已停止等待') && !execute('latestRequest().running') && !nodes['retry-chat'].hidden,'总期限到达后解除等待并说明可核对重试');
  const original=calls.at(-1);
  mode='fail'; await nodes['retry-chat'].onclick(); // 提前重试仍失败，原请求稍后保存。
  completed(original);
  const attempts=calls.length;
  await nodes['retry-chat'].onclick();
  check(calls.length===attempts && nodes.status.textContent.includes('已恢复原请求'),'提前重试失败后仍能识别更早原请求的迟到结果，避免重复执行');
  mode='late';
  await execute("submitChat('继续')");
  const before=calls.length;
  await nodes['retry-chat'].onclick();
  check(calls.length===before && nodes.status.textContent.includes('已恢复原请求'),'迟到结果已保存时直接找回，不重复提交');
  mode='stall';
  const pending = execute("submitChat('继续')");
  await execute("sessionId='B'; loadSession()");
  await pending;
  check(!nodes.status.textContent.includes('已停止等待') && nodes.messages.children.length===0 && nodes['retry-chat'].hidden,'A的晚到超时不覆盖B的页面或重试入口');
  await execute("sessionId='A'; loadSession()");
  check(!nodes['retry-chat'].hidden && nodes.status.textContent.includes('已停止等待'),'返回A可继续处理A的失败请求');
  const output=path.join(root,'tests/recovery_results'); fs.mkdirSync(output,{recursive:true});
  fs.writeFileSync(path.join(output,'frontend-summary.json'),JSON.stringify({result:'PASS',checks,requests:calls,notice:'DOM/HTTP替身测试，非真实浏览器；真实截图同目录。'},null,2));
  console.log(`RESULT: PASS (${checks.length} checks)`);
})().catch(error=>{console.error(error);process.exitCode=1;});
