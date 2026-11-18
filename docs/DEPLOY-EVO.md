# Running CyEM on the EVO-X2

Since 18 Nov 2026 CyEM runs on the EVO-X2 (Windows 11 Pro) in its own WSL2 distro, because the MS-A2 had no RAM to
spare for a VM. Ollama is on the same machine.

| Item | Value |
| --- | --- |
| Distro | `CyEM`, Ubuntu 24.04, `C:\WSL\CyEM`; systemd on; default user `cyem` (uid 1000, in the docker group) |
| Kept running | Scheduled task **CyEM WSL Runtime** (at boot, Neil, S4U): `wsl.exe -d CyEM -u root --exec /usr/bin/sleep infinity`. WSL stops an idle distro otherwise. The WSL VM is shared with ImmichML: `%USERPROFILE%\.wslconfig` gives it 16 GB and 4 processors |
| Code | `/home/cyem/cyem`, cloned with a read-only deploy key (`~/.ssh/cyem_deploy`, GitHub key "cyem-evo") |
| Containers | `cyem` (127.0.0.1:3020 in WSL, forwarded to Windows localhost) and `cyem-searxng` |
| Language model | `OLLAMA_URL=http://100.91.241.55:11434` (the EVO's tailnet address; the LAN address and the WSL gateway are blocked by the firewall from inside WSL) |
| Tailnet | `https://nucbox-evo-x2.tail013324.ts.net/`, no log-in |
| Internet | Same URL through Tailscale Funnel on 443; username and password (`app/auth.py`) |

## Everyday commands

From a Mac on the tailnet:

```
ssh Neil@100.91.241.55                                   # Windows (cmd); then:
wsl -d CyEM                                               # a shell in the distro as cyem
cd ~/cyem && git pull && docker compose up -d --build     # update to main
docker compose logs -f --tail 100 cyem
docker exec cyem python -m app.cli status                 # collector health
```

Accounts for internet access (the password is typed at the prompt, twice):

```
ssh -t Neil@100.91.241.55 wsl -d CyEM -u cyem --cd /home/cyem/cyem -- docker exec -it cyem python -m app.cli user add <name>
... user passwd <name> | user signout <name> | user del <name> | user list
```

Publishing, on Windows as an administrator:

```
"C:\Program Files\Tailscale\tailscale.exe" serve status
"C:\Program Files\Tailscale\tailscale.exe" funnel --https=443 off       # take it off the internet; the tailnet keeps working
"C:\Program Files\Tailscale\tailscale.exe" funnel --bg --https=443 http://127.0.0.1:3020   # put it back
```

## Rebuilding from nothing

1. `wsl --install Ubuntu-24.04 --name CyEM --location C:\WSL\CyEM --no-launch`
2. As root in the distro: `/etc/wsl.conf` with `[boot] systemd=true`, `[user] default=cyem`, `[interop] appendWindowsPath=false`;
   `useradd -m -u 1000 cyem`; `apt-get install docker.io docker-compose-v2 git`; `usermod -aG docker cyem`; restart the distro
   (`wsl --terminate CyEM`) and `systemctl enable --now docker`.
3. As cyem: deploy key, `~/.ssh/known_hosts` from `https://api.github.com/meta`, clone, `.env` from `.env.example`,
   `searxng/settings.yml` from `searxng/settings.example.yml` (before the first `up`), `docker compose up -d --build`.
4. Register the keep-alive task (copy of the ImmichML one with `-d CyEM`), then `tailscale serve` and `tailscale funnel`
   as above, then create the accounts.

## Not yet done

- Off-box copy of `data-store` (accounts, EMO scenarios and COAs, saved links and sites); everything else is re-downloadable.
- The Home Assistant panel (point an iframe card at the tailnet URL).
- Keyed feeds: aisstream, OpenCelliD, Cloudflare Radar keys in `.env`.
- SDR sweeps: the RTL-SDR on the MS-A2 serves trade's Ecowitt receiver.
