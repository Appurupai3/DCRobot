# ============================================================
# Discord MiniGame Bot — Pico 2W 端 v2
# 每 5 分鐘從 Bot 的 /leaderboard API 抓資料並顯示 Dashboard
# ============================================================

import network
import socket
import time
import json
import asyncio

# ── 設定區 ───────────────────────────────────────────────────
WIFI_SSID      = "POCO F5"
WIFI_PASSWORD  = "12345678"
BOT_IP         = "10.233.174.51"   # ← 改成跑 bot 的電腦 IP
BOT_PORT       = 8765
FETCH_INTERVAL = 5              # 5 分鐘抓一次
HTTP_PORT      = 80
# ─────────────────────────────────────────────────────────────

leaderboard_cache = {}
last_fetch = "尚未取得"

# ── Wi-Fi ────────────────────────────────────────────────────
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("[WiFi] connecting " + WIFI_SSID)
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            time.sleep(1)
            timeout -= 1
    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print("[WiFi] connected: " + ip)
        return ip
    raise RuntimeError("[WiFi] failed")

# ── 從 Bot 抓排行榜 ──────────────────────────────────────────
def fetch_leaderboard():
    global leaderboard_cache, last_fetch
    try:
        addr = socket.getaddrinfo(BOT_IP, BOT_PORT)[0][-1]
        s = socket.socket()
        s.settimeout(5)
        s.connect(addr)
        req = "GET /leaderboard HTTP/1.0\r\nHost: " + BOT_IP + "\r\n\r\n"
        s.send(req.encode())

        resp = b""
        while True:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                resp += chunk
            except OSError:
                break
        s.close()

        # 切出 body
        idx = resp.find(b"\r\n\r\n")
        if idx == -1:
            return
        body = resp[idx + 4:]
        leaderboard_cache = json.loads(body.decode("utf-8"))

        t = time.ticks_ms() // 1000
        h = t // 3600 % 24
        m = t // 60 % 60
        s2 = t % 60
        last_fetch = "{:02d}:{:02d}:{:02d}".format(h, m, s2)
        print("[Fetch] OK - " + last_fetch)
    except Exception as e:
        print("[Fetch] error: " + str(e))

