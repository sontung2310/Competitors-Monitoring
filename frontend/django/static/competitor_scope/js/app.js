"use strict";

// The UI uses normal Django form submissions. This small layer only makes the
// real multi-second backend calls visible and prevents duplicate submissions;
// it does not fetch or invent any data.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-company-switch] select").forEach((select) => {
    select.addEventListener("change", () => {
      document.body.classList.add("is-navigating");
      select.form.submit();
    });
  });

  document.querySelectorAll("form[data-loading]").forEach((form) => {
    form.addEventListener("submit", () => {
      if (form.dataset.submitting === "true") return;
      form.dataset.submitting = "true";
      form.classList.add("is-loading");
      const button = form.querySelector("button[type=submit]");
      if (!button) return;
      button.disabled = true;
      button.classList.add("is-loading");
      const label = button.querySelector(".button-label");
      const loadingText = form.dataset.loadingText || "Loading…";
      if (label) label.textContent = loadingText;
      else button.textContent = loadingText;
    });
  });

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });
});
