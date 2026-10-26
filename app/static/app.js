const BUDGET_LABELS = {
  low: "Low (under ₹500)",
  medium: "Medium",
  high: "High (₹1,001 and above)",
};

const BUDGET_HELP = {
  low: "Under ₹500 for two",
  medium: "₹501–₹1,000 for two",
  high: "₹1,001 and above for two",
};

const RELAXATION_LABELS = {
  budget_widened: "Budget widened",
  cuisine_dropped: "Cuisine dropped",
  min_rating_lowered: "Minimum rating lowered",
};

const PREFERENCE_LIMIT = 300;
const SUGGESTION_LIMIT = 8;
const API_BASE = String(window.API_BASE || "").replace(/\/$/, "");

const form = document.querySelector("#search-form");
const locality = document.querySelector("#locality");
const budget = document.querySelector("#budget");
const budgetHint = document.querySelector("#budget-hint");
const cuisineInput = document.querySelector("#cuisine");
const cuisineMenu = document.querySelector("#cuisine-menu");
const cuisineSuggestions = document.querySelector("#cuisine-suggestions");
const ratingSlider = document.querySelector("#rating-slider");
const ratingValue = document.querySelector("#rating-val");
const preferences = document.querySelector("#preferences");
const preferenceCount = document.querySelector("#preference-count");
const submitButton = document.querySelector("#submit");
const loadError = document.querySelector("#load-error");

const idle = document.querySelector("#idle");
const statusRow = document.querySelector("#status-row");
const statusLine = document.querySelector("#status-line");
const relaxedRow = document.querySelector("#relaxed");
const fallbackNote = document.querySelector("#fallback");
const summaryPanel = document.querySelector("#summary");
const summaryText = document.querySelector("#summary-text");
const emptyPanel = document.querySelector("#empty");
const emptyText = document.querySelector("#empty-text");
const errorPanel = document.querySelector("#error");
const errorTitle = document.querySelector("#error-title");
const errorDetail = document.querySelector("#error-detail");
const errorSuggestions = document.querySelector("#error-suggestions");
const cards = document.querySelector("#cards");

let cuisines = [];
let metaReady = false;
let inFlight = false;

function titleBand(band) {
  const text = String(band || "");
  if (!text) return "";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatRatingNumber(value) {
  return Number(value).toFixed(1);
}

function setRatingLabel(value) {
  ratingValue.textContent = formatRatingNumber(value);
}

function setBudgetHint(value) {
  budgetHint.textContent = BUDGET_HELP[value] || "";
}

function setPreferenceCount() {
  preferenceCount.textContent = `${preferences.value.length}/${PREFERENCE_LIMIT}`;
}

function clearResults() {
  statusRow.hidden = true;
  statusLine.textContent = "";
  relaxedRow.replaceChildren();
  fallbackNote.hidden = true;
  summaryPanel.hidden = true;
  summaryText.textContent = "";
  emptyPanel.hidden = true;
  emptyText.textContent = "";
  errorPanel.hidden = true;
  errorTitle.textContent = "";
  errorDetail.textContent = "";
  errorSuggestions.replaceChildren();
  cards.replaceChildren();
}

function showStatus(text) {
  statusLine.textContent = text;
  statusRow.hidden = false;
}

function formStatus() {
  const cuisine = cuisineInput.value.trim() || "Any cuisine";
  return [
    locality.value,
    titleBand(budget.value),
    cuisine,
    `${formatRatingNumber(ratingSlider.value)}+`,
  ].join(" · ");
}

function appliedStatus(filters) {
  const bands = Array.isArray(filters.budget) ? filters.budget : [filters.budget];
  const budgetText = bands.filter(Boolean).map(titleBand).join(", ");
  return [
    filters.location,
    budgetText,
    filters.cuisine || "Any cuisine",
    `${formatRatingNumber(filters.min_rating)}+`,
  ].join(" · ");
}

function showRelaxations(names) {
  relaxedRow.replaceChildren();
  const labels = (names || []).map((name) => RELAXATION_LABELS[name] || name).filter(Boolean);
  for (const label of labels) {
    const chip = document.createElement("span");
    chip.textContent = label;
    relaxedRow.append(chip);
  }
}

function renderSuggestions(query) {
  const needle = query.trim().toLowerCase();
  const matches = cuisines
    .filter((name) => !needle || name.toLowerCase().includes(needle))
    .slice(0, SUGGESTION_LIMIT);
  cuisineSuggestions.replaceChildren();
  if (!matches.length) {
    const empty = document.createElement("li");
    empty.className = "empty-suggestion";
    empty.textContent = "No matching cuisine. You can still search with this text.";
    cuisineSuggestions.append(empty);
    return;
  }
  for (const name of matches) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.value = name;
    const label = document.createElement("span");
    label.textContent = name;
    button.append(label);
    if (name.toLowerCase() === needle) {
      button.className = "active";
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = "Active";
      button.append(badge);
    }
    button.addEventListener("mousedown", (event) => {
      event.preventDefault();
      cuisineInput.value = name;
      cuisineMenu.hidden = true;
      cuisineInput.focus();
    });
    item.append(button);
    cuisineSuggestions.append(item);
  }
}

