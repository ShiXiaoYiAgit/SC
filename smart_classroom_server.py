#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智慧教室数据代理 - Back4App 优化版
"""

import json
import os
import ssl
import sys
import traceback
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from flask import Flask, send_from_directory, jsonify

print("=" * 50, flush=True)
print("[启动] 智慧教室数据代理", flush=True)
print("[启动] Python版本:", sys.version, flush=True)
print("[启动] 工作目录:", os.getcwd(), flush=True)
print("[启动] 文件列表:", os.listdir('.'), flush=True)
print("=" * 50, flush=True)

app = Flask(__name__)

# ============================================
# ⚠️ 请在这里更新你的 API Token！
# 登录 https://iot.dfrobot.com.cn/ → 个人中心 → 复制 Token
# ============================================
CFG = {
    "api_url": "https://api.dfrobot.work/easyiot/apiv3/messages/search",
    "api_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODkwMzgwMDEsImlvdF9uYW1lIjoielV5endOUURSIiwibmJmIjoxNzg4ODY1MjAxLCJ1c2VyX2lkIjoiNWNiMTE2MGQ2YmI3NGE0ZDgzMTc0MDI4YjAyNDM4OWIifQ.NItH-YxAfSlLJkYEYDikxyfZwK1_6w8daNwYktUM4Is",
    "topic": "rqMHQNQvR",
    "http_port": int(os.environ.get("PORT", 5000)),
}

print("[配置] API URL:", CFG["api_url"], flush=True)
print("[配置] Topic:", CFG["topic"], flush=True)
print("[配置] 端口:", CFG["http_port"], flush=True)
print("[配置] Token前缀:", CFG["api_token"][:20] + "...", flush=True)


def extract_messages(data):
    """从 API 响应中递归提取消息列表"""
    if isinstance(data, list):
        if len(data) > 0 and isinstance(data[0], dict):
            return data
        return []
    if isinstance(data, dict):
        for key in ['messages', 'data', 'list', 'items', 'result', 'records', 'rows', 'msgList']:
            if key in data:
                return extract_messages(data[key])
        for value in data.values():
            if isinstance(value, (list, dict)):
                found = extract_messages(value)
                if found:
                    return found
    return []


def get_field(obj, keys):
    """按候选键名顺序获取字典字段"""
    for k in keys:
        if k in obj and obj[k] is not None:
            return obj[k]
    return None


def parse_time(raw):
    """解析各种格式的时间为 YYYY-MM-DD HH:MM:SS"""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            ts = raw / 1000 if raw > 1e10 else raw
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except:
            return str(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        if s.isdigit():
            try:
                ts = int(s) / 1000 if int(s) > 1e10 else int(s)
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            except:
                return s
        clean = s
        if clean.endswith('Z'):
            clean = clean[:-1]
        if '+' in clean:
            clean = clean.split('+')[0]
        formats = [
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(clean, fmt).strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass
        return s
    return str(raw)


def fetch_history_from_api():
    """从 DFRobot API 获取历史数据"""
    try:
        payload = json.dumps({"topic": CFG["topic"], "count": 1000}).encode('utf-8')
        req = Request(
            CFG["api_url"],
            data=payload,
            method='POST',
            headers={
                'Content-Type': 'application/json;charset=UTF-8',
                'Authorization': CFG["api_token"],
                'Origin': 'https://iot.dfrobot.com.cn',
                'Referer': 'https://iot.dfrobot.com.cn/',
                'Accept': 'application/json, text/plain, */*',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            }
        )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urlopen(req, context=ctx, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        raw_messages = extract_messages(data)
        if not raw_messages:
            return [], f"响应中无消息列表。响应预览: {str(data)[:300]}"
        result = []
        time_keys = ['time', 'timestamp', 'created_at', 'create_time', 'updated_at', 'update_time',
                     'date', 'datetime', 'ts', 'send_time', 'pub_time', 'publish_time', 'msg_time',
                     'createTime', 'updateTime', 'sendTime', 'publishTime', 'msgTime', 'createdAt']
        msg_keys = ['message', 'msg', 'content', 'payload', 'data', 'value', 'body', 'text', 'info', 'raw']
        for m in raw_messages:
            if not isinstance(m, dict):
                continue
            raw_time = get_field(m, time_keys)
            raw_msg = get_field(m, msg_keys)
            if raw_msg is None:
                continue
            fmt_time = parse_time(raw_time)
            if fmt_time is None:
                fmt_time = "未知时间"
            result.append({
                "topic": m.get('topic', m.get('topicName', CFG["topic"])),
                "message": str(raw_msg),
                "time": fmt_time,
            })
        return result, None
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode('utf-8')[:300]
        except:
            pass
        return [], f"HTTP {e.code}: {body}"
    except Exception as e:
        return [], f"请求失败: {e}"


def pair_messages(msgs):
    """A_/M_ 配对"""
    a_list = []
    m_list = []
    for m in msgs:
        msg = str(m.get("message", "")).strip()
        t = m.get("time", "")
        if not msg or not t:
            continue
        if msg.startswith("A_"):
            try:
                a_list.append({"time": t, "value": float(msg[2:])})
            except:
                pass
        elif msg.startswith("M_"):
            try:
                m_list.append({"time": t, "value": float(msg[2:])})
            except:
                pass

    def to_dt(t):
        try:
            return datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
        except:
            return None

    a_list.sort(key=lambda x: to_dt(x["time"]) or datetime.min)
    m_list.sort(key=lambda x: to_dt(x["time"]) or datetime.min)

    used = set()
    pairs = []
    for a in a_list:
        a_dt = to_dt(a["time"])
        for i, m in enumerate(m_list):
            if i in used:
                continue
            m_dt = to_dt(m["time"])
            if a_dt and m_dt:
                if abs((a_dt - m_dt).total_seconds()) <= 2:
                    used.add(i)
                    later = a["time"] if a_dt > m_dt else m["time"]
                    pairs.append({"time": later, "light": round(a["value"], 2), "mic": round(m["value"], 2)})
                    break
            elif a["time"] == m["time"]:
                used.add(i)
                pairs.append({"time": a["time"], "light": round(a["value"], 2), "mic": round(m["value"], 2)})
                break

    pairs.sort(key=lambda x: to_dt(x["time"]) or datetime.min, reverse=True)
    return pairs


@app.route('/')
def home():
    try:
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project9.html')
        if os.path.exists(html_path):
            return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'project9.html')
    except Exception as e:
        return f"<h1>加载页面出错: {e}</h1>"
    return "<h1>project9.html not found</h1>"


@app.route('/api/paired')
def api_paired():
    """获取配对后的历史数据"""
    api_messages, error = fetch_history_from_api()
    if error:
        return jsonify({
            "success": False,
            "error": error,
            "latest": None,
            "history": [],
            "count": 0,
            "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    pairs = pair_messages(api_messages)
    latest = pairs[0] if pairs else None
    return jsonify({
        "success": True,
        "latest": latest,
        "history": pairs[:1000],
        "count": len(pairs),
        "raw_count": len(api_messages),
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route('/api/debug')
def api_debug():
    """调试端点"""
    api_messages, error = fetch_history_from_api()
    return jsonify({
        "success": error is None,
        "error": error,
        "parsed_count": len(api_messages),
        "messages_preview": api_messages[:5] if api_messages else [],
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route('/api/status')
def api_status():
    return jsonify({
        "status": "running",
        "topic": CFG["topic"],
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


# ============================================
# 启动应用（兼容直接运行和 gunicorn）
# ============================================
if __name__ == '__main__':
    try:
        port = CFG["http_port"]
        print(f"[启动] 正在启动 Flask 应用，绑定 0.0.0.0:{port}", flush=True)
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except Exception as e:
        print(f"[启动失败] {e}", flush=True)
        traceback.print_exc()
        sys.exit(1)
