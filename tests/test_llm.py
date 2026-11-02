"""Tests for the robustness of model calls: waiting at a rate limit, repairing an answer that is no valid JSON
(DECISIONS 108). Run with `pytest tests/test_llm.py`."""
import json


import llm as L
from fastapi import HTTPException


class CFG:
    provider, model, api_key, base_url = "rwthgpt", "gpt-6-sol", "k", None


class RateLimitError(Exception):
    """Like the SDKs' error: status 429, optionally with a Retry-After header."""
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.status_code = 429
        self.response = type("R", (), {"headers": {"retry-after": retry_after} if retry_after else {}})()


def provider(*outcomes):
    """A fake _call_llm: raises or returns the outcomes in order."""
    calls = []
    def call(cfg, messages, effort="high"):
        calls.append(messages)
        x = outcomes[len(calls) - 1]
        if isinstance(x, Exception):
            raise x
        return x
    call.calls = calls
    return call


def with_fakes(fake, fn):
    real_call, real_sleep, waits = L._call_llm, L._sleep, []
    L._call_llm, L._sleep = fake, waits.append
    try:
        return fn(), waits
    finally:
        L._call_llm, L._sleep = real_call, real_sleep


def test_the_server_key_is_used_only_when_the_request_has_none(monkeypatch):
    # DECISIONS 139: no key in the code; the server may hold one for RWTHgpt
    from types import SimpleNamespace as NS
    from fastapi.testclient import TestClient
    import app as A
    monkeypatch.delenv("LITMO_RWTHGPT_KEY", raising=False)
    assert L.api_key_of(NS(provider="rwthgpt", api_key="")) == ""
    assert TestClient(A.app).get("/api/config").json() == {"server_keys": {"rwthgpt": False}}
    monkeypatch.setenv("LITMO_RWTHGPT_KEY", "server-key")
    assert L.api_key_of(NS(provider="rwthgpt", api_key="")) == "server-key"
    assert L.api_key_of(NS(provider="rwthgpt", api_key="own-key")) == "own-key"
    assert L.api_key_of(NS(provider="anthropic", api_key="")) == ""          # only for the provider it is set for
    r = TestClient(A.app).get("/api/config").json()
    assert r == {"server_keys": {"rwthgpt": True}} and "server-key" not in str(r)


def test_a_rate_limit_is_waited_out():
    limit = RateLimitError("Requests have exceeded token rate limit")
    result, waits = with_fakes(provider(limit, limit, "answer"), lambda: L.call_llm(CFG, []))
    assert result == "answer" and waits == [15, 30]
    # the provider's own waiting time counts; if it is longer than RATE_LIMIT_MAX_WAIT (a quota for the day),
    # waiting does not help: the limit is reported at once
    fake = provider(RateLimitError("slow down", "7"), RateLimitError("come back tomorrow", "900"), "ok")
    try:
        with_fakes(fake, lambda: L.call_llm(CFG, []))
        assert False, "no error"
    except HTTPException as ex:
        assert ex.status_code == 429 and "come back tomorrow" in ex.detail
    assert len(fake.calls) == 2


def test_errors_that_only_mention_a_limit_are_not_waited_for():
    class BadRequest(Exception):
        status_code = 400
    fake = provider(BadRequest("context_length_exceeded: the input exceeds the model's limit"))
    waits = []
    real_call, real_sleep = L._call_llm, L._sleep
    L._call_llm, L._sleep = fake, waits.append
    try:
        L.call_llm(CFG, [])
        assert False, "no error"
    except HTTPException as ex:
        assert ex.status_code == 429                     # reported as before (DECISIONS 81) - but without waiting
    finally:
        L._call_llm, L._sleep = real_call, real_sleep
    assert waits == [] and len(fake.calls) == 1


def test_a_lasting_limit_is_reported_after_the_waits_and_a_used_up_quota_at_once():
    fake = provider(*[RateLimitError("You exceeded your current quota for this period")] * 4)
    try:
        with_fakes(fake, lambda: L.call_llm(CFG, []))
        assert False, "no error"
    except HTTPException as ex:
        assert ex.status_code == 429 and "The model's limit was reached" in ex.detail
    assert len(fake.calls) == 4
    fake = provider(RateLimitError("insufficient_quota: check your plan and billing"))
    try:
        with_fakes(fake, lambda: L.call_llm(CFG, []))
    except HTTPException as ex:
        assert ex.status_code == 429
    assert len(fake.calls) == 1


def test_an_answer_that_is_no_valid_json_is_repaired_once():
    broken = '{"tests": [{"cq": 1, "expected": "the "best" wine"}]}'
    fixed = json.dumps({"tests": [{"cq": 1, "expected": 'the "best" wine'}]})
    fake = provider(broken, fixed)
    result, _ = with_fakes(fake, lambda: L.call_llm_json(CFG, [{"role": "user", "content": "test"}]))
    assert result["tests"][0]["expected"] == 'the "best" wine'
    repair = fake.calls[1]
    assert "Return exactly the same content as valid JSON" in repair[0]["content"]
    assert repair[1]["content"].startswith("Parser error: ") and broken in repair[1]["content"]
    # if the repair fails too, the original error stands - and _run_llm_json reports it as before
    fake = provider(broken, "still {not json")
    try:
        with_fakes(fake, lambda: L._run_llm_json(CFG, []))
        assert False, "no error"
    except HTTPException as ex:
        assert ex.status_code == 500 and "JSONDecodeError" in ex.detail
    # a valid answer needs no second call
    fake = provider('{"a": 1}')
    assert with_fakes(fake, lambda: L.call_llm_json(CFG, []))[0] == {"a": 1} and len(fake.calls) == 1


def test_the_repair_is_counted_as_its_own_step():
    fake = provider("{broken", '{"a": 1}')
    def run():
        with L.track_usage() as log, L.usage_step("Module plan"):
            real = L._call_llm
            def counting(cfg, messages, effort="high"):
                L._record_usage(10, 1)
                return real(cfg, messages, effort)
            L._call_llm = counting
            try:
                L.call_llm_json(CFG, [])
            finally:
                L._call_llm = real
            return [c["step"] for c in log]
    steps, _ = with_fakes(fake, run)
    assert steps == ["Module plan", "Module plan (JSON repair)"]
