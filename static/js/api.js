// api.js — REST + barrramento de eventos (SSE)
export async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const error = new Error(data?.error?.message || `HTTP ${res.status}`);
    error.status = res.status;
    error.code = data?.error?.code;
    error.detail = data?.error?.detail;
    throw error;
  }
  return data;
}

// Bus único de SSE: um EventSource para a página inteira
export function createEventBus() {
  const handlers = new Map(); // topic -> Set(fn)
  const source = new EventSource("/api/events");
  const topics = [
    "cluster.power.state_changed",
    "cluster.power.progress",
    "generation.progress",
    "generation.heartbeat",
    "generation.snapshot",
    "generation.done",
    "session.changed",
    "cluster.reset.done",
  ];
  for (const topic of topics) {
    source.addEventListener(topic, (message) => {
      let payload = {};
      try { payload = JSON.parse(message.data); } catch { /* ignore */ }
      for (const fn of handlers.get(topic) || []) fn(payload);
    });
  }
  return {
    on(topic, fn) {
      if (!handlers.has(topic)) handlers.set(topic, new Set());
      handlers.get(topic).add(fn);
      return () => handlers.get(topic).delete(fn);
    },
  };
}
