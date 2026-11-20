(function () {
  if (location.pathname === "/entrar") {
    history.replaceState(null, "", "/");
  }

  var form = document.getElementById("form");
  var input = document.getElementById("q");
  var status = document.getElementById("status");
  var result = document.getElementById("result");
  var mode = document.getElementById("mode");
  var answer = document.getElementById("answer");
  var sources = document.getElementById("sources");
  var nearby = document.getElementById("nearby");
  var suggestions = document.getElementById("suggestions");
  var install = document.getElementById("install");
  var deferred = null;

  var modes = {
    vetorial: "Busca vetorial local",
    modelo: "Modelo local",
    textual: "Busca textual",
    nenhuma: "Sem correspondência"
  };

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferred = event;
    install.hidden = false;
  });

  install.addEventListener("click", function () {
    if (!deferred) {
      return;
    }
    deferred.prompt();
    deferred = null;
    install.hidden = true;
  });

  if (
    "serviceWorker" in navigator &&
    (location.hostname === "localhost" ||
      location.hostname === "127.0.0.1" ||
      location.protocol === "https:")
  ) {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var query = input.value.trim();
    result.hidden = true;
    sources.replaceChildren();
    nearby.replaceChildren();
    suggestions.replaceChildren();
    answer.textContent = "";
    if (!query) {
      status.textContent = "Escreva uma pergunta.";
      return;
    }
    status.textContent = "Consultando o vault neste computador.";
    fetch("/consultar", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Jarvis-Consult": "1"
      },
      body: JSON.stringify({ q: query })
    })
      .then(function (response) {
        if (response.status === 403) {
          throw new Error("sessao");
        }
        if (!response.ok) {
          throw new Error("falha");
        }
        return response.json();
      })
      .then(show)
      .catch(function (error) {
        result.hidden = true;
        if (error && error.message === "sessao") {
          status.textContent = "A sessão não vale mais. Abra de novo o link impresso no terminal.";
          return;
        }
        status.textContent = "Sem conexão com o Jarvis neste computador. Não há cópia das notas neste aparelho.";
      });
  });

  function show(data) {
    status.textContent = data.evidence
      ? "Trechos encontrados no vault."
      : "Sem evidência suficiente.";
    result.hidden = false;
    result.className = data.evidence ? "ok" : "gap";
    mode.textContent = modes[data.mode] || "Consulta local";
    answer.textContent = data.answer || "";
    fillCards(sources, data.sources, "Trechos de origem");
    fillCards(nearby, data.nearby, "Trechos próximos, sem evidência suficiente");
    fillSuggestions(data.suggestions || {});
  }

  function fillCards(container, items, title) {
    container.replaceChildren();
    if (!items || !items.length) {
      container.hidden = true;
      return;
    }
    container.hidden = false;
    var heading = document.createElement("h2");
    heading.textContent = title;
    container.appendChild(heading);
    items.forEach(function (item) {
      var card = document.createElement("article");
      var titleNode = document.createElement("h3");
      titleNode.textContent = item.title || item.path || "Nota";
      var path = document.createElement("p");
      path.className = "path";
      path.textContent = item.path || "";
      var excerpt = document.createElement("blockquote");
      excerpt.textContent = item.excerpt || "";
      card.append(titleNode, path, excerpt);
      if (item.wikilink) {
        var link = document.createElement("p");
        link.className = "link";
        link.textContent = item.wikilink;
        card.appendChild(link);
      }
      if (item.obsidian && String(item.obsidian).indexOf("obsidian://") === 0) {
        var open = document.createElement("a");
        open.href = item.obsidian;
        open.textContent = "Abrir no Obsidian deste aparelho";
        card.appendChild(open);
      }
      container.appendChild(card);
    });
  }

  function fillSuggestions(data) {
    suggestions.replaceChildren();
    var cards = data.flashcards || [];
    var links = data.connections || [];
    if (!cards.length && !links.length) {
      suggestions.hidden = true;
      return;
    }
    suggestions.hidden = false;
    var heading = document.createElement("h2");
    heading.textContent = "Sugestões de revisão";
    var note = document.createElement("p");
    note.textContent = "Sugestão apenas. Nada foi gravado no vault.";
    suggestions.append(heading, note);
    cards.forEach(function (card) {
      var block = document.createElement("article");
      var front = document.createElement("h3");
      front.textContent = card.front || "";
      var back = document.createElement("p");
      back.textContent = card.back || "";
      block.append(front, back);
      suggestions.appendChild(block);
    });
    links.forEach(function (link) {
      var line = document.createElement("p");
      line.textContent =
        (link.origin || "") +
        " liga com " +
        (link.target || "") +
        (link.reason ? " (" + link.reason + ")" : "");
      suggestions.appendChild(line);
    });
  }
})();
