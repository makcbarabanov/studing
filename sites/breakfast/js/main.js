/**
 * Завтрак — hero, медиа. Диалог: js/sveta-fsm.js
 */

const PLACEHOLDER = "assets/images/placeholder.svg";

const HERO_SLIDES = [
  "assets/images/hero.jpg",
  "assets/images/hero-slide-2.jpg",
  "assets/images/hero-slide-4.jpg",
  "assets/images/example-3.jpg",
  "assets/images/example-1.jpg",
  "assets/images/about.jpg",
];

const HERO_SLIDE_INTERVAL_MS = 6500;

/** @type {Record<string, { images?: string[]; videos?: string[]; alt?: string }>} */
const MEDIA_MANIFEST = {
  about: {
    images: [
      "assets/images/about.jpg",
      "assets/images/about.webp",
      "assets/images/завтрак.jpg",
      "assets/images/breakfast-table.jpg",
    ],
    alt: "Участники завтрака за столом",
  },
  "example-1": {
    images: [
      "assets/images/example-1.jpg",
      "assets/images/example-1.webp",
      "assets/images/пример-1.jpg",
    ],
    alt: "Иллюстрация к мечте о книге",
  },
  "example-2": {
    images: [
      "assets/images/example-2.jpg",
      "assets/images/example-2.webp",
      "assets/images/пример-2.jpg",
    ],
    alt: "Иллюстрация к мечте о беге",
  },
  "example-3": {
    images: [
      "assets/images/example-3.jpg",
      "assets/images/example-3.webp",
      "assets/images/пример-3.jpg",
    ],
    alt: "Иллюстрация к мечте о мастерской",
  },
  "promo-video": {
    videos: ["assets/video/promo.mp4"],
  },
};

/** @param {string} url */
function probeUrl(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(url);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

/** @param {string} url */
function probeVideo(url) {
  return new Promise((resolve) => {
    const v = document.createElement("video");
    const done = (ok) => {
      v.removeAttribute("src");
      v.load();
      resolve(ok ? url : null);
    };
    v.preload = "metadata";
    v.onloadeddata = () => done(true);
    v.onerror = () => done(false);
    v.src = url;
  });
}

/** @param {string[] | undefined} candidates */
async function firstAvailable(candidates, probe) {
  if (!candidates?.length) return null;
  for (const path of candidates) {
    const hit = await probe(path);
    if (hit) return hit;
  }
  return null;
}

async function bindMedia() {
  for (const [key, spec] of Object.entries(MEDIA_MANIFEST)) {
    const root = document.querySelector(`[data-media="${key}"]`);
    if (!root) continue;

    const imgEl = root.querySelector(`[data-media-img="${key}"]`) || root.querySelector("[data-media-img]");
    const videoEl = root.querySelector(`[data-media-video="${key}"]`) || root.querySelector("[data-media-video]");
    const fallback = root.querySelector("[data-media-fallback]");

    const imageUrl = await firstAvailable(spec.images, probeUrl);
    const videoUrl = await firstAvailable(spec.videos, probeVideo);

    if (imageUrl && imgEl) {
      imgEl.src = imageUrl;
      imgEl.alt = spec.alt || imgEl.alt || "";
      imgEl.classList.remove("is-hidden");
      if (fallback) fallback.style.display = "none";
      continue;
    }

    if (videoUrl && videoEl) {
      videoEl.src = videoUrl;
      videoEl.classList.remove("is-hidden");
      if (fallback) fallback.classList.add("is-hidden");
      const promoPh = root.querySelector(".promo__placeholder");
      if (promoPh) promoPh.classList.add("is-hidden");
      continue;
    }

    if (imgEl && !imgEl.getAttribute("src")) {
      imgEl.src = PLACEHOLDER;
    }
  }
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function isSlowConnection() {
  const conn = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (!conn) return false;
  if (conn.saveData) return true;
  return ["slow-2g", "2g"].includes(conn.effectiveType);
}

/** @param {string} url */
function loadImage(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(url);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

function mountHeroSlide(container, url, active) {
  const slide = document.createElement("div");
  slide.className = "hero__slide" + (active ? " hero__slide--active" : "");
  slide.style.backgroundImage = `url("${url}")`;
  container.appendChild(slide);
  return slide;
}

async function initHeroBackground() {
  const container = document.getElementById("hero-slides");
  if (!container) return;

  const sliderOk = !prefersReducedMotion() && !isSlowConnection();
  let urls = sliderOk ? HERO_SLIDES : [HERO_SLIDES[0]];
  const loaded = [];

  if (sliderOk) {
    const results = await Promise.all(urls.map(loadImage));
    results.forEach((url) => {
      if (url) loaded.push(url);
    });
  } else {
    for (const url of urls) {
      const hit = await loadImage(url);
      if (hit) {
        loaded.push(hit);
        break;
      }
    }
  }

  if (!loaded.length) return;

  const useSlider = loaded.length > 1 && sliderOk;
  loaded.forEach((url, i) => mountHeroSlide(container, url, i === 0));

  if (!useSlider) return;

  const slides = container.querySelectorAll(".hero__slide");
  let idx = 0;
  window.setInterval(() => {
    slides[idx].classList.remove("hero__slide--active");
    idx = (idx + 1) % slides.length;
    slides[idx].classList.add("hero__slide--active");
  }, HERO_SLIDE_INTERVAL_MS);
}

initHeroBackground();
bindMedia();

function loadBuildVersion() {
  const el = document.getElementById("site-build-version");
  if (!el) return;
  fetch("version.json", { cache: "no-store" })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      const n = data && typeof data.version === "number" ? data.version : null;
      if (n != null) el.textContent = `v.${n}`;
    })
    .catch(() => {});
}

loadBuildVersion();
