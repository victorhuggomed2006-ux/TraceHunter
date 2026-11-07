// No inline handlers or inline styles: the server CSP only allows scripts and styles from the site itself.
// The texts come from i18n.js. The default language is the browser/computer one; language and theme are remembered.
var content = document.getElementById("content");
var langSelect = document.getElementById("lang");
var themeSelect = document.getElementById("theme");
var current = { view: "list", id: null };
var selectedId = null;
var LANG_KEY = "tracehunter.lang";
var THEME_KEY = "tracehunter.theme";
var THEMES = ["terminal", "classic"];
var lang = pickLanguage();
var theme = pickTheme();

function remember(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* storage blocked: carry on without remembering */ }
}
function recall(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}

function pickLanguage() {
  var saved = recall(LANG_KEY);
  if (saved && I18N[saved]) { return saved; }
  var wanted = (navigator.languages && navigator.languages.length) ? navigator.languages : [navigator.language || "en"];
  for (var i = 0; i < wanted.length; i++) {
    var code = String(wanted[i]).toLowerCase();
    if (I18N[code]) { return code; }
    var base = code.split("-")[0];
    if (I18N[base]) { return base; }
  }
  return "en";
}
function pickTheme() {
  var saved = recall(THEME_KEY);
  return THEMES.indexOf(saved) >= 0 ? saved : "terminal";
}
function t(key) { return (I18N[lang] && I18N[lang][key]) || I18N.en[key] || key; }
function locale() { return LOCALES[lang] || lang; }

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
function st(s) {
  var c = s == "COMPLETED" ? "label-success" : s == "FAILED" ? "label-important" : "label-warning";
  var k = s == "COMPLETED" ? "st_completed" : s == "FAILED" ? "st_failed" : "st_running";
  return '<span class="label ' + c + '">' + esc(t(k)) + "</span>";
}
function dur(d) { return d == null ? "-" : d.toFixed(3) + " s"; }
function when(iso) {
  var d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(locale());
}
function fmt(v) { return v == null ? "-" : "<pre>" + esc(JSON.stringify(v, null, 2)) + "</pre>"; }

function getJson(url) {
  return fetch(url).then(function (r) {
    if (!r.ok) { throw new Error("HTTP " + r.status); }
    return r.json();
  });
}
function showError(e) {
  content.innerHTML = "<div class='box box-error'><span class='errtxt'>" + esc(t("load_error")) + ": " + esc(e.message) + "</span></div>";
}

// ---- list and keyboard selection ----
function rows() { return Array.prototype.slice.call(content.querySelectorAll("tr.row")); }
function markSelected() {
  var all = rows();
  if (!all.length) { return; }
  var cur = all.filter(function (r) { return r.getAttribute("data-id") === selectedId; })[0] || all[0];
  all.forEach(function (r) { r.classList.remove("sel"); });
  cur.classList.add("sel");
  selectedId = cur.getAttribute("data-id");
  return cur;
}
function move(delta) {
  var all = rows();
  if (!all.length) { return; }
  var i = 0;
  all.forEach(function (r, n) { if (r.getAttribute("data-id") === selectedId) { i = n; } });
  i = Math.max(0, Math.min(all.length - 1, i + delta));
  selectedId = all[i].getAttribute("data-id");
  markSelected().scrollIntoView({ block: "nearest" });
}

function showList() {
  current = { view: "list", id: null };
  getJson("/api/traces").then(function (traces) {
    var h = "<h2>" + esc(t("recent")) + "</h2>";
    if (!traces.length) {
      content.innerHTML = h + "<div class='box'>" + esc(t("empty")) + "</div>";
      return;
    }
    h += "<table><tr><th>" + esc(t("th_name")) + "</th><th>" + esc(t("th_status")) + "</th><th>" + esc(t("th_steps")) +
         "</th><th>" + esc(t("th_duration")) + "</th><th>" + esc(t("th_start")) + "</th></tr>";
    traces.forEach(function (tr) {
      h += "<tr class='row' data-id='" + esc(tr.trace_id) + "'><td>" + esc(tr.name) + "</td><td>" + st(tr.status) +
           "</td><td>" + tr.span_count + "</td><td>" + dur(tr.duration_seconds) + "</td><td>" + esc(when(tr.start_time)) + "</td></tr>";
    });
    content.innerHTML = h + "</table>";
    markSelected();
  }).catch(showError);
}

