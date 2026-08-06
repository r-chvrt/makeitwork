/* MakeItWork — logique front : thème, pseudo, onglets, recherche paginée, épinglés.
   Les filtres et la pagination interrogent le serveur (base locale, réponse
   instantanée) — le scraping tourne en tâche de fond côté backend. */
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
  const paginationEl = document.getElementById("pagination");
  const filterSalary = document.getElementById("filter-salary");
  const filterRemote = document.getElementById("filter-remote");
  const filterCategory = document.getElementById("filter-category");
  const filterSalaryRange = document.getElementById("filter-salary-range");
  const filterContract = document.getElementById("filter-contract");
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

  let currentResults = [];  // offres de la page affichée
  let currentPage = 1;
  let pinnedOffers = [];    // offres épinglées (depuis le serveur)
  let hasSearched = false;

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
  document.getElementById("pseudo-skip").addEventListener("click", closePseudoModal);
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
    const byUrl = Object.fromEntries(pinnedOffers.map((p) => [p.url, p.pin_status]));
    for (const offer of currentResults) offer.pin_status = byUrl[offer.url] || null;

    pinCountEl.textContent = pinnedOffers.length;
    renderPinned();
    renderResults();
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

  /* ---------- Recherche (paginée, servie par la base locale) ---------- */
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    // nouvelle recherche : filtres remis à zéro
    filterCategory.value = "";
    filterContract.value = "";
    filterSalaryRange.value = "";
    filterSalary.checked = false;
    filterRemote.checked = false;
    doSearch(1);
  });

  [filterSalary, filterRemote, filterCategory, filterSalaryRange,
   filterContract, sortSel].forEach((el) =>
    el.addEventListener("change", () => { if (hasSearched) doSearch(1); }));

  async function doSearch(page) {
    const q = document.getElementById("q").value.trim();
    const location = locationInput.value.trim();
    const radius = document.getElementById("radius").value;
    const sources = [...form.querySelectorAll('input[name="source"]:checked')]
      .map((c) => c.value);

    if ((!q && !location) || sources.length === 0) return;

    btn.disabled = true;
    if (!hasSearched) loader.classList.remove("hidden");
    emptyState.classList.add("hidden");
    errorsEl.classList.add("hidden");

    try {
      const params = new URLSearchParams({
        q, location, sources: sources.join(","), radius_km: radius,
        page: String(page), sort: sortSel.value,
      });
      if (filterCategory.value) params.set("category", filterCategory.value);
      if (filterContract.value) params.set("contract", filterContract.value);
      if (filterSalaryRange.value) params.set("salary_range", filterSalaryRange.value);
      if (filterRemote.checked) params.set("remote_only", "true");
      if (filterSalary.checked) params.set("salary_only", "true");
      const resp = await fetch("/api/search?" + params, { headers: apiHeaders() });
      if (!resp.ok) throw new Error("Erreur serveur (" + resp.status + ")");
      const data = await resp.json();

      hasSearched = true;
      currentResults = data.results;
      currentPage = data.page;
      renderErrors(data.errors);
      populateFilters(data.facets);
      renderCount(data);
      renderResults();
      renderPagination(data.page, data.pages);
      toolbar.classList.remove("hidden");
      if (page !== 1) window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      errorsEl.innerHTML = "";
      addError("La recherche a échoué : " + err.message);
      errorsEl.classList.remove("hidden");
    } finally {
      btn.disabled = false;
      loader.classList.add("hidden");
    }
  }

  function renderCount(data) {
    let text = data.total + " offre" + (data.total > 1 ? "s" : "");
    if (data.pages > 1) text += " · page " + data.page + "/" + data.pages;
    if (data.last_scraped_at) {
      text += " · actualisé " + relativeTime(data.last_scraped_at);
    }
    countEl.textContent = text;
  }

  /* « 2026-08-06 14:03:12 » (UTC) → « il y a 12 min » */
  function relativeTime(utcStamp) {
    const then = new Date(utcStamp.replace(" ", "T") + "Z");
    const mins = Math.floor((Date.now() - then) / 60000);
    if (mins < 1) return "à l'instant";
    if (mins < 60) return "il y a " + mins + " min";
    const hours = Math.floor(mins / 60);
    if (hours < 24) return "il y a " + hours + " h";
    return "le " + then.toLocaleDateString("fr-FR");
  }

  /* Alimente les selects catégorie et contrat à partir des facettes serveur,
     en conservant la sélection en cours. */
  function populateFilters(facets) {
    fillSelect(filterCategory, "Toutes catégories", facets.categories || []);
    fillSelect(filterContract, "Tous contrats", facets.contracts || []);
  }

  function fillSelect(select, allLabel, entries) {
    const current = select.value;
    select.innerHTML = "";
    const all = document.createElement("option");
    all.value = "";
    all.textContent = allLabel;
    select.appendChild(all);
    for (const [value, count] of entries) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = value + " (" + count + ")";
      select.appendChild(opt);
    }
    select.value = [...select.options].some((o) => o.value === current) ? current : "";
  }

  /* ---------- Pagination ---------- */
  function renderPagination(page, pages) {
    paginationEl.innerHTML = "";
    paginationEl.classList.toggle("hidden", pages <= 1);
    if (pages <= 1) return;

    const mk = (label, target, opts = {}) => {
      const b = document.createElement("button");
      b.textContent = label;
      b.className = "page-btn" + (opts.current ? " current" : "");
      b.disabled = !!opts.disabled || !!opts.current;
      if (!b.disabled) b.addEventListener("click", () => doSearch(target));
      return b;
    };
    const ellipsis = () => {
      const s = document.createElement("span");
      s.className = "page-ellipsis";
      s.textContent = "…";
      return s;
    };

    paginationEl.appendChild(mk("← Précédent", page - 1, { disabled: page <= 1 }));

    const windowPages = new Set([1, 2, pages - 1, pages,
                                 page - 1, page, page + 1]);
    let last = 0;
    for (let p = 1; p <= pages; p++) {
      if (!windowPages.has(p)) continue;
      if (p - last > 1) paginationEl.appendChild(ellipsis());
      paginationEl.appendChild(mk(String(p), p, { current: p === page }));
      last = p;
    }

    paginationEl.appendChild(mk("Suivant →", page + 1, { disabled: page >= pages }));
  }

  /* ---------- Rendu résultats ---------- */
  function renderResults() {
    resultsEl.innerHTML = "";
    if (hasSearched && currentResults.length === 0) {
      emptyState.textContent = "Aucune offre ne correspond à ces critères.";
      emptyState.classList.remove("hidden");
      return;
    }
    for (const offer of currentResults) resultsEl.appendChild(renderCard(offer));
  }

  function renderErrors(errors) {
    errorsEl.innerHTML = "";
    const names = Object.keys(errors || {});
    if (names.length === 0) return;
    for (const src of names) {
      addError("⚠️ " + (SOURCE_NAMES[src] || src) +
        " n'a pas répondu correctement au dernier scrape — résultats partiels. (" +
        errors[src] + ")");
    }
    errorsEl.classList.remove("hidden");
  }

  function addError(msg) {
    const div = document.createElement("div");
    div.className = "error-item";
    div.textContent = msg;
    errorsEl.appendChild(div);
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
    badges.appendChild(dateBadge(o));
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
    footer.append(links);
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

  /* Badge de date : couleur selon la fraîcheur, date exacte au survol. */
  function dateBadge(o) {
    if (!o.published_at) return badge("📅 Date non précisée", "badge-date badge-date-old");
    const days = Math.floor((Date.now() - new Date(o.published_at + "T00:00:00")) / 86400000);
    const cls = days <= 1 ? "badge-date-fresh" : days <= 7 ? "badge-date-recent" : "badge-date-old";
    const b = badge("📅 " + capitalize(relativeDate(o.published_at)), "badge-date " + cls);
    b.title = "Publiée le " + new Date(o.published_at + "T00:00:00").toLocaleDateString("fr-FR", {
      weekday: "long", day: "numeric", month: "long", year: "numeric",
    });
    return b;
  }

  function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
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
