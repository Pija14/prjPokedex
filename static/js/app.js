// CardDex — melhorias progressivas. Todas as páginas funcionam sem JavaScript;
// aqui ficam a busca/filtro instantâneos, a prévia da imagem, a confirmação de exclusão e os avisos.
(() => {
  "use strict";

  const normalize = (text) => String(text || "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().trim();
  const MAX_IMAGE_MB = 8;
  const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

  // Foto do celular (vários MB) vira JPEG menor só para a análise da IA; a original é a que fica salva.
  const shrinkImage = async (blob, maxSide, quality) => {
    try {
      const bitmap = await createImageBitmap(blob, { imageOrientation: "from-image" });
      const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(bitmap.width * scale);
      canvas.height = Math.round(bitmap.height * scale);
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      bitmap.close?.();
      return await new Promise((resolve) => canvas.toBlob((b) => resolve(b || blob), "image/jpeg", quality));
    } catch {
      return blob; // navegador sem suporte: envia a original
    }
  };
  const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

  // ---------- Barra superior: muda de tom ao rolar (Material 3) ----------
  const topBar = document.querySelector(".top-bar");
  if (topBar) {
    const onScroll = () => topBar.classList.toggle("is-scrolled", window.scrollY > 4);
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  // ---------- Avisos (flash) ----------
  document.querySelectorAll("[data-autohide]").forEach((toast) => {
    setTimeout(() => {
      toast.classList.add("is-leaving");
      setTimeout(() => toast.remove(), 350);
    }, 4000);
  });

  // ---------- Minha Coleção: prateleiras (uma por coleção), com setas no computador ----------
  const shelves = [...document.querySelectorAll("[data-shelf]")];
  const canHover = window.matchMedia("(hover: hover) and (pointer: fine)");
  const updateArrows = (shelf) => {
    const track = shelf.querySelector("[data-shelf-track]");
    const arrows = shelf.querySelector("[data-shelf-arrows]");
    const overflow = track.scrollWidth > track.clientWidth + 4;
    arrows.hidden = !(overflow && canHover.matches); // no celular, rola com o dedo
    const atStart = track.scrollLeft <= 4;
    const atEnd = track.scrollLeft + track.clientWidth >= track.scrollWidth - 4;
    shelf.querySelector("[data-shelf-prev]").disabled = atStart;
    shelf.querySelector("[data-shelf-next]").disabled = atEnd;
    // Bordas esmaecidas indicam que o carrossel continua para aquele lado
    shelf.classList.toggle("has-more-left", overflow && !atStart);
    shelf.classList.toggle("has-more-right", overflow && !atEnd);
  };
  const updateAllArrows = () => shelves.forEach(updateArrows);
  shelves.forEach((shelf) => {
    const track = shelf.querySelector("[data-shelf-track]");
    const step = (direction) => {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      track.scrollBy({ left: direction * track.clientWidth * 0.85, behavior: reduce ? "auto" : "smooth" });
    };
    shelf.querySelector("[data-shelf-prev]").addEventListener("click", () => step(-1));
    shelf.querySelector("[data-shelf-next]").addEventListener("click", () => step(1));
    let ticking = false;
    track.addEventListener("scroll", () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => { updateArrows(shelf); ticking = false; });
    }, { passive: true });
  });
  window.addEventListener("resize", updateAllArrows);
  canHover.addEventListener?.("change", updateAllArrows);
  updateAllArrows();

  // ---------- Minha Coleção: busca e filtros instantâneos ----------
  const setupFilters = () => {
    const filterForm = document.querySelector("[data-filters]");
    const grid = document.querySelector("[data-card-grid]");
    if (!filterForm || !grid) return;
    const tiles = [...grid.querySelectorAll(".card-tile")];
    const count = document.querySelector("[data-result-count]");
    const emptyFilter = document.querySelector("[data-empty-filter]");
    const total = Number(grid.dataset.total || tiles.length);

    const apply = () => {
      const q = normalize(filterForm.q.value);
      const collection = filterForm.collection.value;
      const rarity = filterForm.rarity.value;
      let shown = 0;
      tiles.forEach((tile) => {
        const matchText = !q || normalize(tile.dataset.name).includes(q) || normalize(tile.dataset.number).includes(q);
        const visible = matchText && (!collection || tile.dataset.collection === collection) && (!rarity || tile.dataset.rarity === rarity);
        tile.classList.toggle("is-hidden", !visible);
        if (visible) shown += 1;
      });
      if (count) count.textContent = `${shown} de ${total} ${total === 1 ? "card" : "cards"}`;
      shelves.forEach((shelf) => { // coleção sem nenhuma carta no filtro some da tela
        const visible = shelf.querySelectorAll(".card-tile:not(.is-hidden)").length;
        const label = shelf.querySelector("[data-shelf-count]");
        const all = Number(label.dataset.total);
        label.textContent = visible === all ? `${all} ${all === 1 ? "card" : "cards"}` : `${visible} de ${all} ${all === 1 ? "card" : "cards"}`;
        shelf.classList.toggle("is-hidden", visible === 0);
        shelf.querySelector("[data-shelf-track]").scrollLeft = 0;
      });
      updateAllArrows();
      if (emptyFilter) emptyFilter.classList.toggle("is-hidden", shown > 0);
      const params = new URLSearchParams();
      if (filterForm.q.value.trim()) params.set("q", filterForm.q.value.trim());
      if (collection) params.set("collection", collection);
      if (rarity) params.set("rarity", rarity);
      history.replaceState(null, "", params.toString() ? `?${params}` : location.pathname);
    };

    // Se a página já veio filtrada pelo servidor (link com ?q=...), nem todas as cartas estão aqui:
    // nesse caso cada mudança refaz a busca no servidor em vez de filtrar só as visíveis.
    const serverFiltered = tiles.length < Number(grid.dataset.total || 0);
    if (serverFiltered) {
      let timer;
      const submit = () => { clearTimeout(timer); timer = setTimeout(() => filterForm.submit(), 350); };
      filterForm.addEventListener("input", submit);
      filterForm.addEventListener("change", submit);
      return;
    }

    filterForm.addEventListener("input", apply);
    filterForm.addEventListener("change", apply);
    filterForm.addEventListener("submit", (event) => { event.preventDefault(); apply(); });
    document.querySelectorAll("[data-clear-filters]").forEach((link) => link.addEventListener("click", (event) => {
      event.preventDefault();
      filterForm.reset();
      filterForm.q.value = "";
      filterForm.collection.value = "";
      filterForm.rarity.value = "";
      apply();
      filterForm.q.focus();
    }));
    apply();
  };
  setupFilters();

  // ---------- Formulário: prévia e validação da imagem ----------
  const form = document.querySelector("[data-card-form]");
  if (form) {
    const input = form.querySelector("[data-image-input]");
    const dropzone = form.querySelector("[data-dropzone]");
    const preview = form.querySelector("[data-preview]");
    const empty = form.querySelector("[data-preview-empty]");
    const removeImage = form.querySelector("[data-remove-image]");
    const originalSrc = preview?.getAttribute("src") || "";
    let objectUrl = null;

    const showError = (message) => {
      let error = dropzone.parentElement.querySelector(".field-error[data-client]");
      if (!message) { error?.remove(); dropzone.classList.remove("has-error"); return; }
      if (!error) {
        error = document.createElement("p");
        error.className = "field-error";
        error.dataset.client = "";
        dropzone.after(error);
      }
      error.textContent = message;
      dropzone.classList.add("has-error");
    };

    const setPreview = (src) => {
      preview.src = src || "";
      preview.classList.toggle("is-hidden", !src);
      empty.classList.toggle("is-hidden", Boolean(src));
    };

    input?.addEventListener("change", () => {
      const file = input.files?.[0];
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = null;
      if (!file) { setPreview(originalSrc); showError(""); return; }
      if (!IMAGE_TYPES.includes(file.type)) {
        input.value = "";
        setPreview(originalSrc);
        showError("Formato não aceito. Envie JPG, PNG ou WEBP.");
        return;
      }
      if (file.size > MAX_IMAGE_MB * 1024 * 1024) {
        input.value = "";
        setPreview(originalSrc);
        showError(`Imagem grande demais. O limite é ${MAX_IMAGE_MB} MB.`);
        return;
      }
      showError("");
      objectUrl = URL.createObjectURL(file);
      setPreview(objectUrl);
      if (removeImage) removeImage.checked = false;
      form.dispatchEvent(new CustomEvent("carddex:image-selected", { detail: { file } }));
    });

    removeImage?.addEventListener("change", () => {
      if (removeImage.checked) { input.value = ""; setPreview(""); } else { setPreview(originalSrc); }
    });

    ["dragenter", "dragover"].forEach((type) => dropzone?.addEventListener(type, () => dropzone.classList.add("is-dragover")));
    ["dragleave", "drop"].forEach((type) => dropzone?.addEventListener(type, () => dropzone.classList.remove("is-dragover")));

    form.addEventListener("submit", () => {
      const button = form.querySelector("[data-submit]");
      if (button) { button.disabled = true; button.lastChild.textContent = " Salvando…"; }
    });
  }

  // ---------- Reconhecimento da carta pela IA (Gemini, no servidor) ----------
  const aiPanel = form?.querySelector("[data-ai-panel]");
  if (aiPanel) {
    const AI_FIELDS = ["pokemon_name", "collection_name", "card_number", "rarity", "language"];
    const EXTRA_LABELS = { hp: "HP", types: "Tipo", stage: "Estágio", edition: "Edição", set_code: "Código do set",
      regulation_mark: "Regulação", illustrator: "Ilustrador", year: "Ano", card_type: "Tipo de carta", notes: "Observação",
      catalog_set: "Coleção (em inglês)" };
    const status = aiPanel.querySelector("[data-ai-status]");
    const button = aiPanel.querySelector("[data-ai-identify]");
    const buttonLabel = aiPanel.querySelector("[data-ai-label]");
    const extraBox = aiPanel.querySelector("[data-ai-extra]");
    const auto = aiPanel.dataset.aiAuto === "1";
    let currentFile = null, busy = false, identifiedOnce = false;

    const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const setStatus = (kind, html) => {
      status.className = `ai-status is-${kind}`;
      status.querySelector("p").innerHTML = html;
    };
    const markAi = (input, on, chip = "IA") => {
      const fieldBox = input.closest(".field");
      fieldBox?.classList.toggle("is-ai", on);
      const label = fieldBox?.querySelector("label");
      label?.querySelector(".ai-chip")?.remove();
      if (on && label) label.insertAdjacentHTML("beforeend", ` <span class="ai-chip${chip === "IA" ? "" : " is-catalog"}">${chip}</span>`);
    };
    // Coleção e raridade: conferidas no catálogo oficial ou só lidas pela IA.
    const SOURCE = {
      catalogo: { chip: "Catálogo", text: "Coleção e raridade confirmadas no catálogo oficial." },
      codigo: { chip: "Catálogo", text: "Coleção identificada pelo código e número impressos; confira a raridade." },
      ia: { chip: "IA", text: "<strong>Coleção não confirmada no catálogo</strong>: é uma sugestão da IA, confira." },
    };
    // Na edição, os dados já salvos valem como "digitados": a IA só completa os campos vazios.
    if (!auto) AI_FIELDS.forEach((name) => { const input = form.elements[name]; if (input?.value.trim()) input.dataset.userEdited = "1"; });
    AI_FIELDS.forEach((name) => form.elements[name]?.addEventListener("input", (event) => {
      event.target.dataset.userEdited = "1";
      markAi(event.target, false);
    }));

    const showExtra = (data) => {
      const extra = { ...(data.extra || {}) };
      const catalogName = data.catalog?.set_name;
      if (catalogName && catalogName !== data.collection_name) extra.catalog_set = catalogName;
      const rows = Object.entries(extra)
        .filter(([key]) => EXTRA_LABELS[key])
        .map(([key, value]) => `<div><dt>${EXTRA_LABELS[key]}</dt><dd>${escapeHtml(Array.isArray(value) ? value.join(", ") : value)}</dd></div>`);
      extraBox.innerHTML = rows.join("");
      extraBox.hidden = rows.length === 0;
      extraBox.scrollTop = 0;
      const title = aiPanel.querySelector("[data-ai-extra-title]");
      if (title) title.hidden = rows.length === 0;
    };

    const fill = (prefill, source) => {
      let filled = 0;
      AI_FIELDS.forEach((name) => {
        const input = form.elements[name];
        const value = prefill[name];
        if (!input || !value) return;
        if (input.dataset.userEdited && input.value.trim()) return; // não sobrescreve o que a pessoa digitou
        input.value = value;
        input.removeAttribute("aria-invalid");
        const confirmed = (name === "collection_name" || (name === "rarity" && source === "catalogo")) && SOURCE[source]?.chip === "Catálogo";
        markAi(input, true, confirmed ? "Catálogo" : "IA");
        filled += 1;
      });
      return filled;
    };

    const identify = async () => {
      let blob = currentFile;
      if (!blob) {
        const src = form.querySelector("[data-preview]")?.getAttribute("src");
        if (!src) { setStatus("error", "Escolha a foto da carta primeiro."); return; }
        blob = await (await fetch(src)).blob(); // edição: usa a imagem já salva
      }
      if (busy) return;
      busy = true;
      button.hidden = false;
      button.disabled = true;
      buttonLabel.textContent = "Analisando…";
      setStatus("loading", '<span class="ai-spinner" aria-hidden="true"></span> Analisando a carta… isso leva alguns segundos.');
      try {
        const body = new FormData();
        body.append("image", await shrinkImage(blob, 1600, 0.85), "carta.jpg");
        const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
        const response = await fetch(aiPanel.dataset.aiUrl, { method: "POST", body, headers: { "X-CSRF-Token": csrf } });
        if (response.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); return; }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || data.errors?.image || "Não foi possível reconhecer a carta.");
        const filled = fill(data.prefill || {}, data.collection_source);
        identifiedOnce = true;
        showExtra(data);
        const summary = [data.pokemon_name, data.collection_name, data.card_number && `#${data.card_number}`].filter(Boolean).map(escapeHtml).join(" · ");
        const low = typeof data.confidence === "number" && data.confidence < 0.7;
        const unconfirmed = data.collection_source !== "catalogo" && data.collection_source !== "codigo";
        const sourceText = SOURCE[data.collection_source]?.text || "Coleção não identificada: preencha manualmente se souber.";
        setStatus(low || unconfirmed ? "warning" : "success",
          `<strong>${summary || "Carta identificada"}</strong><br>${sourceText}<br>${filled ? `${filled} ${filled === 1 ? "campo preenchido" : "campos preenchidos"}.` : "Nenhum campo novo preenchido."} ${low ? "A IA está em dúvida: confira com atenção." : "Confira os dados"} e informe o valor antes de salvar.`);
      } catch (error) {
        setStatus("error", `${escapeHtml(error.message || "Falha ao reconhecer a carta.")}<br>Você pode preencher manualmente.`);
      } finally {
        busy = false;
        button.disabled = false;
        buttonLabel.textContent = identifiedOnce ? "Identificar de novo" : "Identificar com IA";
      }
    };

    button.addEventListener("click", identify);
    form.addEventListener("carddex:image-selected", (event) => {
      currentFile = event.detail.file;
      button.hidden = false;
      if (auto && !identifiedOnce) identify();
    });
    form.querySelector("[data-remove-image]")?.addEventListener("change", (event) => {
      button.hidden = event.target.checked;
      if (event.target.checked) currentFile = null;
    });
  }

  // ---------- Avaliação da condição por IA: frente + verso ----------
  const gradeForm = document.querySelector("[data-grade-form]");
  if (gradeForm) {
    const submit = gradeForm.querySelector("[data-grade-submit]");
    const missing = gradeForm.querySelector("[data-grade-missing]");
    const progress = gradeForm.querySelector("[data-grade-progress]");
    const steps = [...progress.querySelectorAll("[data-grade-step]")];
    const errorBox = document.querySelector("[data-grade-error]");
    const files = { front: null, back: null };
    let busy = false;

    const showError = (message, issues = [], tips = false) => {
      errorBox.classList.toggle("is-hidden", !message);
      errorBox.querySelector("[data-grade-error-text]").textContent = message ? message : "";
      const list = errorBox.querySelector("[data-grade-issues]");
      list.replaceChildren(...issues.map((text) => Object.assign(document.createElement("li"), { textContent: text })));
      list.classList.toggle("is-hidden", issues.length === 0);
      errorBox.querySelector("[data-grade-tips]").classList.toggle("is-hidden", !tips);
      if (message) errorBox.scrollIntoView({ behavior: "smooth", block: "center" });
    };

    gradeForm.querySelectorAll("[data-grade-input]").forEach((input) => {
      const side = input.dataset.gradeInput;
      const drop = input.closest("[data-grade-drop]");
      const preview = drop.querySelector("[data-grade-preview]");
      const empty = drop.querySelector("[data-grade-empty]");
      const state = gradeForm.querySelector(`[data-grade-state="${side}"]`);
      input.addEventListener("change", () => {
        const file = input.files?.[0] || null;
        if (preview.src.startsWith("blob:")) URL.revokeObjectURL(preview.src);
        let problem = "";
        if (file && !IMAGE_TYPES.includes(file.type)) problem = "Formato não aceito. Envie JPG, PNG ou WEBP.";
        else if (file && file.size > MAX_IMAGE_MB * 1024 * 1024) problem = `Imagem grande demais. O limite é ${MAX_IMAGE_MB} MB.`;
        if (problem) input.value = "";
        files[side] = problem ? null : file;
        preview.classList.toggle("is-hidden", !files[side]);
        empty.classList.toggle("is-hidden", Boolean(files[side]));
        if (files[side]) preview.src = URL.createObjectURL(files[side]);
        drop.classList.toggle("has-error", Boolean(problem));
        drop.classList.toggle("is-ready", Boolean(files[side]));
        state.textContent = problem || (files[side] ? "✓ Foto pronta" : "Nenhuma foto escolhida");
        if (files.front && files.back) missing.classList.add("is-hidden");
      });
    });

    // As etapas avançam com o tempo só para dar retorno visual: a resposta da IA chega de uma vez.
    let timer = null;
    const startProgress = () => {
      progress.classList.remove("is-hidden");
      steps.forEach((step) => { step.classList.remove("is-done"); step.firstElementChild.textContent = "○"; });
      let i = 0;
      timer = setInterval(() => {
        if (i < steps.length - 1) { steps[i].classList.add("is-done"); steps[i].firstElementChild.textContent = "✓"; i += 1; }
      }, 4000);
    };
    const stopProgress = (done) => {
      clearInterval(timer);
      if (done) {
        steps.forEach((step) => { step.classList.add("is-done"); step.firstElementChild.textContent = "✓"; });
        progress.querySelector(".grade-progress-title").textContent = "Análise concluída!";
      } else {
        progress.classList.add("is-hidden");
      }
    };

    gradeForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (busy) return; // não deixa enviar duas vezes
      if (!files.front || !files.back) { missing.classList.remove("is-hidden"); missing.scrollIntoView({ behavior: "smooth", block: "center" }); return; }
      busy = true;
      submit.disabled = true;
      submit.textContent = "Analisando…";
      showError("");
      startProgress();
      try {
        const body = new FormData();
        body.append("front_image", await shrinkImage(files.front, 2048, 0.9), "frente.jpg");
        body.append("back_image", await shrinkImage(files.back, 2048, 0.9), "verso.jpg");
        const response = await fetch(gradeForm.dataset.gradeApi, { method: "POST", body, headers: { "X-CSRF-Token": csrfToken() } });
        if (response.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); return; }
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
          stopProgress(false);
          showError(data.error || "Não foi possível analisar a carta agora.", data.issues || [], Boolean(data.tips));
        } else {
          stopProgress(true);
          submit.textContent = "Análise concluída!";
          setTimeout(() => { location.href = data.evaluation.url; }, 700);
          return; // continua bloqueado até abrir o resultado
        }
      } catch {
        stopProgress(false);
        showError("Não foi possível enviar as fotos. Confira a conexão e escolha as fotos de novo.");
      }
      busy = false;
      submit.disabled = false;
      submit.textContent = "Analisar card";
    });
  }

  // ---------- Scan: câmera ao vivo → IA → vitrine (nada é salvo) ----------
  const scanBox = document.querySelector("[data-scan]");
  if (scanBox) {
    const scanForm = scanBox.querySelector("[data-scan-form]");
    const video = scanBox.querySelector("[data-scan-video]");
    const still = scanBox.querySelector("[data-scan-still]");
    const placeholder = scanBox.querySelector("[data-scan-placeholder]");
    const hint = scanBox.querySelector("[data-scan-hint]");
    const shutter = scanBox.querySelector("[data-scan-shutter]");
    const nativeCamera = scanBox.querySelector("[data-scan-native]");
    const status = scanBox.querySelector("[data-scan-status]");
    const resultBox = scanBox.querySelector("[data-scan-result]");
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const SPINNER = '<span class="ai-spinner" aria-hidden="true"></span> ';
    let stream = null, busy = false, stillUrl = null;

    const setStatus = (kind, html = "") => {
      status.hidden = !kind;
      if (kind) status.className = `ai-status scan-status is-${kind}`;
      status.querySelector("p").innerHTML = html;
    };
    const showStill = (blob) => {
      if (stillUrl) URL.revokeObjectURL(stillUrl);
      stillUrl = blob ? URL.createObjectURL(blob) : null;
      still.hidden = !blob;
      if (blob) still.src = stillUrl; else still.removeAttribute("src");
      placeholder.hidden = Boolean(blob);
    };

    const stopCamera = () => {
      stream?.getTracks().forEach((track) => track.stop());
      stream = null;
      video.srcObject = null;
      video.hidden = true;
      hint.hidden = true;
      shutter.hidden = true;
      nativeCamera.hidden = false;
      scanBox.classList.remove("is-live");
    };
    // Câmera ao vivo só com permissão e em HTTPS/localhost; senão fica o botão "Tirar foto" (câmera nativa).
    const startCamera = async () => {
      if (stream || !navigator.mediaDevices?.getUserMedia || scanBox.dataset.state !== "capture" || document.hidden) return;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false, video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1440 } },
        });
      } catch {
        stream = null;
        return;
      }
      if (scanBox.dataset.state !== "capture" || document.hidden) { stopCamera(); return; }
      video.srcObject = stream;
      await video.play().catch(() => {});
      video.hidden = false;
      showStill(null);
      placeholder.hidden = true;
      hint.hidden = false;
      shutter.hidden = false;
      nativeCamera.hidden = true;
      scanBox.classList.add("is-live");
    };
    const grabFrame = () => new Promise((resolve) => {
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      canvas.toBlob(resolve, "image/jpeg", 0.92);
    });

    // Vitrine: imagem oficial da carta, inclinada seguindo o dedo/mouse.
    const initShowcase = (root) => {
      const card = root.querySelector("[data-tilt]");
      if (!card) return;
      const official = card.querySelector("[data-official]");
      const showEmpty = () => { official?.remove(); card.querySelector("[data-official-empty]").hidden = false; };
      if (official?.complete && !official.naturalWidth) showEmpty(); // já falhou antes do JS
      official?.addEventListener("error", showEmpty); // imagem oficial fora do ar
      if (reduceMotion.matches) return;
      const tilt = (event) => {
        const box = card.getBoundingClientRect();
        const x = (event.clientX - box.left) / box.width;
        const y = (event.clientY - box.top) / box.height;
        if (x < 0 || x > 1 || y < 0 || y > 1) return;
        card.classList.add("is-tilting");
        card.style.setProperty("--ry", `${((x - 0.5) * 18).toFixed(2)}deg`);
        card.style.setProperty("--rx", `${((0.5 - y) * 18).toFixed(2)}deg`);
        card.style.setProperty("--mx", `${(x * 100).toFixed(1)}%`);
        card.style.setProperty("--my", `${(y * 100).toFixed(1)}%`);
      };
      const settle = () => {
        card.classList.remove("is-tilting");
        ["--rx", "--ry", "--mx", "--my"].forEach((name) => card.style.removeProperty(name));
      };
      card.addEventListener("pointermove", tilt);
      ["pointerleave", "pointerup", "pointercancel"].forEach((name) => card.addEventListener(name, settle));
    };

    const analyze = async (blob) => {
      if (busy || !blob) return;
      busy = true;
      stopCamera();
      showStill(blob);
      scanBox.dataset.state = "analyzing";
      setStatus("loading", `${SPINNER}Reconhecendo a carta…`);
      const slow = setTimeout(() => setStatus("loading", `${SPINNER}Conferindo coleção, raridade e valor…`), 5000);
      try {
        const body = new FormData();
        body.append("image", await shrinkImage(blob, 1600, 0.9), "carta.jpg");
        const response = await fetch(scanForm.action, {
          method: "POST", body, headers: { "X-CSRF-Token": csrfToken(), "X-Scan-Fragment": "1" },
        });
        if (response.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); return; }
        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || data.errors?.image || "Não foi possível reconhecer a carta.");
        }
        resultBox.innerHTML = await response.text();
        scanBox.dataset.state = "result";
        setStatus(null);
        initShowcase(resultBox);
        window.scrollTo({ top: 0, behavior: reduceMotion.matches ? "auto" : "smooth" });
        resultBox.focus({ preventScroll: true });
      } catch (error) {
        const message = error instanceof TypeError ? "Sem conexão com o servidor." : error.message;
        scanBox.dataset.state = "capture";
        setStatus("error", `${escapeHtml(message || "Falha no scan.")}<br>Tente de novo: carta inteira na moldura, de frente, com boa luz e sem reflexo.`);
        startCamera();
      } finally {
        clearTimeout(slow);
        busy = false;
      }
    };

    const restart = () => {
      resultBox.innerHTML = "";
      scanBox.dataset.state = "capture";
      showStill(null);
      setStatus(null);
      window.scrollTo({ top: 0, behavior: "auto" });
      startCamera();
    };

    shutter.addEventListener("click", async () => {
      if (video.videoWidth) analyze(await grabFrame());
    });
    scanBox.querySelectorAll("[data-scan-file]").forEach((input) => input.addEventListener("change", () => {
      const file = input.files?.[0];
      input.value = "";
      if (!file) return;
      if (file.type && !file.type.startsWith("image/")) {
        setStatus("error", "Escolha uma imagem (JPG, PNG ou WEBP).");
        return;
      }
      analyze(file); // a foto é reduzida antes do envio; o servidor valida formato e tamanho
    }));
    scanForm.addEventListener("submit", (event) => event.preventDefault()); // com JS o envio é pelo fetch
    resultBox.addEventListener("click", (event) => {
      if (!event.target.closest("[data-scan-again]")) return;
      event.preventDefault();
      restart();
    });
    document.addEventListener("visibilitychange", () => (document.hidden ? stopCamera() : startCamera()));
    window.addEventListener("pagehide", stopCamera);

    if (scanBox.dataset.state === "result") initShowcase(resultBox);
    else startCamera();
  }

  // ---------- Confirmação de exclusão ----------
  const dialog = document.querySelector("[data-confirm-dialog]");
  document.querySelectorAll("form[data-confirm]").forEach((target) => {
    target.addEventListener("submit", (event) => {
      if (target.dataset.confirmed) return;
      event.preventDefault();
      if (!dialog?.showModal) {
        if (window.confirm(target.dataset.confirm)) { target.dataset.confirmed = "1"; target.submit(); }
        return;
      }
      dialog.querySelector("[data-confirm-text]").textContent = target.dataset.confirm;
      dialog.showModal();
      dialog.addEventListener("close", () => {
        if (dialog.returnValue === "ok") { target.dataset.confirmed = "1"; target.submit(); }
      }, { once: true });
    });
  });
})();
