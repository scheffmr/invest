const msg = document.getElementById("msg");
const btn = document.getElementById("login");

btn.addEventListener("click", async () => {
  msg.className = "msg";
  msg.textContent = "";
  btn.disabled = true;
  try {
    if (!window.PublicKeyCredential) throw new Error("Dieser Browser unterstützt keine Passkeys.");
    const { challengeId, options } = await postJSON("/api/auth/login/options");
    const credential = await passkeyGet(options);
    await postJSON("/api/auth/login/verify", { challengeId, credential });
    location.href = "/";
  } catch (e) {
    msg.textContent = e.name === "NotAllowedError" ? "Anmeldung abgebrochen." : e.message;
  } finally {
    btn.disabled = false;
  }
});
