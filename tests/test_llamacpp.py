import pytest

from swe25 import llamacpp as L
from swe25.config import Arm, ConfigError


def arm(**k):
    base = dict(name="a", agent="pi", model="m", endpoint="http://127.0.0.1:8081/v1", context=131072,
                sampling={"temp": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0})
    return Arm(**{**base, **k})


def test_build_cmd_exact():
    assert L.build_cmd(arm(), "/m/x.gguf", "llama-server") == [
        "llama-server", "-m", "/m/x.gguf", "--port", "8081", "--host", "0.0.0.0", "-c", "131072", "-ngl", "99",
        "--jinja", "--temp", "0.6", "--top-p", "0.95", "--top-k", "20", "--min-p", "0.0"]


def test_build_cmd_requires_declared_sampling():
    with pytest.raises(ConfigError, match="sampling"):
        L.build_cmd(arm(sampling=None), "/m/x.gguf", "llama-server")


def test_build_cmd_requires_local_endpoint():
    with pytest.raises(ConfigError, match="local"):
        L.build_cmd(arm(endpoint="http://10.1.2.3:8080/v1"), "/m/x.gguf", "llama-server")


def test_gguf_from_serve_block():
    a = arm(serve={"gguf": "/m/y.gguf", "bin": "/opt/llama-server"})
    assert L.resolve(a, None, None) == ("/m/y.gguf", "/opt/llama-server")
    assert L.resolve(a, "/m/z.gguf", None) == ("/m/z.gguf", "/opt/llama-server")
    with pytest.raises(ConfigError, match="gguf"):
        L.resolve(arm(), None, None)