function openCuisineMenu() {
  if (!metaReady) return;
  renderSuggestions(cuisineInput.value);
  cuisineMenu.hidden = false;
}

function metaLine(card) {
  const types = Array.isArray(card.rest_type) ? card.rest_type.filter(Boolean) : [];
  return [card.address, types.join(", ")].filter(Boolean).join(" · ");
}

function ratingFact(value) {
  const wrapper = document.createElement("div");
  wrapper.className = "fact";
  const label = document.createElement("span");
  label.textContent = "Rating";
  const number = document.createElement("strong");
  if (value === null || value === undefined) {
    number.className = "unavailable";
    number.textContent = "Unavailable";
  } else {
    number.className = "rating";
    number.textContent = formatRatingNumber(value);
  }
  wrapper.append(label, number);
  return wrapper;
}

function costFact(value) {
  const wrapper = document.createElement("div");
  wrapper.className = "fact";
  const label = document.createElement("span");
  label.textContent = "Cost";
  const number = document.createElement("strong");
  if (value === null || value === undefined) {
    number.className = "unavailable";
    number.textContent = "Unknown cost";
  } else {
    number.textContent = `₹${Number(value).toLocaleString("en-IN")} for two`;
  }
  wrapper.append(label, number);
  return wrapper;
}

function renderCard(card) {
  const article = document.createElement("article");
  article.className = "card";

  const head = document.createElement("div");
  head.className = "card-head";
  const rank = document.createElement("span");
  rank.className = "rank";
  rank.textContent = String(card.rank);
  const titles = document.createElement("div");
  const name = document.createElement("h2");
  name.className = "card-name";
  name.textContent = card.name || "";
  const meta = document.createElement("p");
  meta.className = "card-meta";
  meta.textContent = metaLine(card);
  titles.append(name, meta);
  head.append(rank, titles);

  const cuisineRow = document.createElement("div");
  cuisineRow.className = "chips";
  for (const cuisine of card.cuisines || []) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = cuisine;
    cuisineRow.append(chip);
  }

  const facts = document.createElement("div");
  facts.className = "facts";
  const divider = document.createElement("span");
  divider.className = "divider";
  facts.append(ratingFact(card.rating), divider, costFact(card.cost_for_two));

  const explanation = document.createElement("p");
  explanation.className = "explanation";
  explanation.textContent = card.explanation || "";

  article.append(head);
  if (cuisineRow.childNodes.length) article.append(cuisineRow);
  article.append(facts, explanation);
  return article;
}

function showSuccess(body) {
  clearResults();
  idle.hidden = true;
  showStatus(appliedStatus(body.filters_applied || {}));
  showRelaxations(body.filters_applied && body.filters_applied.relaxed);
  const recommendations = body.recommendations || [];
  if (!recommendations.length) {
    emptyText.textContent = body.summary || "No restaurants match this search. Try another locality or a lower rating.";
    emptyPanel.hidden = false;
    return;
  }
  if (body.explanation_source === "fallback") fallbackNote.hidden = false;
  if (body.summary) {
    summaryText.textContent = body.summary;
    summaryPanel.hidden = false;
  }
  for (const card of recommendations) cards.append(renderCard(card));
}

