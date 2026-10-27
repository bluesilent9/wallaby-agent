# Retiring an older Dashboard startup tunnel

An existing SSH forward can occupy local port 38951 before Wallaby Agent starts. On the desktop computer, inspect user services before changing them:

```sh
systemctl --user list-unit-files --type=service --no-pager
systemctl --user cat YOUR_LEGACY_TUNNEL.service
```

Confirm that the exact unit only provides the obsolete Dashboard forward. A general tunnel service may also supply unrelated applications; preserve those forwards. Do not disable `ssh-agent.service`, any `wallaby-agent-*` service, or a storage mount.

For a confirmed obsolete user unit, substitute its exact name below:

```sh
systemctl --user disable --now YOUR_LEGACY_TUNNEL.service
mkdir -p ~/.local/share/wallaby-agent/retired-services
mv --backup=numbered ~/.config/systemd/user/YOUR_LEGACY_TUNNEL.service ~/.local/share/wallaby-agent/retired-services/
systemctl --user daemon-reload
```

This preserves a backup outside systemd's unit directory. Browser access through that old forward stops until **Wallaby Dashboard** is enabled in Agent. Agent's **Open Dashboard** link uses `http://[::1]:38951`. The independent node interface uses server port 56443.

These instructions concern a client tunnel, not the Dashboard server's old system service. Retire a legacy server service separately when installing the new Dashboard DEB. Neither procedure has been executed during source preparation.
