/*
Recipe Box ingredient-row behavior.
This small vanilla script adds and removes repeated ingredient fields without a
frontend framework, keeping the form compatible with the lightweight server.
*/

document.addEventListener("DOMContentLoaded", () => {
  const list = document.querySelector("#ingredients-list");
  const template = document.querySelector("#ingredient-row-template");
  const addButton = document.querySelector("#add-ingredient");

  if (!list || !template || !addButton) {
    return;
  }

  addButton.addEventListener("click", () => {
    list.appendChild(template.content.cloneNode(true));
  });

  list.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    const removeButton = target.closest("[data-remove-ingredient]");
    if (removeButton) {
      removeButton.closest(".ingredient-form-row")?.remove();
    }
  });
});