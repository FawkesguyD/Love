import { formatDayLabel, formatMomentDateTime } from "../timeline-data.mjs";

export function createDayDivider(dateIso) {
  const divider = document.createElement("section");
  divider.className = "timeline-day";

  const label = document.createElement("h2");
  label.className = "timeline-day-label";
  label.textContent = formatDayLabel(dateIso);
  divider.append(label);

  return divider;
}

function createImageElement(moment, imageUrl) {
  const figure = document.createElement("figure");
  figure.className = "timeline-image-wrap";

  if (!imageUrl) {
    const fallback = document.createElement("div");
    fallback.className = "timeline-image-fallback";
    fallback.textContent = "Photo unavailable";
    figure.append(fallback);
    return figure;
  }

  figure.classList.add("is-loading");

  const image = document.createElement("img");
  image.className = "timeline-image";
  image.src = imageUrl;
  image.alt = moment.title;
  image.loading = "lazy";
  image.decoding = "async";

  image.addEventListener("load", () => {
    figure.classList.remove("is-loading");
  });

  image.addEventListener("error", () => {
    figure.classList.remove("is-loading");
    figure.textContent = "";

    const fallback = document.createElement("div");
    fallback.className = "timeline-image-fallback";
    fallback.textContent = "Photo unavailable";
    figure.append(fallback);
  });

  figure.append(image);
  return figure;
}

export function createMomentCard({ moment, index, imageUrl, revealObserver }) {
  const side = index % 2 === 0 ? "left" : "right";

  const card = document.createElement("article");
  card.className = `timeline-card side-${side}`;
  card.setAttribute("role", "listitem");
  card.tabIndex = 0;

  const dot = document.createElement("span");
  dot.className = "timeline-dot";
  dot.setAttribute("aria-hidden", "true");
  card.append(dot);

  const dateNode = document.createElement("p");
  dateNode.className = "timeline-date";
  dateNode.textContent = formatMomentDateTime(moment.dateIso);
  card.append(dateNode);

  const title = document.createElement("h3");
  title.className = "timeline-card-title";
  title.textContent = moment.title;
  card.append(title);

  if (moment.text) {
    const text = document.createElement("p");
    text.className = "timeline-text";
    text.textContent = moment.text;
    card.append(text);
  }

  card.append(createImageElement(moment, imageUrl));

  if (revealObserver) {
    revealObserver.observe(card);
  } else {
    card.classList.add("is-visible");
  }

  return card;
}
