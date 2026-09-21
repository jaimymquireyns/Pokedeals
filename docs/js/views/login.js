import { sendCode, verifyCode } from "../api.js";
import { h } from "../ui.js";

/** Inloggen met een code per e-mail. Geen wachtwoord, geen link (die opent op iPhone in de verkeerde app). */
export function loginView(root, { reason = "Log in om verder te gaan.", onDone }) {
  const err = h("p", { class: "err", role: "alert" });
  const email = h("input", { type: "email", autocomplete: "email", inputmode: "email", placeholder: "jouw@email.nl", "aria-label": "E-mailadres" });
  const code = h("input", { type: "text", inputmode: "numeric", autocomplete: "one-time-code", placeholder: "Code uit de e-mail", "aria-label": "Code" });
  const btn = h("button", { type: "button", class: "cta" });
  let step = 1;

  const draw = () => {
    err.textContent = "";
    btn.textContent = step === 1 ? "Stuur code" : "Inloggen";
    root.replaceChildren(h("div", { class: "login" },
      h("h1", { text: "Inloggen" }),
      h("p", { class: "muted", text: step === 1 ? reason : `We hebben een code gestuurd naar ${email.value}.` }),
      step === 1 ? email : code, err, btn,
      step === 2 ? h("button", { type: "button", class: "linkbtn", text: "Andere e-mail of nieuwe code", onclick: () => { step = 1; draw(); } }) : null));
    (step === 1 ? email : code).focus();
  };

  btn.onclick = async () => {
    btn.disabled = true;
    try {
      if (step === 1) {
        if (!/^\S+@\S+\.\S+$/.test(email.value.trim())) throw new Error("Vul een geldig e-mailadres in.");
        await sendCode(email.value.trim());
        step = 2; draw();
      } else {
        await verifyCode(email.value.trim(), code.value);
        onDone();
      }
    } catch (e) {
      err.textContent = step === 1 ? `Code versturen lukte niet. ${e.message.includes("429") ? "Wacht even en probeer het opnieuw." : "Controleer je e-mailadres."}` : "Die code klopt niet of is verlopen. Vraag een nieuwe aan.";
    } finally { btn.disabled = false; }
  };
  draw();
}
