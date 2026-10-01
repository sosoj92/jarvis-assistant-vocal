(function () {
  "use strict";

  const TOLERANCE = 2;
  const MAX_PAGES = 40;
  const MM = 96 / 25.4;
  // Un carnet plus petit n'a pas d'interet : il est retire plutot que tasse.
  const FILLER_MIN = 30 * MM;
  // Au-dela, un vide devient un espace de notes ligne.
  const GAP_MIN = 35 * MM;
  // Une page moins remplie peut accueillir la rubrique suivante si elle y tient entiere.
  const MERGE_MAX_USED = 0.8;

  function contentOf(sheet) {
    return sheet && sheet.querySelector(":scope > .page-content");
  }

  function isOverflowing(sheet) {
    const content = contentOf(sheet);
    return Boolean(content && content.scrollHeight > content.clientHeight + TOLERANCE);
  }

  function usedRatio(sheet) {
    const content = contentOf(sheet);
    if (!content || !content.children.length) return 0;
    const top = content.getBoundingClientRect().top;
    let bottom = top;
    for (const child of content.children) {
      bottom = Math.max(bottom, child.getBoundingClientRect().bottom);
    }
    return Math.max(0, Math.min(1.5, (bottom - top) / content.clientHeight));
  }

  function continuationHeader(source) {
    const template = document.querySelector(".running-head");
    if (template) {
      const header = template.cloneNode(true);
      const centre = header.querySelector("span:nth-child(2)");
      if (centre) centre.textContent = `${source.dataset.label || "Suite"} - SUITE`;
      return header;
    }
    const header = document.createElement("header");
    header.className = "running-head";
    header.innerHTML = `<strong>Signal Matin</strong><span>${source.dataset.label || "Suite"} - SUITE</span><span></span>`;
    return header;
  }

  function continuationTitle(source) {
    const title = document.createElement("header");
    title.className = "section-header adaptive-section-header";
    title.innerHTML = `<span class="section-eyebrow">La lecture continue</span><h2>${source.dataset.label || "Suite"}</h2>`;
    return title;
  }

  function buildContinuation(source) {
    const sheet = document.createElement("section");
    const classes = [...source.classList].filter(
      (name) => !/^page-\d+$/.test(name) && name !== "page-adaptive-continuation" && name !== "adaptive-sparse"
    );
    sheet.className = `${classes.join(" ")} page-adaptive-continuation`;
    sheet.dataset.label = source.dataset.label || "Suite";
    sheet.dataset.adaptiveContinuation = "true";
    sheet.appendChild(continuationHeader(source));

    const content = document.createElement("main");
    content.className = "page-content";
    content.appendChild(continuationTitle(source));
    sheet.appendChild(content);

    const footer = source.querySelector(":scope > footer");
    sheet.appendChild(footer ? footer.cloneNode(true) : document.createElement("footer"));
    source.after(sheet);
    return sheet;
  }

  function firstMovedNode(destination) {
    const content = contentOf(destination);
    return [...content.children].find(
      (node) => !node.classList.contains("adaptive-section-header")
    ) || null;
  }

  function prependToContinuation(destination, node) {
    const content = contentOf(destination);
    content.insertBefore(node, firstMovedNode(destination));
  }

  function movableDirectChildren(source) {
    const content = contentOf(source);
    return [...content.children].filter(
      (node) => !node.classList.contains("section-header") &&
        !node.classList.contains("adaptive-section-header")
    );
  }

  function nestedCandidates(source) {
    const content = contentOf(source);
    if (!content) return [];
    const selectors = [
      ".briefs-detail-side > .brief-detail",
      ".tech-secondary > .dossier-story",
      ".tech-continuation > .dossier-story",
      ".curiosity-stories > div > .dossier-story",
      ".news-followups > .news-card",
      ".news-grid > .news-card",
      ".brief-list > .news-card",
      ".learning-strip > .learning-card",
      ".adaptive-flow > article"
    ];
    return [...new Set(
      selectors.flatMap((selector) => [...content.querySelectorAll(selector)])
    )];
  }

  function moveNestedItem(source, destination) {
    const candidates = nestedCandidates(source);
    const node = candidates[candidates.length - 1];
    if (!node) return null;
    const record = { node, parent: node.parentNode, next: node.nextSibling };

    const destinationContent = contentOf(destination);
    let flow = destinationContent.querySelector(":scope > .adaptive-flow");
    if (!flow) {
      flow = document.createElement("div");
      flow.className = "adaptive-flow";
      destinationContent.insertBefore(flow, firstMovedNode(destination));
    }
    flow.insertBefore(node, flow.firstChild);
    return record;
  }

  function moveOneBlock(source, destination) {
    const direct = movableDirectChildren(source);
    if (direct.length > 1) {
      const node = direct[direct.length - 1];
      const record = { node, parent: node.parentNode, next: node.nextSibling };
      prependToContinuation(destination, node);
      return record;
    }
    return moveNestedItem(source, destination);
  }

  function rebalance(source, destination) {
    for (let attempt = 0; attempt < 4; attempt += 1) {
      if (usedRatio(destination) >= 0.52 || usedRatio(source) <= 0.58) break;
      const record = moveOneBlock(source, destination);
      if (!record) break;
      if (isOverflowing(destination)) {
        record.parent.insertBefore(record.node, record.next);
        const emptyFlow = contentOf(destination).querySelector(":scope > .adaptive-flow:empty");
        if (emptyFlow) emptyFlow.remove();
        break;
      }
    }
  }

  function splitOverflow(source) {
    const destination = buildContinuation(source);
    let moved = false;
    for (let attempt = 0; attempt < 80 && isOverflowing(source); attempt += 1) {
      if (!moveOneBlock(source, destination)) break;
      moved = true;
    }
    if (!moved) {
      destination.remove();
      source.dataset.paginationUnresolved = "true";
      return false;
    }
    rebalance(source, destination);
    return true;
  }

  function reindexPages() {
    const pages = [...document.querySelectorAll(".sheet")];
    pages.forEach((sheet, index) => {
      for (const className of [...sheet.classList]) {
        if (/^page-\d+$/.test(className)) sheet.classList.remove(className);
      }
      sheet.classList.add(`page-${index + 1}`);
      sheet.dataset.page = String(index + 1);
      const number = sheet.querySelector(":scope > footer span:last-child");
      if (number) number.textContent = String(index + 1);
      sheet.classList.toggle(
        "adaptive-sparse",
        sheet.dataset.adaptiveContinuation === "true" && usedRatio(sheet) < 0.58
      );
    });
  }

  // --- Elements de remplissage (carnet) : jamais la cause d'une page en plus.

  function detachFillers() {
    const kept = [];
    for (const filler of [...document.querySelectorAll(".page-content .page-filler")]) {
      if (filler.classList.contains("is-generated")) {
        filler.remove();
        continue;
      }
      // Un repere invisible garde la place du carnet et suit sa rubrique si elle
      // est decoupee ou remontee sur une autre page.
      const anchor = document.createElement("i");
      anchor.className = "filler-anchor";
      anchor.hidden = true;
      filler.replaceWith(anchor);
      filler.classList.remove("is-sized");
      filler.style.height = "";
      kept.push({ filler, anchor });
    }
    return kept;
  }

  function sizeFiller(sheet, filler, target) {
    filler.classList.add("is-sized");
    let height = Math.max(FILLER_MIN, target);
    filler.style.height = `${height}px`;
    for (let attempt = 0; attempt < 80 && isOverflowing(sheet) && height >= FILLER_MIN; attempt += 1) {
      height -= 4;
      filler.style.height = `${height}px`;
    }
    if (height < FILLER_MIN || isOverflowing(sheet)) {
      filler.remove();
      return false;
    }
    return true;
  }

  function freeBelow(sheet, node) {
    const content = contentOf(sheet);
    const limit = content.getBoundingClientRect().top + content.clientHeight;
    return limit - node.getBoundingClientRect().bottom - 2;
  }

  function restoreFillers(kept) {
    for (const { filler, anchor } of kept) {
      if (!anchor.isConnected) continue;
      const sheet = anchor.closest(".sheet");
      anchor.replaceWith(filler);
      filler.classList.add("is-sized");
      filler.style.height = `${FILLER_MIN}px`;
      sizeFiller(sheet, filler, FILLER_MIN + freeBelow(sheet, filler));
    }
  }

  function generatedNotes() {
    const notes = document.createElement("section");
    notes.className = "notes-space page-filler is-generated";
    notes.innerHTML =
      '<header class="section-header"><span class="section-eyebrow">Idees, reponses, choses a retenir</span>' +
      "<h2>Notes</h2></header>" +
      '<div class="writing-lines"></div>';
    return notes;
  }

  function fillGaps() {
    for (const sheet of document.querySelectorAll(".sheet")) {
      if (sheet.dataset.merge === "false" || sheet.querySelector(".page-filler")) continue;
      const content = contentOf(sheet);
      const children = [...content.children].filter((node) => !node.hidden);
      if (!children.length) continue;
      const top = content.getBoundingClientRect().top;
      let previous = top;
      let best = { size: 0, before: null };
      for (const child of children) {
        const rect = child.getBoundingClientRect();
        if (rect.top - previous > best.size) best = { size: rect.top - previous, before: child };
        previous = Math.max(previous, rect.bottom);
      }
      const endGap = top + content.clientHeight - previous;
      if (endGap >= best.size) best = { size: endGap, before: null };
      if (best.size < GAP_MIN) continue;
      const notes = generatedNotes();
      content.insertBefore(notes, best.before);
      // La marge haute du carnet (8 mm) et une petite respiration sortent de l'espace libre.
      sizeFiller(sheet, notes, best.size - 10 * MM);
    }
  }

  // --- Regroupement : une rubrique courte remonte sur une page peu remplie.

  function mergeSparse() {
    let sheets = [...document.querySelectorAll(".sheet")];
    for (let index = 0; index < sheets.length - 1; index += 1) {
      const host = sheets[index];
      const guest = sheets[index + 1];
      if (host.dataset.merge === "false" || guest.dataset.merge === "false") continue;
      if (usedRatio(host) > MERGE_MAX_USED) continue;
      const hostContent = contentOf(host);
      const guestContent = contentOf(guest);
      if (!hostContent || !guestContent || !guestContent.children.length) continue;

      // Les classes de rubrique (page-day, page-tech...) suivent le contenu : les
      // regles CSS `.page-day .x` continuent de s'appliquer apres le deplacement.
      const wrapper = document.createElement("div");
      wrapper.className = ["merged-section", ...[...guest.classList].filter(
        (name) => name.startsWith("page-") && !/^page-\d+$/.test(name) && name !== "page-adaptive-continuation"
      )].join(" ");
      while (guestContent.firstChild) wrapper.appendChild(guestContent.firstChild);
      hostContent.appendChild(wrapper);
      if (isOverflowing(host)) {
        while (wrapper.firstChild) guestContent.appendChild(wrapper.firstChild);
        wrapper.remove();
        continue;
      }
      const labels = (host.dataset.mergedLabels || host.dataset.label || "").split(" · ");
      labels.push(guest.dataset.mergedLabels || guest.dataset.label || "");
      host.dataset.mergedLabels = labels.filter(Boolean).join(" · ");
      const centre = host.querySelector(":scope > .running-head span:nth-child(2)");
      if (centre) centre.textContent = host.dataset.mergedLabels.toUpperCase();
      guest.remove();
      sheets.splice(index + 1, 1);
      index -= 1;
    }
  }

  function paginate() {
    const fillers = detachFillers();
    for (let round = 0; round < MAX_PAGES; round += 1) {
      const overflowing = [...document.querySelectorAll(".sheet")].find(
        (sheet) => isOverflowing(sheet) && sheet.dataset.paginationUnresolved !== "true"
      );
      if (!overflowing || !splitOverflow(overflowing)) break;
    }
    mergeSparse();
    restoreFillers(fillers);
    fillGaps();
    reindexPages();
    return {
      pages: document.querySelectorAll(".sheet").length,
      unresolved: [...document.querySelectorAll(".sheet")]
        .filter((sheet) => isOverflowing(sheet)).length
    };
  }

  window.SignalMatinPagination = { paginate, usedRatio };
  const ready = () => document.fonts.ready.then(paginate);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready, { once: true });
  } else {
    ready();
  }
})();
