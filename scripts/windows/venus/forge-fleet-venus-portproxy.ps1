$wslIp = (wsl -d Ubuntu hostname -I).Trim().Split()[0]
if (-not $wslIp) { exit 1 }
netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=18766 2>$null
netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=18766 connectaddress=$wslIp connectport=18766
