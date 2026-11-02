"""Modellaufrufe: Anbieter, Fehler der Anbieter, Token-Zaehlung und das Lesen der JSON-Antworten."""

import contextvars, json, os, re, time
from contextlib import contextmanager
from fastapi import HTTPException

# ── LLM ────────────────────────────────────────────────────────────────────────
# Token-Verbrauch je Request: call_llm traegt jeden Aufruf in das Log des laufenden Requests ein (falls
# eines aktiv ist), beschriftet mit dem aktuellen Teilschritt (Generierung, Turtle-Korrektur, OOPS!-Fix …).
_usage_log = contextvars.ContextVar("usage_log", default=None)
_usage_step = contextvars.ContextVar("usage_step", default="LLM call")

@contextmanager
def track_usage():
    log = []
    token = _usage_log.set(log)
    try:
        yield log
    finally:
        _usage_log.reset(token)

@contextmanager
def usage_step(name):
    token = _usage_step.set(name)
    try:
        yield
    finally:
        _usage_step.reset(token)

def _record_usage(input_tokens, output_tokens):
    log = _usage_log.get()
    if log is not None:
        log.append({"step": _usage_step.get(), "input_tokens": input_tokens, "output_tokens": output_tokens})

def usage_summary(log):
    """Fasst das Log zusammen. Manche OpenAI-kompatiblen Server melden keinen Verbrauch — die zaehlen als
    'unknown', damit die Summe nicht stillschweigend zu niedrig erscheint."""
    known = [c for c in log if c["input_tokens"] is not None]
    return {"calls": log,
            "input_tokens": sum(c["input_tokens"] for c in known),
            "output_tokens": sum(c["output_tokens"] or 0 for c in known),
            "unknown_calls": len(log) - len(known)}

ANTHROPIC_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5"}

class LLMTruncatedError(Exception):
    """Antwort am Token-Limit abgeschnitten — das JSON waere unvollstaendig und nicht parsebar."""
    def __init__(self, limit):
        super().__init__(f"Die Antwort des Modells wurde nach {limit} Tokens abgeschnitten und ist "
                         "unvollstaendig. Ontologie verkleinern (weniger Module/Key Notions) oder ein "
                         "Modell mit groesserem Ausgabelimit waehlen.")

# Ein Rate-Limit je Minute (VA-Laeufe 3b, 3b-Nachtest: Generierung bzw. Pruefung verloren) ist nach Sekunden vorbei:
# warten und erneut versuchen, so lange der Anbieter es verlangt (Retry-After), sonst nach diesen Pausen (DECISIONS 108)
RATE_LIMIT_WAITS = (15, 30, 60)
RATE_LIMIT_MAX_WAIT = 120
_sleep = time.sleep

# Ein Schluessel des Servers statt eines im Code (DECISIONS 139): fehlt in der Anfrage der Schluessel fuer diesen
# Anbieter, gilt die Umgebungsvariable. Er steht in keiner Datei des Repositorys und erreicht den Browser nie.
SERVER_KEY_ENV = {"rwthgpt": "LITMO_RWTHGPT_KEY"}

def api_key_of(llm_config) -> str:
    return (getattr(llm_config, "api_key", "") or "").strip() or \
        os.environ.get(SERVER_KEY_ENV.get(getattr(llm_config, "provider", ""), ""), "").strip()

def server_keys() -> dict:
    """Fuer welche Anbieter der Server einen Schluessel hat - nur ja/nein, nie der Schluessel."""
    return {p: bool(os.environ.get(v, "").strip()) for p, v in SERVER_KEY_ENV.items()}

def call_llm(llm_config, messages, effort="high"):
    """Ein Modellaufruf. Fehler des Anbieters werden zu klaren HTTP-Fehlern (DECISIONS 81): ein erreichtes Limit
    (Rate-Limit, Nachrichten-Kontingent) ist 429, ein ungueltiger Schluessel 401, keine Verbindung oder Zeitueberschreitung
    504, alles andere vom Anbieter 502 - statt eines allgemeinen 500 mit dem Namen einer SDK-Klasse. Bei einem
    Rate-Limit wird nach einer Pause erneut versucht (DECISIONS 108)."""
    for attempt in range(len(RATE_LIMIT_WAITS) + 1):
        try:
            return _call_llm(llm_config, messages, effort)
        except HTTPException:
            raise
        except LLMTruncatedError:
            raise
        except Exception as ex:
            mapped = _provider_error(llm_config, ex)
            if mapped and attempt < len(RATE_LIMIT_WAITS) and _waitable(ex):
                wait = _retry_after(ex) or RATE_LIMIT_WAITS[attempt]
                print(f"Rate limit of {llm_config.provider} / {llm_config.model}: waiting {wait:g} s "
                      f"(attempt {attempt + 1} of {len(RATE_LIMIT_WAITS)})")
                _sleep(wait)
                continue
            if mapped:
                raise mapped from ex
            raise