# ── 產生 Dashboard HTML ──────────────────────────────────────
def build_html():
    game_rows = ""
    for game_name, players in leaderboard_cache.items():
        # 彙整這個遊戲的統計
        total_plays = 0
        total_wins  = 0
        total_delta = 0
        player_count = len(players)
        for uid, d in players.items():
            total_plays += d.get("plays", 0)
            total_wins  += d.get("wins", 0)
            total_delta += d.get("total_delta", 0)

        delta_color = "#3DCEA9" if total_delta >= 0 else "#EF4444"
        delta_str = ("+" if total_delta >= 0 else "") + str(total_delta)

        game_rows += (
            "<tr>"
            "<td>" + game_name + "</td>"
            "<td>" + str(player_count) + "</td>"
            "<td>" + str(total_plays) + "</td>"
            "<td>" + str(total_wins) + "</td>"
            "<td style='color:" + delta_color + "'>" + delta_str + "</td>"
            "</tr>"
        )

    # 前三名排行
    top_rows = ""
    all_players = {}
    for game_name, players in leaderboard_cache.items():
        for uid, d in players.items():
            if uid not in all_players:
                all_players[uid] = {"delta": 0, "plays": 0}
            all_players[uid]["delta"] += d.get("total_delta", 0)
            all_players[uid]["plays"] += d.get("plays", 0)

    sorted_players = sorted(all_players.items(), key=lambda x: x[1]["delta"], reverse=True)
    medals = ["#F4C430", "#C0C0C0", "#CD7F32"]
    for i, (uid, data) in enumerate(sorted_players[:3]):
        color = medals[i] if i < 3 else "#D8E0F0"
        d = data["delta"]
        d_str = ("+" if d >= 0 else "") + str(d)
        top_rows += (
            "<tr>"
            "<td style='color:" + color + ";font-weight:bold'>" + str(i + 1) + "</td>"
            "<td style='font-size:.75rem;color:#7A8BB5'>" + uid[-6:] + "</td>"
            "<td>" + str(data["plays"]) + "</td>"
            "<td style='color:" + color + "'>" + d_str + "</td>"
            "</tr>"
        )

    if not game_rows:
        game_rows = "<tr><td colspan='5' style='text-align:center;color:#7A8BB5'>no data</td></tr>"
    if not top_rows:
        top_rows = "<tr><td colspan='4' style='text-align:center;color:#7A8BB5'>no data</td></tr>"

    refresh_sec = str(FETCH_INTERVAL + 10)

    html = (
        "<!DOCTYPE html><html><head>"
        "<meta charset='UTF-8'>"
        "<meta http-equiv='refresh' content='" + refresh_sec + "'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>DCRobot Dashboard</title>"
        "<style>"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{background:#060B1A;color:#D8E0F0;font-family:Arial,sans-serif;padding:20px}"
        "h1{color:#F4C430;font-size:1.5rem;margin-bottom:4px}"
        ".sub{color:#7A8BB5;font-size:.8rem;margin-bottom:20px}"
        "h2{color:#44C9E0;font-size:1rem;margin:20px 0 8px}"
        "table{width:100%;border-collapse:collapse;font-size:.85rem;margin-bottom:24px}"
        "th{background:#0D1533;color:#44C9E0;padding:8px;text-align:left;border-bottom:1px solid #1E2D5A}"
        "td{padding:7px 8px;border-bottom:1px solid #1E2D5A}"
        ".footer{color:#7A8BB5;font-size:.75rem;text-align:center;margin-top:12px}"
        "</style></head><body>"
        "<h1>DCRobot Leaderboard</h1>"
        "<p class='sub'>Pico 2W Dashboard | 每 5 秒更新 | 上次取得: " + last_fetch + "</p>"

        "<h2>遊戲統計</h2>"
        "<table><thead>"
        "<tr><th>遊戲</th><th>玩家數</th><th>總場次</th><th>總勝場</th><th>金幣變化</th></tr>"
        "</thead><tbody>" + game_rows + "</tbody></table>"

        "<h2>總排行（金幣變化）</h2>"
        "<table><thead>"
        "<tr><th>#</th><th>玩家ID後6碼</th><th>場次</th><th>金幣</th></tr>"
        "</thead><tbody>" + top_rows + "</tbody></table>"

        "<p class='footer'>Powered by Raspberry Pi Pico 2W</p>"
        "</body></html>"
    )
    return html

# ── HTTP Server ──────────────────────────────────────────────
def http_response(code, content_type, body):
    if isinstance(body, str):
        body = body.encode("utf-8")
    codes = {200: "200 OK", 404: "404 Not Found"}
    header = (
        "HTTP/1.1 " + codes.get(code, "200 OK") + "\r\n"
        "Content-Type: " + content_type + "; charset=utf-8\r\n"
        "Content-Length: " + str(len(body)) + "\r\n"
        "Connection: close\r\n\r\n"
    )
    return header.encode() + body

async def http_server():
    addr = socket.getaddrinfo("0.0.0.0", HTTP_PORT)[0][-1]
    srv  = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(addr)
    srv.listen(3)
    srv.setblocking(False)
    print("[HTTP] port " + str(HTTP_PORT))

    while True:
        try:
            conn, addr = srv.accept()
        except OSError:
            await asyncio.sleep(0.05)
            continue
        try:
            conn.setblocking(False)
            raw = b""
            deadline = time.ticks_ms() + 2000
            while time.ticks_ms() < deadline:
                try:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    raw += chunk
                    if b"\r\n\r\n" in raw:
                        break
                except OSError:
                    await asyncio.sleep(0.02)

            resp = http_response(200, "text/html", build_html())
            conn.sendall(resp)
        except Exception as e:
            print("[HTTP] error: " + str(e))
        finally:
            conn.close()
        await asyncio.sleep(0)

# ── 定期抓資料 task ──────────────────────────────────────────
async def fetch_loop():
    while True:
        fetch_leaderboard()
        await asyncio.sleep(FETCH_INTERVAL)

# ── Wi-Fi 看門狗 ─────────────────────────────────────────────
async def wifi_watchdog():
    wlan = network.WLAN(network.STA_IF)
    while True:
        await asyncio.sleep(30)
        if not wlan.isconnected():
            print("[WiFi] reconnecting...")
            try:
                connect_wifi()
            except Exception as e:
                print("[WiFi] failed: " + str(e))

# ── 主程式 ───────────────────────────────────────────────────
async def main():
    ip = connect_wifi()
    print("\n[Ready] Dashboard: http://" + ip + "/\n")
    fetch_leaderboard()   # 開機先抓一次
    await asyncio.gather(
        http_server(),
        fetch_loop(),
        wifi_watchdog(),
    )

asyncio.run(main())