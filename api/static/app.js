const fileInput = document.getElementById("fileInput");
const maxPagesInput = document.getElementById("maxPages");
const uploadBtn = document.getElementById("uploadBtn");
const pageSelect = document.getElementById("pageSelect");
const pageList = document.getElementById("pageList");
const selectAllBtn = document.getElementById("selectAll");
const selectNoneBtn = document.getElementById("selectNone");
const dragSelectBtn = document.getElementById("dragSelect");
const dragDeselectBtn = document.getElementById("dragDeselect");
const generateBtn = document.getElementById("generateBtn");
const downloadLink = document.getElementById("downloadLink");
const statusEl = document.getElementById("status");
const canvas = document.getElementById("pageCanvas");
const ctx = canvas.getContext("2d");
const resultImage = document.getElementById("resultImage");
const resultThumbs = document.getElementById("resultThumbs");
const resultHint = document.getElementById("resultHint");
const resultPreview = document.querySelector(".result-preview");
const textEditor = document.getElementById("textEditor");
const saveTextBtn = document.getElementById("saveTextBtn");
const clearTextBtn = document.getElementById("clearTextBtn");
const activeTextMeta = document.getElementById("activeTextMeta");
const replaceImageInput = document.getElementById("replaceImageInput");
const replaceModeBtn = document.getElementById("replaceModeBtn");
const clearReplacementsBtn = document.getElementById("clearReplacementsBtn");
const replaceList = document.getElementById("replaceList");

let dragState = {
  active: false,
  startX: 0,
  startY: 0,
  currentX: 0,
  currentY: 0,
  mode: "select",
};

function getCanvasCoords(e) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return {
    x: (e.clientX - rect.left) * scaleX,
    y: (e.clientY - rect.top) * scaleY,
  };
}

const state = {
  sessionId: null,
  pages: [],
  selections: {},
  currentPageIndex: 0,
  imageCache: {},
  resultPages: [],
  rightMode: "preview",
  rightPageIndex: 0,
  dragMode: "select",
  textOverrides: {},
  activeItem: null,
  imageReplacements: {},
  pendingReplaceImage: null,
};

function setStatus(text) {
  statusEl.textContent = text || "";
}

function getOverrideText(pageIndex, itemId) {
  const pageMap = state.textOverrides[pageIndex];
  if (!pageMap) return null;
  return pageMap[itemId] ?? null;
}

function setActiveItem(pageIndex, item) {
  if (!item) {
    state.activeItem = null;
    activeTextMeta.textContent = "点击左侧文字块以编辑";
    textEditor.value = "";
    return;
  }
  state.activeItem = { page_index: pageIndex, item_id: item.id, item };
  const override = getOverrideText(pageIndex, item.id);
  textEditor.value = override !== null ? override : (item.text || "");
  const selected = state.selections[pageIndex] || new Set();
  const flag = selected.has(item.id) ? "已选中" : "未选中";
  const editFlag = override !== null ? "已修改" : "未修改";
  activeTextMeta.textContent = `当前块：${item.id}（${flag}，${editFlag}）`;
}

function renderReplaceList() {
  const pageIndex = state.currentPageIndex;
  const list = state.imageReplacements[pageIndex] || [];
  replaceList.innerHTML = "";
  if (list.length === 0) {
    const empty = document.createElement("div");
    empty.className = "status";
    empty.textContent = "当前页暂无替换";
    replaceList.appendChild(empty);
    return;
  }
  list.forEach((rep) => {
    const row = document.createElement("div");
    row.className = "replace-item";
    const img = document.createElement("img");
    img.src = rep.image_data;
    const meta = document.createElement("span");
    meta.textContent = `位置：${Math.round(rep.x0)},${Math.round(rep.y0)} - ${Math.round(rep.x1)},${Math.round(rep.y1)}`;
    const btn = document.createElement("button");
    btn.className = "secondary";
    btn.textContent = "移除";
    btn.addEventListener("click", () => {
      const arr = state.imageReplacements[pageIndex] || [];
      state.imageReplacements[pageIndex] = arr.filter((item) => item.id !== rep.id);
      renderReplaceList();
      const page = state.pages.find((p) => p.page_index === pageIndex);
      if (page) redrawPage(page);
    });
    row.appendChild(img);
    row.appendChild(meta);
    row.appendChild(btn);
    replaceList.appendChild(row);
  });
}

