import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from swe25 import preflight as P
from swe25.config import Arm


@pytest.fixture
def server():
    state = {"props": {"default_generation_settings": {"n_ctx": 262144}}, "auth": []}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            state["auth"].append(self.headers.get("Authorization"))
            body = {"/v1/models": {"data": [{"id": "my-model"}]}, "/props": state["props"]}.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.end_headers()
            self.wfile.write(json.dumps(body or {}).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1", state
    srv.shutdown()


def arm(endpoint, **k):
    return Arm(name="a", agent="pi", model="my-model", endpoint=endpoint, **k)


def test_endpoint_models_lists_ids(server, monkeypatch):
    url, state = server
    monkeypatch.setenv("K", "sekrit")
    assert P.endpoint_models(arm(url, api_key_env="K")) == ["my-model"]
    assert state["auth"][-1] == "Bearer sekrit"


def test_endpoint_unreachable_raises():
    with pytest.raises(P.PreflightError, match="not reachable"):
        P.endpoint_models(arm("http://127.0.0.1:1/v1"))


def test_server_ctx_reads_llamacpp_props(server):
    url, _ = server
    assert P.server_ctx(arm(url)) == 262144


def test_ctx_mismatch_refuses(server):
    url, state = server
    state["props"] = {"default_generation_settings": {"n_ctx": 32768}}
    with pytest.raises(P.PreflightError, match="32768"):
        P.check_pi_arm(arm(url, context=262144))


def test_ctx_unverifiable_is_a_warning_not_an_error(server):
    url, state = server
    state["props"] = None                     # not llama.cpp: no /props
    warnings = P.check_pi_arm(arm(url))
    assert any("cannot verify" in w for w in warnings)


def test_unknown_model_id_is_a_warning(server):
    url, _ = server
    a = Arm(name="a", agent="pi", model="other", endpoint=url)
    assert any("other" in w for w in P.check_pi_arm(a))
