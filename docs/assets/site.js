(function () {
  "use strict";

  var POSTHOG_PROJECT_KEY = "phc_vaf796qeQoUXA2FBHi3kGV36FQFBQcyzjup6g5PhDYes";
  var POSTHOG_API_HOST = "https://us.i.posthog.com";
  var PUBLIC_DOCS_HOST = "gowtham0992.github.io";
  var PAGE = (window.location.pathname.split("/").pop() || "index.html").toLowerCase();
  var POSTHOG_LOADED = false;

  function isPublicDocsHost() {
    return window.location.hostname === PUBLIC_DOCS_HOST;
  }

  function allowsAnalytics() {
    return Boolean(POSTHOG_PROJECT_KEY) &&
      isPublicDocsHost() &&
      navigator.doNotTrack !== "1" &&
      navigator.globalPrivacyControl !== true;
  }

  function cleanPageName() {
    return PAGE.replace(/[^a-z0-9._-]/g, "") || "index.html";
  }

  function capture(eventName, properties) {
    if (!POSTHOG_LOADED || !window.posthog || typeof window.posthog.capture !== "function") {
      return;
    }
    window.posthog.capture(eventName, Object.assign({
      docs_page: cleanPageName(),
      docs_surface: "github_pages"
    }, properties || {}));
  }

  function loadPostHog() {
    if (!allowsAnalytics()) {
      return;
    }

    !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister unregister_for_session getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep identify setPersonProperties group resetGroups setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags reset get_distinct_id getGroups get_session_id get_session_replay_url alias set_config startSessionRecording stopSessionRecording sessionRecordingStarted captureException loadToolbar get_property getSessionProperty createPersonProfile opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing debug".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);

    window.posthog.init(POSTHOG_PROJECT_KEY, {
      api_host: POSTHOG_API_HOST,
      defaults: "2026-01-30",
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: false,
      capture_dead_clicks: false,
      disable_persistence: true,
      disable_session_recording: true,
      disable_surveys: true,
      enable_heatmaps: false,
      person_profiles: "identified_only",
      advanced_disable_feature_flags: true,
      advanced_disable_feature_flags_on_first_load: true,
      property_denylist: ["$current_url", "$referrer"],
      before_send: function (event) {
        if (event && event.properties) {
          event.properties.$current_url = null;
          event.properties.$referrer = null;
          event.properties.$pathname = null;
        }
        return event;
      },
      loaded: function () {
        POSTHOG_LOADED = true;
        capture("docs_viewed", { page_title: document.title });
        if (PAGE === "mcp.html") {
          capture("mcp_setup_viewed");
        }
        if (PAGE === "security.html") {
          capture("security_page_viewed");
        }
      }
    });
  }

  function commandCategory(text) {
    var lower = text.toLowerCase();
    if (lower.indexOf("brew install gowtham0992/link/link") !== -1) {
      return "homebrew";
    }
    if (lower.indexOf("pip install") !== -1 && lower.indexOf("link-mcp") !== -1) {
      return "pypi";
    }
    if (lower.indexOf("link demo") !== -1 || lower.indexOf("link.py demo") !== -1) {
      return "demo";
    }
    if (lower.indexOf("integrations/") !== -1 && lower.indexOf("install.sh") !== -1) {
      return "agent_installer";
    }
    return "other";
  }

  function captureCopyEvents(text, category) {
    var props = {
      command_category: category,
      command_lines: text.split(/\r?\n/).filter(Boolean).length
    };
    if (category === "homebrew") {
      capture("install_brew_copied", props);
    }
    if (category === "pypi") {
      capture("install_pypi_copied", props);
    }
    if (category === "demo") {
      capture("demo_command_copied", props);
    }
  }

  function addCopyButtons() {
    document.querySelectorAll("pre").forEach(function (pre) {
      var code = pre.querySelector("code");
      if (!code) {
        return;
      }

      var text = code.innerText.trim();
      if (!text) {
        return;
      }

      var button = document.createElement("button");
      button.type = "button";
      button.className = "copy-command";
      button.textContent = "copy";
      button.setAttribute("aria-label", "Copy command block");
      pre.classList.add("copy-ready");
      pre.appendChild(button);

      button.addEventListener("click", function () {
        var category = commandCategory(text);
        copyText(text).then(function () {
          button.textContent = "copied";
          captureCopyEvents(text, category);
          window.setTimeout(function () {
            button.textContent = "copy";
          }, 1400);
        }).catch(function () {
          selectCodeBlock(pre);
          button.textContent = "selected";
          window.setTimeout(function () {
            button.textContent = "copy";
          }, 1400);
        });
      });
    });
  }

  function selectCodeBlock(pre) {
    var range = document.createRange();
    var selection = window.getSelection();
    range.selectNodeContents(pre.querySelector("code") || pre);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function copyText(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function" && window.isSecureContext) {
      return navigator.clipboard.writeText(text).catch(function () {
        return fallbackCopyText(text);
      });
    }
    return fallbackCopyText(text);
  }

  function fallbackCopyText(text) {
    return new Promise(function (resolve, reject) {
      var textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.top = "-1000px";
      textarea.style.left = "-1000px";
      document.body.appendChild(textarea);
      textarea.select();
      try {
        if (document.execCommand("copy")) {
          resolve();
        } else {
          reject(new Error("copy failed"));
        }
      } catch (error) {
        reject(error);
      } finally {
        document.body.removeChild(textarea);
      }
    });
  }

  function captureOutboundClicks() {
    document.addEventListener("click", function (event) {
      var anchor = event.target.closest && event.target.closest("a[href]");
      if (!anchor) {
        return;
      }
      var href = anchor.getAttribute("href") || "";
      if (href.indexOf("https://github.com/gowtham0992/link") === 0) {
        capture("github_clicked", { link_target: "github_repo" });
      } else if (href.indexOf("https://github.com/gowtham0992/homebrew-link") === 0) {
        capture("homebrew_tap_clicked", { link_target: "homebrew_tap" });
      } else if (href.indexOf("https://pypi.org/project/link-mcp") === 0) {
        capture("pypi_clicked", { link_target: "pypi_package" });
      } else if (href.indexOf("https://registry.modelcontextprotocol.io") === 0) {
        capture("mcp_registry_clicked", { link_target: "mcp_registry" });
      }
    });
  }

  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function initScrollReveal() {
    var targets = Array.prototype.slice.call(
      document.querySelectorAll(".feature, .panel, .media-card, .proof-column, .architecture-card, .compare > div")
    );
    if (!targets.length) {
      return;
    }
    if (prefersReducedMotion() || typeof IntersectionObserver === "undefined") {
      return;
    }
    targets.forEach(function (el) { el.classList.add("reveal"); });
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add("revealed");
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.1 });
    targets.forEach(function (el) { observer.observe(el); });
  }

  // --- Docs chrome: sidebar toggle, on-this-page highlight, search ---------
  // The sidebar and the search index are stamped by scripts/sync_docs_site.py;
  // this only makes them behave. Search is client-side over a checked-in JSON
  // file, so the docs work from a file:// URL with no service behind them.

  function initSidebarToggle() {
    var toggle = document.querySelector(".docs-sidebar-toggle");
    var sidebar = document.querySelector(".docs-sidebar");
    if (!toggle || !sidebar) {
      return;
    }
    toggle.addEventListener("click", function () {
      var open = sidebar.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  function initOnThisPage() {
    var toc = document.querySelector(".toc");
    if (!toc) {
      return;
    }
    var links = {};
    toc.querySelectorAll('a[href^="#"]').forEach(function (a) {
      links[a.getAttribute("href").slice(1)] = a;
    });
    var headings = Array.prototype.slice.call(document.querySelectorAll(".doc-content h2[id]"))
      .filter(function (h) { return links[h.id]; });
    if (!headings.length) {
      return;
    }
    var current = null;
    function update() {
      var top = window.scrollY + 110;
      var active = headings[0];
      headings.forEach(function (h) {
        if (h.offsetTop <= top) {
          active = h;
        }
      });
      if (current === active.id) {
        return;
      }
      current = active.id;
      Object.keys(links).forEach(function (key) {
        links[key].classList.toggle("active", key === current);
      });
    }
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  }

  var SEARCH_INDEX = null;
  var SEARCH_LOADING = null;

  function loadSearchIndex() {
    if (SEARCH_INDEX) {
      return Promise.resolve(SEARCH_INDEX);
    }
    if (!SEARCH_LOADING) {
      SEARCH_LOADING = fetch("assets/search-index.json").then(function (response) {
        return response.json();
      }).then(function (data) {
        SEARCH_INDEX = data;
        return data;
      });
    }
    return SEARCH_LOADING;
  }

  function tokens(text) {
    return String(text || "").toLowerCase().split(/[^a-z0-9_.-]+/).filter(function (t) { return t.length > 1; });
  }

  function scoreEntry(terms, fields) {
    var score = 0;
    terms.forEach(function (term) {
      var hit = false;
      fields.forEach(function (field) {
        var haystack = String(field.text || "").toLowerCase();
        var at = haystack.indexOf(term);
        if (at !== -1) {
          hit = true;
          score += field.weight * (at === 0 || /[^a-z0-9]/.test(haystack.charAt(at - 1)) ? 2 : 1);
        }
      });
      if (!hit) {
        score = -1e9;
      }
    });
    return score;
  }

  function searchResults(index, query) {
    var terms = tokens(query);
    if (!terms.length) {
      return [];
    }
    var results = [];
    index.forEach(function (page) {
      var pageScore = scoreEntry(terms, [
        { text: page.title, weight: 6 }, { text: page.label, weight: 6 },
        { text: page.eyebrow, weight: 2 }, { text: page.lead, weight: 1 }
      ]);
      if (pageScore > 0) {
        results.push({ href: page.page, title: page.title, where: page.label, snippet: page.lead, score: pageScore + 1 });
      }
      page.sections.forEach(function (section) {
        var score = scoreEntry(terms, [
          { text: section.heading, weight: 4 }, { text: section.body || section.text, weight: 1 }, { text: page.label, weight: 1 }
        ]);
        if (score > 0) {
          results.push({ href: page.page + "#" + section.id, title: section.heading,
            where: section.under ? page.label + " \u00b7 " + section.under : page.label, snippet: section.text, score: score });
        }
      });
    });
    results.sort(function (a, b) { return b.score - a.score; });
    return results.slice(0, 12);
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function initSearch() {
    var button = document.querySelector(".site-search");
    if (!button) {
      return;
    }
    var overlay = document.createElement("div");
    overlay.className = "search-overlay";
    overlay.setAttribute("hidden", "");
    overlay.innerHTML =
      '<div class="search-box" role="dialog" aria-label="Search the docs">' +
      '<input type="search" class="search-input" placeholder="Search the docs: commands, concepts, fields" autocomplete="off" spellcheck="false">' +
      '<div class="search-results" role="listbox"></div>' +
      '<div class="search-hint"><span><kbd>↑</kbd><kbd>↓</kbd> move</span><span><kbd>↵</kbd> open</span><span><kbd>esc</kbd> close</span></div>' +
      "</div>";
    document.body.appendChild(overlay);
    var input = overlay.querySelector(".search-input");
    var list = overlay.querySelector(".search-results");
    var selected = 0;
    var current = [];

    function render() {
      if (!input.value.trim()) {
        list.innerHTML = '<div class="search-empty">Type to search every docs page. Try <em>enforce</em>, <em>receipt</em>, <em>review_after</em> or <em>team-sync</em>.</div>';
        current = [];
        return;
      }
      if (!current.length) {
        list.innerHTML = '<div class="search-empty">Nothing matches “' + escapeHtml(input.value) + '”.</div>';
        return;
      }
      list.innerHTML = current.map(function (r, i) {
        return '<a class="search-result' + (i === selected ? " selected" : "") + '" href="' + escapeHtml(r.href) + '" role="option">' +
          '<span class="search-result-title">' + escapeHtml(r.title) + '</span>' +
          '<span class="search-result-where">' + escapeHtml(r.where) + '</span>' +
          (r.snippet ? '<span class="search-result-snippet">' + escapeHtml(r.snippet) + '</span>' : "") +
          "</a>";
      }).join("");
    }

    function update() {
      loadSearchIndex().then(function (index) {
        current = searchResults(index, input.value);
        selected = 0;
        render();
      }).catch(function () {
        list.innerHTML = '<div class="search-empty">Search is unavailable on this copy of the docs.</div>';
      });
    }

    function open() {
      overlay.removeAttribute("hidden");
      document.body.classList.add("search-open");
      input.value = "";
      render();
      input.focus();
      loadSearchIndex().catch(function () {});
    }

    function close() {
      overlay.setAttribute("hidden", "");
      document.body.classList.remove("search-open");
      button.focus();
    }

    button.addEventListener("click", open);
    overlay.addEventListener("click", function (event) {
      if (event.target === overlay) {
        close();
      }
    });
    input.addEventListener("input", update);
    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown" && current.length) {
        selected = (selected + 1) % current.length;
        render();
        event.preventDefault();
      } else if (event.key === "ArrowUp" && current.length) {
        selected = (selected - 1 + current.length) % current.length;
        render();
        event.preventDefault();
      } else if (event.key === "Enter" && current[selected]) {
        var href = current[selected].href;
        if (href.split("#")[0] === PAGE) {
          close();
        }
        window.location.href = href;
      }
    });
    document.addEventListener("keydown", function (event) {
      var target = event.target;
      var typing = /^(input|textarea|select)$/i.test((target && target.tagName) || "") || (target && target.isContentEditable);
      var hidden = overlay.hasAttribute("hidden");
      if (event.key === "Escape" && !hidden) {
        close();
      } else if (event.key === "/" && !typing && hidden) {
        event.preventDefault();
        open();
      } else if ((event.metaKey || event.ctrlKey) && String(event.key).toLowerCase() === "k" && hidden) {
        event.preventDefault();
        open();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    addCopyButtons();
    captureOutboundClicks();
    initScrollReveal();
    initSidebarToggle();
    initOnThisPage();
    initSearch();
    loadPostHog();
  });
})();
