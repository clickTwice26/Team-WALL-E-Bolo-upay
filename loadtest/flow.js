// k6 load test of the payment flow: login -> parse -> assess -> execute.
//
// Needs a server with DEMO_MODE=true (demo PIN 1234, users u1..u3),
// HOLD_SECONDS=0 (a RED hold would park the virtual user) and no LLM key:
//   cd api && DEMO_MODE=true HOLD_SECONDS=0 AUTH_SECRET=x gunicorn -c gunicorn.conf.py app.main:app
//   docker run --rm -i -e BASE=http://host.docker.internal:8000 -e VUS=50 grafana/k6 run - < loadtest/flow.js
//
// Each virtual user signs in once (a session lasts 30 minutes), then loops
// parse -> assess -> execute with THINK seconds between steps, like a person.
// Transfers are Tk 1 to a saved contact and setup() resets the demo data, so
// balances never run out. Only the right PIN is sent, so nothing gets locked.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE = __ENV.BASE || 'http://localhost:8000';
const VUS = Number(__ENV.VUS || 50);
const THINK = Number(__ENV.THINK || 1);

export const options = {
  scenarios: {
    flow: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: __ENV.RAMP || '15s', target: VUS },
        { duration: __ENV.DURATION || '60s', target: VUS },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    // the target: risk check p95 under 300 ms without an LLM (CI's small runner gets more)
    step_assess: [`p(95)<${__ENV.ASSESS_P95 || 300}`],
  },
  summaryTrendStats: ['med', 'p(95)', 'p(99)', 'max'],
};

const step = {
  login: new Trend('step_login', true),
  parse: new Trend('step_parse', true),
  assess: new Trend('step_assess', true),
  execute: new Trend('step_execute', true),
  cancel: new Trend('step_cancel', true),
};
const blocked = new Rate('flow_blocked'); // assess said BLOCKED (would mean balances ran out)
const COMMAND = { u1: 'Ammu ke 1 taka pathao', u2: 'Abbu ke 1 taka pathao', u3: 'Riya ke 1 taka pathao' };
const JSON_HDR = { 'Content-Type': 'application/json' };

function post(path, body, token, name, extra = {}) {
  const headers = Object.assign({}, JSON_HDR, extra, token ? { Authorization: `Bearer ${token}` } : {});
  const r = http.post(`${BASE}${path}`, JSON.stringify(body), { headers, tags: { name } });
  step[name].add(r.timings.duration);
  check(r, { [`${name} 200`]: (x) => x.status === 200 });
  return r;
}

export function setup() {
  const r = http.post(`${BASE}/api/login`, JSON.stringify({ user_id: 'u1', pin: '1234' }), { headers: JSON_HDR });
  const reset = http.post(`${BASE}/api/demo/reset`, null,
    { headers: { Authorization: `Bearer ${r.json('token')}` } });
  if (reset.status !== 200) throw new Error(`demo reset failed (${reset.status}): is DEMO_MODE=true?`);
}

let token = null; // one session per virtual user

export default function () {
  const uid = `u${((__VU - 1) % 3) + 1}`;
  if (!token) {
    const r = post('/api/login', { user_id: uid, pin: '1234' }, null, 'login');
    if (r.status !== 200) return sleep(THINK);
    token = r.json('token');
  }
  const p = post('/api/parse', { text: COMMAND[uid], use_llm: false }, token, 'parse');
  if (p.status !== 200 || !p.json('recipient')) return sleep(THINK);
  sleep(THINK);

  const draft = { intent: p.json('intent'), amount: p.json('amount'), recipient_phone: p.json('recipient.phone'),
    is_return_claim: p.json('is_return_claim'), command_text: COMMAND[uid] };
  const a = post('/api/assess', { draft }, token, 'assess');
  if (a.status !== 200) return sleep(THINK);
  blocked.add(a.json('level') === 'BLOCKED');
  if (a.json('level') === 'BLOCKED') return sleep(THINK);
  sleep(THINK);
  // NO_EXECUTE=1 measures the risk check alone, without the bcrypt PIN check
  if (__ENV.NO_EXECUTE) {
    post('/api/cancel', { assessment_id: a.json('assessment_id') }, token, 'cancel');
    return sleep(THINK);
  }

  // PIN works at every level; a RED warning is acknowledged (HOLD_SECONDS=0)
  post('/api/execute', { assessment_id: a.json('assessment_id'), method: 'pin', pin: '1234',
    acknowledged_warning: true }, token, 'execute', { 'Idempotency-Key': `k6-${__VU}-${__ITER}-${Date.now()}` });
  sleep(THINK);
}
