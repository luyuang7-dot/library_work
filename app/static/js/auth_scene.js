document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-auth-scene]").forEach(setupAuthScene);
});

function setupAuthScene(root) {
  const characters = Array.from(root.querySelectorAll("[data-auth-character]"));
  if (!characters.length) return;

  const textInputs = Array.from(root.querySelectorAll("[data-auth-text-input]"));
  const passwordInputs = Array.from(root.querySelectorAll("[data-auth-password]"));
  const toggles = Array.from(root.querySelectorAll("[data-auth-password-toggle]"));

  let mouseX = window.innerWidth / 2;
  let mouseY = window.innerHeight / 2;
  let isTyping = false;
  let lookAtEachOther = false;
  let passwordVisible = false;
  let passwordHasValue = false;
  let purplePeeking = false;
  let typingTimer = null;
  let peekTimer = null;

  const socials = Array.from(root.querySelectorAll("[data-auth-social]"));

  const blinkState = new Map();
  characters.forEach(character => {
    blinkState.set(character, { timeout: null, active: false });
    scheduleBlink(character, blinkState);
  });

  document.addEventListener("mousemove", onMouseMove);
  textInputs.forEach(input => {
    input.addEventListener("focus", startTypingMode);
    input.addEventListener("blur", stopTypingModeSoon);
    input.addEventListener("input", startTypingMode);
  });

  passwordInputs.forEach(input => {
    input.addEventListener("focus", startTypingMode);
    input.addEventListener("blur", stopTypingModeSoon);
    input.addEventListener("input", () => {
      passwordHasValue = passwordInputs.some(field => field.value.length > 0);
      startTypingMode();
      syncPasswordPeeking();
    });
  });

  socials.forEach(button => {
    button.addEventListener("click", event => {
      if (button.tagName === "A") event.preventDefault();
      const note = root.querySelector("[data-auth-social-note]");
      if (note) note.classList.remove("d-none");
    });
  });

  toggles.forEach(toggle => {
    toggle.addEventListener("click", () => {
      const wrap = toggle.closest(".auth-form__password-wrap");
      const input = wrap ? wrap.querySelector("[data-auth-password]") : null;
      if (!input) return;
      const nextType = input.type === "password" ? "text" : "password";
      input.type = nextType;
      passwordVisible = nextType === "text";
      syncToggleIcons(toggle, passwordVisible);
      syncPasswordPeeking();
      applySceneState();
    });
  });

  function onMouseMove(event) {
    mouseX = event.clientX;
    mouseY = event.clientY;
    applySceneState();
  }

  function startTypingMode() {
    isTyping = true;
    lookAtEachOther = true;
    if (typingTimer) clearTimeout(typingTimer);
    typingTimer = setTimeout(() => {
      lookAtEachOther = false;
      applySceneState();
    }, 850);
    applySceneState();
  }

  function stopTypingModeSoon() {
    window.setTimeout(() => {
      const focused = document.activeElement;
      const typingFieldFocused = [...textInputs, ...passwordInputs].some(
        input => input === focused,
      );
      if (!typingFieldFocused) {
        isTyping = false;
        lookAtEachOther = false;
        applySceneState();
      }
    }, 60);
  }

  function syncToggleIcons(toggle, visible) {
    toggle.querySelectorAll("[data-auth-eye-icon]").forEach(icon => {
      const wants = icon.getAttribute("data-auth-eye-icon") === (visible ? "hide" : "show");
      icon.classList.toggle("d-none", !wants);
    });
  }

  function syncPasswordPeeking() {
    const hasPassword = passwordInputs.some(input => input.value.length > 0);
    if (!(hasPassword && passwordVisible)) {
      purplePeeking = false;
      if (peekTimer) {
        clearTimeout(peekTimer);
        peekTimer = null;
      }
      applySceneState();
      return;
    }

    if (peekTimer) return;
    schedulePeek();
  }

  function schedulePeek() {
    peekTimer = setTimeout(() => {
      purplePeeking = true;
      applySceneState();
      setTimeout(() => {
        purplePeeking = false;
        applySceneState();
        peekTimer = null;
        syncPasswordPeeking();
      }, 700);
    }, Math.random() * 2600 + 1800);
  }

  function scheduleBlink(character, stateMap) {
    const state = stateMap.get(character);
    if (!state) return;
    const delay = Math.random() * 4000 + 2600;
    state.timeout = setTimeout(() => {
      character.setAttribute("data-auth-blink", "true");
      state.active = true;
      applySceneState();
      setTimeout(() => {
        character.setAttribute("data-auth-blink", "false");
        state.active = false;
        applySceneState();
        scheduleBlink(character, stateMap);
      }, 150);
    }, delay);
  }

  function applySceneState() {
    // Purple leans + grows while typing OR while a hidden password has content
    // (mirrors the template's `isTyping || (password && !showPassword)`).
    const purpleLean = isTyping || (passwordHasValue && !passwordVisible);
    characters.forEach(character => {
      const type = character.getAttribute("data-auth-character");
      const face = character.querySelector("[data-auth-face]");
      const pupils = Array.from(character.querySelectorAll("[data-auth-pupil]"));
      if (!face || !pupils.length) return;

      const rect = character.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 3;
      const faceX = clamp((mouseX - centerX) / 20, -15, 15);
      const faceY = clamp((mouseY - centerY) / 28, -10, 10);
      const bodySkew = clamp(-(mouseX - centerX) / 120, -6, 6);

      let transform = `translate(${faceX}px, ${faceY}px)`;
      if (type === "purple" && passwordVisible) {
        transform = purplePeeking
          ? "translate(8px, 10px)"
          : "translate(-6px, -6px)";
      } else if (type === "purple" && lookAtEachOther) {
        transform = "translate(10px, 6px)";
      }
      face.style.transform = transform;

      if (type === "purple") {
        character.style.transform = passwordVisible
          ? "skewX(0deg)"
          : purpleLean
            ? `skewX(${bodySkew - 10}deg) translateX(34px)`
            : `skewX(${bodySkew}deg)`;
        character.setAttribute("data-auth-grow", purpleLean ? "true" : "false");
      } else {
        character.style.transform = passwordVisible ? "skewX(0deg)" : `skewX(${bodySkew}deg)`;
      }

      pupils.forEach(pupil => {
        let offsetX = clamp((mouseX - centerX) / 50, -5, 5);
        let offsetY = clamp((mouseY - centerY) / 60, -5, 5);

        if (passwordVisible) {
          offsetX = type === "purple" ? (purplePeeking ? 4 : -4) : -5;
          offsetY = type === "purple" ? (purplePeeking ? 5 : -4) : -4;
        } else if (lookAtEachOther) {
          if (type === "purple") {
            offsetX = 3;
            offsetY = 4;
          }
        }

        pupil.style.transform = `translate(${offsetX}px, ${offsetY}px)`;
      });
    });
  }

  toggles.forEach(toggle => syncToggleIcons(toggle, false));
  applySceneState();
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}
