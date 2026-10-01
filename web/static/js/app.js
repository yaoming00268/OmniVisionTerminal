/* 全能视像解析终端 — Web 前端逻辑 (原生 JS) */
window.__vt_appjs_loaded = true;   // 调试标记: 判断脚本是否实际执行
(function () {
  "use strict";

  var $ = function (sel) { return document.querySelector(sel); };
  var $$ = function (sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); };

  var state = {
    config: {},
    models: {},
    queue: [],
    selectedQueueId: null,
    outputs: [],
    poll: { batch: null, alpha: null, cloud: null, train: null },
    paramsLocked: false,
    queueView: localStorage.getItem("vt_queue_view") || "list",
  };

  /* ---------- 基础工具 ---------- */
  function toast(msg, ms) {
    var el = $("#toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.hidden = true; }, ms || 1800);
  }

  function fmtSize(n) {
    if (n == null) return "";
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB";
    return (n / 1073741824).toFixed(2) + " GB";
  }

  function isDesktop() {
    return !!(window.pywebview && window.pywebview.api);
  }

  function api(path, opts) {
    opts = opts || {};
    var headers = {};
    if (opts.body && !(opts.body instanceof FormData) && typeof opts.body !== "string") {
      opts.body = JSON.stringify(opts.body);
      headers["Content-Type"] = "application/json";
    }
    if (isDesktop()) {
      var method = opts.method || (opts.body ? "POST" : "GET");
      var route = path.indexOf("/api/") === 0 ? path.slice(5) : path;
      var payload = null;
      if (opts.body != null) {
        if (typeof opts.body === "string") {
          try { payload = JSON.parse(opts.body); } catch (e) { payload = opts.body; }
        } else {
          payload = opts.body;
        }
      }
      return window.pywebview.api.invoke(method, route, payload).then(function (r) {
        if (!r || r.ok === false) {
          return { error: (r && r.error) || "请求失败" };
        }
        return r.data;
      });
    }
    return fetch(path, {
      method: opts.method || (opts.body ? "POST" : "GET"),
      headers: headers,
      body: opts.body || undefined,
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; });
    });
  }

  function dataUrlToBlob(dataUrl) {
    var i = dataUrl.indexOf(",");
    var mime = dataUrl.slice(5, i).split(";")[0];
    var bin = atob(dataUrl.slice(i + 1));
    var arr = new Uint8Array(bin.length);
    for (var k = 0; k < bin.length; k++) arr[k] = bin.charCodeAt(k);
    return new Blob([arr], { type: mime || "application/octet-stream" });
  }

  function apiBlob(path) {
    if (isDesktop()) {
      var route = path.indexOf("/api/") === 0 ? path.slice(5) : path;
      return window.pywebview.api.invoke("GET", route, {}).then(function (r) {
        if (!r || r.ok === false) throw new Error((r && r.error) || "获取失败");
        if (r.data_url) return dataUrlToBlob(r.data_url);
        throw new Error("无法获取文件");
      });
    }
    return fetch(path).then(function (resp) {
      if (!resp.ok) throw new Error("fetch failed " + resp.status);
      return resp.blob();
    });
  }

  function downloadBlob(blob, name) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
  }

  function downloadOutput(token, name) {
    if (isDesktop()) {
      window.pywebview.api.invoke("GET", "output/" + token, {}).then(function (r) {
        if (r && r.ok && r.data && r.data.path) {
          toast("已在资源管理器中定位: " + name);
          window.pywebview.api.invoke("POST", "reveal", { path: r.data.path });
        } else {
          toast("输出文件不存在");
        }
      });
      return;
    }
    apiBlob("/api/output/" + token).then(function (blob) {
      downloadBlob(blob, name);
    }).catch(function () { toast("下载失败"); });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function setVal(sel, v) {
    var el = $(sel);
    if (el && v !== undefined && v !== null) el.value = v;
  }
  function setChecked(sel, v) {
    var el = $(sel);
    if (el) el.checked = !!v;
  }

  /* ---------- 初始化 ---------- */
  function init() {
    bindEvents();
    refreshAll();
    applyQueueView();
  }

  function refreshAll() {
    Promise.all([
      api("/api/config"),
      api("/api/models"),
      api("/api/queue"),
    ]).then(function (results) {
      state.config = results[0];
      state.models = results[1].models || {};
      state.queue = results[2].files || [];
      applyConfigToUI();
      renderModelSelect();
      renderQueue();
      if (state.queue.length && !state.selectedQueueId) {
        var firstImg = state.queue.find(function (q) { return q.is_image; });
        if (firstImg) selectQueueItem(firstImg.id);
      }
    }).catch(function (e) {
      toast("初始化失败: " + e.message);
    });
    refreshBgPreview();
  }

  function applyConfigToUI() {
    var c = state.config || {};
    setVal("#scaleRange", c.scale); setVal("#scaleNum", c.scale);
    setVal("#blockRange", c.block_size); setVal("#blockNum", c.block_size);
    setVal("#outFormat", c.output_format);
    setVal("#videoMode", c.video_mode);
    setVal("#interpRatio", c.interp_ratio);
    setChecked("#chkFast", c.use_fast_mode);
    setChecked("#chkCompress", c.use_compression);
    setChecked("#chkCpu", c.use_cpu);
    setChecked("#chkSilent", c.silent_mode);
    setChecked("#chkKeepSlices", c.keep_slices);
    setChecked("#chkCustomRes", c.force_custom_res);
    setVal("#targetWidth", c.target_width);
    setVal("#targetHeight", c.target_height);
    setVal("#sliceDir", c.slice_dir);
    setVal("#outputDir", c.output_dir);
    setVal("#trainDir", c.train_dataset_dir);
    setVal("#trainEpochs", c.train_epochs);
    setVal("#trainBatch", c.train_batch_size);
    setVal("#trainLr", c.train_learning_rate);
    setVal("#trainSaveFreq", c.train_save_freq);
    setVal("#setCloudUrl", c.cloud_server_url);
    setVal("#setCloudKey", c.cloud_api_key);
    setVal("#setPort", c.webui_port);
    setVal("#setServerName", c.webui_server_name);
    setChecked("#setShare", !!c.webui_share);
    setVal("#setImgFormat", c.default_image_format);
    setVal("#setVidFormat", c.default_video_format);
    setVal("#setLaunchMode", c.launcher_default_mode || "ask");
    setChecked("#setQueueThumb", c.show_queue_thumb !== false);
    setChecked("#setFullName", !!c.show_full_filename);
    setChecked("#setPreview", c.show_result_preview !== false);
    var dark = c.webui_theme === "dark";
    setChecked("#setDark", dark);
    document.body.dataset.theme = dark ? "dark" : "light";
  }

  /* ---------- 模型 ---------- */
  function modelOrder() {
    var order = state.config.model_order || [];
    var names = Object.keys(state.models);
    var sorted = order.filter(function (n) { return names.indexOf(n) >= 0; });
    names.forEach(function (n) {
      if (sorted.indexOf(n) < 0) sorted.push(n);
    });
    return sorted;
  }

  function renderModelSelect() {
    var sel = $("#modelChoice");
    sel.innerHTML = "";
    modelOrder().forEach(function (name) {
      var opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      sel.appendChild(opt);
    });
    setVal("#modelChoice", state.config.model_choice || "anime_6B");
    var sel2 = $("#setDefaultModel");
    sel2.innerHTML = "";
    Object.keys(state.models).forEach(function (name) {
      var opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      sel2.appendChild(opt);
    });
    setVal("#setDefaultModel", state.config.model_choice || "anime_6B");
    updateModelDesc();
  }

  function updateModelDesc() {
    var name = $("#modelChoice").value;
    $("#modelDesc").textContent = state.models[name] || "本地模型。";
  }

  /* ---------- 模型库弹窗 ---------- */
  var modelLibCache = [];

  function openModelLib() {
    $("#modelLibMask").hidden = false;
    api("/api/model_library").then(function (r) {
      modelLibCache = r.models || [];
      renderModelLib();
    }).catch(function () { toast("模型库加载失败"); });
  }

  function renderModelLib() {
    var list = $("#modelLibList");
    list.innerHTML = "";
    var locals = modelLibCache.filter(function (m) { return !m.builtin; });
    $("#modelLibTip").textContent = "内置 " + (modelLibCache.length - locals.length) +
      " 个 · 本地 " + locals.length + " 个";
    modelLibCache.forEach(function (m, idx) {
      var row = document.createElement("div");
      row.className = "model-lib-row" + (m.builtin ? " builtin" : "");
      var nameEl = document.createElement("span");
      nameEl.className = "model-lib-name";
      nameEl.textContent = m.name + (m.builtin ? " (内置)" : "");
      nameEl.title = m.desc;
      row.appendChild(nameEl);
      var sizeEl = document.createElement("span");
      sizeEl.className = "model-lib-size";
      sizeEl.textContent = m.size ? fmtSize(m.size) : "";
      row.appendChild(sizeEl);
      var ops = document.createElement("span");
      ops.className = "model-lib-ops";
      if (!m.builtin) {
        var up = document.createElement("button");
        up.textContent = "上移";
        up.className = "mini-btn";
        up.disabled = idx === 0;
        up.addEventListener("click", function () { moveModel(idx, -1); });
        var down = document.createElement("button");
        down.textContent = "下移";
        down.className = "mini-btn";
        down.disabled = idx === modelLibCache.length - 1;
        down.addEventListener("click", function () { moveModel(idx, 1); });
        var ren = document.createElement("button");
        ren.textContent = "重命名";
        ren.className = "mini-btn";
        ren.addEventListener("click", function () { renameModel(m.name); });
        var del = document.createElement("button");
        del.textContent = "删除";
        del.className = "mini-btn danger";
        del.addEventListener("click", function () { deleteModel(m.name); });
        ops.appendChild(up);
        ops.appendChild(down);
        ops.appendChild(ren);
        ops.appendChild(del);
      }
      row.appendChild(ops);
      list.appendChild(row);
    });
  }

  function saveModelOrder() {
    var order = modelLibCache.map(function (m) { return m.name; });
    state.config.model_order = order;
    return api("/api/model/order", { method: "POST", body: { order: order } });
  }

  function moveModel(idx, delta) {
    var j = idx + delta;
    if (j < 0 || j >= modelLibCache.length) return;
    var tmp = modelLibCache[idx];
    modelLibCache[idx] = modelLibCache[j];
    modelLibCache[j] = tmp;
    saveModelOrder().then(function () { renderModelLib(); });
  }

  function renameModel(oldName) {
    var newName = prompt("输入新名称(仅名称,不含 .pth):", oldName);
    if (!newName || newName === oldName) return;
    api("/api/model/rename", { method: "POST", body: { old: oldName, new: newName } }).then(function (r) {
      if (r.ok) {
        toast("已重命名");
        var idx = modelLibCache.findIndex(function (m) { return m.name === oldName; });
        if (idx >= 0) modelLibCache[idx].name = newName;
        renderModelLib();
        refreshModelChoice();
      } else {
        toast(r.error || "重命名失败");
      }
    });
  }

  function deleteModel(name) {
    if (!window.confirm("确定删除本地模型 [" + name + "] ?\n删除后无法恢复。")) return;
    api("/api/model/delete", { method: "POST", body: { name: name } }).then(function (r) {
      if (r.ok) {
        toast("已删除");
        modelLibCache = modelLibCache.filter(function (m) { return m.name !== name; });
        renderModelLib();
        refreshModelChoice();
      } else {
        toast(r.error || "删除失败");
      }
    });
  }

  function importModel(file) {
    if (isDesktop()) {
      desktopUpload("model", file).then(function (r) {
        if (r && r.ok) {
          toast("模型已导入: " + (r.name || file.name));
          refreshAll();
          openModelLib();
        } else {
          toast((r && r.error) || "导入失败");
        }
      });
      return;
    }
    var fd = new FormData();
    fd.append("file", file);
    api("/api/model/import", { method: "POST", body: fd }).then(function (r) {
      if (r.ok) {
        toast("模型已导入: " + r.name);
        refreshAll();
        openModelLib();
      } else {
        toast(r.error || "导入失败");
      }
    });
  }

  function refreshModelChoice() {
    api("/api/models").then(function (r) {
      state.models = r.models || {};
      renderModelSelect();
      refreshAll();
    });
  }

  /* ---------- 队列 ---------- */
  function renderQueue() {
    var list = $("#queueList");
    list.innerHTML = "";
    var isGrid = state.queueView === "grid";
    list.classList.toggle("grid-view", isGrid);
    var head = $("#queueCount");
    if (!state.queue.length) {
      head.textContent = "队列为空";
    } else {
      var imgs = state.queue.filter(function (q) { return q.is_image; }).length;
      head.textContent = "共 " + state.queue.length + " 个文件 (图片 " + imgs + " 个)";
    }
    // 网格视图下强制显示缩略图；列表视图尊重用户开关配置
    var showThumb = isGrid || (state.config.show_queue_thumb !== false);
    var fullName = !!state.config.show_full_filename;
    state.queue.forEach(function (item) {
      var cell = document.createElement("div");
      cell.className = "weui-cell queue-item";
      cell.dataset.id = item.id;
      cell.tabIndex = 0;
      if (showThumb && (item.is_image || item.is_video)) {
        var thumb = document.createElement("img");
        thumb.className = "queue-item-thumb";
        thumb.alt = item.name;
        var thumbUrl = "/api/file/" + item.id + "?thumb=1";
        if (isDesktop()) {
          window.pywebview.api.invoke("GET", "file/" + item.id + "?thumb=1", {}).then(function (r) {
            if (r && r.ok && r.data_url) thumb.src = r.data_url;
            else thumb.src = thumbUrl;
          }).catch(function () {
            thumb.src = thumbUrl;
          });
        } else {
          thumb.src = thumbUrl;
        }
        // 优雅降级占位图，彻底杜绝裂图
        thumb.onerror = function () {
          this.onerror = null;
          this.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 40 40'%3E%3Crect width='40' height='40' fill='%23e9ebee' rx='8'/%3E%3Ctext x='50%25' y='55%25' font-size='10' fill='%238a8f99' text-anchor='middle' dominant-baseline='middle'%3E" + (item.is_video ? "%E8%A7%86%E9%A2%91" : "%E5%9B%BE%E7%89%87") + "%3C/text%3E%3C/svg%3E";
        };
        cell.appendChild(thumb);
      }
      var bd = document.createElement("div");
      bd.className = "weui-cell__bd";
      var nameDiv = document.createElement("div");
      nameDiv.className = "queue-item-name";
      nameDiv.textContent = fullName ? item.name : truncateName(item.name);
      nameDiv.title = item.name;
      bd.appendChild(nameDiv);
      var metaDiv = document.createElement("div");
      metaDiv.className = "queue-item-meta";
      metaDiv.textContent = fmtSize(item.size) + (item.is_video ? " · 视频" : item.is_image ? " · 图片" : "");
      bd.appendChild(metaDiv);
      cell.appendChild(bd);
      var del = document.createElement("span");
      del.className = "queue-item-del";
      del.textContent = "✕";
      del.title = "移除";
      del.addEventListener("click", function (ev) {
        ev.stopPropagation();
        removeQueueItem(item.id);
      });
      cell.appendChild(del);
      cell.addEventListener("click", function () { selectQueueItem(item.id); });
      list.appendChild(cell);
    });
    renderSourceSelects();
  }

  function truncateName(name) {
    if (name.length <= 26) return name;
    return name.slice(0, 24) + "…";
  }

  function selectQueueItem(id) {
    state.selectedQueueId = id;
    $$(".queue-list .queue-item").forEach(function (el) {
      el.style.background = el.dataset.id === id ? "var(--active)" : "";
    });
    var item = state.queue.find(function (q) { return q.id === id; });
    if (item && item.is_image) {
      var s = parseFloat($("#scaleNum").value) || 4;
      if (item.width && item.height) {
        setVal("#targetWidth", Math.round(item.width * s));
        setVal("#targetHeight", Math.round(item.height * s));
      } else {
        api("/api/inspect?id=" + id).then(function (info) {
          if (info && info.width && info.height) {
            item.width = info.width;
            item.height = info.height;
            setVal("#targetWidth", Math.round(info.width * s));
            setVal("#targetHeight", Math.round(info.height * s));
          }
        });
      }
    }
  }

  function removeQueueItem(id) {
    api("/api/queue?id=" + encodeURIComponent(id), { method: "DELETE" }).then(function (resp) {
      state.queue = resp.files || [];
      if (state.selectedQueueId === id) state.selectedQueueId = null;
      renderQueue();
    });
  }

  function desktopUpload(kind, file) {
    /* kind: queue | model | bg — 桌面模式: 优先本地路径直注册, 否则 base64 上传 */
    function viaPath() {
      if (kind === "queue") {
        return api("/api/queue", { method: "POST", body: { paths: [file.path] } });
      }
      if (kind === "model") {
        return window.pywebview.api.invoke("POST", "model/import", { path: file.path });
      }
      return window.pywebview.api.invoke("POST", "bg", { path: file.path });
    }
    function viaB64() {
      return new Promise(function (resolve) {
        var rd = new FileReader();
        rd.onload = function () {
          var b64 = String(rd.result).split(",")[1] || "";
          var p;
          if (kind === "queue") {
            p = window.pywebview.api.invoke("POST", "queue", { uploads: [{ name: file.name, b64: b64 }] });
          } else if (kind === "model") {
            p = window.pywebview.api.invoke("POST", "model/import", { name: file.name, b64: b64 });
          } else {
            p = window.pywebview.api.invoke("POST", "bg", { name: file.name, b64: b64 });
          }
          resolve(p);
        };
        rd.onerror = function () { resolve({ ok: false, error: "读取文件失败" }); };
        rd.readAsDataURL(file);
      });
    }
    if (file && file.path) return viaPath();
    return viaB64();
  }

  function addFiles(fileList) {
    if (isDesktop()) {
      var files = Array.prototype.slice.call(fileList).filter(function (f) { return f; });
      if (!files.length) return;
      var localPaths = files.filter(function (f) { return f.path; }).map(function (f) { return f.path; });
      var others = files.filter(function (f) { return !f.path; });
      var chain = Promise.resolve();
      if (localPaths.length) {
        chain = chain.then(function () {
          return api("/api/queue", { method: "POST", body: { paths: localPaths } });
        });
      }
      others.forEach(function (f) {
        chain = chain.then(function () { return desktopUpload("queue", f); });
      });
      chain.then(function (resp) {
        var added = resp && resp.added != null ? resp.added : (resp && resp.data ? resp.data.added : 0);
        return api("/api/queue").then(function (r2) {
          state.queue = r2.files || [];
          renderQueue();
          if (state.queue.length && !state.selectedQueueId) {
            var firstImg = state.queue.find(function (q) { return q.is_image; });
            if (firstImg) selectQueueItem(firstImg.id);
          }
          if (added > 0) toast("已添加 " + added + " 个文件");
          else toast("未找到有效文件");
        });
      }).catch(function () { toast("添加失败"); });
      return;
    }
    var fd = new FormData();
    var count = 0;
    Array.prototype.forEach.call(fileList, function (f) { fd.append("file", f); count++; });
    if (!count) return;
    api("/api/queue", { method: "POST", body: fd }).then(function (resp) {
      state.queue = resp.files || [];
      renderQueue();
      if (state.queue.length && !state.selectedQueueId) {
        var firstImg = state.queue.find(function (q) { return q.is_image; });
        if (firstImg) selectQueueItem(firstImg.id);
      }
      toast("已添加 " + resp.added + " 个文件");
    }).catch(function () { toast("上传失败"); });
  }

  function addLocalPaths() {
    var text = prompt("输入本地文件或目录的绝对路径(多个用 | 或换行分隔):", "");
    if (!text) return;
    var paths = text.split(/[\n|]+/).map(function (s) { return s.trim(); }).filter(Boolean);
    if (!paths.length) return;
    api("/api/queue", { method: "POST", body: { paths: paths } }).then(function (resp) {
      state.queue = resp.files || [];
      renderQueue();
      if (state.queue.length && !state.selectedQueueId) {
        var firstImg = state.queue.find(function (q) { return q.is_image; });
        if (firstImg) selectQueueItem(firstImg.id);
      }
      if (resp.added) toast("已添加 " + resp.added + " 个文件");
      else toast("未找到有效文件");
    });
  }

  function renderSourceSelects() {
    var imgs = state.queue.filter(function (q) { return q.is_image; });
    ["#cropSource", "#compressSource"].forEach(function (sel) {
      var el = $(sel);
      var prev = el.value;
      el.innerHTML = "";
      if (!imgs.length) {
        var opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "队列中没有图片";
        el.appendChild(opt);
      }
      imgs.forEach(function (q) {
        var opt = document.createElement("option");
        opt.value = q.id;
        opt.textContent = q.name;
        el.appendChild(opt);
      });
      if (prev && imgs.some(function (q) { return q.id === prev; })) el.value = prev;
    });
  }

  function applyQueueView() {
    $("#viewList").classList.toggle("active", state.queueView === "list");
    $("#viewGrid").classList.toggle("active", state.queueView === "grid");
    var list = $("#queueList");
    if (list) list.classList.toggle("grid-view", state.queueView === "grid");
  }

  var isSyncingDimensions = false;

  function syncScaleToDimensions(scaleVal) {
    if (isSyncingDimensions) return;
    isSyncingDimensions = true;
    try {
      var scale = parseFloat(scaleVal) || 4;
      var activeId = state.selectedQueueId;
      var firstImg = (activeId && state.queue.find(function (q) { return q.id === activeId && q.is_image; })) ||
                     state.queue.find(function (q) { return q.is_image; });
      if (firstImg) {
        if (firstImg.width && firstImg.height) {
          var nw = Math.round(firstImg.width * scale);
          var nh = Math.round(firstImg.height * scale);
          setVal("#targetWidth", nw);
          setVal("#targetHeight", nh);
        } else {
          api("/api/inspect?id=" + firstImg.id).then(function (info) {
            if (info && info.width && info.height) {
              firstImg.width = info.width;
              firstImg.height = info.height;
              var nw = Math.round(info.width * scale);
              var nh = Math.round(info.height * scale);
              setVal("#targetWidth", nw);
              setVal("#targetHeight", nh);
            }
          });
        }
      } else {
        var curW = parseInt($("#targetWidth").value, 10) || 1920;
        var curH = parseInt($("#targetHeight").value, 10) || 1080;
        var baseRatio = curW / curH;
        var nw = Math.round(480 * scale * (baseRatio >= 1 ? 1 : baseRatio));
        var nh = Math.round(nw / baseRatio);
        setVal("#targetWidth", nw);
        setVal("#targetHeight", nh);
      }
    } finally {
      isSyncingDimensions = false;
    }
  }

  function syncDimensionToScale(changedDim) {
    if (isSyncingDimensions) return;
    isSyncingDimensions = true;
    try {
      var activeId = state.selectedQueueId;
      var firstImg = (activeId && state.queue.find(function (q) { return q.id === activeId && q.is_image; })) ||
                     state.queue.find(function (q) { return q.is_image; });
      var isCustom = $("#chkCustomRes").checked;

      function updateWithDim(imgW, imgH) {
        if (changedDim === "width") {
          var w = parseInt($("#targetWidth").value, 10);
          if (!w || w <= 0) return;
          var s = Math.round((w / imgW) * 100) / 100;
          s = Math.min(64, Math.max(1, s));
          $("#scaleRange").value = s;
          $("#scaleNum").value = s;
          if (!isCustom) {
            setVal("#targetHeight", Math.round(imgH * s));
          }
        } else if (changedDim === "height") {
          var h = parseInt($("#targetHeight").value, 10);
          if (!h || h <= 0) return;
          var s = Math.round((h / imgH) * 100) / 100;
          s = Math.min(64, Math.max(1, s));
          $("#scaleRange").value = s;
          $("#scaleNum").value = s;
          if (!isCustom) {
            setVal("#targetWidth", Math.round(imgW * s));
          }
        }
      }

      if (firstImg) {
        if (firstImg.width && firstImg.height) {
          updateWithDim(firstImg.width, firstImg.height);
        } else {
          api("/api/inspect?id=" + firstImg.id).then(function (info) {
            if (info && info.width && info.height) {
              firstImg.width = info.width;
              firstImg.height = info.height;
              updateWithDim(info.width, info.height);
            }
          });
        }
      } else {
        if (!isCustom) {
          if (changedDim === "width") {
            var w = parseInt($("#targetWidth").value, 10);
            if (w && w > 0) {
              var s = Math.round((w / 1920) * 100) / 100;
              s = Math.min(64, Math.max(1, s));
              $("#scaleRange").value = s;
              $("#scaleNum").value = s;
              setVal("#targetHeight", Math.round(w * (9 / 16)));
            }
          } else {
            var h = parseInt($("#targetHeight").value, 10);
            if (h && h > 0) {
              var s = Math.round((h / 1080) * 100) / 100;
              s = Math.min(64, Math.max(1, s));
              $("#scaleRange").value = s;
              $("#scaleNum").value = s;
              setVal("#targetWidth", Math.round(h * (16 / 9)));
            }
          }
        }
      }
    } finally {
      isSyncingDimensions = false;
    }
  }

  function bindSliderSpin(rangeSel, numSel) {
    var range = $(rangeSel), num = $(numSel);
    var handleRange = function () {
      num.value = range.value;
      if (rangeSel === "#scaleRange") syncScaleToDimensions(range.value);
    };
    range.addEventListener("input", handleRange);
    range.addEventListener("change", handleRange);

    var handleNum = function () {
      var v = parseFloat(num.value);
      if (isNaN(v)) return;
      v = Math.min(parseFloat(num.max), Math.max(parseFloat(num.min), v));
      range.value = v;
      if (numSel === "#scaleNum") syncScaleToDimensions(v);
    };
    num.addEventListener("input", handleNum);
    num.addEventListener("change", handleNum);
  }

  /* ---------- 参数锁定 ---------- */
  function applyParams() {
    var c = collectConfig();
    Object.keys(c).forEach(function (k) { state.config[k] = c[k]; });
    api("/api/config", { method: "POST", body: c }).then(function () {
      state.paramsLocked = true;
      $("#btnApplyParams").textContent = "修改参数";
      $("#paramLockTip").hidden = false;
      $("#scaleRange").disabled = true; $("#scaleNum").disabled = true;
      $("#blockRange").disabled = true; $("#blockNum").disabled = true;
      toast("参数已应用并锁定");
    }).catch(function () { toast("保存失败"); });
  }

  function unlockParams() {
    state.paramsLocked = false;
    $("#btnApplyParams").textContent = "应用参数";
    $("#paramLockTip").hidden = true;
    $("#scaleRange").disabled = false; $("#scaleNum").disabled = false;
    $("#blockRange").disabled = false; $("#blockNum").disabled = false;
  }

  function syncLockUI() {
    if (state.paramsLocked) {
      $("#btnApplyParams").textContent = "修改参数";
      $("#paramLockTip").hidden = false;
      $("#scaleRange").disabled = true; $("#scaleNum").disabled = true;
      $("#blockRange").disabled = true; $("#blockNum").disabled = true;
    } else {
      $("#btnApplyParams").textContent = "应用参数";
      $("#paramLockTip").hidden = true;
      $("#scaleRange").disabled = false; $("#scaleNum").disabled = false;
      $("#blockRange").disabled = false; $("#blockNum").disabled = false;
    }
  }

  /* ---------- 配置收集与保存 ---------- */
  function collectConfig() {
    var c = {};
    c.scale = parseFloat($("#scaleNum").value) || 4;
    c.block_size = parseInt($("#blockNum").value, 10) || 1000;
    c.output_format = $("#outFormat").value;
    c.video_mode = $("#videoMode").value;
    c.interp_ratio = parseInt($("#interpRatio").value, 10) || 2;
    c.use_fast_mode = $("#chkFast").checked;
    c.use_compression = $("#chkCompress").checked;
    c.use_cpu = $("#chkCpu").checked;
    c.silent_mode = $("#chkSilent").checked;
    c.keep_slices = $("#chkKeepSlices").checked;
    c.force_custom_res = $("#chkCustomRes").checked;
    c.target_width = parseInt($("#targetWidth").value, 10) || 1920;
    c.target_height = parseInt($("#targetHeight").value, 10) || 1080;
    c.slice_dir = $("#sliceDir").value.trim();
    c.output_dir = $("#outputDir").value.trim();
    c.model_choice = $("#modelChoice").value;
    c.train_dataset_dir = $("#trainDir").value.trim();
    c.train_epochs = parseInt($("#trainEpochs").value, 10) || 100;
    c.train_batch_size = parseInt($("#trainBatch").value, 10) || 4;
    c.train_learning_rate = parseFloat($("#trainLr").value) || 0.0001;
    c.train_save_freq = parseInt($("#trainSaveFreq").value, 10) || 10;
    return c;
  }

  function saveWorkbenchConfig() {
    var c = collectConfig();
    Object.keys(c).forEach(function (k) { state.config[k] = c[k]; });
    return api("/api/config", { method: "POST", body: c });
  }

  /* ---------- 任务启动与进度轮询 ---------- */
  var currentJobType = null;

  function startJob(type, modeLabel) {
    if (!state.queue.length) { toast("队列为空，请先添加文件"); return; }
    setStartButtons(true);
    saveWorkbenchConfig().then(function () {
      return api("/api/job/start", { method: "POST", body: { type: type } });
    }).then(function () {
      currentJobType = type;
      $("#btnPause").hidden = false;
      $("#btnPause").textContent = "暂停";
      var btnStop = $("#btnStop");
      if (btnStop) btnStop.hidden = false;
      toast(modeLabel + " 任务已启动");
      beginPoll(type, { logBox: "#logBox", bar: "#progressBar", pct: "#progressPct", outputs: "#outputsList" });
    }).catch(function (e) {
      toast(e && e.error ? e.error : "启动失败");
      setStartButtons(false);
    });
  }

  function setStartButtons(disabled) {
    ["#btnStartBatch", "#btnStartAlpha", "#btnStartCloud", "#btnTrain"].forEach(function (sel) {
      var el = $(sel);
      if (el) el.disabled = disabled;
    });
  }

  function controlJob(action) {
    var type = currentJobType || "batch";
    if (action === "stop") {
      var btnStop = $("#btnStop");
      if (btnStop) btnStop.disabled = true;
      toast("正在中止任务...");
    }
    api("/api/job/control", { method: "POST", body: { type: type, action: action } }).then(function (r) {
      if (r && (r.ok || r.status === 200)) {
        if (action === "stop") {
          toast("已下达中止指令");
        } else {
          $("#btnPause").textContent = action === "pause" ? "继续" : "暂停";
        }
      } else {
        toast((r && r.error) || "操作失败");
        var btnStop = $("#btnStop");
        if (btnStop) btnStop.disabled = false;
      }
    }).catch(function (e) {
      toast("操作失败: " + (e && e.message ? e.message : e));
      var btnStop = $("#btnStop");
      if (btnStop) btnStop.disabled = false;
    });
  }

  function beginPoll(type, ui) {
    var poll = state.poll[type];
    if (poll) clearInterval(poll);
    var since = 0;
    $(ui.logBox).textContent = "";
    setBar(ui.bar, ui.pct, 0);
    state.outputs = [];
    renderOutputs(ui.outputs, []);
    hidePreview();
    var tick = function () {
      api("/api/job/status?type=" + type + "&since=" + since).then(function (payload) {
        if (payload.idle) { return; }
        (payload.logs || []).forEach(function (l) {
          since = Math.max(since, l.seq);
          appendLog(ui.logBox, l.text);
        });
        setBar(ui.bar, ui.pct, payload.progress || 0);
        if (payload.outputs) {
          renderOutputs(ui.outputs, payload.outputs);
        }
        if (payload.paused !== undefined) {
          $("#btnPause").textContent = payload.paused ? "继续" : "暂停";
        }
        renderPreview(payload.preview, payload.done && !payload.running);
        if (payload.done && !payload.running) {
          clearInterval(state.poll[type]);
          state.poll[type] = null;
          setStartButtons(false);
          $("#btnPause").hidden = true;
          var btnStop = $("#btnStop");
          if (btnStop) btnStop.hidden = true;
          currentJobType = null;
          if (payload.error) toast("任务失败: " + payload.error, 3000);
          else if (payload.stopped) toast("任务已中止", 2000);
          else toast("任务完成", 2000);
        }
      }).catch(function () { /* 网络抖动忽略 */ });
    };
    tick();
    state.poll[type] = setInterval(tick, 800);
  }

  function setBar(barSel, pctSel, v) {
    $(barSel).style.width = v + "%";
    $(pctSel).textContent = v + "%";
  }

  function appendLog(boxSel, text) {
    var box = $(boxSel);
    var nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    var line = document.createElement("div");
    line.textContent = text;
    box.appendChild(line);
    if (nearBottom) box.scrollTop = box.scrollHeight;
  }

  function renderOutputs(boxSel, outputs) {
    var box = $(boxSel);
    box.innerHTML = "";
    outputs.forEach(function (o) {
      var item = document.createElement("div");
      item.className = "output-item";
      var link = document.createElement("a");
      link.href = "javascript:void(0)";
      link.textContent = o.name + " (" + fmtSize(o.size) + ")";
      link.addEventListener("click", function () { downloadOutput(o.id, o.name); });
      item.appendChild(link);
      box.appendChild(item);
    });
  }

  /* ---------- 图片预览(设置开启时) ---------- */
  function renderPreview(preview, isDone) {
    if (!preview || !preview.src || !preview.dst) return;
    if (state.config.show_result_preview === false) return;
    if (isDone && !state.config.show_result_preview) return;
    var pair = $("#previewPair");
    if (pair.hidden) pair.hidden = false;
    var now = Date.now();
    if ($("#previewSrc").dataset.t !== String(preview.t)) {
      $("#previewSrc").src = preview.src;
      $("#previewSrc").dataset.t = preview.t;
    }
    if ($("#previewDst").dataset.t !== String(preview.t)) {
      $("#previewDst").src = preview.dst;
      $("#previewDst").dataset.t = preview.t;
    }
  }

  function hidePreview() {
    $("#previewPair").hidden = true;
    $("#previewSrc").removeAttribute("src");
    $("#previewDst").removeAttribute("src");
    $("#previewSrc").dataset.t = "";
    $("#previewDst").dataset.t = "";
  }

  function openOutputDir() {
    api("/api/open_dir", { method: "POST", body: {} }).then(function () {
      toast("已打开输出文件夹");
    }).catch(function () { toast("打开失败"); });
  }

  /* ---------- 快捷分辨率 ---------- */
  function applyPreset(w, h) {
    $("#chkCustomRes").checked = true;
    $("#targetWidth").value = w;
    $("#targetHeight").value = h;
    var activeId = state.selectedQueueId;
    var firstImg = (activeId && state.queue.find(function (q) { return q.id === activeId && q.is_image; })) ||
                   state.queue.find(function (q) { return q.is_image; });
    if (!firstImg) { toast("队列无图片，仅设置目标尺寸"); return; }
    function applyWithDim(imgW, imgH) {
      var s = Math.min(w / imgW, h / imgH);
      s = Math.round(s * 100) / 100;
      s = Math.min(64, Math.max(1, s));
      $("#scaleRange").value = s;
      $("#scaleNum").value = s;
      toast("已按 " + w + "×" + h + " 锁定画幅，倍率 " + s);
    }
    if (firstImg.width && firstImg.height) {
      applyWithDim(firstImg.width, firstImg.height);
    } else {
      api("/api/inspect?id=" + firstImg.id).then(function (info) {
        if (info && info.width && info.height) {
          firstImg.width = info.width;
          firstImg.height = info.height;
          applyWithDim(info.width, info.height);
        }
      });
    }
  }

  /* ---------- 裁切画布 ---------- */
  var crop = { img: null, scale: 1, rect: null, dragging: false, startX: 0, startY: 0 };

  function loadCropImage(id) {
    if (!id) { clearCrop(); return; }
    apiBlob("/api/file/" + id).then(function (blob) {
      var url = URL.createObjectURL(blob);
      var img = new Image();
      img.onload = function () {
        crop.img = img;
        var canvas = $("#cropCanvas");
        var maxW = Math.min(640, canvas.parentElement.clientWidth - 20);
        var maxH = 480;
        crop.scale = Math.min(maxW / img.width, maxH / img.height, 1);
        canvas.width = Math.round(img.width * crop.scale);
        canvas.height = Math.round(img.height * crop.scale);
        crop.rect = null;
        $("#cropHint").textContent = img.width + " × " + img.height + " — 按住鼠标框选区域";
        drawCrop();
        URL.revokeObjectURL(url);
      };
      img.src = url;
    }).catch(function () { toast("图片载入失败"); });
  }

  function clearCrop() {
    crop.img = null; crop.rect = null;
    var canvas = $("#cropCanvas");
    var ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    $("#cropHint").textContent = "从队列选择图片后载入，按住鼠标框选区域";
  }

  function drawCrop() {
    var canvas = $("#cropCanvas");
    var ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!crop.img) return;
    ctx.drawImage(crop.img, 0, 0, canvas.width, canvas.height);
    if (crop.rect) {
      ctx.strokeStyle = "#07c160";
      ctx.lineWidth = 2;
      ctx.strokeRect(crop.rect.x, crop.rect.y, crop.rect.w, crop.rect.h);
      ctx.fillStyle = "rgba(7,193,96,0.15)";
      ctx.fillRect(crop.rect.x, crop.rect.y, crop.rect.w, crop.rect.h);
    }
  }

  function canvasPos(ev) {
    var canvas = $("#cropCanvas");
    var r = canvas.getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  }

  function bindCropCanvas() {
    var canvas = $("#cropCanvas");
    canvas.addEventListener("mousedown", function (ev) {
      if (!crop.img) return;
      var p = canvasPos(ev);
      crop.dragging = true;
      crop.startX = p.x; crop.startY = p.y;
      crop.rect = { x: p.x, y: p.y, w: 0, h: 0 };
    });
    canvas.addEventListener("mousemove", function (ev) {
      if (!crop.dragging || !crop.img) return;
      var p = canvasPos(ev);
      var x = Math.min(crop.startX, p.x), y = Math.min(crop.startY, p.y);
      crop.rect = { x: x, y: y, w: Math.abs(p.x - crop.startX), h: Math.abs(p.y - crop.startY) };
      drawCrop();
    });
    window.addEventListener("mouseup", function () {
      crop.dragging = false;
    });
  }

  function saveCrop(mode) {
    var id = $("#cropSource").value;
    if (!id || !crop.rect || crop.rect.w < 4 || crop.rect.h < 4) {
      toast("请先框选裁切区域"); return;
    }
    var body = {
      id: id,
      x: Math.round(crop.rect.x / crop.scale),
      y: Math.round(crop.rect.y / crop.scale),
      w: Math.round(crop.rect.w / crop.scale),
      h: Math.round(crop.rect.h / crop.scale),
      ext: $("#cropExt").value,
      mode: mode,
    };
    if (mode === "copy") {
      body.save_dir = $("#cropSaveDir").value.trim();
    }
    if (mode === "replace") {
      if (!window.confirm("确定用裁切结果覆盖原文件?\n原文件将被替换,无法恢复。")) return;
    }
    api("/api/crop", { method: "POST", body: body }).then(function (resp) {
      if (resp.id) {
        toast(mode === "replace" ? "已替换原文件" : "已保存副本: " + resp.name);
        if (mode === "replace") {
          refreshAll();
        } else {
          downloadOutput(resp.id, resp.name);
        }
        showCropResult(resp.id, resp.name);
      } else {
        toast(resp.error || "裁切失败");
      }
    });
  }

  function showCropResult(token, name) {
    var img = $("#cropResult");
    var box = $("#cropResultBox");
    box.hidden = false;
    img.hidden = false;
    $("#cropResultCap").textContent = "裁切结果: " + name;
    if (isDesktop()) {
      window.pywebview.api.invoke("GET", "output/" + token, {}).then(function (r) {
        if (r && r.ok && r.data_url) img.src = r.data_url;
        else { img.hidden = true; box.hidden = true; }
      });
    } else {
      img.src = "/api/preview/" + token;
    }
  }

  /* ---------- 目录选择 ---------- */
  var dirBrowser = { current: "", onPick: null };

  function openDirBrowser(onPick) {
    dirBrowser.onPick = onPick;
    $("#dirBrowserMask").hidden = false;
    loadDirList("");
  }

  function closeDirBrowser() {
    $("#dirBrowserMask").hidden = true;
    dirBrowser.onPick = null;
  }

  function loadDirList(path) {
    api("/api/dir_list?path=" + encodeURIComponent(path || "")).then(function (r) {
      if (!r || r.error) { toast((r && r.error) || "目录读取失败"); return; }
      dirBrowser.current = r.path;
      $("#dirBrowserPath").value = r.path;
      var list = $("#dirBrowserList");
      list.innerHTML = "";
      if (r.parent && r.parent !== r.path) {
        var up = document.createElement("div");
        up.className = "dir-row dir-up";
        up.textContent = ".. 上一级";
        up.addEventListener("click", function () { loadDirList(r.parent); });
        list.appendChild(up);
      }
      (r.dirs || []).forEach(function (d) {
        var row = document.createElement("div");
        row.className = "dir-row";
        row.textContent = d.name;
        row.title = d.path;
        row.addEventListener("click", function () { loadDirList(d.path); });
        list.appendChild(row);
      });
    }).catch(function () { toast("目录读取失败"); });
  }

  /* 选择目录并写入输入框; cfgKey 非空时同步保存到配置 */
  function pickDirInto(inputSel, cfgKey) {
    var apply = function (path) {
      if (!path) return;
      $(inputSel).value = path;
      if (cfgKey) {
        state.config[cfgKey] = path;
        var body = {};
        body[cfgKey] = path;
        api("/api/config", { method: "POST", body: body });
      }
    };
    if (isDesktop()) {
      window.pywebview.api.invoke("POST", "pick_dir", {}).then(function (r) {
        if (r && r.ok && r.path) apply(r.path);
        else toast((r && r.error) || "选择失败");
      });
      return;
    }
    openDirBrowser(apply);
  }

  /* ---------- 工具箱动作 ---------- */
  function doHardware() {
    var w = parseInt($("#hwWidth").value, 10), h = parseInt($("#hwHeight").value, 10),
        s = parseFloat($("#hwScale").value);
    if (!w || !h || !s) { toast("请填写有效的宽高与倍数"); return; }
    api("/api/hardware", { method: "POST", body: { width: w, height: h, scale: s } }).then(function (r) {
      var el = $("#hwReport");
      el.hidden = false;
      el.textContent =
        "内存是否充足: " + (r.ram_ok ? "是" : "否") + "\n" +
        "推荐放大倍数: " + r.rec_scale + "\n" +
        "推荐切块大小: " + r.rec_block_size + "\n" +
        "可用内存: " + r.avail_ram.toFixed(1) + " GB\n" +
        "可用显存: " + r.avail_vram.toFixed(1) + " GB";
    });
  }

  function doCompress() {
    var id = $("#compressSource").value;
    if (!id) { toast("队列中没有图片"); return; }
    api("/api/compress", { method: "POST", body: { id: id } }).then(function (r) {
      var el = $("#compressReport");
      el.hidden = false;
      if (r.id) {
        el.innerHTML = "压缩完成: " + escapeHtml(r.name) + " (" + fmtSize(r.size) + ")";
        downloadOutput(r.id, r.name);
      } else {
        el.textContent = "压缩失败: " + (r.error || "未知错误");
      }
    });
  }

  function doAutotune() {
    api("/api/autotune", { method: "POST", body: {} }).then(function (r) {
      var el = $("#autotuneReport");
      el.hidden = false;
      el.textContent = r.msg || "调优完成";
      if (r.cuda !== undefined) {
        state.config.use_cpu = r.cpu;
        state.config.use_fast_mode = r.fast;
        state.config.block_size = r.block;
        setChecked("#chkCpu", r.cpu);
        setChecked("#chkFast", r.fast);
        setVal("#blockRange", r.block);
        setVal("#blockNum", r.block);
        toast("调优参数已应用");
      }
    });
  }

  function doTrain() {
    var dir = $("#trainDir").value.trim();
    if (!dir) { toast("请先填写训练数据集目录"); return; }
    $("#btnTrain").disabled = true;
    saveWorkbenchConfig().then(function () {
      return api("/api/job/start", { method: "POST", body: { type: "train" } });
    }).then(function () {
      toast("训练任务已启动");
      beginPoll("train", { logBox: "#trainLog", bar: "#trainBar", pct: "#trainPct", outputs: "#outputsList" });
    }).catch(function (e) {
      $("#btnTrain").disabled = false;
      toast(e && e.error ? e.error : "启动失败");
    });
  }

  /* ---------- 背景 ---------- */
  var pendingBgFile = null;
  function refreshBgPreview() {
    apiBlob("/api/bg").then(function (blob) {
      var url = URL.createObjectURL(blob);
      $("#bgPreview").src = url;
      $("#bgPreview").hidden = false;
    }).catch(function () { $("#bgPreview").hidden = true; });
  }
  function uploadBg() {
    if (!pendingBgFile) { toast("请先选择背景图片"); return; }
    if (isDesktop()) {
      desktopUpload("bg", pendingBgFile).then(function (r) {
        if (r && r.ok) { toast("背景已应用"); refreshBgPreview(); }
        else toast((r && r.error) || "上传失败");
      });
      return;
    }
    var fd = new FormData();
    fd.append("file", pendingBgFile);
    api("/api/bg", { method: "POST", body: fd }).then(function (r) {
      if (r.ok) { toast("背景已应用"); refreshBgPreview(); }
      else toast(r.error || "上传失败");
    });
  }
  function clearBg() {
    api("/api/config", { method: "POST", body: { bg_image_path: "" } }).then(function () {
      state.config.bg_image_path = "";
      toast("背景已清除");
      refreshBgPreview();
    }).catch(function () { toast("清除失败"); });
  }

  /* ---------- 引导包 ---------- */
  function doPackage() {
    $("#btnPackage").disabled = true;
    api("/api/package", { method: "POST", body: {} }).then(function (r) {
      $("#btnPackage").disabled = false;
      var el = $("#packageReport");
      el.hidden = false;
      if (r.id) {
        el.innerHTML = "生成完毕: " + escapeHtml(r.name) + " (" + fmtSize(r.size) + ")";
        downloadOutput(r.id, r.name);
      } else {
        el.textContent = "生成失败: " + (r.error || "未知错误");
      }
    }).catch(function () {
      $("#btnPackage").disabled = false;
      toast("生成失败");
    });
  }

  /* ---------- 设置 ---------- */
  function saveSettings() {
    var body = {
      cloud_server_url: $("#setCloudUrl").value.trim(),
      cloud_api_key: $("#setCloudKey").value.trim(),
      webui_port: parseInt($("#setPort").value, 10) || 7860,
      webui_server_name: $("#setServerName").value.trim() || "0.0.0.0",
      webui_share: $("#setShare").checked,
      webui_theme: $("#setDark").checked ? "dark" : "light",
      default_image_format: $("#setImgFormat").value,
      default_video_format: $("#setVidFormat").value,
      launcher_default_mode: $("#setLaunchMode").value,
      model_choice: $("#setDefaultModel").value,
      show_queue_thumb: $("#setQueueThumb").checked,
      show_full_filename: $("#setFullName").checked,
      show_result_preview: $("#setPreview").checked,
    };
    api("/api/config", { method: "POST", body: body }).then(function () {
      Object.keys(body).forEach(function (k) { state.config[k] = body[k]; });
      document.body.dataset.theme = body.webui_theme === "dark" ? "dark" : "light";
      renderQueue();
      toast("设置已保存");
    }).catch(function () { toast("保存失败"); });
  }

  function toggleTheme() {
    var dark = document.body.dataset.theme !== "dark";
    document.body.dataset.theme = dark ? "dark" : "light";
    state.config.webui_theme = dark ? "dark" : "light";
    setChecked("#setDark", dark);
    api("/api/config", { method: "POST", body: { webui_theme: state.config.webui_theme } });
  }

  /* ---------- 事件绑定 ---------- */
  function bindEvents() {
    /* 标签页 */
    $$(".tabbar-item").forEach(function (tab) {
      tab.addEventListener("click", function () {
        $$(".tabbar-item").forEach(function (t) { t.classList.remove("active"); });
        tab.classList.add("active");
        $$(".panel").forEach(function (p) { p.hidden = true; });
        $("#" + tab.dataset.panel).hidden = false;
      });
    });
    $("#settingsJump").addEventListener("click", function () {
      $$(".tabbar-item").forEach(function (t) {
        t.classList.toggle("active", t.dataset.panel === "panel-settings");
      });
      $$(".panel").forEach(function (p) { p.hidden = true; });
      $("#panel-settings").hidden = false;
    });
    $("#themeToggle").addEventListener("click", toggleTheme);

    /* 队列 */
    var dz = $("#dropzone");
    var fileInput = $("#fileInput");
    $("#btnPickFiles").addEventListener("click", function () {
      if (isDesktop()) {
        window.pywebview.api.invoke("POST", "pick_files", {}).then(function (r) {
          if (!r || !r.ok) { toast((r && r.error) || "选择失败"); return; }
          if (r.paths && r.paths.length) {
            api("/api/queue", { method: "POST", body: { paths: r.paths } }).then(function (resp) {
              state.queue = resp.files || [];
              renderQueue();
              if (state.queue.length && !state.selectedQueueId) {
                var firstImg = state.queue.find(function (q) { return q.is_image; });
                if (firstImg) selectQueueItem(firstImg.id);
              }
              toast("已添加 " + resp.added + " 个文件");
            });
          }
        });
        return;
      }
      fileInput.click();
    });
    fileInput.addEventListener("change", function () {
      addFiles(fileInput.files);
      fileInput.value = "";
    });
    $("#btnPickPath").addEventListener("click", addLocalPaths);
    $("#btnClearQueue").addEventListener("click", function () {
      api("/api/queue", { method: "DELETE" }).then(function (resp) {
        state.queue = resp.files || [];
        state.selectedQueueId = null;
        renderQueue();
        toast("队列已清空");
      });
    });
    $("#viewList").addEventListener("click", function () {
      state.queueView = "list";
      localStorage.setItem("vt_queue_view", "list");
      applyQueueView();
    });
    $("#viewGrid").addEventListener("click", function () {
      state.queueView = "grid";
      localStorage.setItem("vt_queue_view", "grid");
      applyQueueView();
    });
    ["dragenter", "dragover"].forEach(function (evt) {
      dz.addEventListener(evt, function (e) { e.preventDefault(); dz.classList.add("drag-over"); });
    });
    ["dragleave", "drop"].forEach(function (evt) {
      dz.addEventListener(evt, function (e) { e.preventDefault(); dz.classList.remove("drag-over"); });
    });
    dz.addEventListener("drop", function (e) {
      if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
    });
    document.addEventListener("keydown", function (e) {
      if ((e.key === "Delete" || e.key === "Del") && state.selectedQueueId) {
        removeQueueItem(state.selectedQueueId);
      }
    });

    /* 参数 */
    bindSliderSpin("#scaleRange", "#scaleNum");
    bindSliderSpin("#blockRange", "#blockNum");
    $("#modelChoice").addEventListener("change", updateModelDesc);
    $("#btnApplyParams").addEventListener("click", function () {
      if (state.paramsLocked) unlockParams();
      else applyParams();
    });
    $$(".preset-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        applyPreset(parseInt(btn.dataset.w, 10), parseInt(btn.dataset.h, 10));
      });
    });
    $("#chkCustomRes").addEventListener("change", function () {
      if (!this.checked) {
        syncScaleToDimensions($("#scaleNum").value);
        toast("已切换为原图自由比例");
      } else {
        toast("已锁定固定画幅，超出部分将黑边填充");
      }
    });
    ["input", "change"].forEach(function (evt) {
      $("#targetWidth").addEventListener(evt, function () {
        syncDimensionToScale("width");
      });
      $("#targetHeight").addEventListener(evt, function () {
        syncDimensionToScale("height");
      });
    });

    /* 模型库 */
    $("#btnModelLib").addEventListener("click", openModelLib);
    $("#btnModelLibClose").addEventListener("click", function () { $("#modelLibMask").hidden = true; });
    $("#modelLibMask").addEventListener("click", function (e) {
      if (e.target === $("#modelLibMask")) $("#modelLibMask").hidden = true;
    });
    $("#btnImportModel").addEventListener("click", function () { $("#modelImportInput").click(); });
    $("#modelImportInput").addEventListener("change", function () {
      if (this.files && this.files[0]) importModel(this.files[0]);
      this.value = "";
    });

    /* 任务 */
    $("#btnStartBatch").addEventListener("click", function () { startJob("batch", "基础解析"); });
    $("#btnStartAlpha").addEventListener("click", function () { startJob("alpha", "立绘引擎"); });
    $("#btnStartCloud").addEventListener("click", function () { startJob("cloud", "云端"); });
    $("#btnPause").addEventListener("click", function () {
      var paused = $("#btnPause").textContent === "继续";
      controlJob(paused ? "resume" : "pause");
    });
    var btnStop = $("#btnStop");
    if (btnStop) {
      btnStop.addEventListener("click", function () {
        controlJob("stop");
      });
    }
    $("#btnOpenDir").addEventListener("click", openOutputDir);

    /* 工具箱 */
    bindCropCanvas();
    $("#cropSource").addEventListener("change", function () { loadCropImage($("#cropSource").value); });
    $("#btnCropReplace").addEventListener("click", function () { saveCrop("replace"); });
    $("#btnCropCopy").addEventListener("click", function () { saveCrop("copy"); });
    $("#btnHardware").addEventListener("click", doHardware);
    $("#btnCompress").addEventListener("click", doCompress);
    $("#btnAutotune").addEventListener("click", doAutotune);
    $("#btnTrain").addEventListener("click", doTrain);
    $("#btnPickTrainDir").addEventListener("click", function () {
      pickDirInto("#trainDir", "train_dataset_dir");
    });
    $("#btnPickOutputDir").addEventListener("click", function () {
      pickDirInto("#outputDir", "output_dir");
    });
    $("#btnPickSliceDir").addEventListener("click", function () {
      pickDirInto("#sliceDir", "slice_dir");
    });
    $("#btnPickCropSaveDir").addEventListener("click", function () {
      pickDirInto("#cropSaveDir", null);
    });
    $("#btnDirGo").addEventListener("click", function () {
      loadDirList($("#dirBrowserPath").value.trim());
    });
    $("#dirBrowserPath").addEventListener("keydown", function (e) {
      if (e.key === "Enter") loadDirList($("#dirBrowserPath").value.trim());
    });
    $("#btnDirPick").addEventListener("click", function () {
      var cb = dirBrowser.onPick;
      closeDirBrowser();
      if (cb) cb(dirBrowser.current);
    });
    $("#btnDirCancel").addEventListener("click", closeDirBrowser);
    $("#dirBrowserMask").addEventListener("click", function (e) {
      if (e.target === $("#dirBrowserMask")) closeDirBrowser();
    });
    $("#btnPackage").addEventListener("click", doPackage);

    /* 背景 */
    $("#btnPickBg").addEventListener("click", function () { $("#bgInput").click(); });
    $("#bgInput").addEventListener("change", function () {
      pendingBgFile = $("#bgInput").files[0] || null;
      if (pendingBgFile) {
        var url = URL.createObjectURL(pendingBgFile);
        $("#bgPreview").src = url;
        $("#bgPreview").hidden = false;
      }
    });
    $("#btnUploadBg").addEventListener("click", uploadBg);
    $("#btnClearBg").addEventListener("click", clearBg);

    /* 设置 */
    $("#btnSaveConfig").addEventListener("click", saveSettings);
  }

  /* 初始化时机统一用轮询: 桌面版(pywebview)等待 js_api 注入完成
     (注入在导航完成后分两步执行, 且可能晚于本脚本), WebUI 模式
     等待 DOM 就绪。不依赖 DOMContentLoaded 事件与注入时序。 */
  var bootStarted = false;
  function boot() {
    if (bootStarted) return;
    bootStarted = true;
    init();
  }
  var _tries = 0;
  (function waitReady() {
    var domReady = document.readyState !== "loading";
    if (isDesktop()) {
      if (domReady && window.pywebview && window.pywebview.api &&
          typeof window.pywebview.api.invoke === "function") {
        boot();
        return;
      }
    } else if (domReady) {
      init();
      return;
    }
    if (++_tries < 150) setTimeout(waitReady, 200);   // 最长等待 30 秒
  })();
})();
