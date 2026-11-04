# wslrelay already publishes the WSL Fleet listener on Windows localhost.
# An extra portproxy on 127.0.0.1:18766 accepts connections and never returns
# a response, so cloudflared reports Cloudflare 502. Keep that rule absent.
netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=18766 | Out-Null
exit 0
