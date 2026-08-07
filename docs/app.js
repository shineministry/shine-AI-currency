(function () {
  "use strict";

  const CURRENCY_WORDS = {
    usd: "USD", dollar: "USD", dollars: "USD",
    eur: "EUR", euro: "EUR", euros: "EUR",
    gbp: "GBP", pound: "GBP", pounds: "GBP", sterling: "GBP",
    inr: "INR", rupee: "INR", rupees: "INR",
    jpy: "JPY", yen: "JPY",
    aud: "AUD", cad: "CAD",
    chf: "CHF", franc: "CHF",
    cny: "CNY", yuan: "CNY", renminbi: "CNY",
    hkd: "HKD", nzd: "NZD",
    sek: "SEK", nok: "NOK", dkk: "DKK",
    pln: "PLN", zloty: "PLN",
    try: "TRY", lira: "TRY",
    rub: "RUB", ruble: "RUB", rouble: "RUB",
    zar: "ZAR", rand: "ZAR",
    brl: "BRL", real: "BRL",
    mxn: "MXN", peso: "MXN",
    sgd: "SGD"
  };

  const SYMBOLS = {
    USD: "$", EUR: "\u20ac", GBP: "\u00a3", JPY: "\u00a5", INR: "\u20b9",
    AUD: "A$", CAD: "C$", CHF: "Fr", CNY: "\u00a5", HKD: "HK$", NZD: "NZ$",
    SEK: "kr", NOK: "kr", DKK: "kr", PLN: "z\u0142", TRY: "\u20ba", RUB: "\u20bd",
    ZAR: "R", BRL: "R$", MXN: "MX$", SGD: "S$", CZK: "K\u010d", HUF: "Ft",
    IDR: "Rp", ILS: "\u20aa", ISK: "kr", KRW: "\u20a9", MYR: "RM", PHP: "\u20b1",
    RON: "lei", THB: "\u0e3f"
  };

  const NAMES = {
    USD: "US Dollar", EUR: "Euro", GBP: "British Pound", JPY: "Japanese Yen",
    INR: "Indian Rupee", AUD: "Australian Dollar", CAD: "Canadian Dollar",
    CHF: "Swiss Franc", CNY: "Chinese Yuan", HKD: "Hong Kong Dollar",
    NZD: "New Zealand Dollar", SEK: "Swedish Krona", NOK: "Norwegian Krone",
    DKK: "Danish Krone", PLN: "Polish Zloty", TRY: "Turkish Lira",
    RUB: "Russian Ruble", ZAR: "South African Rand", BRL: "Brazilian Real",
    MXN: "Mexican Peso", SGD: "Singapore Dollar", CZK: "Czech Koruna",
    HUF: "Hungarian Forint", IDR: "Indonesian Rupiah", ILS: "Israeli Shekel",
    ISK: "Icelandic Krona", KRW: "South Korean Won", MYR: "Malaysian Ringgit",
    PHP: "Philippine Peso", RON: "Romanian Leu", THB: "Thai Baht"
  };

  const FNV_OFFSET = 0xcbf29ce484222325n;
  const FNV_PRIME = 0x100000001b3n;
  const FNV_MASK = (1n << 64n) - 1n;
  const EMBED_DIM = 384;

  const THEME_KEY = "shinefx-theme";

  let state = { latest: null, history: null, context: null, base: "EUR" };
  let lastRefresh = 0;
  let sortKey = "pair", sortDir = "asc";
  let timeframe = 7;        // history chart
  let convTimeframe = 7;    // convert chart
  let favorites = new Set(JSON.parse(localStorage.getItem("shinefx-favs") || "[]"));
  let alerts = JSON.parse(localStorage.getItem("shinefx-alerts") || "[]");
  let comparePairs = JSON.parse(localStorage.getItem("shinefx-compare") || "[]");

  const $ = (id) => document.getElementById(id);

  /* ---------- Theme ---------- */

  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function storedTheme() {
    const saved = localStorage.getItem(THEME_KEY);
    return saved === "light" || saved === "dark" ? saved : null;
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(THEME_KEY, theme);
    if (state.latest) renderRates();
    if (state.history) { renderConvertChart(); renderHistChart(); }
  }

  function toggleTheme() {
    applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  }

  /* ---------- Utils ---------- */

  function fnv1a64(str) {
    let h = FNV_OFFSET;
    for (let i = 0; i < str.length; i++) {
      h ^= BigInt(str.charCodeAt(i));
      h = (h * FNV_PRIME) & FNV_MASK;
    }
    return h;
  }

  function tokenize(text) {
    return (text.toLowerCase().match(/[a-z0-9]{2,}/g) || []).map((w) => CURRENCY_WORDS[w] || w);
  }

  function embed(text) {
    const v = new Float64Array(EMBED_DIM);
    for (const w of tokenize(text)) {
      const h = fnv1a64(w);
      v[Number(h % BigInt(EMBED_DIM))] += (h >> 63n) === 0n ? 1 : -1;
    }
    let norm = 0;
    for (let i = 0; i < EMBED_DIM; i++) norm += v[i] * v[i];
    norm = Math.sqrt(norm) || 1;
    for (let i = 0; i < EMBED_DIM; i++) v[i] /= norm;
    return v;
  }

  function dot(a, b) {
    let s = 0;
    for (let i = 0; i < a.length; i++) s += a[i] * b[i];
    return s;
  }

  async function loadJSON(url) {
    const resp = await fetch(url, { cache: "no-cache" });
    if (!resp.ok) throw new Error(url + " -> " + resp.status);
    return resp.json();
  }

  function fmt(n, d) {
    d = d === undefined ? 4 : d;
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: d });
  }

  function fmtDate(ts) {
    return new Date(ts * 1000).toLocaleString();
  }

  function fmtClock(d) {
    return d.toISOString().substr(11, 8) + " UTC";
  }

  function label(code) {
    return NAMES[code] || code;
  }

  function symbol(code) {
    return SYMBOLS[code] || code;
  }

  function trendClass(t) {
    return t === "rising" ? "up" : t === "falling" ? "down" : "flat";
  }

  function trendArrow(t) {
    return t === "rising" ? "\u25b2" : t === "falling" ? "\u25bc" : "\u2014";
  }

  function animateNumber(el, target, duration, format) {
    const start = performance.now();
    const from = 0;
    format = format || fmt;
    function step(now) {
      const p = Math.min(1, (now - start) / (duration || 900));
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = format(from + (target - from) * eased);
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function initReveal() {
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && (e.target.classList.add("in"), io.unobserve(e.target))),
      { threshold: 0.1 }
    );
    document.querySelectorAll(".reveal").forEach((el) => io.observe(el));
    document.querySelectorAll(".reveal").forEach((el) => {
      if (el.getBoundingClientRect().top < window.innerHeight) el.classList.add("in");
    });
  }

  /* ---------- Visit Streak ---------- */

  function updateStreak() {
    const today = new Date().toISOString().slice(0, 10);
    const last = localStorage.getItem("shinefx-last-visit");
    const streak = parseInt(localStorage.getItem("shinefx-streak") || "0", 10);
    let newStreak = streak;
    if (last === today) {
      newStreak = streak || 1;
    } else if (last) {
      const diff = (new Date(today) - new Date(last)) / 86400000;
      newStreak = diff <= 1 ? streak + 1 : 1;
    } else {
      newStreak = 1;
    }
    localStorage.setItem("shinefx-last-visit", today);
    localStorage.setItem("shinefx-streak", String(newStreak));
    const el = $("footStreak");
    if (el && newStreak > 1) el.textContent = "\uD83D\uDD25 " + newStreak + " day streak";
  }

  /* ---------- Base Currency Selector ---------- */

  function buildBaseSelect() {
    if (!state.latest) return;
    const allCodes = [state.latest.base].concat(state.latest.currencies || Object.keys(state.latest.rates).sort());
    const sel = $("baseSelect");
    sel.innerHTML = allCodes.map((c) =>
      "<option value='" + c + "'" + (c === state.base ? " selected" : "") + ">" + c + "</option>"
    ).join("");
  }

  function onBaseChange() {
    const newBase = $("baseSelect").value;
    if (newBase === state.base) return;
    state.base = newBase;
    localStorage.setItem("shinefx-base", newBase);
    buildSelects();
    doConvert();
    renderStats();
    renderRates();
    renderHistChart();
    buildTicker();
    buildWatchlist();
    renderCompare();
  }

  function ratesForBase(base) {
    if (!state.latest || !state.latest.rates) return {};
    const eurRates = state.latest.rates;
    if (base === "EUR") return Object.assign({}, eurRates, { EUR: 1.0 });
    const baseEur = eurRates[base];
    if (!baseEur) return {};
    const result = { EUR: 1.0 / baseEur };
    for (const [code, rate] of Object.entries(eurRates)) {
      if (code !== base) result[code] = rate / baseEur;
    }
    return result;
  }

  /* ---------- Share ---------- */

  function shareRate() {
    const from = $("fromCur").value;
    const to = $("toCur").value;
    const amount = $("amount").value;
    const url = location.origin + location.pathname + "#pair=" + from + "-" + to + "&amt=" + amount;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(url).then(() => {
        const btn = $("shareBtn");
        btn.classList.add("copied");
        setTimeout(() => btn.classList.remove("copied"), 1500);
      });
    } else {
      prompt("Copy this link:", url);
    }
  }

  /* ---------- Price Alerts ---------- */

  function renderAlerts() {
    const list = $("alertList");
    if (!list) return;
    if (!alerts.length) {
      list.innerHTML = "<div class='alert-empty'>No alerts set. Create one above to get notified when rates cross your target.</div>";
      return;
    }
    list.innerHTML = alerts.map((a, i) => {
      const curRate = state.latest && state.latest.rates ? ratesForBase(state.base)[a.pair.split("/")[1]] : null;
      let status = "active";
      let statusText = "watching";
      if (curRate != null) {
        if ((a.dir === "above" && curRate >= a.target) || (a.dir === "below" && curRate <= a.target)) {
          status = "triggered";
          statusText = "triggered!";
        }
      }
      return "<div class='alert-item'>" +
        "<div class='alert-info'>" +
        "<span class='alert-pair'>" + a.pair + "</span>" +
        "<span class='alert-dir'>" + (a.dir === "above" ? "\u25b2 above" : "\u25bc below") + "</span>" +
        "<span class='alert-target'>" + fmt(a.target, 4) + "</span>" +
        "</div>" +
        "<div style='display:flex;align-items:center;gap:8px'>" +
        "<span class='alert-status " + status + "'>" + statusText + "</span>" +
        "<button class='alert-remove' data-i='" + i + "' title='Remove'>&times;</button>" +
        "</div></div>";
    }).join("");
    list.querySelectorAll(".alert-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        alerts.splice(parseInt(btn.dataset.i, 10), 1);
        localStorage.setItem("shinefx-alerts", JSON.stringify(alerts));
        renderAlerts();
      });
    });
  }

  function addAlert() {
    const pair = $("alertPair").value;
    const dir = $("alertDir").value;
    const target = parseFloat($("alertTarget").value);
    if (!pair || !isFinite(target) || target <= 0) return;
    alerts.push({ pair: pair, dir: dir, target: target });
    localStorage.setItem("shinefx-alerts", JSON.stringify(alerts));
    $("alertTarget").value = "";
    renderAlerts();
    checkAlerts();
  }

  function checkAlerts() {
    if (!state.latest || !alerts.length) return;
    const eurRates = ratesForBase(state.base);
    alerts.forEach((a) => {
      const parts = a.pair.split("/");
      const toCode = parts[1];
      const rate = eurRates[toCode];
      if (rate == null) return;
      const triggered = (a.dir === "above" && rate >= a.target) || (a.dir === "below" && rate <= a.target);
      if (triggered && !a._fired) {
        a._fired = true;
        if ("Notification" in window && Notification.permission === "granted") {
          new Notification("ShineFX Alert: " + a.pair, {
            body: "Rate is now " + fmt(rate, 4) + " (" + a.dir + " " + fmt(a.target, 4) + ")",
          });
        }
      } else if (!triggered) {
        a._fired = false;
      }
    });
  }

  /* ---------- Compare ---------- */

  function renderCompare() {
    const grid = $("compareGrid");
    const picks = $("comparePicks");
    if (!grid || !picks) return;

    const allQuotes = state.latest ? (state.latest.currencies || Object.keys(state.latest.rates).sort()) : [];
    const validPairs = comparePairs.filter((p) => {
      const parts = p.split("/");
      return allQuotes.includes(parts[1]);
    });
    comparePairs = validPairs;

    if (!comparePairs.length) {
      picks.innerHTML = "";
      grid.innerHTML = "<div class='compare-empty'>Add currency pairs above to compare them side-by-side.</div>";
      return;
    }

    picks.innerHTML = comparePairs.map((p, i) =>
      "<span class='compare-pick'>" + p +
      "<button class='compare-remove' data-i='" + i + "'>&times;</button></span>"
    ).join("");
    picks.querySelectorAll(".compare-remove").forEach((btn) => {
      btn.addEventListener("click", () => {
        comparePairs.splice(parseInt(btn.dataset.i, 10), 1);
        localStorage.setItem("shinefx-compare", JSON.stringify(comparePairs));
        renderCompare();
      });
    });

    const eurRates = ratesForBase(state.base);
    grid.innerHTML = comparePairs.map((p) => {
      const parts = p.split("/");
      const toCode = parts[1];
      const rate = eurRates[toCode];
      const t = state.latest.trends[toCode] || {};
      const cls = trendClass(t.trend);
      return "<div class='compare-card'>" +
        "<div class='cc-pair'>" + state.base + "/" + toCode + "</div>" +
        "<div class='cc-rate " + cls + "'>" + (rate ? fmt(rate, 4) : "\u2014") + "</div>" +
        "<div class='cc-change " + cls + "'>" + (t.change_pct != null ? (t.change_pct >= 0 ? "+" : "") + fmt(t.change_pct, 2) + "%" : "") + "</div>" +
        "</div>";
    }).join("");

    const pts = comparePairs.map((p) => {
      const parts = p.split("/");
      return trendPoints(parts[0] + "/" + parts[1], 30);
    });
    drawCompareChart($("compareChart"), pts, comparePairs);
  }

  function drawCompareChart(canvas, seriesList, labels) {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth || 720;
    const H = canvas.clientHeight || 300;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const colors = ["#1a73e8", "#d93025", "#188038", "#f9ab00"];
    const padL = 62, padR = 16, padT = 30, padB = 34;
    const iw = W - padL - padR, ih = H - padT - padB;

    if (!seriesList.length || !seriesList[0].length) {
      ctx.fillStyle = cssVar("--chart-text");
      ctx.font = "13px 'Google Sans', Segoe UI, Arial";
      ctx.textAlign = "center";
      ctx.fillText("Add pairs to compare", W / 2, H / 2);
      return;
    }

    const allRates = seriesList.flat().map((p) => p[1]);
    let min = Math.min.apply(null, allRates);
    let max = Math.max.apply(null, allRates);
    const span = max - min || 1;
    min -= span * 0.08;
    max += span * 0.08;

    const maxLen = Math.max.apply(null, seriesList.map((s) => s.length));
    const x = (i) => padL + (i / (maxLen - 1)) * iw;
    const y = (v) => padT + ih - ((v - min) / (max - min)) * ih;

    ctx.fillStyle = cssVar("--chart-text");
    ctx.font = "13px 'Google Sans', Segoe UI, Arial";
    ctx.textAlign = "left";
    ctx.fillText("Compare (" + labels.join(", ") + ")", 14, 12);

    ctx.strokeStyle = cssVar("--chart-grid");
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const gv = min + ((max - min) * i) / 4;
      const gy = y(gv);
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(W - padR, gy); ctx.stroke();
      ctx.fillStyle = cssVar("--chart-text"); ctx.fillText(gv.toFixed(4), 4, gy - 6);
    }

    seriesList.forEach((points, si) => {
      if (points.length < 2) return;
      ctx.strokeStyle = colors[si % colors.length];
      ctx.lineWidth = 2;
      ctx.beginPath();
      points.forEach((p, i) => { i === 0 ? ctx.moveTo(x(i), y(p[1])) : ctx.lineTo(x(i), y(p[1])); });
      ctx.stroke();
    });
  }

  function addComparePair() {
    const allQuotes = state.latest ? (state.latest.currencies || Object.keys(state.latest.rates).sort()) : [];
    const remaining = allQuotes.filter((q) => !comparePairs.includes(state.base + "/" + q));
    if (!remaining.length || comparePairs.length >= 4) return;
    const pick = remaining[0];
    comparePairs.push(state.base + "/" + pick);
    localStorage.setItem("shinefx-compare", JSON.stringify(comparePairs));
    renderCompare();
  }

  function startClock() {
    const tick = () => { $("clock").textContent = fmtClock(new Date()); };
    tick();
    setInterval(tick, 1000);
  }

  function buildTicker() {
    const latest = state.latest;
    if (!latest) return;
    const items = [];
    const eurRates = ratesForBase(state.base);
    const quotes = Object.keys(eurRates).filter((q) => q !== state.base).sort();
    for (const q of quotes) {
      const t = latest.trends[q] || {};
      const cls = trendClass(t.trend);
      const arrow = trendArrow(t.trend);
      items.push(
        "<span class='tick-item'><b>" + state.base + "/" + q + "</b> " +
        fmt(eurRates[q], 6) + " <span class='" + cls + "'>" + arrow + "</span></span>"
      );
    }
    const half = items.join("");
    $("ticker").innerHTML = "<div>" + half + "</div><div>" + half + "</div>";
  }

  function buildSelects() {
    const quotes = state.latest.currencies || Object.keys(state.latest.rates).sort();
    const codes = [state.base].concat(quotes);
    const opts = codes.map((c) => "<option value='" + c + "'>" + c + " \u2014 " + label(c) + "</option>").join("");
    $("fromCur").innerHTML = opts;
    $("toCur").innerHTML = opts;
    $("toCur").value = quotes[0] || "USD";
    $("histPair").innerHTML = quotes.map((q) => "<option value='" + q + "'>" + state.base + "/" + q + "</option>").join("");
    $("histPair").value = quotes[0] || "USD";
    if ($("alertPair")) {
      $("alertPair").innerHTML = quotes.map((q) => "<option value='" + state.base + "/" + q + "'>" + state.base + "/" + q + "</option>").join("");
    }
    updateFromSymbol();
  }

  function updateFromSymbol() {
    $("fromSymbol").textContent = symbol($("fromCur").value);
  }

  function convertRate(from, to) {
    const r = ratesForBase(state.base);
    if (from === to) return 1;
    if (from === state.base) return r[to];
    if (to === state.base) return 1 / r[from];
    return r[to] / r[from];
  }

  function pairRateAt(e, from, to) {
    const base = state.base;
    const eurRates = e.rates || {};
    const baseEur = eurRates[base];
    if (!baseEur) return null;
    const r = {};
    r["EUR"] = 1.0 / baseEur;
    for (const [code, rate] of Object.entries(eurRates)) {
      if (code !== base) r[code] = rate / baseEur;
    }
    if (from === to) return 1;
    if (from === base && r[to]) return r[to];
    if (to === base && r[from]) return 1 / r[from];
    if (r[from] && r[to]) return r[to] / r[from];
    return null;
  }

  function trendPoints(pair, days) {
    const events = state.history.events || [];
    const cutoff = Date.now() / 1000 - days * 86400;
    const parts = pair.split("/");
    const from = parts[0], to = parts[1];
    const points = [];
    const seen = new Set();
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      if (e.ts < cutoff) break;
      if (seen.has(e.ts)) continue;
      seen.add(e.ts);
      const v = pairRateAt(e, from, to);
      if (v != null) points.push([e.ts, v]);
    }
    points.reverse();
    return points;
  }

  function doConvert(animate) {
    if (!state.latest) return;
    const amount = parseFloat($("amount").value);
    const from = $("fromCur").value;
    const to = $("toCur").value;
    $("pairName").textContent = from + "/" + to;
    $("pairSub").textContent = (NAMES[from] || from) + " to " + (NAMES[to] || to);

    if (!isFinite(amount) || amount < 0) {
      $("priceValue").textContent = "\u2014";
      $("priceUnit").textContent = "Enter a valid amount.";
      $("priceChange").textContent = "";
      $("priceChange").className = "price-change";
      updateFromSymbol();
      renderConvertChart(animate);
      return;
    }

    const trackedRate = convertRate(from, to);
    const cross = state.liveCross && state.liveCross.from === from && state.liveCross.to === to
      ? state.liveCross : null;
    const rate = cross ? cross.rate : trackedRate;
    const target = amount * rate;
    $("priceValue").textContent = symbol(to) + " " + fmt(target, 2);
    $("priceUnit").textContent = "1 " + from + " = " + fmt(rate, 6) + " " + to +
      "  \u00b7  " + (cross ? "live cross-check" : state.latest.source);

    const pts = trendPoints(from + "/" + to, convTimeframe);
    if (pts.length >= 2) {
      const first = pts[0][1], last = pts[pts.length - 1][1];
      const pct = ((last - first) / first) * 100;
      $("priceChange").textContent = (pct >= 0 ? "+" : "") + fmt(pct, 2) + "% (" + convTimeframe + "d)";
      $("priceChange").className = "price-change " + (pct >= 0 ? "up" : "down");
    } else {
      $("priceChange").textContent = "";
      $("priceChange").className = "price-change";
    }

    updateFromSymbol();
    renderConvertChart(animate);
    buildWatchlist();
  }

  function renderStats() {
    const latest = state.latest;
    const eurRates = ratesForBase(state.base);
    const quotes = Object.keys(eurRates).filter((q) => q !== state.base);
    animateNumber($("statPairs"), quotes.length, 800, (v) => Math.round(v));

    const trends = Object.keys(latest.trends).filter((q) => latest.trends[q].n >= 2);
    let gainer = null, loser = null;
    for (const q of trends) {
      const pct = latest.trends[q].change_pct;
      if (!gainer || pct > gainer.pct) gainer = { q, pct };
      if (!loser || pct < loser.pct) loser = { q, pct };
    }
    $("statGainer").innerHTML = gainer ? gainer.q + " " + fmt(gainer.pct, 2) + "%" : "\u2014";
    $("statLoser").innerHTML = loser ? loser.q + " " + fmt(loser.pct, 2) + "%" : "\u2014";
    $("statUpdated").textContent = fmtDate(latest.timestamp).split(",")[0];
  }

  function sparkColor(trend) {
    return trend === "rising" ? cssVar("--up") : trend === "falling" ? cssVar("--down") : cssVar("--flat");
  }

  function drawSparkAnimated(canvas, values, color, delay) {
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    const startAt = delay || 0;
    const duration = 700;
    const t0 = performance.now();
    ctx.clearRect(0, 0, W, H);
    if (!values || values.length < 2) return;
    const min = Math.min.apply(null, values);
    const max = Math.max.apply(null, values);
    const span = max - min || 1;
    function frame(now) {
      const p = Math.max(0, Math.min(1, (now - t0 - startAt) / duration));
      const eased = 1 - Math.pow(1 - p, 3);
      const count = Math.max(2, Math.floor(values.length * eased));
      ctx.clearRect(0, 0, W, H);
      ctx.beginPath();
      for (let i = 0; i < count; i++) {
        const x = (i / (values.length - 1)) * (W - 2) + 1;
        const y = H - 2 - ((values[i] - min) / span) * (H - 4);
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.6;
      ctx.lineCap = "round";
      ctx.stroke();
      if (count < values.length) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  function renderRates() {
    const latest = state.latest;
    const term = ($("search").value || "").toLowerCase();
    const eurRates = ratesForBase(state.base);
    let quotes = Object.keys(eurRates).filter((q) => q !== state.base);

    quotes.sort((a, b) => {
      const fa = favorites.has(a) ? 0 : 1;
      const fb = favorites.has(b) ? 0 : 1;
      if (fa !== fb) return fa - fb;
      const tA = latest.trends[a] || {}, tB = latest.trends[b] || {};
      let cmp = 0;
      switch (sortKey) {
        case "rate": cmp = eurRates[a] - eurRates[b]; break;
        case "trend":
          cmp = (trendRank(tA.trend) - trendRank(tB.trend)) || (eurRates[a] - eurRates[b]); break;
        case "low": cmp = (tA.low || 0) - (tB.low || 0); break;
        case "high": cmp = (tA.high || 0) - (tB.high || 0); break;
        case "chg": cmp = (tA.change_pct || 0) - (tB.change_pct || 0); break;
        default: cmp = a.localeCompare(b);
      }
      return sortDir === "asc" ? cmp : -cmp;
    });

    if (term) {
      quotes = quotes.filter((q) => q.toLowerCase().includes(term) || (NAMES[q] || "").toLowerCase().includes(term));
    }

    const tbody = document.querySelector("#ratesTable tbody");
    tbody.innerHTML = "";
    let delay = 0;
    for (const q of quotes) {
      const rate = eurRates[q];
      const t = latest.trends[q] || {};
      const fav = favorites.has(q);
      const tr = document.createElement("tr");
      if (fav) tr.classList.add("fav-row");
      tr.innerHTML =
        "<td class='quote'><span class='star " + (fav ? "on" : "") + "' data-q='" + q + "' title='favorite'>&#9733;</span> " +
        latest.base + "/" + q + " <small>" + (NAMES[q] || "") + "</small></td>" +
        "<td>" + fmt(rate, 6) + "</td>" +
        "<td><span class='trend-badge " + trendClass(t.trend) + "'>" + trendArrow(t.trend) + " " + (t.trend || "\u2014") + "</span></td>" +
        "<td>" + (t.low ? fmt(t.low, 6) : "\u2014") + "</td>" +
        "<td>" + (t.high ? fmt(t.high, 6) : "\u2014") + "</td>" +
        "<td class='" + trendClass(t.trend) + "'>" + (t.change_pct != null ? fmt(t.change_pct, 3) + "%" : "\u2014") + "</td>" +
        "<td><canvas class='spark' width='84' height='26'></canvas></td>";
      const canvas = tr.querySelector("canvas");
      drawSparkAnimated(canvas, t.spark || [rate], sparkColor(t.trend), delay);
      delay += 60;
      tbody.appendChild(tr);
    }
    if (!quotes.length) {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td colspan='7'>No currencies match your search.</td>";
      tbody.appendChild(tr);
    }
    updateSortIndicators();
  }

  function trendRank(t) {
    return t === "rising" ? 2 : t === "falling" ? 0 : 1;
  }

  function updateSortIndicators() {
    document.querySelectorAll(".sortable").forEach((th) => th.classList.remove("asc", "desc"));
    const th = document.querySelector('.sortable[data-key="' + sortKey + '"]');
    if (th) th.classList.add(sortDir);
  }

  /* ---------- Charts ---------- */

  function renderConvertChart(animate) {
    const from = $("fromCur").value, to = $("toCur").value;
    const pair = from + "/" + to;
    drawChart($("chart"), trendPoints(pair, convTimeframe), pair, animate !== false);
  }

  function renderHistChart() {
    const quote = $("histPair").value;
    const pair = state.base + "/" + quote;
    const points = trendPoints(pair, timeframe);
    $("histHint").textContent = pair + " over " + timeframe + " days";
    drawChart($("histChart"), points, pair);
    if (points.length) {
      const rates = points.map((p) => p[1]);
      const low = Math.min.apply(null, rates);
      const high = Math.max.apply(null, rates);
      const pct = ((rates[rates.length - 1] - rates[0]) / rates[0]) * 100;
      $("histStats").innerHTML =
        "low <b class='down'>" + fmt(low, 6) + "</b>  &middot;  high <b class='up'>" + fmt(high, 6) + "</b>  &middot;  change <b class='" +
        trendClass(pct >= 0 ? "rising" : "falling") + "'>" + (pct >= 0 ? "+" : "") + fmt(pct, 2) + "%</b>  &middot;  " + points.length + " observations";
    } else {
      $("histStats").innerHTML = "No history yet \u2014 data is collected hourly. Check back soon.";
    }
  }

  function drawChart(canvas, points, title, animate) {
    animate = animate !== false;
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth || 720;
    const H = canvas.clientHeight || 300;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const textColor = cssVar("--chart-text");
    const gridColor = cssVar("--chart-grid");
    const upColor = cssVar("--up");
    const downColor = cssVar("--down");

    ctx.fillStyle = textColor;
    ctx.font = "13px 'Google Sans', Segoe UI, Arial";
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    ctx.fillText(title, 14, 12);

    if (points.length < 2) {
      ctx.textAlign = "center";
      ctx.fillText("Collecting data\u2026 check back after a few updates.", W / 2, H / 2);
      ctx.textAlign = "left";
      return;
    }

    const padL = 62, padR = 16, padT = 30, padB = 34;
    const rates = points.map((p) => p[1]);
    let min = Math.min.apply(null, rates);
    let max = Math.max.apply(null, rates);
    const span = max - min;
    min -= span * 0.08;
    max += span * 0.08;
    const iw = W - padL - padR, ih = H - padT - padB;
    const x = (i) => padL + (i / (points.length - 1)) * iw;
    const y = (v) => padT + ih - ((v - min) / (max - min)) * ih;
    const color = points[points.length - 1][1] >= points[0][1] ? upColor : downColor;
    const fillTop = color + "44";

    function paint(count) {
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = textColor;
      ctx.font = "13px 'Google Sans', Segoe UI, Arial";
      ctx.textAlign = "left";
      ctx.fillText(title, 14, 12);
      ctx.strokeStyle = gridColor;
      ctx.fillStyle = textColor;
      ctx.lineWidth = 1;
      for (let i = 0; i <= 4; i++) {
        const gv = min + ((max - min) * i) / 4;
        const gy = y(gv);
        ctx.beginPath();
        ctx.moveTo(padL, gy);
        ctx.lineTo(W - padR, gy);
        ctx.stroke();
        ctx.fillText(gv.toFixed(4), 4, gy - 6);
      }
      ctx.fillStyle = textColor;
      ctx.font = "11px 'Google Sans', Segoe UI, Arial";
      ctx.fillText(new Date(points[0][0] * 1000).toLocaleDateString(), padL, H - 20);
      ctx.textAlign = "right";
      ctx.fillText(new Date(points[points.length - 1][0] * 1000).toLocaleDateString(), W - padR, H - 20);
      ctx.textAlign = "left";

      const grad = ctx.createLinearGradient(0, padT, 0, H - padB);
      grad.addColorStop(0, fillTop);
      grad.addColorStop(1, color + "00");
      ctx.beginPath();
      for (let i = 0; i < count; i++) ctx.lineTo(x(i), y(points[i][1]));
      ctx.lineTo(x(count - 1), H - padB);
      ctx.lineTo(x(0), H - padB);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();

      ctx.beginPath();
      for (let i = 0; i < count; i++) {
        const px = x(i), py = y(points[i][1]);
        i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
      }
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.4;
      ctx.lineCap = "round";
      ctx.stroke();

      // Live endpoint dot — marks exactly where the current rate sits.
      const lastX = x(count - 1), lastY = y(points[count - 1][1]);
      ctx.beginPath();
      ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.beginPath();
      ctx.arc(lastX, lastY, 7, 0, Math.PI * 2);
      ctx.strokeStyle = color + "66";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    if (animate) {
      const t0 = performance.now();
      const duration = 900;
      function frame(now) {
        const p = Math.min(1, (now - t0) / duration);
        const eased = 1 - Math.pow(1 - p, 3);
        const count = Math.max(2, Math.floor(points.length * eased));
        paint(count);
        if (count < points.length) requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    } else {
      // Instant redraw — the live point simply moves to its new position
      // rather than replaying the whole reveal animation on every poll.
      paint(points.length);
    }

    canvas._chart = { points, x, y, padL, padR, W, H, repaint: () => paint(points.length) };
  }

  function attachChartHover(canvas, tip) {
    canvas.addEventListener("mousemove", (e) => {
      const c = canvas._chart;
      if (!c || c.points.length < 2) return;
      if (c.repaint) c.repaint();   // erase any previous hover line first
      const rect = canvas.getBoundingClientRect();
      const relX = e.clientX - rect.left;
      const i = Math.max(0, Math.min(c.points.length - 1, Math.round(((relX - c.padL) / (rect.width - c.padL - c.padR)) * (c.points.length - 1))));
      const px = c.x(i), py = c.y(c.points[i][1]);
      const ctx = canvas.getContext("2d");
      const scale = rect.width / canvas.clientWidth;
      ctx.save();
      ctx.setTransform(window.devicePixelRatio || 1, 0, 0, window.devicePixelRatio || 1, 0, 0);
      ctx.strokeStyle = cssVar("--accent");
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(px, 0);
      ctx.lineTo(px, canvas.clientHeight);
      ctx.stroke();
      ctx.restore();
      tip.innerHTML = "<b>" + new Date(c.points[i][0] * 1000).toLocaleString() + "</b><br>" + fmt(c.points[i][1], 6);
      tip.style.left = Math.min(px * scale + 14, rect.width - 150) + "px";
      tip.style.top = Math.max(py * scale - 40, 0) + "px";
      tip.classList.add("show");
    });
    canvas.addEventListener("mouseleave", () => {
      tip.classList.remove("show");
      const c = canvas._chart;
      if (c && c.repaint) c.repaint();   // wipe the last hover line
    });
  }

  /* ---------- Ask ---------- */

  function orderedCodes(text) {
    const lower = text.toLowerCase();
    const words = Object.keys(CURRENCY_WORDS).sort((a, b) => b.length - a.length);
    const pat = new RegExp("\\b(" + words.join("|") + ")\\b", "g");
    const matches = [];
    let m;
    while ((m = pat.exec(lower)) !== null) matches.push({ pos: m.index, code: CURRENCY_WORDS[m[0]] });
    const unique = (list) => list.filter((c, i) => list.indexOf(c) === i);
    const codes = unique(matches.map((x) => x.code));
    if (matches.length >= 2) {
      if (lower.includes("how many") && lower.includes(" for ")) {
        const idx = lower.indexOf(" for ");
        const before = unique(matches.filter((x) => x.pos < idx).map((x) => x.code));
        const after = unique(matches.filter((x) => x.pos > idx).map((x) => x.code));
        if (before.length && after.length) return [after[0], before[0]];
      }
      const toPos = lower.search(/\bto\b/);
      if (toPos >= 0) {
        const before = unique(matches.filter((x) => x.pos < toPos).map((x) => x.code));
        const after = unique(matches.filter((x) => x.pos > toPos).map((x) => x.code));
        if (before.length && after.length) return [before[0], after[0]];
      }
    }
    return codes;
  }

  function parseAmount(text) {
    const match = text.replace(/,/g, "").match(/(\d+(?:[.,]\d+)?)/);
    return match ? parseFloat(match[1]) : null;
  }

  function rateFor(from, to) {
    const r = ratesForBase(state.base);
    if (from === to) return 1;
    if (from === state.base && r[to]) return r[to];
    if (to === state.base && r[from]) return 1 / r[from];
    if (r[from] && r[to]) return r[to] / r[from];
    return null;
  }

  function searchContext(query) {
    const qv = embed(query);
    return state.context.docs
      .map((doc) => ({ doc, score: dot(qv, doc.embedding) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, 3);
  }

  function deterministicAnswer(query, hits) {
    const codes = orderedCodes(query);
    let rate = null, base = null, quote = null;
    if (codes.length >= 2) { base = codes[0]; quote = codes[1]; rate = rateFor(base, quote); }
    else if (codes.length === 1) { base = state.base; quote = codes[0]; rate = rateFor(base, quote); }

    if (rate != null) {
      const amount = parseAmount(query);
      if (amount != null) {
        return amount + " " + base + " = " + fmt(amount * rate, 4) + " " + quote + ".";
      }
      return "Latest recorded rate: 1 " + base + " = " + fmt(rate, 6) + " " + quote + ".";
    }
    const lines = hits.map((h) =>
      "\u2022 " + h.doc.meta.base + "/" + h.doc.meta.quote + ": 1 " + h.doc.meta.base + " = " + fmt(h.doc.meta.latest_rate) +
      " (" + (h.doc.meta.trend || "flat") + ")");
    return "I retrieved these tracked reports for your question:\n" + (lines.join("\n") || "No data yet \u2014 check back after a few hourly updates.");
  }

  function ask() {
    const question = $("askInput").value.trim();
    if (!question) return;
    const hits = searchContext(question);
    const answer = deterministicAnswer(question, hits);
    $("askAnswer").textContent = answer;
    $("askSources").innerHTML = hits
      .map((h) => "<div class='source'><span class='sc'>score " + h.score.toFixed(3) + "</span> \u2014 " + h.doc.content + "</div>")
      .join("");
  }

  /* ---------- Watchlist (Google Finance style left rail) ---------- */

  function buildWatchlist() {
    const latest = state.latest;
    const box = $("watchlistRows");
    if (!box) return;
    const eurRates = ratesForBase(state.base);
    const favList = [...favorites].filter((q) => eurRates[q] != null);
    const rest = Object.keys(eurRates).filter((q) => q !== state.base && !favorites.has(q)).sort();
    const shown = favList.concat(rest).slice(0, 10);
    const current = $("toCur") ? $("toCur").value : null;
    box.innerHTML = shown.map((q) => {
      const t = latest.trends[q] || {};
      const cls = trendClass(t.trend);
      const chg = t.change_pct != null ? (t.change_pct >= 0 ? "+" : "") + fmt(t.change_pct, 2) + "%" : "\u2014";
      return "<div class='wl-row" + (q === current ? " active" : "") + "' data-q='" + q + "'>" +
        "<span class='wl-pair'>" + (favorites.has(q) ? "\u2605 " : "") + state.base + "/" + q + "</span>" +
        "<span class='wl-chg " + cls + "'>" + chg + "</span></div>";
    }).join("");
  }

  function selectWatchlistPair(q) {
    if (!state.latest || !state.latest.rates[q]) return;
    $("toCur").value = q;
    doConvert();
    buildWatchlist();
  }

  /* ---------- Header search-jump ---------- */

  function runHeaderSearch() {
    const box = $("gfSearchResults");
    const term = $("gfSearchInput").value.trim().toLowerCase();
    if (!term || !state.latest) { box.classList.remove("show"); return; }
    const eurRates = ratesForBase(state.base);
    const matches = Object.keys(eurRates)
      .filter((q) => q !== state.base && (q.toLowerCase().includes(term) || (NAMES[q] || "").toLowerCase().includes(term)))
      .slice(0, 8);
    if (!matches.length) { box.classList.remove("show"); return; }
    box.innerHTML = matches.map((q) =>
      "<div class='gf-search-row' data-q='" + q + "'><span>" + state.base + "/" + q + "</span>" +
      "<span class='muted'>" + (NAMES[q] || "") + "</span></div>").join("");
    box.classList.add("show");
  }

  /* ---------- Events ---------- */

  function setupEvents() {
    $("themeToggle").addEventListener("click", toggleTheme);
    $("baseSelect").addEventListener("change", onBaseChange);
    $("shareBtn").addEventListener("click", shareRate);
    $("alertAdd").addEventListener("click", addAlert);
    $("compareAdd").addEventListener("click", addComparePair);

    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }

    $("watchlist").addEventListener("click", (e) => {
      const row = e.target.closest(".wl-row");
      if (!row) return;
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      document.querySelector('.tab[data-tab="convert"]').classList.add("active");
      $("tab-convert").classList.add("active");
      selectWatchlistPair(row.dataset.q);
    });

    $("gfSearchInput").addEventListener("input", runHeaderSearch);
    $("gfSearchInput").addEventListener("focus", runHeaderSearch);
    $("gfSearchResults").addEventListener("click", (e) => {
      const row = e.target.closest(".gf-search-row");
      if (!row) return;
      $("gfSearchInput").value = "";
      $("gfSearchResults").classList.remove("show");
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
      document.querySelector('.tab[data-tab="convert"]').classList.add("active");
      $("tab-convert").classList.add("active");
      selectWatchlistPair(row.dataset.q);
    });
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".gf-search")) $("gfSearchResults").classList.remove("show");
    });

    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
        document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        $("tab-" + tab.dataset.tab).classList.add("active");
        if (tab.dataset.tab === "convert") renderConvertChart();
        if (tab.dataset.tab === "rates") renderRates();
        if (tab.dataset.tab === "history") renderHistChart();
      });
    });

    $("amount").addEventListener("input", doConvert);
    $("fromCur").addEventListener("change", () => { doConvert(); refreshCrossCheckNow(); });
    $("toCur").addEventListener("change", () => { doConvert(); refreshCrossCheckNow(); });

    $("swap").addEventListener("click", () => {
      const f = $("fromCur").value;
      $("fromCur").value = $("toCur").value;
      $("toCur").value = f;
      doConvert();
      refreshCrossCheckNow();
    });

    document.querySelectorAll(".qf-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".qf-tab").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        convTimeframe = parseInt(btn.dataset.days, 10);
        doConvert();
      });
    });

    $("histPair").addEventListener("change", renderHistChart);
    document.querySelectorAll(".tf").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tf").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        timeframe = parseInt(btn.dataset.days, 10);
        renderHistChart();
      });
    });

    $("search").addEventListener("input", renderRates);

    document.querySelector("#ratesTable tbody").addEventListener("click", (e) => {
      const star = e.target.closest(".star");
      if (!star) return;
      const q = star.dataset.q;
      favorites.has(q) ? favorites.delete(q) : favorites.add(q);
      localStorage.setItem("shinefx-favs", JSON.stringify([...favorites]));
      renderRates();
    });

    document.querySelectorAll(".sortable").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.key;
        if (sortKey === key) sortDir = sortDir === "asc" ? "desc" : "asc";
        else { sortKey = key; sortDir = "asc"; }
        renderRates();
      });
    });

    $("askBtn").addEventListener("click", ask);
    $("askInput").addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });
    document.querySelectorAll(".qchip").forEach((c) => {
      c.addEventListener("click", () => {
        $("askInput").value = c.dataset.q;
        ask();
      });
    });

    window.addEventListener("resize", () => {
      if (state.history) { renderConvertChart(); renderHistChart(); }
    });
  }

  /* ---------- Data ---------- */

  async function refreshData() {
    try {
      const latest = await loadJSON("data/latest.json");
      const history = await loadJSON("data/history.json");
      const context = await loadJSON("data/context.json");
      const selFrom = $("fromCur").value;
      const selTo = $("toCur").value;
      const selHist = $("histPair").value;
      state.latest = latest;
      state.history = history;
      state.context = context;
      if (!localStorage.getItem("shinefx-base")) state.base = latest.base;
      $("liveBadge").textContent = "updated " + fmtDate(latest.timestamp);
      buildBaseSelect();
      buildTicker();
      buildSelects();
      if (selFrom && selTo) { $("fromCur").value = selFrom; $("toCur").value = selTo; }
      if (selHist) $("histPair").value = selHist;
      doConvert();
      renderStats();
      renderRates();
      renderHistChart();
      buildWatchlist();
      renderAlerts();
      renderCompare();
      lastRefresh = Date.now();
    } catch (err) {
      $("liveBadge").textContent = "refresh failed \u2014 showing last data";
    }
  }

  function flashIfChanged(el, changed) {
    if (!changed) return;
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  }

  /* Cross-checks the currently selected pair against an independent FX
     source (open.er-api.com) so the displayed price tracks closer to
     real market quotes rather than only your hourly-collected backend
     data. Note: this is a best-effort cross-check with a free, keyless
     source — it is NOT a live interbank tick feed. Google Finance blends
     multiple live market/interbank feeds that require a paid data
     subscription (e.g. Twelve Data, Alpha Vantage) to match exactly;
     a free source will still lag Google's live number somewhat. */
  async function fetchLiveCrossCheck(from, to) {
    if (from === to) return null;
    try {
      const resp = await fetch(
        "https://open.er-api.com/v6/latest/" + encodeURIComponent(from),
        { cache: "no-cache" }
      );
      if (!resp.ok) return null;
      const data = await resp.json();
      const rate = data && data.result === "success" && data.rates && data.rates[to];
      return typeof rate === "number" ? { rate, ts: Date.now() } : null;
    } catch (err) {
      return null;
    }
  }

  async function refreshCrossCheckNow() {
    const from = $("fromCur").value, to = $("toCur").value;
    const cross = await fetchLiveCrossCheck(from, to);
    if (cross && $("fromCur").value === from && $("toCur").value === to) {
      state.liveCross = { from, to, rate: cross.rate, ts: cross.ts };
      doConvert(false);
    }
  }

  async function pollLive() {
    if (!state.latest) return;
    try {
      const from = $("fromCur").value, to = $("toCur").value;
      const [latest, cross] = await Promise.all([
        loadJSON("data/latest.json?t=" + Date.now()),
        fetchLiveCrossCheck(from, to)
      ]);
      const prevPrice = $("priceValue").textContent;
      const prevRates = state.latest.rates;
      state.latest = latest;
      state.base = latest.base;
      state.liveCross = cross ? { from, to, rate: cross.rate, ts: cross.ts } : null;

      const anyChanged = Object.keys(latest.rates).some(
        (q) => prevRates[q] !== undefined && prevRates[q] !== latest.rates[q]
      );

      $("liveBadge").textContent = "updated " + fmtDate(latest.timestamp);
      buildTicker();
      doConvert(false);
      renderRates();
      buildWatchlist();
      checkAlerts();

      if (anyChanged || cross || prevPrice !== $("priceValue").textContent) {
        flashIfChanged($("priceValue"), true);
      }
    } catch (err) {
      // silent — keep last good data, next 10s tick will retry
    }
  }

  function startLivePolling() {
    setInterval(pollLive, 10000);
  }

  function scheduleHourlyRefresh() {
    const delay = (60 * 60 - (new Date().getMinutes() * 60 + new Date().getSeconds())) * 1000;
    setTimeout(() => {
      refreshData();
      setInterval(refreshData, 60 * 60 * 1000);
    }, delay);
  }

  async function init() {
    applyTheme(storedTheme() || "light");
    setupEvents();
    startClock();
    initReveal();
    updateStreak();
    try {
      state.latest = await loadJSON("data/latest.json");
      state.history = await loadJSON("data/history.json");
      state.context = await loadJSON("data/context.json");
      const savedBase = localStorage.getItem("shinefx-base");
      if (savedBase && savedBase !== "EUR") {
        state.base = savedBase;
      } else {
        state.base = state.latest.base;
      }
      $("liveBadge").textContent = "updated " + fmtDate(state.latest.timestamp);
      $("footLink").innerHTML = "next update hourly \u00b7 source " + state.latest.source;
      buildBaseSelect();
      buildTicker();
      buildSelects();
      doConvert();
      renderStats();
      renderRates();
      renderHistChart();
      buildWatchlist();
      renderAlerts();
      renderCompare();
      attachChartHover($("chart"), $("tooltip"));
      attachChartHover($("histChart"), $("histTooltip"));
      lastRefresh = Date.now();
    } catch (err) {
      $("liveBadge").textContent = "data unavailable";
      $("ticker").innerHTML = "<div>Could not load currency data.</div>";
      document.querySelector("#tab-rates").innerHTML = "<p class='hint'>Could not load currency data: " + err.message + "</p>";
    }
    scheduleHourlyRefresh();
    startLivePolling();
    refreshCrossCheckNow();
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && Date.now() - lastRefresh > 30 * 60 * 1000) refreshData();
    });
  }

  init();
})();