def _retry_after(ex):
    """Die Wartezeit, die der Anbieter nennt (Header Retry-After in Sekunden), oder None."""
    headers = getattr(getattr(ex, "response", None), "headers", None) or {}
    try:
        return float(headers.get("retry-after")) or None
    except (TypeError, ValueError):
        return None

def _waitable(ex) -> bool:
    """Lohnt Warten? Nur bei einem echten Rate-Limit (HTTP 429), nicht bei einem aufgebrauchten Guthaben, nicht bei
    400/403-Fehlern, die nur wegen Woertern wie "limit" als Limit gemeldet werden (etwa eine zu lange Eingabe), und
    nicht, wenn der Anbieter laenger als RATE_LIMIT_MAX_WAIT warten laesst (ein Kontingent fuer den Tag)."""
    status = getattr(ex, "status_code", None) or getattr(getattr(ex, "response", None), "status_code", None)
    if not (status == 429 or type(ex).__name__ == "RateLimitError") or "insufficient_quota" in str(ex):
        return False
    return (_retry_after(ex) or 0) <= RATE_LIMIT_MAX_WAIT

def _provider_error(llm_config, ex):
    name = type(ex).__name__
    status = getattr(ex, "status_code", None) or getattr(getattr(ex, "response", None), "status_code", None)
    text = str(getattr(ex, "message", "") or ex)[:300]
    who = f"{llm_config.provider} / {llm_config.model}"
    limit_words = ("rate limit", "rate_limit", "quota", "limit reached", "too many requests", "exceeded", "limit")
    if name == "RateLimitError" or status == 429 or (status in (400, 403) and any(w in text.lower() for w in limit_words)):
        return HTTPException(status_code=429, detail=f"The model's limit was reached ({who}): {text}. Wait until the "
                                                     "limit resets, or choose another model in step 1.")
    if name in ("AuthenticationError", "PermissionDeniedError") or status in (401, 403):
        return HTTPException(status_code=401, detail=f"The provider refused the API key ({who}): {text}")
    if name in ("APIConnectionError", "APITimeoutError", "ConnectTimeout", "ReadTimeout", "ConnectionError"):
        return HTTPException(status_code=504, detail=f"No answer from the provider ({who}): {text}")
    if name == "APIStatusError" or status:
        return HTTPException(status_code=502, detail=f"The provider returned an error ({who}, HTTP {status}): {text}")
    return None

def _call_llm(llm_config, messages, effort="high"):
    if llm_config.provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key_of(llm_config))
        sys_msg = ""
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                sys_msg = m["content"]
            else:
                user_msgs.append(m)
        # Grosse Ontologien brauchen deutlich mehr als 8192 Tokens; bei so grossem Budget verlangt das
        # SDK Streaming, um HTTP-Timeouts zu vermeiden.
        kwargs = {"model": llm_config.model, "max_tokens": 64000, "messages": user_msgs}
        if sys_msg:
            kwargs["system"] = sys_msg
        if not llm_config.model.startswith("claude-haiku"):
            # Ontologie-Modellierung ist anspruchsvoll; Opus 5.5 stuende ohne Angabe nur auf "medium".
            # (Haiku 4.5 kennt den effort-Parameter nicht.)
            kwargs["output_config"] = {"effort": effort}
        if llm_config.model in ANTHROPIC_FALLBACK_MODELS:
            # Lehnen die Sicherheitsklassifikatoren eine Anfrage ab, beantwortet die API sie serverseitig
            # mit einem passenden Ersatzmodell, statt nur abzubrechen.
            with client.beta.messages.stream(**kwargs, betas=["server-side-fallback-2026-07-01"],
                                             fallbacks="default") as stream:
                msg = stream.get_final_message()
        else:
            with client.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
        u = msg.usage
        _record_usage(u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0),
                      u.output_tokens)
        if msg.stop_reason == "max_tokens":
            raise LLMTruncatedError(kwargs["max_tokens"])
        if msg.stop_reason == "refusal":
            raise HTTPException(status_code=502, detail="The model declined the request (refusal). "
                                "Choose another model or rephrase the description.")
        # Bei aktivem Thinking ist der erste Block ein Thinking-Block, nicht der Text
        return "".join(b.text for b in msg.content if b.type == "text")

    elif llm_config.provider in ("openai", "rwthgpt", "gemini"):
        import openai
        from openai import OpenAI
        kwargs = {"api_key": api_key_of(llm_config)}
        if llm_config.provider == "gemini":
            kwargs["base_url"] = "https://generativelanguage.googleapis.com/v1beta/openai/"
        elif llm_config.provider == "rwthgpt":
            kwargs["base_url"] = llm_config.base_url or "https://chat.kiconnect.nrw/api/v1"
        elif llm_config.base_url:
            kwargs["base_url"] = llm_config.base_url
        client = OpenAI(**kwargs)
        # Neuere OpenAI-Modelle (GPT-5.x, GPT-6) verlangen max_completion_tokens, aeltere und viele
        # OpenAI-kompatible Server (KI:connect, Gemini) max_tokens. KI:connect reicht GPT-5.x-Anfragen
        # unveraendert durch — daher nicht nach Provider raten, sondern bei Ablehnung umschalten.
        # Das groessere Budget deckt auch Reasoning-Tokens ab, damit das JSON nicht abgeschnitten wird.
        attempts = [{"max_tokens": 32000}, {"max_completion_tokens": 32000}]
        if llm_config.provider == "openai":
            attempts.reverse()
        for i, limit in enumerate(attempts):
            try:
                resp = client.chat.completions.create(model=llm_config.model, messages=messages, **limit)
                u = resp.usage
                _record_usage(u.prompt_tokens if u else None, u.completion_tokens if u else None)
                choice = resp.choices[0]
                if choice.finish_reason == "length":
                    raise LLMTruncatedError(next(iter(limit.values())))
                return choice.message.content
            except openai.BadRequestError as ex:
                rejected = next(iter(limit))
                if i == 0 and rejected in str(ex) and ("nsupported" in str(ex) or "not supported" in str(ex)):
                    continue
                raise

    raise HTTPException(status_code=400, detail=f"Unknown provider: {llm_config.provider}")

