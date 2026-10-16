/* Authenticated domain API adapter. Local demo accounts never send data to AWS. */
(() => {
  const cfg = window.APP_CONFIG || {};
  const KEYS = ["ideas4", "fp1", "asg1", "notes1", "wlog1", "weights1", "theme1"];
  let active = null, timer = null, applying = false, busy = false, baseline = {}, publicLibrary = [];
  const originalSet = Storage.prototype.setItem;
  const safeSet = (key, value) => { try { applying = true; originalSet.call(localStorage, key, value); } catch (_) {} finally { applying = false; } };
  const read = key => { try { return JSON.parse(localStorage.getItem(key) || "null"); } catch (_) { return null; } };
  const writeJson = (key, value) => safeSet(key, JSON.stringify(value));
  const token = () => sessionStorage.getItem("cognito_id_token");
  const enabled = () => Boolean(cfg.apiBaseUrl && cfg.userPoolId && cfg.userPoolClientId);
  async function request(path, method = "GET", body) {
    if (!active || !enabled() || !token()) throw new Error("Sign in to use the cloud workspace.");
    const res = await fetch(cfg.apiBaseUrl.replace(/\/$/, "") + path, {
      method, headers: { Authorization: token(), "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `API request failed (${res.status})`);
    return data;
  }
  const parseArray = x => Array.isArray(x) ? x : [];
  const mapIdea = d => ({ ...d, owner: String(d.ownerEmail || d.owner || "").toLowerCase(), ownerEmail: String(d.ownerEmail || "").toLowerCase(), team: parseArray(d.team),
    created: Number(d.created || 0) * (Number(d.created || 0) < 1e12 ? 1000 : 1),
    log: parseArray(d.log).map(x => ({ ...x, at: Number(x.at || 0) * (Number(x.at || 0) < 1e12 ? 1000 : 1) })) });
  const mapAssignment = a => ({ ...a, owner: String(a.ownerEmail || a.owner || "").toLowerCase(), closed: Boolean(a.closed) });
  const mapProject = p => ({ ...p, owner: String(p.ownerEmail || p.ownerName || "Faculty").toLowerCase(), ownerEmail: String(p.ownerEmail || "").toLowerCase(), slots: Number(p.slots || 1),
    requests: parseArray(p.requests).map(r => ({ ...r, student: r.email || r.student || "", at: Number(r.created || r.at || 0) * (Number(r.created || r.at || 0) < 1e12 ? 1000 : 1), status: r.status === "Declined" ? "Declined" : r.status })) });
  const mapNote = n => ({ ...n, to: active?.email || "", at: Number(n.at || 0) * (Number(n.at || 0) < 1e12 ? 1000 : 1), read: Boolean(n.seen) });
  async function loadDomain() {
    const [ideas, assignments, projects, settings, notifications, library] = await Promise.all([
      request("/ideas"), request("/assignments"), request("/projects"), request("/settings"), request("/notifications"), request("/library")
    ]);
    publicLibrary = parseArray(library);
    const mapped = {
      ideas4: parseArray(ideas).map(mapIdea),
      asg1: parseArray(assignments).map(mapAssignment),
      fp1: parseArray(projects).map(mapProject),
      notes1: parseArray(notifications).map(mapNote),
      weights1: settings?.weights || null,
      wlog1: settings?.log || []
    };
    applying = true;
    try {
      for (const [key, value] of Object.entries(mapped)) if (value !== null) originalSet.call(localStorage, key, JSON.stringify(value));
      sessionStorage.setItem("cloud_domain_loaded", active.sub);
    } finally { applying = false; }
    baseline = snapshot();
    return mapped;
  }
  function snapshot() {
    const out = {};
    for (const key of KEYS) out[key] = read(key);
    return out;
  }
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  function queue() {
    if (!active || applying || busy) return;
    clearTimeout(timer); timer = setTimeout(() => syncDomain().catch(e => console.warn("Cloud save failed:", e.message)), 500);
  }
  async function syncIdeas(now, before) {
    const old = new Map(parseArray(before.ideas4).map(x => [x.id, x]));
    const cur = parseArray(now.ideas4);
    for (const prev of old.values()) if (!cur.some(x => x.id === prev.id) && prev.id && !String(prev.id).startsWith("i")) {
      await request("/ideas/" + encodeURIComponent(prev.id), "DELETE");
    }
    for (let i = 0; i < cur.length; i++) {
      let item = cur[i], prev = old.get(item.id);
      if (!prev && String(item.id || "").startsWith("i")) {
        const payload = { ...item, id: undefined, owner: undefined, status: "Pending" };
        const created = mapIdea(await request("/ideas", "POST", payload));
        cur[i] = created;
        old.set(created.id, created);
        writeJson("ideas4", cur);
        continue;
      }
      if (!prev || String(item.id || "").startsWith("seed") || String(item.id || "").startsWith("s")) continue;
      if (item.status !== prev.status || item.feedback !== prev.feedback || item.ovr !== prev.ovr) {
        await request("/ideas/" + encodeURIComponent(item.id), "PATCH", { status: item.status, feedback: item.feedback || "", innovation: item.ovr == null ? null : item.ovr });
      }
      if (item.gh !== prev.gh || item.demo !== prev.demo || item.note !== prev.note || item.pub !== prev.pub) {
        await request("/ideas/" + encodeURIComponent(item.id), "PATCH", { gh: item.gh || "", demo: item.demo || "", note: item.note || "", pub: item.pub !== false });
      }
    }
  }
  async function syncAssignments(now, before) {
    const old = new Map(parseArray(before.asg1).map(x => [x.id, x]));
    for (const item of parseArray(now.asg1)) {
      const prev = old.get(item.id);
      if (!prev && String(item.id || "").startsWith("a")) {
        const created = await request("/assignments", "POST", item);
        item.id = created.id;
        writeJson("asg1", now.asg1);
      } else if (prev && item.closed !== prev.closed && String(item.id || "").startsWith("asg:")) {
        await request("/assignments/" + encodeURIComponent(item.id), "PATCH", {});
      }
    }
  }
  async function syncProjects(now, before) {
    const old = new Map(parseArray(before.fp1).map(x => [x.id, x]));
    for (const item of parseArray(now.fp1)) {
      const prev = old.get(item.id);
      if (!prev && String(item.id || "").startsWith("p")) {
        const created = await request("/projects", "POST", { title: item.title, desc: item.desc, skills: item.skills, slots: item.slots, deadline: item.deadline || "" });
        Object.assign(item, mapProject(created));
        writeJson("fp1", now.fp1);
        continue;
      }
      if (!prev || !String(item.id || "").startsWith("fp:")) continue;
      const path = "/projects/" + encodeURIComponent(item.id);
      const beforeReq = new Map(parseArray(prev.requests).map(r => [r.id, r]));
      for (const r of parseArray(item.requests)) {
        const pr = beforeReq.get(r.id);
        if (!pr && r.status === "Pending") await request(path, "PATCH", { action: "request", msg: r.msg });
        else if (pr && r.status !== pr.status) {
          if (r.status === "Withdrawn") await request(path, "PATCH", { action: "withdraw" });
          else if (r.status === "Accepted" || r.status === "Declined") await request(path, "PATCH", { action: "decide", requestId: r.id, decision: r.status });
          else if (r.status === "Removed") await request(path, "PATCH", { action: "remove", requestId: r.id });
        }
      }
      if (item.status !== prev.status) await request(path, "PATCH", { action: "toggle" });
      if (item.gh !== prev.gh || item.demo !== prev.demo || item.pub !== prev.pub) await request(path, "PATCH", { action: "links", gh: item.gh || "", demo: item.demo || "", pub: item.pub !== false });
    }
  }
  async function syncDomain() {
    if (!active || busy) return;
    busy = true;
    try {
      const now = snapshot(), before = baseline;
      const domainChanged = !same(now.ideas4, before.ideas4) || !same(now.asg1, before.asg1) || !same(now.fp1, before.fp1) || !same(now.weights1, before.weights1);
      await syncIdeas(now, before);
      await syncAssignments(now, before);
      await syncProjects(now, before);
      const currentWeights = now.weights1;
      if (currentWeights && !same(currentWeights, before.weights1)) await request("/settings", "PUT", { weights: currentWeights });
      if (domainChanged) {
        // Reload canonical records so generated server IDs and request IDs are used by the UI.
        await loadDomain();
        window.dispatchEvent(new CustomEvent("cloud-state-updated"));
      } else {
        baseline = snapshot();
      }
    } finally { busy = false; }
  }
  Storage.prototype.setItem = function(key, value) {
    originalSet.call(this, key, value);
    if (this === localStorage && KEYS.includes(String(key))) queue();
  };
  window.AppCloud = {
    enabled,
    request,
    get publicLibrary() { return publicLibrary; },
    async activate(user) {
      if (!enabled() || !user?.sub || user.localDemo) return;
      active = user;
      const oldOwner = localStorage.getItem("cloud_owner_sub");
      if (oldOwner && oldOwner !== user.sub) {
        applying = true; KEYS.forEach(k => localStorage.removeItem(k)); applying = false;
        sessionStorage.removeItem("cloud_domain_loaded"); safeSet("cloud_owner_sub", user.sub); location.reload(); return;
      }
      safeSet("cloud_owner_sub", user.sub);
      if (sessionStorage.getItem("cloud_domain_loaded") === user.sub) { baseline = snapshot(); return; }
      try { await loadDomain(); location.reload(); }
      catch (err) { console.error("Cloud workspace could not be loaded:", err.message); throw err; }
    },
    async deactivate() { try { await syncDomain(); } finally { active = null; clearTimeout(timer); sessionStorage.removeItem("cloud_domain_loaded"); } },
    async syncNow() { await syncDomain(); },
    async markNotificationsSeen() { await request("/notifications", "PATCH", {}); }
  };
})();
