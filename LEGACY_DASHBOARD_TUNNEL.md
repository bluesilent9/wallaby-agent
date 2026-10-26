# Retiring wallet-laptop's old Dashboard startup tunnel

Run these commands on **wallet-laptop**, as desktop user dave, outside any server SSH session. The inspected legacy unit is `/home/dave/.config/systemd/user/ssh-tunnels.service`, described as Persistent SSH tunnels. Its SSH command forwards browser port 38951 on IPv4 and IPv6 loopback to server [::1]:38951; it is not an SSHFS/storage mount.

```sh
systemctl --user disable --now ssh-tunnels.service
mkdir -p ~/.local/share/wallaby-agent/retired-services
mv --backup=numbered ~/.config/systemd/user/ssh-tunnels.service ~/.local/share/wallaby-agent/retired-services/
systemctl --user daemon-reload
```

This stops/removes the old startup entry and preserves a backup outside systemd's unit directory. Do not disable `ssh-agent.service` or any `wallaby-agent-*` service. The working Agent node interface on port 56443 can remain enabled.

Browser access through the old tunnel will stop until build 3 is installed and **Wallaby Dashboard** is enabled in Agent. Its **Open Dashboard** link uses `http://[::1]:38951`. Existing localhost bookmarks may also work when localhost resolves over IPv6; changing browser origin can require signing in again.

The exact name, user-unit path and forwarding command above were confirmed from wallet-laptop's user-provided systemd output. No removal command was executed remotely by this preparation task.