function suggestionTarget(field) {
  if (field === "location") return locality;
  if (field === "cuisine") return cuisineInput;
  return null;
}

function showError(payload, statusText) {
  clearResults();
  idle.hidden = true;
  showStatus(formStatus());
  const field = payload && payload.field;
  const detail = (payload && payload.detail) || statusText || "The search could not be completed.";
  if (field === "cuisine") errorTitle.textContent = "Unknown cuisine";
  else if (field === "location") errorTitle.textContent = "Unknown locality";
  else errorTitle.textContent = "Check the form";
  errorDetail.textContent = detail;
  const suggestions = (payload && payload.suggestions) || [];
  for (const name of suggestions) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = name;
    button.addEventListener("click", () => {
      const target = suggestionTarget(field);
      if (!target) return;
      target.value = name;
      if (target === cuisineInput) cuisineMenu.hidden = true;
      target.focus();
    });
    errorSuggestions.append(button);
  }
  errorPanel.hidden = false;
}

function setBusy(busy) {
  inFlight = busy;
  submitButton.disabled = busy || !metaReady;
  submitButton.textContent = busy ? "Searching…" : "Recommend";
  form.setAttribute("aria-busy", busy ? "true" : "false");
}

async function readPayload(response) {
  try {
    return await response.json();
  } catch (_error) {
    return null;
  }
}

async function search(event) {
  event.preventDefault();
  if (inFlight || !metaReady) return;
  setBusy(true);
  cuisineMenu.hidden = true;
  const payload = {
    location: locality.value,
    budget: budget.value,
    min_rating: Number(ratingSlider.value),
    additional_preferences: preferences.value,
  };
  const cuisine = cuisineInput.value.trim();
  if (cuisine) payload.cuisine = cuisine;
  try {
    const response = await fetch(`${API_BASE}/api/recommendations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await readPayload(response);
    if (response.ok && body) showSuccess(body);
    else showError(body, response.ok ? "The search could not be completed." : `The search failed (${response.status}).`);
  } catch (_error) {
    showError(null, "The search could not be completed.");
  } finally {
    setBusy(false);
  }
}

function fillLocalities(names) {
  locality.replaceChildren();
  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    locality.append(option);
  }
  const preferred = names.find((name) => name.toLowerCase() === "banashankari");
  if (preferred) locality.value = preferred;
}

function fillBudgets(names) {
  const current = budget.value || "medium";
  budget.replaceChildren();
  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = BUDGET_LABELS[name] || titleBand(name);
    budget.append(option);
  }
  if ([...budget.options].some((option) => option.value === current)) budget.value = current;
  setBudgetHint(budget.value);
}

async function loadMeta() {
  try {
    const response = await fetch(`${API_BASE}/api/meta`);
    if (!response.ok) throw new Error("meta failed");
    const body = await response.json();
    const localities = body.localities || [];
    if (!localities.length) throw new Error("no localities");
    fillLocalities(localities);
    fillBudgets(body.budgets || ["low", "medium", "high"]);
    cuisines = body.cuisines || [];
    const minimum = Number(body.default_min_rating);
    if (!Number.isNaN(minimum)) {
      ratingSlider.value = String(minimum);
      setRatingLabel(minimum);
    }
    metaReady = true;
    submitButton.disabled = false;
    loadError.hidden = true;
  } catch (_error) {
    metaReady = false;
    submitButton.disabled = true;
    locality.replaceChildren();
    loadError.textContent = "The catalog could not be loaded. Refresh the page to try again.";
    loadError.hidden = false;
  }
}

ratingSlider.addEventListener("input", () => setRatingLabel(ratingSlider.value));
budget.addEventListener("change", () => setBudgetHint(budget.value));
preferences.addEventListener("input", setPreferenceCount);
cuisineInput.addEventListener("focus", openCuisineMenu);
cuisineInput.addEventListener("input", openCuisineMenu);
cuisineInput.addEventListener("blur", () => {
  cuisineMenu.hidden = true;
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") cuisineMenu.hidden = true;
});
form.addEventListener("submit", search);

setRatingLabel(ratingSlider.value);
setBudgetHint(budget.value);
setPreferenceCount();
loadMeta();
