"use strict";

// Reads the static JSON API next to this page and draws the selected species' index and the
// region's bottom temperature. No libraries: plain SVG and DOM. Every string that comes from the
// data is inserted with textContent, never as HTML.

const API = "api/v1";
const GEAR_CHANGE = 1981.5; // Yankee #36 trawl to 1981, Western IIA from 1982
const REGION_LABELS = {
  core: "Core area (strata 440–495)",
  "4VW": "4VW (strata 440–466)",
  "4X5Y": "4X5Y (strata 470–495)",
};
const METRICS = {
  weight: { mean: "mean_weight_kg_per_tow", se: "se_weight_kg_per_tow", label: "kg per standard tow", unit: "kg/tow" },
  count: { mean: "mean_count_per_tow", se: "se_count_per_tow", label: "number per standard tow", unit: "per tow" },
};
const DEFAULT_SPECIES = 11; // haddock

const $ = (id) => document.getElementById(id);
const state = {
  meta: null, temp: null, series: null,
  byCode: new Map(), byLabel: new Map(),
  code: DEFAULT_SPECIES, region: "core", metric: "weight",
};

async function getJSON(path) {
  const response = await fetch(`${API}/${path}`);
  if (!response.ok) throw new Error(`Could not load ${path} (HTTP ${response.status})`);
  return response.json();
}

// ---------- names and numbers ----------

function titleCase(text) {
  return text.toLowerCase().replace(/(^|[\s\-/(])([a-z])/g, (_, before, letter) => before + letter.toUpperCase()).trim();
}

function sentenceCase(text) {
  const lower = text.toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

function speciesNames(s) {
  const scientific = sentenceCase(s.scientific_name);
  const common = s.common_name ? titleCase(s.common_name.split(";")[0]) : "";
  return { common, scientific, label: common ? `${common} (${scientific})` : scientific };
}

function formatNumber(v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return "–";
  const abs = Math.abs(v);
  if (abs >= 1000) return Math.round(v).toLocaleString("en-CA");
  if (abs >= 100) return v.toFixed(0);
  if (abs >= 10) return v.toFixed(1);
  if (abs >= 1) return v.toFixed(2);
  if (abs === 0) return "0";
  return v.toPrecision(2);
}

function formatTick(v) {
  const abs = Math.abs(v);
  if (abs >= 1e6) return `${+(v / 1e6).toFixed(1)}M`;
  if (abs >= 1e4) return `${+(v / 1e3).toFixed(0)}K`;
  if (abs >= 1000) return v.toLocaleString("en-CA");
  return `${+v.toPrecision(3)}`;
}

function vesselNames(codes) {
  if (!codes) return "Vessel: –";
  return `Vessel: ${codes.split(";").map((c) => state.meta.vessels[c] || c).join(", ")}`;
}

function yearList(years) {
  return years.length ? years.join(", ") : "none";
}

function niceTicks(min, max, count = 5) {
  if (!(max > min)) max = min + 1;
  const raw = (max - min) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw);
  const start = Math.floor(min / step) * step;
  const ticks = [];
  for (let t = start; t < max + step; t += step) ticks.push(+t.toFixed(10));
  return ticks;
}

// ---------- chart ----------

const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(name, attributes, parent) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (parent) parent.appendChild(node);
  return node;
}

function appendText(parent, tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  parent.appendChild(node);
  return node;
}

/**
 * Line chart of one series with a 95% band. Complete years are joined by the line; incomplete
 * years are separate grey points; years without data leave a gap.
 * cfg: { years, mean, se, complete, domain: [first, last], fromZero, gearChange, unit, empty, details(i) }
 */
