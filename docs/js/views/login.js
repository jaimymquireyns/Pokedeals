import { signIn, signUp } from "../api.js";
import { h } from "../ui.js";

/** Inloggen of een account maken met e-mailadres en wachtwoord. */
export function loginView(root, { reason = "Log in om verder te gaan.", onDone }) {
  let mode = "in";
  const err = h("p", { class: "err", role: "alert" });
  const email = h("input", { type: "email", autocomplete: "email", inputmode: "email", placeholder: "jouw@email.nl", "aria-label": "E-mailadres" });
  const pass = h("input", { type: "password", placeholder: "Wachtwoord", "aria-label": "Wachtwoord" });
  const btn = h("button", { type: "button", class: "cta" });

  const draw = () => {
    err.textContent = "";
    pass.autocomplete = mode === "in" ? "current-password" : "new-password";
    btn.textContent = mode === "in" ? "Inloggen" : "Account maken";
    root.replaceChildren(h("div", { class: "login" },
      h("h1", { text: mode === "in" ? "Inloggen" : "Account maken" }),
      h("p", { class: "muted", text: mode === "in" ? reason : "Kies een wachtwoord van minstens 8 tekens. Je hoeft dit maar één keer te doen." }),
      email, pass, err, btn,
      h("button", { type: "button", class: "linkbtn", text: mode === "in" ? "Nog geen account? Maak er een" : "Al een account? Inloggen",
        onclick: () => { mode = mode === "in" ? "up" : "in"; draw(); } })));
    email.focus();
  };

  btn.onclick = async () => {
    const mail = email.value.trim();
    if (!/^\S+@\S+\.\S+$/.test(mail)) { err.textContent = "Vul een geldig e-mailadres in."; return; }
    if (mode === "up" && pass.value.length < 8) { err.textContent = "Kies een wachtwoord van minstens 8 tekens."; return; }
    if (!pass.value) { err.textContent = "Vul je wachtwoord in."; return; }
    btn.disabled = true;
    try {
      if (mode === "in") await signIn(mail, pass.value);
      else if (!(await signUp(mail, pass.value))) { err.textContent = "Account gemaakt, maar Supabase vraagt nog om e-mailbevestiging. Zet die uit (zie de README) en log daarna in."; mode = "in"; btn.disabled = false; return; }
      onDone();
    } catch (e) {
      const m = String(e.message);
      err.textContent = m.includes("429") ? "Te veel pogingen. Wacht even en probeer het opnieuw."
        : mode === "in" ? "E-mailadres of wachtwoord klopt niet."
        : m.includes("already") ? "Dit e-mailadres heeft al een account. Kies 'Inloggen'."
        : "Account maken lukte niet. Controleer je gegevens.";
    } finally { btn.disabled = false; }
  };
  draw();
}