def _relax_json(text: str) -> str:
    """Entfernt, was LLMs gern in JSON schreiben, JSON aber verbietet: //- und /* */-Kommentare sowie
    Kommas vor } oder ]. Inhalte von Strings (z.B. URLs mit //) bleiben unangetastet."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        elif c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
            out.append(c)
        else:
            out.append(c)
        i += 1
    return "".join(out)

def parse_llm_json(raw):
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    s = cleaned.find("{")
    e = cleaned.rfind("}") + 1
    if s == -1 or e == 0:
        raise ValueError("Kein JSON gefunden in: " + cleaned[:200])
    # strict=False: LLMs schreiben mehrzeilige Werte (z.B. Turtle-Beispieldaten) oft mit echten
    # Zeilenumbruechen statt \n in JSON-Strings — der Inhalt ist trotzdem eindeutig.
    try:
        return json.loads(cleaned[s:e], strict=False)
    except json.JSONDecodeError:
        pass
    relaxed = _relax_json(cleaned[s:e])
    try:
        return json.loads(relaxed, strict=False)
    except json.JSONDecodeError as ex:
        # Rohantwort um die Fehlerstelle loggen — sonst ist nicht nachvollziehbar, was das Modell lieferte
        print(f"JSON-Fehler: {ex}\n…{relaxed[max(0, ex.pos - 300):ex.pos + 300]}…")
        raise

# Eine Antwort, die kein gueltiges JSON ist (VA-Lauf 3b: die Hold-out-Tests gingen an einem JSONDecodeError
# verloren), wird nicht neu erzeugt - das kostete den ganzen Aufruf noch einmal -, sondern ein kurzer Aufruf
# schreibt sie als gueltiges JSON ab (DECISIONS 108).
JSON_REPAIR_SYS = ("The text below was meant to be ONE JSON object, but it cannot be parsed. Return exactly the same "
                   "content as valid JSON: the same keys and values, nothing added, nothing left out, nothing "
                   "reworded. Escape quotes and line breaks inside strings. Answer ONLY with the JSON object.")

def call_llm_json(llm_config, messages, effort="high"):
    """call_llm und parse_llm_json; ist die Antwort kein gueltiges JSON, einmal reparieren lassen. Scheitert auch das,
    gilt der urspruengliche Fehler."""
    return parse_llm_json(json_text(llm_config, call_llm(llm_config, messages, effort)))

def json_text(llm_config, raw) -> str:
    """Die Antwort, wenn sie sich als JSON lesen laesst, sonst ihre reparierte Fassung; scheitert auch die, gilt der
    urspruengliche Fehler. Fuer Aufrufer, die den Text selbst brauchen (die Edit-Operationen schicken ihn zurueck)."""
    try:
        parse_llm_json(raw)
        return raw
    except ValueError as ex:             # auch json.JSONDecodeError
        first = ex
    with usage_step(_usage_step.get() + " (JSON repair)"):
        fixed = call_llm(llm_config, [{"role": "system", "content": JSON_REPAIR_SYS},
                                      {"role": "user", "content": f"Parser error: {first}\n\n{raw}"}], effort="low")
    try:
        parse_llm_json(fixed)
        return fixed
    except ValueError:
        raise first

def _run_llm_json(llm_config, messages):
    try:
        return call_llm_json(llm_config, messages)
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=500, detail=type(ex).__name__ + ": " + str(ex))
