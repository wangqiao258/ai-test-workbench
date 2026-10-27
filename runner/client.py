"""平台 API 客户端。runner 是平台的普通调用方，所有读写都走 HTTP。"""

import requests


class ApiError(Exception):
    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body}")


class Platform:
    def __init__(self, base_url, token, timeout=30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-API-Token": token})

    # ---- 基础 -------------------------------------------------------
    def _call(self, method, path, **kw):
        kw.setdefault("timeout", self.timeout)
        resp = self.session.request(method, self.base + path, **kw)
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, (resp.text or "")[:800])
        return resp.json() if resp.content else None

    # ---- 批次 -------------------------------------------------------
    def queued_runs(self, project_id=None):
        q = "?status=queued"
        if project_id:
            q += f"&project_id={project_id}"
        return self._call("GET", "/api/runs" + q) or []

    def claim(self, run_id, runner_id=""):
        return self._call("POST", f"/api/runs/{run_id}/claim",
                          json={"runner_id": runner_id})

    def heartbeat(self, run_id):
        """报活：平台靠它区分"还在跑"和"进程已经死了"。"""
        return self._call("POST", f"/api/runs/{run_id}/heartbeat")

    def finish(self, run_id, status="done", note=""):
        return self._call("POST", f"/api/runs/{run_id}/finish",
                          json={"status": status, "note": note})

    # ---- 执行回填 ---------------------------------------------------
    def accounts(self, project_id):
        return self._call("GET", f"/api/projects/{project_id}/accounts") or []

    def add_execution(self, case_id, payload):
        return self._call("POST", f"/api/cases/{case_id}/executions", json=payload)

    def add_packet(self, payload):
        return self._call("POST", "/api/packets", json=payload)
