// Floating action menu for the navbar account button.
// Ported from the React/framer-motion template to plain JS + CSS transitions:
// the trigger rotates on open, the panel blurs/slides in, items stagger.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-fab-menu]").forEach(menu => {
    const trigger = menu.querySelector("[data-fab-trigger]");
    if (!trigger) return;

    const close = () => {
      menu.classList.remove("is-open");
      trigger.setAttribute("aria-expanded", "false");
    };

    trigger.addEventListener("click", event => {
      event.stopPropagation();
      const open = menu.classList.toggle("is-open");
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
    });

    document.addEventListener("click", event => {
      if (!menu.contains(event.target)) close();
    });

    document.addEventListener("keydown", event => {
      if (event.key === "Escape") close();
    });
  });
});
