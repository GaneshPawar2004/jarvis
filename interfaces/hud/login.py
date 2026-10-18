"""The JARVIS unlock page, shared by the laptop HUD (PIN) and the cloud server (password)."""
import html

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="theme-color" content="#03070d">
<title>J.A.R.V.I.S. Login</title><link rel="manifest" href="/static/manifest.json">
<style>
:root{--cyan:#3fd9ff;--bg:#03070d;--muted:#6c93a8;--red:#ff5a5f}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;
background:radial-gradient(ellipse at 50% 40%,#0a2233 0%,var(--bg) 65%);color:#cfefff;font-family:"Segoe UI",sans-serif}
form{width:100%;max-width:340px;text-align:center}
.orb{width:110px;height:110px;margin:0 auto 22px;border-radius:50%;border:3px solid var(--cyan);
box-shadow:0 0 30px var(--cyan),inset 0 0 30px var(--cyan);display:grid;place-items:center}
.orb::after{content:"";width:46px;height:46px;border-radius:50%;background:#e8fbff;box-shadow:0 0 24px var(--cyan)}
h1{margin:0 0 4px;letter-spacing:6px;color:var(--cyan);font-size:22px}p{margin:0 0 22px;color:var(--muted);font-size:14px}
input{width:100%;font-size:{size};letter-spacing:{spacing};text-align:center;padding:12px;background:rgba(0,0,0,.4);
border:1px solid rgba(63,217,255,.4);color:#fff;outline:none}input:focus{border-color:var(--cyan);box-shadow:0 0 14px rgba(63,217,255,.35)}
button{margin-top:14px;width:100%;padding:13px;font-size:15px;letter-spacing:3px;background:transparent;
border:1px solid var(--cyan);color:var(--cyan);cursor:pointer}.err{color:var(--red);margin-top:14px;min-height:20px}
</style></head><body><form method="post" action="/login">
<div class="orb"></div><h1>J.A.R.V.I.S.</h1><p>{hint}</p>
<input name="{field}" type="password" {inputmode} autocomplete="{autocomplete}" autofocus required aria-label="{field}">
<button type="submit">UNLOCK</button><div class="err">{error}</div></form></body></html>"""


def pin_page(error: str = "") -> str:
    return _render("Enter the PIN shown on your laptop", "pin", 'inputmode="numeric"', "off", "28px", "10px", error)


def password_page(error: str = "") -> str:
    return _render("Enter your JARVIS password", "password", "", "current-password", "18px", "2px", error)


def _render(hint, field, inputmode, autocomplete, size, spacing, error) -> str:
    page = _PAGE
    for key, value in {"hint": hint, "field": field, "inputmode": inputmode, "autocomplete": autocomplete,
                       "size": size, "spacing": spacing, "error": html.escape(error)}.items():
        page = page.replace("{" + key + "}", value)
    return page
