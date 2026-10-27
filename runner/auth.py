"""鉴权策略：把 project_settings.auth 变成一组请求头。

两种形态（都是数据，引擎不硬编码业务）：
  {"type":"static","static_headers":{"Authorization":"Bearer xxx","tenant-id":"163"}}
  {"type":"login","method":"POST","path":"/admin-api/system/auth/login",
   "headers":{"tenant-id":"163"},
   "body":{"username":"{{username}}","password":"{{password}}","clientType":"h5"},
   "token_path":"$.data.accessToken",
   "inject":{"header":"Authorization","prefix":"Bearer "},
   "account_id": 1}
"""

import requests

from core.asserts import get_path, parse_path


def _pick_account(accounts, account_id=None):
    if not accounts:
        return None
    if account_id not in (None, ""):
        for a in accounts:
            if str(a.get("id")) == str(account_id):
                return a
        return None
    return accounts[0]


def _render(value, account):
    """把 {{username}} / {{password}} 换成账号里的值。"""
    if isinstance(value, str):
        return (value.replace("{{username}}", account.get("username", ""))
                     .replace("{{password}}", account.get("password", "")))
    if isinstance(value, dict):
        return {k: _render(v, account) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, account) for v in value]
    return value


def build_headers(platform, project_id, auth, base_url, timeout=30, verify=True):
    """返回 (headers, account, err)。

    err 非空时整轮 run 标 failed，不产生假结果；
    account 交给 executor，供步骤里的 {{account.username}} 使用。
    """
    if not auth:
        return {}, None, ""
    typ = (auth.get("type") or "").lower()
    if typ == "static":
        return ({str(k): str(v) for k, v in (auth.get("static_headers") or {}).items()},
                None, "")
    if typ != "login":
        return {}, None, f"未知的 auth.type: {typ}"

    accounts = platform.accounts(project_id)
    account = _pick_account(accounts, auth.get("account_id"))
    if not account:
        return {}, None, "login 策略需要账号，但项目里没有可用账号（网页「环境与账号」里先添加）"

    url = base_url.rstrip("/") + (auth.get("path") or "")
    body = _render(auth.get("body") or {}, account)
    headers = {str(k): str(v) for k, v in (auth.get("headers") or {}).items()}
    try:
        resp = requests.request(auth.get("method") or "POST", url, headers=headers,
                                json=body, timeout=timeout, verify=verify)
    except requests.RequestException as exc:
        return {}, None, f"登录请求异常: {exc}"
    if resp.status_code >= 400:
        return {}, None, f"登录失败 HTTP {resp.status_code}: {resp.text[:200]}"
    try:
        data = resp.json()
    except ValueError:
        return {}, None, "登录响应不是 JSON，检查 auth.path 是否指对"

    found, token = get_path(data, parse_path(auth.get("token_path")))
    if not found or not token:
        return {}, None, f"登录响应里取不到 token（token_path={auth.get('token_path')}）"

    inject = auth.get("inject") or {}
    name = inject.get("header") or "Authorization"
    prefix = inject.get("prefix")
    if prefix is None:
        prefix = "Bearer "
    # 登录用的租户头等通常业务请求也要带，一并保留
    out = dict(headers)
    out[name] = f"{prefix}{token}"
    return out, account, ""