function getSelectionsPayload() {
  return Object.entries(state.selections).map(([pageIndex, set]) => ({
    page_index: Number(pageIndex),
    selected_ids: Array.from(set),
  }));
}

function pointInPoly(pt, poly) {
  let x = pt[0], y = pt[1];
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1];
    const xj = poly[j][0], yj = poly[j][1];
    const intersect = ((yi > y) !== (yj > y)) &&
      (x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-6) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function redrawPage(page, dragRect = null) {
  const img = state.imageCache[page.page_index];
  if (!img) return;
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0);

  const selected = state.selections[page.page_index] || new Set();
  page.ocr.forEach((item) => {
    if (!item.poly || item.poly.length < 3) return;
    ctx.beginPath();
    item.poly.forEach((pt, idx) => {
      const x = pt[0], y = pt[1];
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    const isActive =
      state.activeItem &&
      state.activeItem.page_index === page.page_index &&
      state.activeItem.item_id === item.id;
    ctx.lineWidth = isActive ? 3 : 2;
    if (isActive) {
      ctx.strokeStyle = "#1c7aa8";
    } else {
      ctx.strokeStyle = selected.has(item.id) ? "#2aa36b" : "#ff5c5c";
    }
    ctx.stroke();
  });

  const replacements = state.imageReplacements[page.page_index] || [];
  replacements.forEach((rep) => {
    const rect = pageRectToCanvas(rep, page);
    ctx.save();
    ctx.fillStyle = "rgba(28, 122, 168, 0.12)";
    ctx.strokeStyle = "#1c7aa8";
    ctx.lineWidth = 2;
    ctx.fillRect(rect.x0, rect.y0, rect.x1 - rect.x0, rect.y1 - rect.y0);
    ctx.strokeRect(rect.x0, rect.y0, rect.x1 - rect.x0, rect.y1 - rect.y0);
    ctx.restore();
  });

  if (dragRect) {
    ctx.save();
    ctx.strokeStyle = "#2aa36b";
    ctx.setLineDash([6, 4]);
    ctx.lineWidth = 2;
    ctx.strokeRect(dragRect.x0, dragRect.y0, dragRect.x1 - dragRect.x0, dragRect.y1 - dragRect.y0);
    ctx.restore();
  }
}

function getItemBounds(item, page) {
  if (item.poly && item.poly.length >= 3) {
    const xs = item.poly.map((p) => p[0]);
    const ys = item.poly.map((p) => p[1]);
    return {
      x0: Math.min(...xs),
      y0: Math.min(...ys),
      x1: Math.max(...xs),
      y1: Math.max(...ys),
    };
  }
  const bbox = item.bbox || {};
  const sx = canvas.width / page.width;
  const sy = canvas.height / page.height;
  return {
    x0: (bbox.x0 || 0) * sx,
    y0: (bbox.y0 || 0) * sy,
    x1: (bbox.x1 || 0) * sx,
    y1: (bbox.y1 || 0) * sy,
  };
}

function canvasRectToPage(rect, page) {
  const sx = page.width / canvas.width;
  const sy = page.height / canvas.height;
  return {
    x0: rect.x0 * sx,
    y0: rect.y0 * sy,
    x1: rect.x1 * sx,
    y1: rect.y1 * sy,
  };
}

function pageRectToCanvas(rect, page) {
  const sx = canvas.width / page.width;
  const sy = canvas.height / page.height;
  return {
    x0: rect.x0 * sx,
    y0: rect.y0 * sy,
    x1: rect.x1 * sx,
    y1: rect.y1 * sy,
  };
}

function renderPage(pageIndex) {
  const page = state.pages.find((p) => p.page_index === pageIndex);
  if (!page) return;
  state.currentPageIndex = pageIndex;
  pageSelect.value = String(pageIndex);
  renderPageButtons();
  syncRightToPage(pageIndex);
  if (!state.activeItem || state.activeItem.page_index !== pageIndex) {
    setActiveItem(null);
  }
  renderReplaceList();

  const img = new Image();
  img.onload = () => {
    state.imageCache[page.page_index] = img;
    redrawPage(page);
  };
  img.src = page.image_url;
}

function populatePageSelect() {
  pageSelect.innerHTML = "";
  state.pages.forEach((page) => {
    const opt = document.createElement("option");
    opt.value = page.page_index;
    opt.textContent = `第 ${page.page_number} 页`;
    pageSelect.appendChild(opt);
  });
}

function renderPageButtons() {
  pageList.innerHTML = "";
  state.pages.forEach((page) => {
    const btn = document.createElement("button");
    btn.className = "page-btn" + (page.page_index === state.currentPageIndex ? " active" : "");
    btn.textContent = `${page.page_number}`;
    btn.addEventListener("click", () => renderPage(page.page_index));
    pageList.appendChild(btn);
  });
}

async function uploadAndPreview() {
  const file = fileInput.files[0];
  if (!file) {
    setStatus("请先选择 PDF 文件");
    return;
  }
  const maxPages = Number(maxPagesInput.value || 5);
  const form = new FormData();
  form.append("file", file);
  setStatus("正在上传并生成预览...");
  downloadLink.style.display = "none";
  resultImage.src = "";
  resultThumbs.innerHTML = "";
  resultHint.style.display = "flex";
  resultPreview.style.display = "none";

  const resp = await fetch(`/api/v1/preview?max_pages=${maxPages}`, {
    method: "POST",
    body: form,
  });

  if (!resp.ok) {
    setStatus("预览失败，请检查文件格式");
    return;
  }
  const data = await resp.json();
  state.sessionId = data.session_id;
  state.pages = data.pages || [];
  state.selections = {};
  state.imageCache = {};
  state.resultPages = [];
  state.rightMode = "preview";
  state.textOverrides = {};
  state.activeItem = null;
  state.imageReplacements = {};
  state.pendingReplaceImage = null;
  textEditor.value = "";
  activeTextMeta.textContent = "点击左侧文字块以编辑";
  replaceList.innerHTML = "";
  replaceImageInput.value = "";

  state.pages.forEach((page) => {
    state.selections[page.page_index] = new Set(page.ocr.map((o) => o.id));
  });

  populatePageSelect();
  if (state.pages.length > 0) {
    renderPage(state.pages[0].page_index);
  }
  renderRightPreview(state.currentPageIndex, state.pages);
  renderRightThumbs(state.pages);
  resultHint.style.display = "none";
  resultPreview.style.display = "flex";
  setStatus(`预览完成：${state.pages.length} 页`);
}

async function generateDocx() {
  if (!state.sessionId) {
    setStatus("请先上传并预览文件");
    return;
  }
  setStatus("正在生成 DOCX...");
  const payload = {
    session_id: state.sessionId,
    selections: getSelectionsPayload(),
    text_overrides: [],
    image_replacements: [],
  };
  Object.entries(state.textOverrides).forEach(([pageIndex, map]) => {
    Object.entries(map).forEach(([itemId, text]) => {
      payload.text_overrides.push({
        page_index: Number(pageIndex),
        item_id: Number(itemId),
        text,
      });
    });
  });
  Object.entries(state.imageReplacements).forEach(([pageIndex, list]) => {
    list.forEach((rep) => {
      payload.image_replacements.push({
        page_index: Number(pageIndex),
        x0: rep.x0,
        y0: rep.y0,
        x1: rep.x1,
        y1: rep.y1,
        image_data: rep.image_data,
      });
    });
  });
  const resp = await fetch("/api/v1/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    setStatus("生成失败，请稍后重试");
    return;
  }
  const data = await resp.json();
  downloadLink.href = data.download_url;
  downloadLink.style.display = "inline-block";
  setStatus(`生成完成：${data.pages} 页`);

  state.resultPages = data.result_pages || [];
  if (state.resultPages.length > 0) {
    state.rightMode = "result";
    resultHint.style.display = "none";
    resultPreview.style.display = "flex";
    renderRightPreview(state.currentPageIndex || state.resultPages[0].page_index, state.resultPages);
    renderRightThumbs(state.resultPages);
  }
}

function renderRightPreview(pageIndex, pages) {
  const page = pages.find((p) => p.page_index === pageIndex);
  if (!page) return;
  if (resultPreview.style.display !== "flex") {
    resultPreview.style.display = "flex";
    resultHint.style.display = "none";
  }
  resultImage.src = page.image_url;
  state.rightPageIndex = pageIndex;
  Array.from(resultThumbs.querySelectorAll("img")).forEach((img) => {
    img.classList.toggle("active", img.dataset.pageIndex === String(pageIndex));
  });
}

function renderRightThumbs(pages) {
  resultThumbs.innerHTML = "";
  pages.forEach((page) => {
    const img = document.createElement("img");
    img.src = page.image_url;
    img.dataset.pageIndex = String(page.page_index);
    img.addEventListener("click", () => renderPage(page.page_index));
    resultThumbs.appendChild(img);
  });
}

resultImage.addEventListener("click", () => {
  if (state.rightPageIndex !== undefined) {
    renderPage(state.rightPageIndex);
  }
});

uploadBtn.addEventListener("click", uploadAndPreview);

pageSelect.addEventListener("change", (e) => {
  const idx = Number(e.target.value);
  renderPage(idx);
});

selectAllBtn.addEventListener("click", () => {
  const page = state.pages.find((p) => p.page_index === state.currentPageIndex);
  if (!page) return;
  state.selections[page.page_index] = new Set(page.ocr.map((o) => o.id));
  redrawPage(page);
});

selectNoneBtn.addEventListener("click", () => {
  const page = state.pages.find((p) => p.page_index === state.currentPageIndex);
  if (!page) return;
  state.selections[page.page_index] = new Set();
  redrawPage(page);
});

saveTextBtn.addEventListener("click", () => {
  if (!state.activeItem) {
    setStatus("请先点击左侧文字块");
    return;
  }
  const pageIndex = state.activeItem.page_index;
  const itemId = state.activeItem.item_id;
  if (!state.textOverrides[pageIndex]) {
    state.textOverrides[pageIndex] = {};
  }
  state.textOverrides[pageIndex][itemId] = textEditor.value;
  setActiveItem(pageIndex, state.activeItem.item);
  setStatus("已保存文本修改，点击生成 DOCX 预览结果");
});

clearTextBtn.addEventListener("click", () => {
  if (!state.activeItem) {
    setStatus("请先点击左侧文字块");
    return;
  }
  const pageIndex = state.activeItem.page_index;
  const itemId = state.activeItem.item_id;
  if (state.textOverrides[pageIndex]) {
    delete state.textOverrides[pageIndex][itemId];
    if (Object.keys(state.textOverrides[pageIndex]).length === 0) {
      delete state.textOverrides[pageIndex];
    }
  }
  textEditor.value = state.activeItem.item.text || "";
  setActiveItem(pageIndex, state.activeItem.item);
  setStatus("已清除该文本修改");
});

replaceImageInput.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    state.pendingReplaceImage = reader.result;
    if (state.dragMode !== "replace") {
      setDragMode("replace");
    }
    setStatus("已选择替换图片，拖拽框选区域");
  };
  reader.readAsDataURL(file);
});

