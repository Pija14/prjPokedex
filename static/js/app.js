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
