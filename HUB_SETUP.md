# Jarvis hub setup

## 0. Back up first
    cd ~/desktopjarvis && cp jarvis.py jarvis.py.bak

## 1. Drop in the files
Copy brain.py, server.py, jarvis.py (replaces yours), jarvis-hub.service into ~/desktopjarvis.

## 2. Test desktop Jarvis BEFORE anything else
    python jarvis.py
Wake him, ask something that uses a tool (calendar, read a project file), try
"house knowledge ...", switch to Friday and back. Should behave exactly as before.
If anything is off: cp jarvis.py.bak jarvis.py, and report the error.

## 3. Server dependencies + secrets
    pip install fastapi uvicorn
    python -c "import secrets; print(secrets.token_urlsafe(32))"
Add to ~/desktopjarvis/.env:
    FRIDAY_TOKEN=<the value printed above>
    FRIDAY_SPEAKER=<your name exactly as the key in users/household_voiceprints.json>

## 4. Run the server (test manually first)
    python server.py
    # other terminal:
    curl -H "Authorization: Bearer <token>" http://127.0.0.1:8765/health   # -> {"ok":true}

## 5. Tailscale
Laptop:
    sudo pacman -S tailscale
    sudo systemctl enable --now tailscaled
    sudo tailscale up
Phone: install Tailscale from the Play Store, sign in with the same account.
Admin console (login.tailscale.com) -> DNS: enable MagicDNS and HTTPS Certificates.
Laptop:
    sudo tailscale serve --bg 8765
    tailscale serve status        # shows your https://<machine>.<tailnet>.ts.net URL
(If the serve syntax differs on your version: tailscale serve --help)

## 6. Friday
In Friday's local.properties add:
    JARVIS_HUB_URL=https://<machine>.<tailnet>.ts.net
    JARVIS_HUB_TOKEN=<same token as FRIDAY_TOKEN>
Sync Gradle, Run. Test on Wi-Fi, then with Wi-Fi off (cellular), then with the
server stopped (should say she can't reach home and show "offline mode").

## 7. Run the server permanently (optional, once it works)
    mkdir -p ~/.config/systemd/user
    cp jarvis-hub.service ~/.config/systemd/user/
    # edit ExecStart if your venv isn't ~/desktopjarvis/venv
    systemctl --user daemon-reload
    systemctl --user enable --now jarvis-hub
    loginctl enable-linger $USER      # keep it running when you're logged out
    journalctl --user -u jarvis-hub -f   # live logs

## Public repo
Add brain.py, server.py, jarvis-hub.service, HUB_SETUP.md to your allowlist script.
.env stays excluded.
