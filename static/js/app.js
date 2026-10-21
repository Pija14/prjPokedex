// CardDex — melhorias progressivas. Todas as páginas funcionam sem JavaScript;
// aqui ficam a busca/filtro instantâneos, a prévia da imagem, a confirmação de exclusão e os avisos.
(() => {
  "use strict";

  const normalize = (text) => String(text || "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().trim();
  const MAX_IMAGE_MB = 8;
  const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

  // ---------- Avisos (flash) ----------
  document.querySelectorAll("[data-autohide]").forEach((toast) => {
    setTimeout(() => {
      toast.classList.add("is-leaving");
      setTimeout(() => toast.remove(), 350);
    }, 4000);
  });

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
      regulation_mark: "Regulação", illustrator: "Ilustrador", year: "Ano", card_type: "Tipo de carta", notes: "Observação" };
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
    const markAi = (input, on) => {
      const fieldBox = input.closest(".field");
      fieldBox?.classList.toggle("is-ai", on);
      const label = fieldBox?.querySelector("label");
      if (on && label && !label.querySelector(".ai-chip")) label.insertAdjacentHTML("beforeend", ' <span class="ai-chip">IA</span>');
      if (!on) label?.querySelector(".ai-chip")?.remove();
    };
    // Na edição, os dados já salvos valem como "digitados": a IA só completa os campos vazios.
    if (!auto) AI_FIELDS.forEach((name) => { const input = form.elements[name]; if (input?.value.trim()) input.dataset.userEdited = "1"; });
    AI_FIELDS.forEach((name) => form.elements[name]?.addEventListener("input", (event) => {
      event.target.dataset.userEdited = "1";
      markAi(event.target, false);
    }));

    // Foto do celular (vários MB) vira JPEG de até 1600 px só para a análise; a original é a que fica salva.
    const shrink = async (blob) => {
      try {
        const bitmap = await createImageBitmap(blob, { imageOrientation: "from-image" });
        const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(bitmap.width * scale);
        canvas.height = Math.round(bitmap.height * scale);
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        bitmap.close?.();
        return await new Promise((resolve) => canvas.toBlob((b) => resolve(b || blob), "image/jpeg", 0.85));
      } catch {
        return blob; // navegador sem suporte: envia a original
      }
    };

    const showExtra = (data) => {
      const rows = Object.entries(data.extra || {})
        .filter(([key]) => EXTRA_LABELS[key])
        .map(([key, value]) => `<div><dt>${EXTRA_LABELS[key]}</dt><dd>${escapeHtml(Array.isArray(value) ? value.join(", ") : value)}</dd></div>`);
      extraBox.innerHTML = rows.join("");
      extraBox.hidden = rows.length === 0;
    };

    const fill = (prefill) => {
      let filled = 0;
      AI_FIELDS.forEach((name) => {
        const input = form.elements[name];
        const value = prefill[name];
        if (!input || !value) return;
        if (input.dataset.userEdited && input.value.trim()) return; // não sobrescreve o que a pessoa digitou
        input.value = value;
        input.removeAttribute("aria-invalid");
        markAi(input, true);
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
        body.append("image", await shrink(blob), "carta.jpg");
        const response = await fetch(aiPanel.dataset.aiUrl, { method: "POST", body });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || data.errors?.image || "Não foi possível reconhecer a carta.");
        const filled = fill(data.prefill || {});
        identifiedOnce = true;
        showExtra(data);
        const summary = [data.pokemon_name, data.collection_name, data.card_number && `#${data.card_number}`].filter(Boolean).map(escapeHtml).join(" · ");
        const low = typeof data.confidence === "number" && data.confidence < 0.7;
        setStatus(low ? "warning" : "success",
          `<strong>${summary || "Carta identificada"}</strong><br>${filled ? `${filled} ${filled === 1 ? "campo preenchido" : "campos preenchidos"} pela IA.` : "Nenhum campo novo preenchido."} ${low ? "A IA está em dúvida: confira com atenção." : "Confira os dados"} e informe o valor antes de salvar.`);
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
