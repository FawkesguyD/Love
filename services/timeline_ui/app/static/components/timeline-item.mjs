import { formatMomentDateTime } from "../timeline-data.mjs";

function createImageNode({ imageUrl, altText, tileClass }) {
  const item = document.createElement("figure");
  item.className = tileClass;

  if (!imageUrl) {
    const fallback = document.createElement("div");
    fallback.className = "spiral-fallback";
    fallback.textContent = "Photo unavailable";
    item.append(fallback);
    return item;
  }

  const image = document.createElement("img");
  image.className = "spiral-image";
  image.src = imageUrl;
  image.alt = altText;
  image.loading = "lazy";
  image.decoding = "async";

  image.addEventListener("error", () => {
    item.textContent = "";

    const fallback = document.createElement("div");
    fallback.className = "spiral-fallback";
    fallback.textContent = "Photo unavailable";
    item.append(fallback);
  });

  item.append(image);
  return item;
}

function createSingleImageElement(moment, imageUrl) {
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

function createSpiralGallery(moment, imageUrls) {
  const mediaNode = document.createElement("section");
  mediaNode.className = "timeline-media";

  const grid = document.createElement("div");
  const shownImages = imageUrls.slice(0, 6);
  const count = Math.max(2, Math.min(6, shownImages.length));
  grid.className = `timeline-spiral count-${count}`;

  shownImages.forEach((imageUrl, imageIndex) => {
    const tileNumber = imageIndex + 1;
    const altText = `${moment.title} image ${tileNumber}`;
    const tile = createImageNode({
      imageUrl,
      altText,
      tileClass: `spiral-item spiral-item-${tileNumber}`,
    });
    grid.append(tile);
  });

  mediaNode.append(grid);

  const hiddenCount = Math.max(0, moment.images.length - shownImages.length);
  if (hiddenCount > 0) {
    const badge = document.createElement("p");
    badge.className = "timeline-spiral-more";
    badge.textContent = `+${hiddenCount}`;
    mediaNode.append(badge);
  }

  return mediaNode;
}

function formatDotBadge(dateIso) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(dateIso));
}

export function createMomentCard({ moment, index, imageUrls, revealObserver }) {
  const side = index % 2 === 0 ? "left" : "right";

  const card = document.createElement("article");
  card.className = `timeline-card side-${side}`;
  card.setAttribute("role", "listitem");
  card.tabIndex = 0;

  const dot = document.createElement("span");
  dot.className = "timeline-dot";
  dot.setAttribute("aria-hidden", "true");
  card.append(dot);

  const dotBadge = document.createElement("span");
  dotBadge.className = "timeline-dot-badge";
  dotBadge.textContent = formatDotBadge(moment.dateIso);
  card.append(dotBadge);

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

  const validImageUrls = imageUrls.filter((imageUrl) => typeof imageUrl === "string" || imageUrl === null);
  if (validImageUrls.length <= 1) {
    card.append(createSingleImageElement(moment, validImageUrls[0] || null));
  } else {
    card.append(createSpiralGallery(moment, validImageUrls));
  }

  if (revealObserver) {
    revealObserver.observe(card);
  } else {
    card.classList.add("is-visible");
  }

  return card;
}
