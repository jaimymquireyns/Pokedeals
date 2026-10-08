import { signIn, signUp } from "../api.js";
import { h } from "../ui.js";

/** Inloggen of een account maken met e-mailadres en wachtwoord. */
export function loginView(root, { reason = "Log in to continue.", onDone }) {
  let mode = "in";
  const err = h("p", { class: "err", role: "alert" });
  const email = h("input", { type: "email", autocomplete: "email", inputmode: "email", placeholder: "you@email.com", "aria-label": "Email" });
  const pass = h("input", { type: "password", placeholder: "Password", "aria-label": "Password" });
  const btn = h("button", { type: "button", class: "cta" });

  const draw = () => {
    err.textContent = "";
    pass.autocomplete = mode === "in" ? "current-password" : "new-password";
    btn.textContent = mode === "in" ? "Log in" : "Create account";
    root.replaceChildren(h("div", { class: "login" },
      h("h1", { text: mode === "in" ? "Log in" : "Create account" }),
      h("p", { class: "muted", text: mode === "in" ? reason : "Choose a password of at least 8 characters. You only do this once." }),
      email, pass, err, btn,
      h("button", { type: "button", class: "linkbtn", text: mode === "in" ? "No account? Create one" : "Have an account? Log in",
        onclick: () => { mode = mode === "in" ? "up" : "in"; draw(); } })));
    email.focus();
  };

  btn.onclick = async () => {
    const mail = email.value.trim();
    if (!/^\S+@\S+\.\S+$/.test(mail)) { err.textContent = "Enter a valid email."; return; }
    if (mode === "up" && pass.value.length < 8) { err.textContent = "Choose a password of at least 8 characters."; return; }
    if (!pass.value) { err.textContent = "Enter your password."; return; }
    btn.disabled = true;
    try {
      if (mode === "in") await signIn(mail, pass.value);
      else if (!(await signUp(mail, pass.value))) { err.textContent = "Account created, but Supabase still requires email confirmation. Turn it off (see the README), then log in."; mode = "in"; btn.disabled = false; return; }
      onDone();
    } catch (e) {
      const m = String(e.message);
      err.textContent = m.includes("429") ? "Too many attempts. Wait a moment and try again."
        : mode === "in" ? "Wrong email or password."
        : m.includes("already") ? "This email already has an account. Choose 'Log in'."
        : "Couldn't create account. Check your details.";
    } finally { btn.disabled = false; }
  };
  draw();
}
