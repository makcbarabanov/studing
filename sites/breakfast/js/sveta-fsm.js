/**
 * Завтрак — UI state machine (States 1–7).
 * States 1–5: inline на лендинге. States 6–7: модалка поверх.
 */
(function () {
  const S = {
    GREETING: 1,
    DREAMS: 2,
    REACTION_1: 3,
    BARRIERS: 4,
    REACTION_2: 5,
    FORM: 6,
    SUCCESS: 7,
  };

  const INLINE_STATES = [S.GREETING, S.DREAMS, S.REACTION_1, S.BARRIERS, S.REACTION_2];

  const TEXT = {
    s1: `Привет! Меня зовут Светлана. Я автор проекта «Завтрак, исполняющий желания» и со-творец твоей мечты. Я здесь, чтобы помочь тебе приблизиться к желаемому. Для начала представься, пожалуйста: как тебя зовут?`,
    s2: (name) =>
      `Очень приятно, ${name}! Поделись, о чем ты мечтаешь? Напиши одну или несколько своих мечт, и я отправлю их в нашу копилку.`,
    s2more: "Внимательно слушаю, что еще добавим?",
    s4more: "Что еще может помешать или чего не хватает?",
    s6: "Почти всё! Оставь свои данные — команда уже ждёт твои мечты.",
    s7: "Спасибо тебе! Скоро с тобой свяжется наш творец мечты, возьмёт тебя за руку, и вы вместе пойдёте реализовывать задуманное.",
    aiError: "Ой, магия немного зависла. Можешь отправить еще раз?",
    dbError: "Не удалось сохранить, попробуй еще раз",
  };

  const SVETA_VIDEO = {
    hello: "assets/video/sveta_hello.mp4",
    listen: "assets/video/sveta_listen.mp4",
    clap: "assets/video/sveta_clap.mp4",
  };

  function normalizeName(raw) {
    let s = raw.trim();
    if (!s) return "";
    let m = s.match(/(?:меня\s+зовут|this\s+is)\s+([a-zA-Zа-яА-ЯёЁ\-]+)/iu);
    if (m) s = m[1];
    else {
      m = s.match(/^я\s+([a-zA-Zа-яА-ЯёЁ\-]+)/iu);
      if (m) s = m[1];
    }
    if (/\s/.test(s) && s.length > 12) {
      const parts = s.split(/[\s,]+/).filter(Boolean);
      const last = parts[parts.length - 1] || "";
      if (last.length >= 2 && last.length <= 20 && /^[a-zA-Zа-яА-ЯёЁ\-]+$/u.test(last)) s = last;
    }
    return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
  }

  function splitLines(text) {
    const out = [];
    for (const part of text.replace(/;/g, "\n").split("\n")) {
      const chunk = part.trim().replace(/^[•\-*\d.)]+\s*/, "");
      if (chunk) out.push(chunk);
    }
    return out;
  }

  function apiBase() {
    const custom = typeof window.ISLAND_API_BASE === "string" ? window.ISLAND_API_BASE.trim() : "";
    return custom ? custom.replace(/\/$/, "") : "";
  }

  async function apiChat(payload) {
    const base = apiBase();
    let res;
    try {
      res = await fetch(`${base}/api/v1/funnel/breakfast/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId(), ...payload }),
      });
    } catch {
      throw new Error("network");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail;
      const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg : "";
      throw new Error(msg || "api");
    }
    return data;
  }

  function sessionId() {
    const key = "breakfast_session_id";
    try {
      let id = sessionStorage.getItem(key);
      if (!id) {
        id =
          typeof crypto !== "undefined" && crypto.randomUUID
            ? crypto.randomUUID()
            : `bf-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
        sessionStorage.setItem(key, id);
      }
      return id;
    } catch {
      return `bf-${Date.now()}`;
    }
  }

  /** Fire-and-forget: JSONL на бэке (logs/chat_sessions.jsonl). */
  function logEvent(payload) {
    const base = apiBase();
    fetch(`${base}/api/v1/funnel/breakfast/log`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId(), ...payload }),
    }).catch(() => {});
  }

  function createMessage(text, role) {
    const el = document.createElement("div");
    el.className = `msg msg--${role}`;
    el.textContent = text;
    return el;
  }

  function createSvetaAvatar(videoEl, wrapEl) {
    if (!videoEl || !wrapEl) {
      return { playHello: () => {}, playListen: () => {}, playClap: () => {} };
    }
    let current = "idle";
    let chain = Promise.resolve();

    function setPlaying(on) {
      wrapEl.classList.toggle("is-playing", on);
      wrapEl.classList.toggle("is-fallback", !on);
    }

    function playClip(clip, loop) {
      const src = SVETA_VIDEO[clip];
      if (!src) return Promise.resolve();
      current = clip;
      videoEl.muted = true;
      videoEl.playsInline = true;
      videoEl.setAttribute("muted", "");
      videoEl.setAttribute("playsinline", "");
      videoEl.loop = loop;
      if (videoEl.dataset.clip !== clip) {
        videoEl.dataset.clip = clip;
        videoEl.src = src;
        videoEl.load();
      }
      return videoEl
        .play()
        .then(() => setPlaying(true))
        .catch(() => setPlaying(false));
    }

    function enqueue(fn) {
      chain = chain.then(fn).catch(() => {});
      return chain;
    }

    videoEl.addEventListener("ended", () => {
      if (videoEl.dataset.clip === "hello" || videoEl.dataset.clip === "clap") {
        enqueue(() => playClip("listen", true));
      }
    });
    videoEl.addEventListener("error", () => setPlaying(false));

    return {
      playHello: () => enqueue(() => playClip("hello", false)),
      playListen: () => enqueue(() => playClip("listen", true)),
      playClap: () => enqueue(() => playClip("clap", false)),
    };
  }

  const CHANNEL_LABELS = {
    telegram: "Telegram",
    max: "Макс",
    vk: "VK",
    whatsapp: "WhatsApp",
    email: "Email",
  };

  /** @type {Record<string, { fieldLabel?: string, placeholder?: string, inputType?: string, mode: string }>} */
  const CHANNEL_UI = {
    telegram: {
      fieldLabel: "Юзернейм",
      placeholder: "Введите ваш @telegram",
      inputType: "text",
      mode: "username",
    },
    max: {
      fieldLabel: "Юзернейм",
      placeholder: "Введите username в Макс",
      inputType: "text",
      mode: "username",
    },
    vk: {
      fieldLabel: "Ссылка",
      placeholder: "Вставьте ссылку на профиль",
      inputType: "text",
      mode: "vk",
    },
    whatsapp: { mode: "whatsapp" },
    email: {
      fieldLabel: "Email",
      placeholder: "you@example.com",
      inputType: "email",
      mode: "email",
    },
  };

  function phoneDigits(input) {
    return input ? input.value.replace(/\D/g, "") : "";
  }

  function isEmailValid(value) {
    const v = value.trim();
    return v.length >= 5 && v.includes("@") && v.includes(".");
  }

  function bindPhoneMask(input) {
    if (!input) return;
    input.addEventListener("input", () => {
      let digits = input.value.replace(/\D/g, "");
      if (digits.startsWith("8")) digits = "7" + digits.slice(1);
      if (digits.startsWith("7")) digits = digits.slice(1);
      digits = digits.slice(0, 10);
      let formatted = "+7";
      if (digits.length > 0) formatted += " (" + digits.slice(0, 3);
      if (digits.length >= 3) formatted += ") " + digits.slice(3, 6);
      if (digits.length >= 6) formatted += "-" + digits.slice(6, 8);
      if (digits.length >= 8) formatted += "-" + digits.slice(8, 10);
      input.value = formatted;
    });
  }

  function initBreakfastFsm() {
    const overlay = document.getElementById("sveta-overlay-modal");
    const overlayBackdrop = document.getElementById("sveta-overlay-backdrop");
    const overlayClose = document.getElementById("sveta-overlay-close");
    const formView = document.getElementById("sveta-form-view");
    const successView = document.getElementById("sveta-success-view");
    const successText = document.getElementById("sveta-success-text");

    const messagesEl = document.getElementById("sveta-messages");
    const composer = document.getElementById("sveta-composer");
    const input = /** @type {HTMLInputElement} */ (document.getElementById("sveta-input"));
    const sendBtn = document.getElementById("sveta-send");
    const branchEl = document.getElementById("sveta-branch");
    const btnAddDream = document.getElementById("sveta-btn-add-dream");
    const btnGoOn = document.getElementById("sveta-btn-go-on");
    const btnAddDream2 = document.getElementById("sveta-btn-add-dream-2");
    const btnAddComment = document.getElementById("sveta-btn-add-comment");
    const btnNext = document.getElementById("sveta-btn-next");
    const btnCloseSuccess = document.getElementById("sveta-btn-close");

    const avatar = createSvetaAvatar(
      document.getElementById("sveta-inline-video"),
      document.getElementById("sveta-inline-avatar")
    );

    const form = /** @type {HTMLFormElement} */ (document.getElementById("sveta-contact-form"));
    const formName = /** @type {HTMLInputElement} */ (document.getElementById("sveta-form-name"));
    const formCity = /** @type {HTMLInputElement} */ (document.getElementById("sveta-form-city"));
    const formPhone = /** @type {HTMLInputElement} */ (document.getElementById("sveta-form-phone"));
    const channelBtns = form?.querySelectorAll("[data-channel]");
    const channelInputRow = document.getElementById("sveta-channel-input-row");
    const channelInputLabel = document.getElementById("sveta-channel-input-label");
    const channelInput = /** @type {HTMLInputElement | null} */ (
      document.getElementById("sveta-channel-input")
    );
    const channelPhoneLinked = document.getElementById("sveta-channel-phone-linked");
    const channelPhoneLinkedCb = /** @type {HTMLInputElement | null} */ (
      document.getElementById("sveta-channel-phone-linked-cb")
    );
    const channelHint = document.getElementById("sveta-channel-hint");
    const formError = document.getElementById("sveta-form-error");
    const formSubmit = document.getElementById("sveta-form-submit");

    if (!messagesEl || !input || !sendBtn) return;

    bindPhoneMask(formPhone);

    const data = {
      userName: "",
      dreams: /** @type {string[]} */ ([]),
      barriers: /** @type {string[]} */ ([]),
    };

    /** @type {string | null} */
    let activeChannel = null;
    /** @type {Record<string, { username?: string, phoneLinked?: boolean, vk?: string, email?: string }>} */
    const channelStore = {};

    let uiState = S.GREETING;
    let loading = false;
    let started = false;

    function appendBot(text) {
      const t = String(text || "").trim();
      if (!t) return;
      messagesEl.appendChild(createMessage(t, "bot"));
      messagesEl.scrollTop = messagesEl.scrollHeight;
      logEvent({ event: "bot_message", state: uiState, text: t });
    }

    function appendUser(text) {
      const t = String(text || "").trim();
      if (!t) return;
      messagesEl.appendChild(createMessage(t, "user"));
      messagesEl.scrollTop = messagesEl.scrollHeight;
      logEvent({ event: "user_message", state: uiState, text: t });
    }

    function setLoading(on) {
      loading = on;
      syncUi();
    }

    function inputMinLen() {
      if (uiState === S.GREETING) return 2;
      return 1;
    }

    function canSendText() {
      if (loading) return false;
      if (!INLINE_STATES.includes(uiState)) return false;
      return input.value.trim().length >= inputMinLen();
    }

    function syncComposer() {
      const showComposer = INLINE_STATES.includes(uiState);
      if (composer) composer.hidden = !showComposer;
      if (branchEl) {
        branchEl.hidden = uiState !== S.REACTION_1 && uiState !== S.REACTION_2;
        branchEl.dataset.mode = uiState === S.REACTION_2 ? "three" : "two";
      }

      input.disabled = loading || !showComposer;
      sendBtn.disabled = loading || !showComposer || !canSendText();

      [btnAddDream, btnGoOn, btnAddDream2, btnAddComment, btnNext].forEach((btn) => {
        if (btn) btn.disabled = loading;
      });

      if (uiState === S.GREETING) input.placeholder = "Твоё имя…";
      else if (uiState === S.DREAMS) input.placeholder = "Твоя мечта…";
      else if (uiState === S.REACTION_1) input.placeholder = "Или напиши ещё мечту…";
      else if (uiState === S.BARRIERS) input.placeholder = "Напиши от сердца…";
      else if (uiState === S.REACTION_2) input.placeholder = "Или добавь комментарий…";
    }

    function syncUi() {
      syncComposer();
      updateChannelButtons();
      syncPhoneField();
      if (formSubmit) formSubmit.disabled = loading || !formValid();
    }

    function phoneRequired() {
      if (!activeChannel) return false;
      if (activeChannel === "whatsapp") return true;
      const stored = channelStore[activeChannel] || {};
      return (
        (activeChannel === "telegram" || activeChannel === "max") && !!stored.phoneLinked
      );
    }

    function syncPhoneField() {
      const wrap = formPhone?.closest(".sveta-form-row");
      const missing = phoneRequired() && phoneDigits(formPhone).length < 10;
      wrap?.classList.toggle("is-field-error", missing);
      formPhone?.classList.toggle("is-invalid", missing);
    }

    function readFieldValues(id) {
      const mode = CHANNEL_UI[id]?.mode;
      if (mode === "username") {
        channelStore[id] = {
          username: channelInput?.value || "",
          phoneLinked: !!channelPhoneLinkedCb?.checked,
        };
      } else if (mode === "vk") {
        channelStore[id] = { vk: channelInput?.value || "" };
      } else if (mode === "email") {
        channelStore[id] = { email: channelInput?.value || "" };
      } else if (mode === "whatsapp") {
        channelStore[id] = {};
      }
    }

    function persistActiveChannelValues() {
      if (activeChannel) readFieldValues(activeChannel);
    }

    function isChannelValid(id) {
      const stored = channelStore[id] || {};
      if (id === "whatsapp") {
        return phoneDigits(formPhone).length >= 10;
      }
      if (id === "email") {
        return isEmailValid(stored.email || "");
      }
      if (id === "vk") {
        return (stored.vk || "").trim().length >= 2;
      }
      if (id === "telegram" || id === "max") {
        const hasUser = (stored.username || "").trim().length >= 2;
        if (stored.phoneLinked) return phoneDigits(formPhone).length >= 10;
        return hasUser;
      }
      return false;
    }

    function formValid() {
      if (!formName?.value.trim() || !formCity?.value.trim()) return false;
      if (!activeChannel) return false;
      if (phoneRequired() && phoneDigits(formPhone).length < 10) return false;
      return isChannelValid(activeChannel);
    }

    function updateChannelButtons() {
      channelBtns?.forEach((btn) => {
        const id = btn.getAttribute("data-channel") || "";
        const isActive = activeChannel === id;
        btn.classList.toggle("is-active", isActive);
        btn.classList.toggle("is-filled", isActive && isChannelValid(id));
        btn.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
    }

    function renderChannelSlot(id) {
      const ui = CHANNEL_UI[id];
      if (!ui) return;

      channelInputRow?.classList.remove("is-visible");
      channelHint?.classList.remove("is-visible");
      if (channelInputRow) channelInputRow.hidden = true;
      if (channelPhoneLinked) channelPhoneLinked.hidden = true;
      if (channelHint) channelHint.hidden = true;

      if (ui.mode === "whatsapp") {
        if (channelHint) {
          channelHint.textContent = "Будем использовать номер телефона из поля выше.";
          channelHint.hidden = false;
        }
        requestAnimationFrame(() => channelHint?.classList.add("is-visible"));
        return;
      }

      const stored = channelStore[id] || {};
      if (channelInputLabel) channelInputLabel.textContent = ui.fieldLabel || "Контакт";
      if (channelInput) {
        channelInput.type = ui.inputType || "text";
        channelInput.placeholder = ui.placeholder || "";
        channelInput.value =
          ui.mode === "username"
            ? stored.username || ""
            : ui.mode === "vk"
              ? stored.vk || ""
              : ui.mode === "email"
                ? stored.email || ""
                : "";
      }
      if (ui.mode === "username" && channelPhoneLinkedCb) {
        channelPhoneLinkedCb.checked = !!stored.phoneLinked;
        if (channelPhoneLinked) channelPhoneLinked.hidden = false;
      }
      if (channelInputRow) {
        channelInputRow.hidden = false;
        requestAnimationFrame(() => channelInputRow.classList.add("is-visible"));
      }
    }

    function selectChannel(id) {
      if (!id) return;
      if (id !== activeChannel) persistActiveChannelValues();
      if (id === activeChannel) {
        syncUi();
        return;
      }
      activeChannel = id;
      renderChannelSlot(id);
      updateChannelButtons();
      syncUi();
      if (channelInput && !channelInputRow?.hidden) channelInput.focus();
    }

    channelInput?.addEventListener("input", () => {
      if (activeChannel) readFieldValues(activeChannel);
      syncUi();
    });
    channelPhoneLinkedCb?.addEventListener("change", () => {
      if (activeChannel) readFieldValues(activeChannel);
      syncUi();
    });

    channelBtns?.forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-channel") || "";
        logEvent({ event: "button", state: uiState, button: CHANNEL_LABELS[id] || id });
        selectChannel(id);
      });
    });

    [formName, formCity, formPhone].forEach((el) => el?.addEventListener("input", syncUi));

    function openOverlay(mode) {
      if (!overlay) return;
      overlay.hidden = false;
      overlay.setAttribute("aria-hidden", "false");
      document.body.style.overflow = "hidden";
      if (formView) formView.hidden = mode !== "form";
      if (successView) successView.hidden = mode !== "success";
    }

    function closeOverlay() {
      if (!overlay) return;
      overlay.hidden = true;
      overlay.setAttribute("aria-hidden", "true");
      document.body.style.overflow = "";
      if (formView) formView.hidden = false;
      if (successView) successView.hidden = true;
      if (formError) formError.hidden = true;
      if (uiState === S.SUCCESS || uiState === S.FORM) {
        uiState = S.REACTION_2;
      }
      syncUi();
    }

    function startInlineChat() {
      if (started) return;
      started = true;
      appendBot(TEXT.s1);
      avatar.playHello();
      goState(S.GREETING);
    }

    async function callAi(kind, message) {
      setLoading(true);
      avatar.playListen();
      try {
        const res = await apiChat({
          action: "ai",
          ai_kind: kind,
          user_name: data.userName,
          dreams: data.dreams,
          barriers: data.barriers,
          message: message || undefined,
        });
        if (!res.reply) {
          appendBot(TEXT.aiError);
          return false;
        }
        appendBot(res.reply);
        return res.ok !== false;
      } catch {
        appendBot(TEXT.aiError);
        return false;
      } finally {
        setLoading(false);
      }
    }

    function goState(next) {
      if (next !== uiState) {
        logEvent({ event: "state_change", state: next, meta: { from: uiState } });
      }
      uiState = next;
      syncUi();
    }

    async function submitDreams(text) {
      if (loading) return;
      const chunks = splitLines(text);
      data.dreams.push(...chunks.filter((c) => !data.dreams.includes(c)));
      const ok = await callAi("dreams_reaction", text);
      if (ok) {
        avatar.playClap();
        goState(S.REACTION_1);
      }
    }

    async function submitBarriers(text) {
      if (loading) return;
      const chunks = splitLines(text);
      data.barriers.push(...chunks.filter((c) => !data.barriers.includes(c)));
      const ok = await callAi("barriers_reaction", text);
      if (ok) goState(S.REACTION_2);
    }

    async function openBarriersStage() {
      if (loading) return;
      goState(S.BARRIERS);
      setLoading(true);
      avatar.playListen();
      try {
        const res = await apiChat({
          action: "ai",
          ai_kind: "barriers_open",
          user_name: data.userName,
          dreams: data.dreams,
          barriers: data.barriers,
        });
        if (!res.ok || !res.reply) appendBot(TEXT.aiError);
        else appendBot(res.reply);
      } catch {
        appendBot(TEXT.aiError);
      } finally {
        setLoading(false);
        input.focus();
      }
    }

    function openContactForm() {
      if (loading) return;
      appendBot(TEXT.s6);
      if (formName) formName.value = data.userName;
      goState(S.FORM);
      openOverlay("form");
      formName?.focus();
    }

    async function onSendText() {
      const text = input.value.trim();
      if (!canSendText()) return;
      input.value = "";
      appendUser(text);
      syncUi();

      if (uiState === S.GREETING) {
        data.userName = normalizeName(text);
        appendBot(TEXT.s2(data.userName));
        goState(S.DREAMS);
        avatar.playListen();
        return;
      }

      if (uiState === S.DREAMS) {
        await submitDreams(text);
        return;
      }

      if (uiState === S.REACTION_1) {
        await submitDreams(text);
        return;
      }

      if (uiState === S.BARRIERS) {
        await submitBarriers(text);
        return;
      }

      if (uiState === S.REACTION_2) {
        await submitBarriers(text);
        return;
      }
    }

    composer?.addEventListener("submit", (e) => {
      e.preventDefault();
      onSendText();
    });

    input.addEventListener("input", syncUi);

    btnAddDream?.addEventListener("click", () => {
      logEvent({ event: "button", state: uiState, button: "Добавить ещё" });
      appendBot(TEXT.s2more);
      goState(S.DREAMS);
      avatar.playListen();
      input.focus();
    });

    btnGoOn?.addEventListener("click", () => {
      logEvent({ event: "button", state: uiState, button: "Идём дальше" });
      openBarriersStage();
    });

    btnAddDream2?.addEventListener("click", () => {
      logEvent({ event: "button", state: uiState, button: "Добавить мечту" });
      appendBot(TEXT.s2more);
      goState(S.DREAMS);
      avatar.playListen();
      input.focus();
    });

    btnAddComment?.addEventListener("click", () => {
      logEvent({ event: "button", state: uiState, button: "Добавить комментарий" });
      appendBot(TEXT.s4more);
      goState(S.BARRIERS);
      avatar.playListen();
      input.focus();
    });

    btnNext?.addEventListener("click", () => {
      logEvent({ event: "button", state: uiState, button: "Дальше" });
      openContactForm();
    });

    form?.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!formValid() || loading) return;
      setLoading(true);
      if (formError) formError.hidden = true;

      if (activeChannel) readFieldValues(activeChannel);
      const contacts = [];
      if (activeChannel) {
        const id = activeChannel;
        const stored = channelStore[id] || {};
        if (id === "telegram" || id === "max") {
          contacts.push({
            channel: id,
            value: (stored.username || "").trim() || undefined,
            phone_linked: !!stored.phoneLinked,
          });
        } else if (id === "vk") {
          contacts.push({ channel: id, value: (stored.vk || "").trim() || undefined });
        } else if (id === "email") {
          contacts.push({ channel: id, value: (stored.email || "").trim() || undefined });
        } else if (id === "whatsapp") {
          contacts.push({ channel: id });
        }
      }

      logEvent({ event: "button", state: uiState, button: "Отправить мечты в работу" });
      try {
        await apiChat({
          action: "save",
          name: formName.value.trim(),
          city: formCity.value.trim(),
          phone: formPhone.value.trim(),
          contacts,
          dreams: data.dreams,
          barriers: data.barriers,
        });
        appendBot(TEXT.s7);
        if (successText) successText.textContent = TEXT.s7;
        goState(S.SUCCESS);
        openOverlay("success");
        avatar.playHello();
      } catch {
        if (formError) {
          formError.textContent = TEXT.dbError;
          formError.hidden = false;
        }
      } finally {
        setLoading(false);
      }
    });

    overlayClose?.addEventListener("click", closeOverlay);
    overlayBackdrop?.addEventListener("click", closeOverlay);
    btnCloseSuccess?.addEventListener("click", closeOverlay);

    startInlineChat();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initBreakfastFsm);
  } else {
    initBreakfastFsm();
  }
})();