function lineChart(container, cfg) {
  container.replaceChildren();
  container.classList.remove("loading");
  const n = cfg.years.length;
  const withData = [...Array(n).keys()].filter((i) => cfg.mean[i] !== null);
  if (!withData.length) {
    appendText(container, "p", "empty", cfg.empty);
    container.onkeydown = container.onfocus = container.onblur = null;
    return;
  }

  const width = Math.max(container.clientWidth, 280);
  const height = width < 560 ? 230 : 300;
  const m = { top: 22, right: 12, bottom: 28, left: 46 };
  const half = cfg.se.map((s) => (s === null ? null : 1.96 * s));
  const lower = cfg.mean.map((v, i) => (v === null || half[i] === null ? null : cfg.fromZero ? Math.max(0, v - half[i]) : v - half[i]));
  const upper = cfg.mean.map((v, i) => (v === null || half[i] === null ? null : v + half[i]));
  const values = [...cfg.mean, ...lower, ...upper].filter((v) => v !== null);
  const ticks = niceTicks(cfg.fromZero ? 0 : Math.min(...values), Math.max(...values));
  const [x0, x1] = cfg.domain;
  const x = (year) => m.left + ((year - x0) / (x1 - x0)) * (width - m.left - m.right);
  const y = (v) => height - m.bottom - ((v - ticks[0]) / (ticks[ticks.length - 1] - ticks[0])) * (height - m.top - m.bottom);

  const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": cfg.ariaLabel }, container);

  for (const t of ticks) {
    svgEl("line", { class: "grid", x1: m.left, x2: width - m.right, y1: y(t), y2: y(t) }, svg);
    svgEl("text", { class: "tick", x: m.left - 8, y: y(t), "text-anchor": "end", "dominant-baseline": "middle" }, svg).textContent = formatTick(t);
  }
  svgEl("line", { class: "baseline", x1: m.left, x2: width - m.right, y1: height - m.bottom, y2: height - m.bottom }, svg);
  for (let year = Math.ceil(x0 / 10) * 10; year <= x1; year += 10) {
    svgEl("text", { class: "tick", x: x(year), y: height - m.bottom + 18, "text-anchor": "middle" }, svg).textContent = year;
  }
  if (cfg.gearChange && GEAR_CHANGE > x0 && GEAR_CHANGE < x1) {
    svgEl("line", { class: "rule", x1: x(GEAR_CHANGE), x2: x(GEAR_CHANGE), y1: m.top - 14, y2: height - m.bottom }, svg);
    if (width >= 560) {
      svgEl("text", { class: "rule-label", x: x(GEAR_CHANGE) - 6, y: m.top - 6, "text-anchor": "end" }, svg).textContent = "Yankee #36 trawl";
      svgEl("text", { class: "rule-label", x: x(GEAR_CHANGE) + 6, y: m.top - 6 }, svg).textContent = "Western IIA trawl";
    }
  }

  // Runs of consecutive complete years, for the line and (where an SE exists) the band
  const runs = (keep) => {
    const out = [];
    let run = [];
    for (let i = 0; i < n; i++) {
      if (keep(i) && run.length && cfg.years[i] - cfg.years[run[run.length - 1]] === 1) run.push(i);
      else if (keep(i)) { if (run.length) out.push(run); run = [i]; }
      else if (run.length) { out.push(run); run = []; }
    }
    if (run.length) out.push(run);
    return out;
  };
  const isComplete = (i) => cfg.complete[i] === true && cfg.mean[i] !== null;
  for (const run of runs((i) => isComplete(i) && upper[i] !== null)) {
    if (run.length < 2) continue;
    const top = run.map((i) => `${x(cfg.years[i])},${y(upper[i])}`);
    const bottom = run.slice().reverse().map((i) => `${x(cfg.years[i])},${y(lower[i])}`);
    svgEl("path", { class: "band", d: `M${top.join("L")}L${bottom.join("L")}Z` }, svg);
  }
  for (const run of runs(isComplete)) {
    if (run.length === 1) {
      svgEl("circle", { class: "point", cx: x(cfg.years[run[0]]), cy: y(cfg.mean[run[0]]), r: 3.5 }, svg);
    } else {
      svgEl("path", { class: "line", d: `M${run.map((i) => `${x(cfg.years[i])},${y(cfg.mean[i])}`).join("L")}` }, svg);
    }
  }
  for (const i of withData.filter((i) => !isComplete(i))) {
    svgEl("circle", { class: "incomplete", cx: x(cfg.years[i]), cy: y(cfg.mean[i]), r: 4.5 }, svg);
  }

  // Hover and keyboard layer: a crosshair snapped to the nearest year with data
  const cross = svgEl("line", { class: "crosshair", y1: m.top, y2: height - m.bottom, visibility: "hidden" }, svg);
  const dot = svgEl("circle", { class: "focus-dot", r: 4.5, visibility: "hidden" }, svg);
  const overlay = svgEl("rect", { class: "overlay", x: m.left, y: 0, width: width - m.left - m.right, height: height - m.bottom }, svg);
  const tip = document.createElement("div");
  tip.className = "tooltip";
  tip.hidden = true;
  container.appendChild(tip);
  let current = null;

  function show(i) {
    current = i;
    const cx = x(cfg.years[i]);
    for (const attr of ["x1", "x2"]) cross.setAttribute(attr, cx);
    cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", cx);
    dot.setAttribute("cy", y(cfg.mean[i]));
    dot.setAttribute("class", isComplete(i) ? "focus-dot" : "focus-dot incomplete");
    dot.setAttribute("visibility", "visible");

    tip.replaceChildren();
    const value = appendText(tip, "div", "value", "");
    appendText(value, "span", isComplete(i) ? "key" : "key incomplete-key", "");
    value.appendChild(document.createTextNode(`${formatNumber(cfg.mean[i])} ${cfg.unit}`));
    const interval = upper[i] === null ? "no interval (single tow per stratum)" : `95% interval ${formatNumber(lower[i])}–${formatNumber(upper[i])}`;
    appendText(tip, "div", "detail", `${cfg.years[i]} · ${interval}`);
    for (const line of cfg.details(i)) appendText(tip, "div", "detail", line);
    if (!isComplete(i)) appendText(tip, "div", "warn", "Incomplete coverage: not comparable with other years");

    tip.hidden = false;
    const box = container.getBoundingClientRect();
    const tipWidth = tip.offsetWidth;
    const scale = box.width / width;
    let left = cx * scale + 14;
    if (left + tipWidth > box.width) left = cx * scale - tipWidth - 14;
    tip.style.left = `${Math.max(0, left)}px`;
    tip.style.top = `${m.top * scale}px`;
  }

  function hide() {
    cross.setAttribute("visibility", "hidden");
    dot.setAttribute("visibility", "hidden");
    tip.hidden = true;
  }

  function nearest(px) {
    let best = withData[0];
    for (const i of withData) if (Math.abs(x(cfg.years[i]) - px) < Math.abs(x(cfg.years[best]) - px)) best = i;
    return best;
  }

  overlay.addEventListener("pointermove", (event) => {
    const box = svg.getBoundingClientRect();
    show(nearest((event.clientX - box.left) * (width / box.width)));
  });
  overlay.addEventListener("pointerleave", hide);
  container.onfocus = () => show(current ?? withData[withData.length - 1]);
  container.onblur = hide;
  container.onkeydown = (event) => {
    const moves = { ArrowLeft: -1, ArrowRight: 1, Home: -Infinity, End: Infinity };
    if (!(event.key in moves)) return;
    event.preventDefault();
    const pos = withData.indexOf(current ?? withData[withData.length - 1]);
    const next = Math.min(withData.length - 1, Math.max(0, pos + moves[event.key]));
    show(withData[Number.isFinite(next) ? next : moves[event.key] < 0 ? 0 : withData.length - 1]);
  };
}

