/* MakeItWork — logique front : thème, pseudo, onglets, recherche, autocomplétion, épinglés. */
(() => {
  "use strict";

  /* ---------- Thème clair / sombre ---------- */
  const root = document.documentElement;
  const saved = localStorage.getItem("theme");
  const preferred = saved ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  root.dataset.theme = preferred;

  document.getElementById("theme-toggle").addEventListener("click", () => {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", root.dataset.theme);
  });

  /* ---------- Éléments ---------- */
  const form = document.getElementById("search-form");
  const btn = document.getElementById("search-btn");
  const loader = document.getElementById("loader");
  const resultsEl = document.getElementById("results");
  const emptyState = document.getElementById("empty-state");
  const errorsEl = document.getElementById("errors");
  const toolbar = document.getElementById("toolbar");
  const countEl = document.getElementById("result-count");
  const filterSalary = document.getElementById("filter-salary");
  const filterRemote = document.getElementById("filter-remote");
  const sortSel = document.getElementById("sort");

  const viewSearch = document.getElementById("view-search");
  const viewPins = document.getElementById("view-pins");
  const tabSearch = document.getElementById("tab-search");
  const tabPins = document.getElementById("tab-pins");
  const pinCountEl = document.getElementById("pin-count");
  const pinnedSections = document.getElementById("pinned-sections");
  const pinsEmpty = document.getElementById("pins-empty");

  const pseudoModal = document.getElementById("pseudo-modal");
  const pseudoInput = document.getElementById("pseudo-input");
  const pseudoNameEl = document.getElementById("pseudo-name");

  const locationInput = document.getElementById("location");
  const cityList = document.getElementById("city-list");

  const SOURCE_NAMES = {
    wttj: "Welcome to the Jungle",
    indeed: "Indeed",
    hellowork: "Hellowork",
  };
  const REMOTE_LABELS = {
    total: "Télétravail total",
    partiel: "Télétravail partiel",
    occasionnel: "Télétravail occasionnel",
    non: "Pas de télétravail",
  };
  const PIN_STATUSES = ["a_postuler", "postule", "entretien"];
  const PIN_LABELS = {
    a_postuler: "À postuler",
    postule: "Postulé",
    entretien: "Entretien",
  };

  let allResults = [];   // résultats de la dernière recherche
  let pinnedOffers = []; // offres épinglées (depuis le serveur)

  /* ---------- Pseudo (session légère, stockée côté serveur) ---------- */
  let pseudo = (localStorage.getItem("pseudo") || "").trim();

  function apiHeaders(extra) {
    const h = Object.assign({}, extra || {});
    if (pseudo) h["X-Pseudo"] = pseudo;
    return h;
  }

  function updatePseudoChip() {
    pseudoNameEl.textContent = pseudo || "invité";
  }

  function openPseudoModal() {
    pseudoInput.value = pseudo;
    pseudoModal.classList.remove("hidden");
    pseudoInput.focus();
  }

  function closePseudoModal() {
    pseudoModal.classList.add("hidden");
    localStorage.setItem("pseudoAsked", "1");
  }

  function savePseudo() {
    pseudo = pseudoInput.value.trim().toLowerCase().slice(0, 40);
    localStorage.setItem("pseudo", pseudo);
    updatePseudoChip();
    closePseudoModal();
    loadPins();
  }

  document.getElementById("pseudo-chip").addEventListener("click", openPseudoModal);
  document.getElementById("pseudo-save").addEventListener("click", savePseudo);
  document.getElementById("pseudo-skip").addEventListener("click", () => {
    closePseudoModal();
  });
  pseudoInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") savePseudo();
    if (e.key === "Escape") closePseudoModal();
  });

  if (!pseudo && !localStorage.getItem("pseudoAsked")) openPseudoModal();
  updatePseudoChip();

  /* ---------- Autocomplétion ville ---------- */
  let cityItems = [];
  let cityHighlight = -1;
  let cityDebounce = null;
  let cityAbort = null;

  function hideCityList() {
    cityList.classList.add("hidden");
    cityList.innerHTML = "";
    cityItems = [];
    cityHighlight = -1;
  }

  function selectCity(index) {
    const city = cityItems[index];
    if (!city) return;
    locationInput.value = city.nom;
    hideCityList();
    locationInput.focus();
  }

  function renderCityList() {
    cityList.innerHTML = "";
    if (cityItems.length === 0) { hideCityList(); return; }
    cityItems.forEach((c, i) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      if (i === cityHighlight) li.classList.add("highlighted");
      const name = document.createElement("span");
      name.textContent = c.nom;
      const meta = document.createElement("span");
      meta.className = "city-meta";
      meta.textContent = c.cp + (c.dep ? " · " + c.dep : "");
      li.append(name, meta);
      // mousedown (pas click) pour passer avant le blur de l'input
      li.addEventListener("mousedown", (e) => { e.preventDefault(); selectCity(i); });
      cityList.appendChild(li);
    });
    cityList.classList.remove("hidden");
  }

  locationInput.addEventListener("input", () => {
    const q = locationInput.value.trim();
    clearTimeout(cityDebounce);
    if (q.length < 2) { hideCityList(); return; }
    cityDebounce = setTimeout(async () => {
      try {
        if (cityAbort) cityAbort.abort();
        cityAbort = new AbortController();
        const resp = await fetch("/api/cities?q=" + encodeURIComponent(q),
                                 { signal: cityAbort.signal });
        if (!resp.ok) return;
        cityItems = (await resp.json()).cities;
        cityHighlight = cityItems.length > 0 ? 0 : -1;
        renderCityList();
      } catch { /* requête annulée ou réseau : on ignore */ }
    }, 220);
  });

  locationInput.addEventListener("keydown", (e) => {
    if (cityList.classList.contains("hidden")) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      cityHighlight = (cityHighlight + 1) % cityItems.length;
      renderCityList();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      cityHighlight = (cityHighlight - 1 + cityItems.length) % cityItems.length;
      renderCityList();
    } else if (e.key === "Enter") {
      e.preventDefault(); // ne pas soumettre le formulaire : on sélectionne la ville
      selectCity(cityHighlight >= 0 ? cityHighlight : 0);
    } else if (e.key === "Escape") {
      hideCityList();
    }
  });

  locationInput.addEventListener("blur", () => setTimeout(hideCityList, 150));

  /* ---------- Onglets ---------- */
  function showView(name) {
    const isSearch = name === "search";
    viewSearch.classList.toggle("hidden", !isSearch);
    viewPins.classList.toggle("hidden", isSearch);
    tabSearch.classList.toggle("active", isSearch);
    tabPins.classList.toggle("active", !isSearch);
  }
  tabSearch.addEventListener("click", () => showView("search"));
  tabPins.addEventListener("click", () => showView("pins"));

  /* ---------- Épinglés (serveur) ---------- */
  async function loadPins() {
    try {
      const resp = await fetch("/api/pins", { headers: apiHeaders() });
      if (!resp.ok) throw new Error(resp.status);
      pinnedOffers = (await resp.json()).pins;
    } catch {
      pinnedOffers = [];
    }
    // synchroniser le statut sur les résultats de recherche affichés
    const byUrl = Object.fromEntries(pinnedOffers.map((p) => [p.url, p.pin_status]));
    for (const offer of allResults) offer.pin_status = byUrl[offer.url] || null;

    pinCountEl.textContent = pinnedOffers.length;
    renderPinned();
    render();
  }

  async function setPin(offer, status) {
    if (!pseudo && !localStorage.getItem("pseudoAsked")) openPseudoModal();
    await fetch("/api/pins", {
      method: "PUT",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ status, offer }),
    });
    await loadPins();
  }

  async function unpin(offer) {
    await fetch("/api/pins?url=" + encodeURIComponent(offer.url),
                { method: "DELETE", headers: apiHeaders() });
    await loadPins();
  }

  function renderPinned() {
    pinnedSections.innerHTML = "";
    pinsEmpty.classList.toggle("hidden", pinnedOffers.length > 0);
    for (const status of PIN_STATUSES) {
      const group = pinnedOffers.filter((p) => p.pin_status === status);
      if (group.length === 0) continue;
      const h = document.createElement("h2");
      h.className = "pin-section-title";
      const dot = document.createElement("span");
      dot.className = "pin-dot inline-dot pin-" + status;
      const count = document.createElement("span");
      count.className = "count";
      count.textContent = "(" + group.length + ")";
      h.append(dot, document.createTextNode(PIN_LABELS[status] + " "), count);
      pinnedSections.appendChild(h);
      for (const offer of group) pinnedSections.appendChild(renderCard(offer));
    }
  }

  /* ---------- Recherche ---------- */
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = document.getElementById("q").value.trim();
    const location = locationInput.value.trim();
    const radius = document.getElementById("radius").value;
    const sources = [...form.querySelectorAll('input[name="source"]:checked')]
      .map((c) => c.value);

    if (!q || sources.length === 0) return;

    btn.disabled = true;
    loader.classList.remove("hidden");
    emptyState.classList.add("hidden");
    toolbar.classList.add("hidden");
    errorsEl.classList.add("hidden");
    resultsEl.innerHTML = "";

    try {
      const params = new URLSearchParams({
        q, location, sources: sources.join(","), radius_km: radius,
      });
      const resp = await fetch("/api/search?" + params, { headers: apiHeaders() });
      if (!resp.ok) throw new Error("Erreur serveur (" + resp.status + ")");
      const data = await resp.json();

      allResults = data.results;
      renderErrors(data.errors);
      render();
      toolbar.classList.remove("hidden");
    } catch (err) {
      errorsEl.innerHTML = "";
      addError("La recherche a échoué : " + err.message);
      errorsEl.classList.remove("hidden");
    } finally {
      btn.disabled = false;
      loader.classList.add("hidden");
    }
  });

  [filterSalary, filterRemote, sortSel].forEach((el) =>
    el.addEventListener("change", render));

  function renderErrors(errors) {
    errorsEl.innerHTML = "";
    const names = Object.keys(errors || {});
    if (names.length === 0) return;
    for (const src of names) {
      addError("⚠️ " + (SOURCE_NAMES[src] || src) +
        " n'a pas répondu correctement — résultats partiels. (" + errors[src] + ")");
    }
    errorsEl.classList.remove("hidden");
  }

  function addError(msg) {
    const div = document.createElement("div");
    div.className = "error-item";
    div.textContent = msg;
    errorsEl.appendChild(div);
  }

  /* ---------- Rendu résultats ---------- */
  function render() {
    let list = [...allResults];
    if (filterSalary.checked) list = list.filter((o) => o.salary);
    if (filterRemote.checked)
      list = list.filter((o) => o.remote && o.remote !== "non");
    if (sortSel.value === "date") {
      list.sort((a, b) => (b.published_at || "").localeCompare(a.published_at || ""));
    } else if (sortSel.value === "relevance") {
      list.sort((a, b) => (b.relevance || 0) - (a.relevance || 0));
    }

    countEl.textContent = list.length + " offre" + (list.length > 1 ? "s" : "") +
      (list.length !== allResults.length ? " (sur " + allResults.length + ")" : "");

    resultsEl.innerHTML = "";
    if (allResults.length > 0 && list.length === 0) {
      emptyState.textContent = "Aucune offre ne correspond à ces critères.";
      emptyState.classList.remove("hidden");
      return;
    }
    emptyState.classList.add("hidden");

    for (const offer of list) resultsEl.appendChild(renderCard(offer));
  }

  function renderCard(o) {
    const card = document.createElement("article");
    card.className = "card" + (o.pin_status ? " pinned-" + o.pin_status : "");

    const head = document.createElement("div");
    head.className = "card-head";
    if (o.logo) {
      const img = document.createElement("img");
      img.className = "card-logo";
      img.src = o.logo;
      img.alt = "";
      img.loading = "lazy";
      head.appendChild(img);
    }
    const headText = document.createElement("div");
    const h = document.createElement("h2");
    h.className = "card-title";
    const a = document.createElement("a");
    a.href = o.url;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = o.title;
    h.appendChild(a);
    const sub = document.createElement("div");
    sub.className = "card-sub";
    sub.textContent = [o.company, o.location].filter(Boolean).join(" · ");
    headText.append(h, sub);
    head.appendChild(headText);
    head.appendChild(pinControls(o));

    const badges = document.createElement("div");
    badges.className = "badges";
    badges.appendChild(badge(SOURCE_NAMES[o.source] || o.source, "badge-source-" + o.source));
    if (o.contract) badges.appendChild(badge(o.contract, "badge-muted"));
    badges.appendChild(o.salary
      ? badge("💰 " + o.salary, "badge-salary")
      : badge("Salaire non indiqué", "badge-muted"));
    if (o.remote) {
      badges.appendChild(badge(
        (o.remote === "non" ? "" : "🏠 ") + (REMOTE_LABELS[o.remote] || o.remote),
        o.remote === "non" ? "badge-muted" : "badge-remote"));
    } else {
      badges.appendChild(badge("Télétravail non précisé", "badge-muted"));
    }

    card.append(head, badges);

    if (o.summary) {
      const p = document.createElement("p");
      p.className = "card-summary";
      p.textContent = o.summary;
      card.appendChild(p);
    }

    const footer = document.createElement("div");
    footer.className = "card-footer";
    const dateSpan = document.createElement("span");
    dateSpan.className = "card-date";
    dateSpan.textContent = o.published_at
      ? "Publiée " + relativeDate(o.published_at)
      : "Date non précisée";
    const links = document.createElement("span");
    links.className = "card-links";
    if (o.also_on && o.also_on.length > 0) {
      const alt = document.createElement("span");
      alt.className = "card-alt";
      alt.appendChild(document.createTextNode("Aussi sur "));
      o.also_on.forEach((d, i) => {
        if (i > 0) alt.appendChild(document.createTextNode(", "));
        const aLink = document.createElement("a");
        aLink.href = d.url;
        aLink.target = "_blank";
        aLink.rel = "noopener";
        aLink.textContent = SOURCE_NAMES[d.source] || d.source;
        alt.appendChild(aLink);
      });
      links.appendChild(alt);
    }
    const link = document.createElement("a");
    link.className = "card-link";
    link.href = o.url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "Voir l'annonce ↗";
    links.appendChild(link);
    footer.append(dateSpan, links);
    card.appendChild(footer);

    return card;
  }

  function pinControls(o) {
    const wrap = document.createElement("div");
    wrap.className = "pin-controls";
    for (const status of PIN_STATUSES) {
      const b = document.createElement("button");
      b.className = "pin-dot pin-" + status + (o.pin_status === status ? " active" : "");
      b.title = o.pin_status === status
        ? PIN_LABELS[status] + " — cliquer pour désépingler"
        : "Épingler : " + PIN_LABELS[status];
      b.addEventListener("click", () =>
        o.pin_status === status ? unpin(o) : setPin(o, status));
      wrap.appendChild(b);
    }
    if (o.pin_status) {
      const x = document.createElement("button");
      x.className = "pin-remove";
      x.title = "Désépingler";
      x.textContent = "✕";
      x.addEventListener("click", () => unpin(o));
      wrap.appendChild(x);
    }
    return wrap;
  }

  function badge(text, cls) {
    const span = document.createElement("span");
    span.className = "badge " + cls;
    span.textContent = text;
    return span;
  }

  function relativeDate(iso) {
    const days = Math.floor((Date.now() - new Date(iso + "T00:00:00")) / 86400000);
    if (days <= 0) return "aujourd'hui";
    if (days === 1) return "hier";
    if (days < 7) return "il y a " + days + " jours";
    if (days < 30) return "il y a " + Math.floor(days / 7) + " semaine" + (days >= 14 ? "s" : "");
    return "le " + new Date(iso + "T00:00:00").toLocaleDateString("fr-FR");
  }

  loadPins();
})();
