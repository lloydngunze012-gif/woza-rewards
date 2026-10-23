(function (global) {
  "use strict";

  const DEFAULT_SLOGAN = "Pay today. Earn tomorrow.";

  const WAVE_OP_RIGHT = 0.18;
  const TIER_ART = {
    gold: { waveRight: WAVE_OP_RIGHT, rose: 0.26, roseHi: 0.2 },
    silver: { waveRight: WAVE_OP_RIGHT, rose: 0.26, roseHi: 0.2 },
    black: { waveRight: 0.22, rose: 0.3, roseHi: 0.24 },
    starter: { waveRight: WAVE_OP_RIGHT, rose: 0.26, roseHi: 0.2 },
  };

  let guillocheCache = null;
  let defsInjected = false;
  const waveCache = Object.create(null);
  let fmtPtsFn = (n) => String(n);
  let slogan = DEFAULT_SLOGAN;
  let getPointsFn = (u) => u.available_points ?? u.points ?? 0;
  let cardTiltGranted = false;
  let cardOrientBound = false;

  function configure(opts) {
    if (opts.fmtPts) fmtPtsFn = opts.fmtPts;
    if (opts.slogan) slogan = opts.slogan;
    if (opts.getPoints) getPointsFn = opts.getPoints;
    if (opts.cardTiltGranted != null) cardTiltGranted = opts.cardTiltGranted;
    if (opts.cardOrientBound != null) cardOrientBound = opts.cardOrientBound;
  }

  function getTiltState() {
    return { cardTiltGranted, cardOrientBound };
  }

  function setTiltState(granted, bound) {
    cardTiltGranted = granted;
    cardOrientBound = bound;
  }

  function gcd(a, b) {
    a = Math.abs(Math.round(a));
    b = Math.abs(Math.round(b));
    while (b) {
      const t = b;
      b = a % b;
      a = t;
    }
    return a || 1;
  }

  function hypotrochoidPath(R, r, d, points) {
    const g = gcd(R, r);
    const maxT = (2 * Math.PI * r) / g;
    const steps = points;
    let s = "";
    for (let i = 0; i <= steps; i++) {
      const t = (i / steps) * maxT;
      const x = (R - r) * Math.cos(t) + d * Math.cos(((R - r) / r) * t);
      const y = (R - r) * Math.sin(t) - d * Math.sin(((R - r) / r) * t);
      s += (i === 0 ? "M" : "L") + x.toFixed(2) + "," + y.toFixed(2);
    }
    return s + "Z";
  }

  function getGuillochePaths() {
    if (guillocheCache) return guillocheCache;
    guillocheCache = [
      { scale: 1.0, d: 58 },
      { scale: 0.82, d: 50 },
      { scale: 0.64, d: 42 },
    ].map((c) => ({
      scale: c.scale,
      d: c.d,
      path: hypotrochoidPath(96, 22, c.d, 1600),
    }));
    return guillocheCache;
  }

  function tierKey(status) {
    const k = (status || "Gold").toLowerCase();
    return TIER_ART[k] ? k : "starter";
  }

  function tierClass(status) {
    const key = tierKey(status);
    if (key === "starter") return "tier-starter";
    return "tier-" + key;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function memberSinceYear(u) {
    const m = (u.member_since || "2023").match(/\d{4}/);
    return m ? m[0] : "2023";
  }

  function ensureGlobalDefs() {
    if (defsInjected || !global.document || !global.document.body) return;
    defsInjected = true;
    getGuillochePaths();
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("id", "woza-card-defs");
    svg.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
    let inner = "<defs>";
    guillocheCache.forEach((p) => {
      inner +=
        '<path id="woza-rose-' +
        p.d +
        '" d="' +
        p.path +
        '" fill="none"/>';
    });
    inner += "</defs>";
    svg.innerHTML = inner;
    document.body.prepend(svg);
  }

  function buildWaveSvg(tier) {
    const art = TIER_ART[tier] || TIER_ART.gold;
    const maskId = "waveMask-v2-" + tier;
    const gradId = "waveGrad-v2-" + tier;
    let lines = "";
    for (let i = 0; i < 40; i++) {
      const baseline = i * 7;
      const pts = [];
      for (let x = 0; x <= 420; x += 5) {
        const y = baseline + 6 * Math.sin(x / 38 + i * 0.35);
        pts.push(x.toFixed(1) + "," + y.toFixed(2));
      }
      lines +=
        '<polyline points="' +
        pts.join(" ") +
        '" fill="none" stroke="var(--mem-ink)" stroke-width="0.6" opacity="' +
        art.waveRight +
        '"/>';
    }
    return (
      '<svg class="mem-waves" viewBox="0 0 420 300" preserveAspectRatio="none" aria-hidden="true">' +
      "<defs>" +
      '<linearGradient id="' +
      gradId +
      '" x1="0" y1="0" x2="1" y2="0">' +
      '<stop offset="0%" stop-color="white" stop-opacity="0.35"/>' +
      '<stop offset="38%" stop-color="white" stop-opacity="0.45"/>' +
      '<stop offset="52%" stop-color="white" stop-opacity="1"/>' +
      '<stop offset="100%" stop-color="white" stop-opacity="1"/>' +
      "</linearGradient>" +
      '<mask id="' +
      maskId +
      '"><rect width="100%" height="100%" fill="url(#' +
      gradId +
      ')"/></mask>' +
      "</defs>" +
      '<g mask="url(#' +
      maskId +
      ')" transform="rotate(-18 210 150)">' +
      lines +
      "</g></svg>"
    );
  }

  function getWaveSvg(tier) {
    if (waveCache[tier]) return waveCache[tier];
    waveCache[tier] = buildWaveSvg(tier);
    return waveCache[tier];
  }

  function buildRosetteSvg(tier) {
    ensureGlobalDefs();
    const art = TIER_ART[tier] || TIER_ART.gold;
    const configs = [
      { scale: 1.0, d: 58 },
      { scale: 0.82, d: 50 },
      { scale: 0.64, d: 42 },
    ];
    let base = "";
    let hi = "";
    configs.forEach((c) => {
      base +=
        '<g transform="scale(' +
        c.scale +
        ')"><use href="#woza-rose-' +
        c.d +
        '" stroke="var(--mem-ink)" stroke-width="0.5" opacity="' +
        art.rose +
        '"/></g>';
      hi +=
        '<g transform="scale(' +
        c.scale +
        ')"><use href="#woza-rose-' +
        c.d +
        '" stroke="var(--mem-hi)" stroke-width="0.5" opacity="' +
        art.roseHi +
        '"/></g>';
    });
    return (
      '<div class="mem-rosette-wrap" aria-hidden="true">' +
      '<svg class="mem-rosette" viewBox="-120 -120 240 240" preserveAspectRatio="xMidYMid meet">' +
      '<g class="mem-rosette-base">' +
      base +
      "</g>" +
      '<g class="mem-rosette-hl">' +
      hi +
      "</g></svg></div>"
    );
  }

  function microtextLine() {
    const unit = "PAY TODAY EARN TOMORROW · WOZA · ";
    return unit.repeat(12);
  }

  const MEMBER_ID = "WZ-2023-04817";

  function membershipCardBackHtml(u) {
    const tier = u.status || "Gold";
    const since = u.member_since || "Oct 2023";
    return (
      '<div class="membership-card membership-card-back ' +
      tierClass(tier) +
      '" data-card-back>' +
      getWaveSvg(tierKey(tier)) +
      '<div class="mem-inset-border" aria-hidden="true"></div>' +
      '<div class="mem-back-content">' +
      '<span class="mem-back-label">Woza member</span>' +
      '<span class="mem-back-id">' +
      MEMBER_ID +
      "</span>" +
      '<div class="mem-qr" data-qr="' +
      MEMBER_ID +
      '"></div>' +
      '<span class="mem-back-scan">Scan to verify on-time record</span>' +
      '<span class="mem-back-foot">' +
      escapeHtml(tier) +
      " · Member since " +
      escapeHtml(since) +
      "</span></div>" +
      '<div class="mem-microtext" aria-hidden="true">' +
      microtextLine() +
      "</div></div>"
    );
  }

  function fillQrCodes(root) {
    const qrFn = global.qrcode;
    if (typeof qrFn !== "function") return;
    (root || document).querySelectorAll("[data-qr]").forEach((el) => {
      if (el.getAttribute("data-qr-ready")) return;
      try {
        const qr = qrFn(4, "M");
        qr.addData("woza://verify/" + (el.getAttribute("data-qr") || MEMBER_ID));
        qr.make();
        el.innerHTML = qr.createSvgTag(4, 0);
        el.setAttribute("data-qr-ready", "1");
      } catch { /* leave empty */ }
    });
  }

  function membershipCardStageHtml(u, compact, opts) {
    opts = opts || {};
    const hint = opts.hint
      ? '<span class="card-flip-hint">Tap to flip</span>'
      : "";
    return (
      '<div class="card-flip' +
      (compact ? " compact" : "") +
      '" data-card-flip>' +
      '<div class="card-flip-inner">' +
      '<div class="card-face card-face-front">' +
      membershipCardHtml(u, compact) +
      hint +
      "</div>" +
      '<div class="card-face card-face-back">' +
      membershipCardBackHtml(u) +
      "</div></div></div>"
    );
  }

  function bindCardFlips() {
    document.querySelectorAll("[data-card-flip]").forEach((stage) => {
      if (stage._flipBound) return;
      stage._flipBound = true;
      stage.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        stage.classList.toggle("is-flipped");
      });
    });
    fillQrCodes();
  }

  function membershipCardHtml(u, compact) {
    ensureGlobalDefs();
    const tier = u.status || "Gold";
    const tk = tierKey(tier);
    const pts = getPointsFn(u);
    return (
      '<div class="membership-card ' +
      tierClass(tier) +
      (compact ? " compact" : "") +
      '" data-membership-card tabindex="0">' +
      getWaveSvg(tk) +
      buildRosetteSvg(tk) +
      '<div class="mem-inset-border" aria-hidden="true"></div>' +
      '<div class="mem-sweep" aria-hidden="true"></div>' +
      '<div class="mem-sheen" aria-hidden="true"></div>' +
      '<span class="mem-tier">' +
      escapeHtml(tier) +
      "</span>" +
      '<div class="mem-content">' +
      '<div class="mem-top">' +
      '<div class="mem-monogram">' +
      '<div class="mem-emblem"><span>W</span></div>' +
      '<span class="mem-wordmark">Woza</span></div></div>' +
      '<div class="mem-center">' +
      '<span class="mem-label">Available points</span>' +
      '<span class="mem-points font-num">' +
      fmtPtsFn(pts) +
      "</span></div>" +
      '<div class="mem-footer">' +
      '<div class="mem-member">' +
      '<span class="mem-name">' +
      escapeHtml(u.name) +
      "</span>" +
      '<span class="mem-since">Member since ' +
      escapeHtml(memberSinceYear(u)) +
      "</span></div>" +
      '<span class="mem-slogan">' +
      slogan +
      "</span></div></div>" +
      '<div class="mem-microtext" aria-hidden="true">' +
      microtextLine() +
      "</div></div>"
    );
  }

  function setCardSheen(card, tx, ty) {
    if (card.closest && card.closest(".card-flip.is-flipped")) return;
    const reduced = global.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const sheen = card.querySelector(".mem-sheen");
    if (sheen && !reduced) {
      const clamp = (n) => Math.max(-20, Math.min(20, n));
      sheen.style.setProperty("--sheen-tx", clamp(tx) + "%");
      sheen.style.setProperty("--sheen-ty", clamp(ty) + "%");
    }
    const hl = card.querySelector(".mem-rosette-hl");
    if (hl && !reduced) {
      const rx = (-tx / 20) * 3;
      const ry = (-ty / 20) * 3;
      hl.style.transform =
        "translate(" + rx.toFixed(2) + "px," + ry.toFixed(2) + "px) rotate(4deg)";
    } else if (hl && reduced) {
      hl.style.transform = "rotate(4deg)";
    }
  }

  function onDeviceOrientation(ev) {
    if (!cardTiltGranted) return;
    const gamma = ev.gamma ?? 0;
    const beta = ev.beta ?? 45;
    const tx = gamma * 0.65;
    const ty = (beta - 45) * 0.35;
    document.querySelectorAll("[data-membership-card]").forEach((card) => setCardSheen(card, tx, ty));
  }

  async function requestCardTiltPermission() {
    if (cardTiltGranted) return true;
    if (global.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
    const DO = global.DeviceOrientationEvent;
    if (DO && typeof DO.requestPermission === "function") {
      try {
        const res = await DO.requestPermission();
        cardTiltGranted = res === "granted";
      } catch {
        cardTiltGranted = false;
      }
    } else {
      cardTiltGranted = true;
    }
    if (cardTiltGranted && !cardOrientBound) {
      global.addEventListener("deviceorientation", onDeviceOrientation, { passive: true });
      cardOrientBound = true;
    }
    return cardTiltGranted;
  }

  function bindMembershipCards() {
    if (global.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const needsIos =
      typeof DeviceOrientationEvent !== "undefined" &&
      typeof DeviceOrientationEvent.requestPermission === "function";
    document.querySelectorAll("[data-membership-card]:not([data-card-back])").forEach((card) => {
      card.onpointermove = (e) => {
        if (needsIos && !cardTiltGranted) return;
        const r = card.getBoundingClientRect();
        setCardSheen(
          card,
          ((e.clientX - r.left) / r.width - 0.5) * 40,
          ((e.clientY - r.top) / r.height - 0.5) * 40
        );
      };
      card.onpointerleave = () => setCardSheen(card, 0, 0);
      if (needsIos && !card._tiltMoveBound) {
        card._tiltMoveBound = true;
        card.addEventListener(
          "pointerdown",
          async () => {
            if (!cardTiltGranted) await requestCardTiltPermission();
          },
          { passive: true }
        );
      } else if (!needsIos && !cardOrientBound) {
        cardTiltGranted = true;
        global.addEventListener("deviceorientation", onDeviceOrientation, { passive: true });
        cardOrientBound = true;
      }
    });
  }

  global.WozaCard = {
    configure,
    getTiltState,
    setTiltState,
    tierClass,
    memberSinceYear,
    membershipCardHtml,
    membershipCardStageHtml,
    bindMembershipCards,
    bindCardFlips,
    fillQrCodes,
    requestCardTiltPermission,
    getGuillochePaths,
  };
})(typeof window !== "undefined" ? window : globalThis);
