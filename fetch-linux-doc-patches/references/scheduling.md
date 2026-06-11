# Daily Scheduling

Use one of these examples after confirming the fetch command works interactively.

## cron

Run daily at 04:15:

```cron
15 4 * * * /usr/bin/python3 /path/to/fetch-linux-doc-patches/scripts/fetch_linux_doc_patches.py --output /path/to/linux-doc-patches >> /path/to/linux-doc-patches/fetch.log 2>&1
```

## systemd user timer

`~/.config/systemd/user/linux-doc-patches.service`:

```ini
[Unit]
Description=Fetch linux-doc patches from lore NNTP

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /path/to/fetch-linux-doc-patches/scripts/fetch_linux_doc_patches.py --output %h/lkml/linux-doc
```

`~/.config/systemd/user/linux-doc-patches.timer`:

```ini
[Unit]
Description=Daily linux-doc patch fetch

[Timer]
OnCalendar=*-*-* 04:15:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now linux-doc-patches.timer
```

## macOS launchd

Create `~/Library/LaunchAgents/org.kernel.linux-doc-patches.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>org.kernel.linux-doc-patches</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/to/fetch-linux-doc-patches/scripts/fetch_linux_doc_patches.py</string>
    <string>--output</string>
    <string>/path/to/linux-doc-patches</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>4</integer>
    <key>Minute</key>
    <integer>15</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/path/to/linux-doc-patches/fetch.log</string>
  <key>StandardErrorPath</key>
  <string>/path/to/linux-doc-patches/fetch.err</string>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/org.kernel.linux-doc-patches.plist
```
