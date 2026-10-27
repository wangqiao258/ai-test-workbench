"""API 鉴权依赖：X-API-Token 校验与装饰器。"""

import functools

from flask import g, jsonify, request

from db import get_db

def check_token():
    token = request.headers.get("X-API-Token", "")
    if not token:
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT id, name FROM tokens WHERE token=? AND revoked=0", (token,)
    ).fetchone()
    conn.close()
    return row

def token_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        tok = check_token()
        if not tok:
            return jsonify({"error": "missing or invalid X-API-Token"}), 401
        g.actor = f"ai:{tok['name'] or tok['id']}"
        return view(*args, **kwargs)
    return wrapper

