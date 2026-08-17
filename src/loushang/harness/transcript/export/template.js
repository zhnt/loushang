(() => {
  const sessionDataElement = document.getElementById("session-data");
  if (!sessionDataElement) {
    document.documentElement.dataset.sessionExport = "missing-data";
    return;
  }

  try {
    const base64 = sessionDataElement.textContent || "";
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    window.loushangSessionData = JSON.parse(new TextDecoder("utf-8").decode(bytes));
    document.documentElement.dataset.sessionExport = "ready";
    const search = document.getElementById("transcript-search");
    const typeFilter = document.getElementById("message-type-filter");
    const count = document.getElementById("transcript-count");
    const messages = Array.from(document.querySelectorAll(".timeline .message"));
    const updateFilter = () => {
      const query = String(search?.value || "").trim().toLowerCase();
      const type = String(typeFilter?.value || "");
      let visible = 0;
      for (const message of messages) {
        const matchesText = !query || String(message.dataset.search || "").includes(query);
        const matchesType = !type || message.dataset.messageType === type;
        const show = matchesText && matchesType;
        message.classList.toggle("hidden", !show);
        if (show) {
          visible += 1;
        }
      }
      if (count) {
        count.textContent = `${visible}/${messages.length} messages`;
      }
    };
    search?.addEventListener("input", updateFilter);
    typeFilter?.addEventListener("change", updateFilter);
    updateFilter();
    for (const block of document.querySelectorAll("pre")) {
      const text = block.textContent || "";
      const looksJson = text.trim().startsWith("{") || text.trim().startsWith("[");
      if (!looksJson) {
        continue;
      }
      block.innerHTML = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/("(?:[^"\\]|\\.)*")(\s*:)?|\b(-?\d+(?:\.\d+)?)\b/g, (match, stringValue, keySuffix, numberValue) => {
          if (stringValue && keySuffix) {
            return `<span class="syntax-key">${stringValue}</span>${keySuffix}`;
          }
          if (stringValue) {
            return `<span class="syntax-string">${stringValue}</span>`;
          }
          if (numberValue) {
            return `<span class="syntax-number">${numberValue}</span>`;
          }
          return match;
        });
    }
  } catch (error) {
    window.loushangSessionDataError = String(error);
    document.documentElement.dataset.sessionExport = "error";
  }
})();
