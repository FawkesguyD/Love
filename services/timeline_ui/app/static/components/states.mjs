export function clearContainer(node) {
  node.textContent = "";
}

export function renderLoadingState(container) {
  clearContainer(container);

  const skeleton = document.createElement("div");
  skeleton.className = "timeline-skeleton";

  for (let index = 0; index < 4; index += 1) {
    const card = document.createElement("article");
    card.className = `timeline-skeleton-card ${index % 2 === 0 ? "side-left" : "side-right"}`;
    skeleton.append(card);
  }

  container.append(skeleton);
}

function renderPanel(container, { title, message, buttonLabel, onButtonClick }) {
  clearContainer(container);

  const panel = document.createElement("section");
  panel.className = "timeline-panel";
  panel.setAttribute("role", "status");

  const heading = document.createElement("h2");
  heading.textContent = title;
  panel.append(heading);

  const body = document.createElement("p");
  body.textContent = message;
  panel.append(body);

  if (buttonLabel && typeof onButtonClick === "function") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "timeline-retry";
    button.textContent = buttonLabel;
    button.addEventListener("click", onButtonClick);
    panel.append(button);
  }

  container.append(panel);
}

export function renderEmptyState(container) {
  renderPanel(container, {
    title: "Пока нет моментов",
    message: "Добавьте первую карточку, и таймлайн оживёт.",
  });
}

export function renderErrorState(container, message, onRetry) {
  renderPanel(container, {
    title: "Не удалось загрузить таймлайн",
    message,
    buttonLabel: "Retry",
    onButtonClick: onRetry,
  });
}
