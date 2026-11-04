const msg = document.getElementById("msg");
const btn = document.getElementById("reg");
const token = new URLSearchParams(location.search).get("token") || "";
// Token aus der Adresszeile entfernen
history.replaceState(null, "", "/register");

if (!token) {
  msg.textContent = "Kein Einladungslink. Erzeuge einen neuen per SSH.";
  btn.disabled = true;
}

btn.addEventListener("click", async () => {
  msg.className = "msg";
  msg.textContent = "";
  btn.disabled = true;
  try {
    if (!window.PublicKeyCredential) throw new Error("Dieser Browser unterstützt keine Passkeys.");
    const options = await postJSON("/api/auth/register/options", { token });
    const credential = await passkeyCreate(options);
    await postJSON("/api/auth/register/verify", {
      token, credential, label: document.getElementById("label").value,
    });
    msg.className = "msg ok";
    msg.textContent = "Passkey gespeichert. Weiter zum Depot …";
    setTimeout(() => (location.href = "/"), 800);
  } catch (e) {
    msg.textContent = e.name === "NotAllowedError" ? "Vorgang abgebrochen." : e.message;
    btn.disabled = false;
  }
});