function showTrace(id) {
  current = { view: "trace", id: id };
  selectedId = id;
  getJson("/api/traces/" + encodeURIComponent(id)).then(function (tr) {
    var depth = {};
    var h = "<h2>" + esc(tr.name) + "</h2><div class='box" + (tr.status == "FAILED" ? " box-error" : "") + "'>" +
            esc(t("label_status")) + ": " + st(tr.status) + " &nbsp; " + esc(t("label_duration")) + ": " + dur(tr.duration_seconds) +
            " &nbsp; " + esc(t("label_steps")) + ": " + tr.spans.length + "<br>" + esc(t("label_id")) + ": " + esc(tr.trace_id) + "</div>" +
            "<table><tr><th>" + esc(t("th_step")) + "</th><th>" + esc(t("th_status")) + "</th><th>" + esc(t("th_duration")) +
            "</th><th>" + esc(t("th_input")) + "</th><th>" + esc(t("th_output")) + "</th></tr>";
    tr.spans.forEach(function (s) {
      depth[s.span_id] = s.parent_span_id && depth[s.parent_span_id] != null ? depth[s.parent_span_id] + 1 : 0;
      var out = s.status == "FAILED" ? "<span class='errtxt'>" + esc((s.metadata || {}).error) + "</span>" : fmt(s.output_data);
      h += "<tr><td data-depth='" + depth[s.span_id] + "'>" + (depth[s.span_id] ? "&raquo; " : "") + esc(s.name) +
           "</td><td>" + st(s.status) + "</td><td>" + dur(s.duration_seconds) + "</td><td>" + fmt(s.input_data) + "</td><td>" + out + "</td></tr>";
    });
    content.innerHTML = h + "</table><p><a href='#' class='back'>&laquo; " + esc(t("back")) + "</a></p>";
    // Indent nested steps via CSSOM (allowed by the CSP, unlike the style attribute).
    content.querySelectorAll("td[data-depth]").forEach(function (td) {
      td.style.paddingInlineStart = (11 + Number(td.getAttribute("data-depth")) * 18) + "px";
    });
  }).catch(showError);
}

function render() { if (current.view == "trace") { showTrace(current.id); } else { showList(); } }

// ---- language and theme ----
function applyTheme() {
  document.documentElement.setAttribute("data-theme", theme);
  themeSelect.value = theme;
}
function buildThemeMenu() {
  themeSelect.innerHTML = "";
  THEMES.forEach(function (name) {
    var opt = document.createElement("option");
    opt.value = name;
    opt.textContent = t("theme_" + name);
    themeSelect.appendChild(opt);
  });
  themeSelect.value = theme;
  themeSelect.title = t("theme");
  themeSelect.setAttribute("aria-label", t("theme"));
}
function setTheme(name) {
  theme = name;
  remember(THEME_KEY, theme);
  applyTheme();
}
function applyStatic() {
  document.documentElement.lang = locale();
  document.documentElement.dir = RTL_LANGS[lang] ? "rtl" : "ltr";
  document.querySelectorAll("[data-t]").forEach(function (el) { el.textContent = t(el.getAttribute("data-t")); });
  langSelect.title = t("language");
  langSelect.setAttribute("aria-label", t("language"));
  buildThemeMenu();
}
function buildLanguageMenu() {
  Object.keys(I18N).forEach(function (code) {
    var opt = document.createElement("option");
    opt.value = code;
    opt.textContent = I18N[code].lang_name;
    langSelect.appendChild(opt);
  });
  langSelect.value = lang;
  langSelect.addEventListener("change", function () {
    lang = langSelect.value;
    remember(LANG_KEY, lang);
    applyStatic();
    render();
  });
}

// ---- events ----
content.addEventListener("click", function (e) {
  var row = e.target.closest("tr.row");
  if (row) { selectedId = row.getAttribute("data-id"); showTrace(selectedId); return; }
  if (e.target.closest("a.back")) { e.preventDefault(); showList(); }
});
document.getElementById("nav-list").addEventListener("click", showList);
document.getElementById("nav-refresh").addEventListener("click", render);
themeSelect.addEventListener("change", function () { setTheme(themeSelect.value); });

// Shortcuts: j/k or arrows move, Enter opens, Esc/b/Backspace goes back, r refreshes, t switches the theme.
document.addEventListener("keydown", function (e) {
  if (e.ctrlKey || e.metaKey || e.altKey) { return; }
  var tag = (e.target.tagName || "").toLowerCase();
  if (tag === "select" || tag === "input" || tag === "textarea") { return; }
  var k = e.key;
  var inList = current.view == "list";
  if (k === "j" || k === "ArrowDown") { e.preventDefault(); if (inList) { move(1); } else { window.scrollBy(0, 70); } }
  else if (k === "k" || k === "ArrowUp") { e.preventDefault(); if (inList) { move(-1); } else { window.scrollBy(0, -70); } }
  else if (k === "Enter" && inList) {
    var sel = content.querySelector("tr.row.sel");
    if (sel) { showTrace(sel.getAttribute("data-id")); }
  }
  else if ((k === "Escape" || k === "b" || k === "Backspace") && !inList) { e.preventDefault(); showList(); }
  else if (k === "r") { render(); }
  else if (k === "t") { setTheme(theme === "terminal" ? "classic" : "terminal"); }
});

// Auto-refresh: redraw the screen every 3 s without losing the scroll position.
setInterval(function () {
  if (document.getElementById("auto").checked && !document.hidden) {
    var y = window.scrollY;
    render();
    setTimeout(function () { window.scrollTo(0, y); }, 250);
  }
}, 3000);

buildLanguageMenu();
applyStatic();
applyTheme();
showList();