clearReplacementsBtn.addEventListener("click", () => {
  const pageIndex = state.currentPageIndex;
  state.imageReplacements[pageIndex] = [];
  renderReplaceList();
  const page = state.pages.find((p) => p.page_index === pageIndex);
  if (page) redrawPage(page);
});

canvas.addEventListener("click", (e) => {
  const page = state.pages.find((p) => p.page_index === state.currentPageIndex);
  if (!page) return;
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  const x = (e.clientX - rect.left) * scaleX;
  const y = (e.clientY - rect.top) * scaleY;

  const selected = state.selections[page.page_index] || new Set();
  let hit = false;
  for (const item of page.ocr) {
    if (!item.poly || item.poly.length < 3) continue;
    if (pointInPoly([x, y], item.poly)) {
      hit = true;
      setActiveItem(page.page_index, item);
      if (state.dragMode !== "replace") {
        if (selected.has(item.id)) {
          selected.delete(item.id);
        } else {
          selected.add(item.id);
        }
        state.selections[page.page_index] = selected;
      }
      redrawPage(page);
      break;
    }
  }
  if (!hit) {
    setActiveItem(null);
    redrawPage(page);
  }
});

function applyRectSelection(page, rect, mode) {
  const selected = state.selections[page.page_index] || new Set();
  page.ocr.forEach((item) => {
    const bbox = getItemBounds(item, page);
    const intersects = !(bbox.x1 < rect.x0 || bbox.x0 > rect.x1 || bbox.y1 < rect.y0 || bbox.y0 > rect.y1);
    if (!intersects) return;
    if (mode === "deselect") {
      selected.delete(item.id);
    } else {
      selected.add(item.id);
    }
  });
  state.selections[page.page_index] = selected;
  redrawPage(page);
}

