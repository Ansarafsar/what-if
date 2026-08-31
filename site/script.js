/* WHAT IF docs site - progressive enhancement only.
   The page is fully readable with JavaScript disabled. */

(function () {
  "use strict";

  // ---- mobile navigation ----
  var toggle = document.querySelector(".nav-toggle");
  var links = document.getElementById("nav-links");

  if (toggle && links) {
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });

    // Tapping a link on mobile should close the menu behind it.
    links.addEventListener("click", function (event) {
      if (event.target.tagName === "A") {
        links.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  // ---- copy buttons ----
  document.querySelectorAll(".copy").forEach(function (button) {
    button.addEventListener("click", function () {
      var target = document.querySelector(button.dataset.copy);
      if (!target) return;

      var text = target.innerText;
      var done = function () {
        var original = button.textContent;
        button.textContent = "Copied";
        button.classList.add("done");
        setTimeout(function () {
          button.textContent = original;
          button.classList.remove("done");
        }, 1600);
      };

      // navigator.clipboard needs a secure context; fall back for file:// use.
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done).catch(fallback);
      } else {
        fallback();
      }

      function fallback() {
        var area = document.createElement("textarea");
        area.value = text;
        area.setAttribute("readonly", "");
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.select();
        try {
          document.execCommand("copy");
          done();
        } catch (err) {
          button.textContent = "Press Ctrl+C";
        }
        document.body.removeChild(area);
      }
    });
  });

  // ---- highlight the section currently in view ----
  var sections = document.querySelectorAll("main section[id]");
  var navLinks = document.querySelectorAll('.nav-links a[href^="#"]');

  if (sections.length && navLinks.length && "IntersectionObserver" in window) {
    var byId = {};
    navLinks.forEach(function (link) {
      byId[link.getAttribute("href").slice(1)] = link;
    });

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          var link = byId[entry.target.id];
          if (!link) return;
          if (entry.isIntersecting) {
            navLinks.forEach(function (other) {
              other.style.color = "";
            });
            link.style.color = "var(--text)";
          }
        });
      },
      { rootMargin: "-45% 0px -50% 0px" }
    );

    sections.forEach(function (section) {
      observer.observe(section);
    });
  }
})();
