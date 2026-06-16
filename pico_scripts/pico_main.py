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
FETCH_INTERVAL = 5 * 60        # 5 分鐘抓一次
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
    total_games = 0
    dashboard_plays = 0
    dashboard_wins = 0
    dashboard_delta = 0
    for game_name, players in leaderboard_cache.items():
        # 彙整這個遊戲的統計
        total_plays = 0
        total_wins  = 0
        total_delta = 0
        player_count = len(players)
        total_games += 1
        for uid, d in players.items():
            total_plays += d.get("plays", 0)
            total_wins  += d.get("wins", 0)
            total_delta += d.get("total_delta", 0)

        dashboard_plays += total_plays
        dashboard_wins += total_wins
        dashboard_delta += total_delta
        delta_class = "pos" if total_delta >= 0 else "neg"
        delta_str = ("+" if total_delta >= 0 else "") + str(total_delta)

        game_rows += (
            "<tr>"
            "<td><span class='game-dot'></span>" + game_name + "</td>"
            "<td>" + str(player_count) + "</td>"
            "<td>" + str(total_plays) + "</td>"
            "<td>" + str(total_wins) + "</td>"
            "<td class='" + delta_class + "'>" + delta_str + "</td>"
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
    medals = ["gold", "silver", "bronze"]
    for i, (uid, data) in enumerate(sorted_players[:3]):
        medal = medals[i] if i < 3 else ""
        d = data["delta"]
        d_str = ("+" if d >= 0 else "") + str(d)
        delta_class = "pos" if d >= 0 else "neg"
        top_rows += (
            "<tr>"
            "<td><span class='rank " + medal + "'>" + str(i + 1) + "</span></td>"
            "<td class='player'>" + uid[-6:] + "</td>"
            "<td>" + str(data["plays"]) + "</td>"
            "<td class='" + delta_class + "'>" + d_str + "</td>"
            "</tr>"
        )

    if not game_rows:
        game_rows = "<tr><td colspan='5' style='text-align:center;color:#7A8BB5'>no data</td></tr>"
    if not top_rows:
        top_rows = "<tr><td colspan='4' style='text-align:center;color:#7A8BB5'>no data</td></tr>"

    refresh_sec = str(FETCH_INTERVAL + 10)
    total_players = len(all_players)
    dashboard_delta_str = ("+" if dashboard_delta >= 0 else "") + str(dashboard_delta)
    dashboard_delta_class = "pos" if dashboard_delta >= 0 else "neg"

    html = (
        "<!DOCTYPE html><html><head>"
        "<meta charset='UTF-8'>"
        "<meta http-equiv='refresh' content='" + refresh_sec + "'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>DCRobot Dashboard</title>"
        "<style>"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{min-height:100vh;background:linear-gradient(135deg,#071025 0%,#101A3B 55%,#230B38 100%);color:#EAF1FF;font-family:Arial,sans-serif;padding:16px}"
        ".wrap{max-width:920px;margin:0 auto}"
        ".hero{background:linear-gradient(135deg,rgba(68,201,224,.2),rgba(244,196,48,.12));border:1px solid rgba(255,255,255,.12);border-radius:22px;padding:18px;box-shadow:0 16px 40px rgba(0,0,0,.28);margin-bottom:14px}"
        ".eyebrow{color:#44C9E0;font-size:.72rem;font-weight:bold;letter-spacing:.14em;text-transform:uppercase;margin-bottom:6px}"
        "h1{color:#fff;font-size:1.75rem;line-height:1.1;margin-bottom:8px;text-shadow:0 2px 18px rgba(68,201,224,.35)}"
        ".sub{color:#AAB8D8;font-size:.82rem;line-height:1.4}"
        ".cards{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:14px 0}"
        ".card{background:rgba(13,21,51,.78);border:1px solid rgba(68,201,224,.18);border-radius:16px;padding:12px;box-shadow:inset 0 1px 0 rgba(255,255,255,.06)}"
        ".label{color:#7A8BB5;font-size:.72rem;margin-bottom:5px}"
        ".value{font-size:1.35rem;font-weight:bold;color:#fff}"
        ".panel{background:rgba(6,11,26,.72);border:1px solid rgba(255,255,255,.1);border-radius:18px;overflow:hidden;margin-bottom:14px;box-shadow:0 12px 28px rgba(0,0,0,.22)}"
        "h2{color:#44C9E0;font-size:1rem;padding:14px 14px 4px}"
        "table{width:100%;border-collapse:collapse;font-size:.86rem}"
        "th{color:#8EEBFF;font-size:.72rem;font-weight:bold;text-transform:uppercase;letter-spacing:.04em;padding:10px 12px;text-align:left;border-bottom:1px solid rgba(68,201,224,.18)}"
        "td{padding:11px 12px;border-bottom:1px solid rgba(255,255,255,.07)}"
        "tr:last-child td{border-bottom:0}"
        ".game-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#44C9E0;box-shadow:0 0 12px #44C9E0;margin-right:8px}"
        ".rank{display:inline-grid;place-items:center;width:25px;height:25px;border-radius:50%;background:#1E2D5A;color:#EAF1FF;font-weight:bold}"
        ".gold{background:#F4C430;color:#1B1500}.silver{background:#C0C8D8;color:#111827}.bronze{background:#CD7F32;color:#1B0D00}"
        ".player{color:#AAB8D8;font-family:monospace}"
        ".pos{color:#3DCEA9;font-weight:bold}.neg{color:#FF6B7A;font-weight:bold}"
        ".footer{color:#7A8BB5;font-size:.75rem;text-align:center;margin-top:16px}"
        "@media(min-width:680px){body{padding:28px}.cards{grid-template-columns:repeat(4,1fr)}h1{font-size:2.15rem}}"
        "</style></head><body><div class='wrap'>"
        "<section class='hero'><p class='eyebrow'>MiniGame Live Stats</p>"
        "<h1>DCRobot Leaderboard</h1>"
        "<p class='sub'>Pico 2W Dashboard | 每 5 分鐘更新 | 上次取得: " + last_fetch + "</p></section>"
        "<section class='cards'>"
        "<div class='card'><p class='label'>遊戲數</p><p class='value'>" + str(total_games) + "</p></div>"
        "<div class='card'><p class='label'>玩家數</p><p class='value'>" + str(total_players) + "</p></div>"
        "<div class='card'><p class='label'>總場次</p><p class='value'>" + str(dashboard_plays) + "</p></div>"
        "<div class='card'><p class='label'>金幣變化</p><p class='value " + dashboard_delta_class + "'>" + dashboard_delta_str + "</p></div>"
        "</section>"

        "<section class='panel'><h2>遊戲統計</h2>"
        "<table><thead>"
        "<tr><th>遊戲</th><th>玩家數</th><th>總場次</th><th>總勝場</th><th>金幣變化</th></tr>"
        "</thead><tbody>" + game_rows + "</tbody></table></section>"

        "<section class='panel'><h2>總排行（金幣變化）</h2>"
        "<table><thead>"
        "<tr><th>#</th><th>玩家ID後6碼</th><th>場次</th><th>金幣</th></tr>"
        "</thead><tbody>" + top_rows + "</tbody></table></section>"

        "<p class='footer'>Powered by Raspberry Pi Pico 2W</p>"
        "</div></body></html>"
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