canvas.addEventListener("mousedown", (e) => {
  const page = state.pages.find((p) => p.page_index === state.currentPageIndex);
  if (!page) return;
  dragState.active = true;
  const pos = getCanvasCoords(e);
  dragState.startX = pos.x;
  dragState.startY = pos.y;
  dragState.currentX = dragState.startX;
  dragState.currentY = dragState.startY;
  dragState.mode = state.dragMode;
  if (state.dragMode !== "replace" && e.shiftKey) {
    dragState.mode = "deselect";
  }
  e.preventDefault();
});

canvas.addEventListener("mousemove", (e) => {
  if (!dragState.active) return;
  const pos = getCanvasCoords(e);
  dragState.currentX = pos.x;
  dragState.currentY = pos.y;
  const page = state.pages.find((p) => p.page_index === state.currentPageIndex);
  if (!page) return;
  const x0 = Math.min(dragState.startX, dragState.currentX);
  const y0 = Math.min(dragState.startY, dragState.currentY);
  const x1 = Math.max(dragState.startX, dragState.currentX);
  const y1 = Math.max(dragState.startY, dragState.currentY);
  redrawPage(page, { x0, y0, x1, y1 });
  e.preventDefault();
});

canvas.addEventListener("mouseup", (e) => {
  if (!dragState.active) return;
  const page = state.pages.find((p) => p.page_index === state.currentPageIndex);
  if (!page) return;
  const x0 = Math.min(dragState.startX, dragState.currentX);
  const y0 = Math.min(dragState.startY, dragState.currentY);
  const x1 = Math.max(dragState.startX, dragState.currentX);
  const y1 = Math.max(dragState.startY, dragState.currentY);
  dragState.active = false;
  const minDrag = 6;
  if (Math.abs(x1 - x0) < minDrag && Math.abs(y1 - y0) < minDrag) {
    redrawPage(page);
    return;
  }
  if (dragState.mode === "replace") {
    if (!state.pendingReplaceImage) {
      setStatus("请先选择替换图片");
      redrawPage(page);
      return;
    }
    const pageRect = canvasRectToPage({ x0, y0, x1, y1 }, page);
    const rep = {
      id: `${Date.now()}_${Math.random().toString(16).slice(2)}`,
      x0: pageRect.x0,
      y0: pageRect.y0,
      x1: pageRect.x1,
      y1: pageRect.y1,
      image_data: state.pendingReplaceImage,
    };
    if (!state.imageReplacements[page.page_index]) {
      state.imageReplacements[page.page_index] = [];
    }
    state.imageReplacements[page.page_index].push(rep);
    renderReplaceList();
    redrawPage(page);
    return;
  }
  applyRectSelection(page, { x0, y0, x1, y1 }, dragState.mode);
  e.preventDefault();
});