// ---------- table and download ----------

function renderTable(container, headers, rows, incomplete) {
  const table = document.createElement("table");
  const head = table.createTHead().insertRow();
  for (const h of headers) appendText(head, "th", null, h);
  const body = table.createTBody();
  rows.forEach((cells, r) => {
    const row = body.insertRow();
    if (incomplete[r]) row.className = "incomplete-row";
    for (const c of cells) appendText(row, "td", null, c);
  });
  container.replaceChildren(table);
}

function csvCell(v) {
  if (v === null || v === undefined) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function csvText() {
  const region = state.series.regions[state.region];
  const fields = Object.keys(region);
  const lines = [["species_code", "region", ...fields].join(",")];
  for (let i = 0; i < region.year.length; i++) {
    lines.push([state.code, state.region, ...fields.map((f) => csvCell(region[f][i]))].join(","));
  }
  return lines.join("\n") + "\n";
}

function downloadCsv() {
  const url = URL.createObjectURL(new Blob([csvText()], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `maritimes-rv-index-${state.code}-${state.region}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------- page ----------

function render() {
  const species = state.byCode.get(state.code);
  const names = speciesNames(species);
  const metric = METRICS[state.metric];
  const region = state.series.regions[state.region];
  const domain = state.meta.years;

  $("index-title").textContent = `${names.common || names.scientific}: ${metric.label}`;
  $("index-subtitle").textContent =
    `${names.scientific}, ${REGION_LABELS[state.region]}. Stratified mean with 95% interval (±1.96 SE). ` +
    "Grey points: incomplete survey coverage. Vessel conversion factors not applied.";
  const mean = region[metric.mean];
  const se = region[metric.se];
  lineChart($("index-chart"), {
    years: region.year, mean, se, complete: region.complete, domain, fromZero: true, gearChange: true,
    unit: metric.unit,
    ariaLabel: `${names.label}, ${metric.label}, ${REGION_LABELS[state.region]}, ${domain[0]} to ${domain[1]}`,
    empty: `No tows in ${REGION_LABELS[state.region]} for this selection.`,
    details: (i) => [
      `${region.n_sets[i]} tows · ${region.n_strata_sampled[i]} of ${region.n_strata_total[i]} strata`,
      vesselNames(region.vessels[i]),
    ],
  });
  renderTable(
    $("index-table"),
    ["Year", "Tows", "Strata", "Complete", `Mean (${metric.unit})`, "SE", "95% interval"],
    region.year.map((year, i) => [
      year, region.n_sets[i], `${region.n_strata_sampled[i]}/${region.n_strata_total[i]}`, region.complete[i] ? "yes" : "no",
      formatNumber(mean[i]), formatNumber(se[i]),
      mean[i] === null || se[i] === null ? "–" : `${formatNumber(Math.max(0, mean[i] - 1.96 * se[i]))}–${formatNumber(mean[i] + 1.96 * se[i])}`,
    ]),
    region.complete.map((c) => !c),
  );

  const temp = state.temp.regions[state.region];
  $("temp-subtitle").textContent =
    `${REGION_LABELS[state.region]}. Stratified mean of tows with a reading, with 95% interval. ` +
    "Grey points: readings from less than 90% of the area.";
  lineChart($("temp-chart"), {
    years: temp.year, mean: temp.mean_bottom_temp_c, se: temp.se_bottom_temp_c, complete: temp.complete, domain,
    fromZero: false, gearChange: false, unit: "°C",
    ariaLabel: `Summer bottom temperature, ${REGION_LABELS[state.region]}`,
    empty: "No bottom temperature readings for this region.",
    details: (i) => [`${temp.n_sets_with_temp[i]} tows with a reading · ${Math.round(temp.area_coverage[i] * 100)}% of area`],
  });
  renderTable(
    $("temp-table"),
    ["Year", "Tows with reading", "Area covered", "Mean (°C)", "SE"],
    temp.year.map((year, i) => [
      year, temp.n_sets_with_temp[i], `${Math.round(temp.area_coverage[i] * 100)}%`,
      formatNumber(temp.mean_bottom_temp_c[i]), formatNumber(temp.se_bottom_temp_c[i]),
    ]),
    temp.complete.map((c) => !c),
  );

  const params = new URLSearchParams({ species: state.code, region: state.region, metric: state.metric });
  history.replaceState(null, "", `?${params}`);
}

async function selectSpecies(code) {
  state.code = code;
  $("species").value = speciesNames(state.byCode.get(code)).label;
  $("index-chart").classList.add("loading");
  try {
    state.series = await getJSON(`index/${code}.json`);
    $("status").textContent = "";
    render();
  } catch (error) {
    $("status").textContent = error.message;
  }
}

function fillStaticText() {
  const { meta } = state;
  $("years").textContent = `${meta.years[0]}–${meta.years[1]}`;
  const releaseUrl = /^local/.test(meta.release) ? `${meta.repository}/releases/latest` : `${meta.repository}/releases/tag/${meta.release}`;
  for (const id of ["link-release", "link-release-2"]) $(id).href = releaseUrl;
  $("link-repo").href = meta.repository;
  $("link-method").href = `${meta.repository}#readme`;
  $("incomplete-years").textContent = Object.entries(meta.incomplete_years)
    .map(([region, years]) => `${region} ${yearList(years)}`).join("; ");
  $("temp-gaps").textContent = Object.entries(state.temp.regions)
    .map(([region, t]) => `${region} ${yearList(t.year.filter((_, i) => t.n_sets_with_temp[i] === 0))}`).join("; ");
  $("provenance").textContent =
    `Data release ${meta.release}, generated ${meta.generated.slice(0, 10)} by maritimes-rv ${meta.package_version}.`;

  const base = new URL(`${API}/`, location.href).href;
  $("example-python").textContent = [
    "import json, urllib.request",
    "import pandas as pd",
    "",
    `base = "${base}"`,
    'haddock = json.load(urllib.request.urlopen(base + "index/11.json"))',
    'df = pd.DataFrame(haddock["regions"]["4X5Y"])',
    'df = df[df["complete"]]   # compare complete years only',
  ].join("\n");
  $("example-r").textContent = [
    `haddock <- jsonlite::fromJSON("${base}index/11.json")`,
    'df <- as.data.frame(haddock$regions[["4X5Y"]])',
    "df <- df[df$complete, ]   # compare complete years only",
  ].join("\n");
}

async function init() {
  try {
    const [meta, species, temp] = await Promise.all([getJSON("meta.json"), getJSON("species.json"), getJSON("bottom_temp.json")]);
    Object.assign(state, { meta, temp });
    const options = document.createDocumentFragment();
    for (const s of species) {
      const { label } = speciesNames(s);
      state.byCode.set(s.code, s);
      state.byLabel.set(label, s.code);
      const option = document.createElement("option");
      option.value = label;
      options.appendChild(option);
    }
    $("species-options").replaceChildren(options);

    const params = new URLSearchParams(location.search);
    const code = Number(params.get("species"));
    if (state.byCode.has(code)) state.code = code;
    if (params.get("region") in REGION_LABELS) state.region = params.get("region");
    if (params.get("metric") in METRICS) state.metric = params.get("metric");
    $("region").value = state.region;
    document.querySelector(`input[name="metric"][value="${state.metric}"]`).checked = true;

    fillStaticText();
    await selectSpecies(state.code);
  } catch (error) {
    $("status").textContent = `${error.message}. The data files may still be deploying; try again in a minute.`;
    return;
  }

  const pickSpecies = () => {
    const code = state.byLabel.get($("species").value);
    if (code && code !== state.code) selectSpecies(code);
  };
  $("species").addEventListener("input", pickSpecies);
  $("species").addEventListener("change", pickSpecies);
  $("species").addEventListener("focus", (event) => event.target.select());
  $("region").addEventListener("change", (event) => { state.region = event.target.value; render(); });
  for (const radio of document.querySelectorAll('input[name="metric"]')) {
    radio.addEventListener("change", (event) => { state.metric = event.target.value; render(); });
  }
  $("download").addEventListener("click", downloadCsv);

  // Redraw only when the width changes (opening a table changes the height, not the charts)
  let lastWidth = document.querySelector("main").clientWidth;
  new ResizeObserver((entries) => {
    const width = entries[0].contentRect.width;
    if (Math.abs(width - lastWidth) < 1 || !state.series) return;
    lastWidth = width;
    requestAnimationFrame(render);
  }).observe(document.querySelector("main"));
}

init();
