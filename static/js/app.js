// ELLOMAX · comportamento da interface (sem dependências)
(function () {
  "use strict";
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  // confirmação antes de enviar formulários destrutivos
  document.addEventListener("submit", (e) => {
    const f = e.target;
    const msg = (e.submitter && e.submitter.dataset.confirm) || f.dataset.confirm;
    if (msg && !confirm(msg)) e.preventDefault();
  });

  // menu lateral no celular
  const app = document.querySelector(".app");
  $$("[data-nav-toggle]").forEach((b) => b.addEventListener("click", () => app && app.classList.toggle("nav-open")));

  // fecha menus <details> ao clicar fora
  document.addEventListener("click", (e) => {
    $$("details.menu[open]").forEach((d) => { if (!d.contains(e.target)) d.removeAttribute("open"); });
  });

  // avisos com botão de fechar
  $$(".alert .x").forEach((b) => b.addEventListener("click", () => b.closest(".alert").remove()));

  // alternar painéis (ex.: devolução parcial)
  $$("[data-toggle]").forEach((b) => b.addEventListener("click", () => {
    const alvo = document.getElementById(b.dataset.toggle);
    if (alvo) alvo.classList.toggle("hidden");
  }));

  // formulário de OS: empenhos filtrados pelo contrato escolhido
  const selEdital = document.querySelector("[data-edital-select]");
  const selEmp = document.querySelector("[data-empenho-select]");
  if (selEdital && selEmp) {
    const filtra = () => {
      $$("option[data-edital]", selEmp).forEach((o) => {
        const ok = o.dataset.edital === selEdital.value;
        o.hidden = !ok;
        if (!ok && o.selected) selEmp.value = "";
      });
    };
    selEdital.addEventListener("change", () => {
      filtra();
      const loc = selEdital.selectedOptions[0] && selEdital.selectedOptions[0].dataset.local;
      const campo = document.getElementById("local");
      if (campo && !campo.value && loc) campo.value = loc;
    });
    filtra();
  }
  // pedido de compra: custo do frete = km × R$/km
  const kmIn = document.querySelector("[data-frete-km]");
  const vkIn = document.querySelector("[data-frete-valor]");
  const frOut = document.querySelector("[data-frete-total]");
  if (kmIn && vkIn && frOut) {
    const n = (v) => { v = (v || "").trim().replace(/\s|R\$/g, ""); if (v.includes(",")) v = v.replace(/\./g, "").replace(",", "."); return parseFloat(v) || 0; };
    const calc = () => { frOut.textContent = (n(kmIn.value) * n(vkIn.value)).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }); };
    kmIn.addEventListener("input", calc); vkIn.addEventListener("input", calc); calc();
  }

  // tipo de OS sugere o modelo de checklist
  const selTipo = document.querySelector("[data-tipo-os]");
  const selModelo = document.querySelector("[data-modelo-select]");
  if (selTipo && selModelo) {
    selTipo.addEventListener("change", () => {
      const ops = $$("option[data-tipo]", selModelo).filter((o) => o.dataset.tipo === selTipo.value);
      ops.sort((a, b) => Number(a.value) - Number(b.value));
      if (ops.length) selModelo.value = ops[0].value;
    });
  }

  // checklist: marcar todos os pendentes como conforme + destaque das não conformidades
  const ckForm = document.querySelector("[data-checklist]");
  if (ckForm) {
    const atualiza = () => {
      let ok = 0, nc = 0, na = 0, pend = 0;
      $$(".ck", ckForm).forEach((li) => {
        const v = (li.querySelector("input[type=radio]:checked") || {}).value;
        li.classList.toggle("nc", v === "nc");
        li.classList.toggle("pend", !v);
        if (v === "ok") ok++; else if (v === "nc") nc++; else if (v === "na") na++; else pend++;
      });
      const r = document.querySelector("[data-ck-resumo]");
      if (r) r.innerHTML = `<span>Conforme <b>${ok}</b></span><span>Não conforme <b>${nc}</b></span><span>N/A <b>${na}</b></span><span>Sem resposta <b>${pend}</b></span>`;
    };
    ckForm.addEventListener("change", atualiza);
    const todos = document.querySelector("[data-ck-todos]");
    if (todos) todos.addEventListener("click", () => {
      $$(".ck", ckForm).forEach((li) => {
        if (!li.querySelector("input[type=radio]:checked")) {
          const r = li.querySelector("input[value=ok]");
          if (r) r.checked = true;
        }
      });
      atualiza();
    });
    atualiza();
  }

  // quadros de assinatura (dedo, caneta ou mouse)
  $$("[data-pad]").forEach((wrap) => {
    const canvas = wrap.querySelector("canvas");
    const campo = document.getElementById(wrap.dataset.pad);
    const ctx = canvas.getContext("2d");
    let desenhando = false, ultimo = null, sujo = false;
    const ajusta = () => {
      const r = canvas.getBoundingClientRect();
      const dpr = Math.max(window.devicePixelRatio || 1, 1);
      const copia = sujo ? canvas.toDataURL() : null;
      canvas.width = Math.round(r.width * dpr);
      canvas.height = Math.round(r.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#0B1A24";
      if (copia) { const im = new Image(); im.onload = () => ctx.drawImage(im, 0, 0, r.width, r.height); im.src = copia; }
    };
    const ponto = (e) => { const r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top, p: e.pressure || 0.5 }; };
    canvas.addEventListener("pointerdown", (e) => { desenhando = true; ultimo = ponto(e); canvas.setPointerCapture(e.pointerId); e.preventDefault(); });
    canvas.addEventListener("pointermove", (e) => {
      if (!desenhando) return;
      const p = ponto(e);
      ctx.lineWidth = 1.4 + p.p * 2.2;
      ctx.beginPath(); ctx.moveTo(ultimo.x, ultimo.y); ctx.lineTo(p.x, p.y); ctx.stroke();
      ultimo = p; sujo = true; e.preventDefault();
    });
    const fim = () => {
      if (!desenhando) return;
      desenhando = false;
      if (sujo) { campo.value = exporta(); wrap.classList.add("assinado"); }
    };
    canvas.addEventListener("pointerup", fim);
    canvas.addEventListener("pointercancel", fim);
    canvas.addEventListener("pointerleave", fim);
    // exporta com fundo transparente, recortado e em tamanho moderado
    function exporta() {
      const max = 900, esc = Math.min(1, max / canvas.width);
      const c2 = document.createElement("canvas");
      c2.width = Math.round(canvas.width * esc); c2.height = Math.round(canvas.height * esc);
      c2.getContext("2d").drawImage(canvas, 0, 0, c2.width, c2.height);
      return c2.toDataURL("image/png");
    }
    const limpar = wrap.querySelector("[data-pad-limpar]");
    if (limpar) limpar.addEventListener("click", () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height); sujo = false; campo.value = ""; wrap.classList.remove("assinado");
    });
    ajusta();
    window.addEventListener("resize", ajusta);
  });

  // impede envio de assinatura sem o quadro do cliente
  const fAss = document.querySelector("[data-form-assinatura]");
  if (fAss) fAss.addEventListener("submit", (e) => {
    const c = document.getElementById("assinatura_cliente");
    if (c && !c.value) { e.preventDefault(); alert("Peça ao cliente para assinar no quadro antes de concluir."); }
  });
})();