canvas.addEventListener("mouseleave", () => {
  if (!dragState.active) return;
  dragState.active = false;
  const page = state.pages.find((p) => p.page_index === state.currentPageIndex);
  if (page) redrawPage(page);
});

generateBtn.addEventListener("click", generateDocx);

function syncRightToPage(pageIndex) {
  if (state.rightMode === "result") {
    if (!state.resultPages || state.resultPages.length === 0) return;
    const hit = state.resultPages.find((p) => p.page_index === pageIndex);
    if (hit) renderRightPreview(pageIndex, state.resultPages);
    return;
  }
  if (!state.pages || state.pages.length === 0) return;
  const hit = state.pages.find((p) => p.page_index === pageIndex);
  if (hit) renderRightPreview(pageIndex, state.pages);
}

function setDragMode(mode) {
  state.dragMode = mode;
  dragSelectBtn.classList.toggle("active", mode === "select");
  dragDeselectBtn.classList.toggle("active", mode === "deselect");
  replaceModeBtn.classList.toggle("active", mode === "replace");
}

dragSelectBtn.addEventListener("click", () => setDragMode("select"));
dragDeselectBtn.addEventListener("click", () => setDragMode("deselect"));
replaceModeBtn.addEventListener("click", () => {
  if (state.dragMode === "replace") {
    setDragMode("select");
    return;
  }
  if (!state.pendingReplaceImage) {
    setStatus("请先选择替换图片");
  }
  setDragMode("replace");
});

setDragMode("select");
