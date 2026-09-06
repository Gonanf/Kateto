"""
Filtro de secretos — regex + entropía, sin modelo.

Descarta mensajes que contengan API keys, tokens, credenciales o
material sensible antes de que lleguen al dataset de fine-tuning.
Corre ANTES del filtro IA: es barato y un leak en dataset.jsonl
es peor que un falso positivo (se pierde un par, no se filtra una key).

Uso:
    from .secrets_filter import contains_secret, redact
    r = contains_secret(text)
    if r.found: drop(reason=r.reasons)
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field

log = logging.getLogger("dataset_filter.secrets")

# Prefijos conocidos: si aparecen, es secreto casi seguro.
KNOWN_PREFIXES = [
    r"sk-[A-Za-z0-9][A-Za-z0-9\-_]{20,}",          # OpenAI / genérico sk-
    r"sk-ant-[A-Za-z0-9\-_]{20,}",                 # Anthropic
    r"AKIA[0-9A-Z]{16}",                           # AWS access key
    r"ASIA[0-9A-Z]{16}",                           # AWS session key
    r"ghp_[A-Za-z0-9]{20,}",                       # GitHub personal
    r"gho_[A-Za-z0-9]{20,}",                       # GitHub OAuth
    r"ghu_[A-Za-z0-9]{20,}",                       # GitHub user-to-server
    r"ghs_[A-Za-z0-9]{20,}",                       # GitHub server-to-server
    r"ghr_[A-Za-z0-9]{20,}",                       # GitHub refresh
    r"github_pat_[A-Za-z0-9_]{20,}",               # GitHub fine-grained
    r"glpat-[A-Za-z0-9\-_]{16,}",                  # GitLab
    r"xox[baprs]-[A-Za-z0-9\-]{10,}",              # Slack
    r"hf_[A-Za-z0-9]{20,}",                        # HuggingFace
    r"AIza[0-9A-Za-z\-_]{35}",                     # Google API
    r"sk_live_[A-Za-z0-9]{16,}",                   # Stripe
    r"rk_live_[A-Za-z0-9]{16,}",                   # Stripe restricted
    r"\b\d{8,10}:AA[A-Za-z0-9\-_]{30,}",           # Telegram bot token
    r"discord(?:app)?\.com/api/webhooks/[A-Za-z0-9\-_/]{20,}",  # Discord webhook
    r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----",  # PEM
    r"-----BEGIN PGP PRIVATE KEY BLOCK-----",
]

# keyword + valor: api_key=... / password: "..." / token=...
# exige valor de 12+ chars para no comerse "password: 1234" de un chiste
CRED_ASSIGN_RE = re.compile(
    r"(?i)\b(api[\-_ ]?key|apikey|api[\-_ ]?secret|secret[\-_ ]?key|"
    r"access[\-_ ]?token|auth[\-_ ]?token|bearer|client[\-_ ]?secret|"
    r"password|passwd|pwd|contrase[ñn]a)\b\s*[:=]\s*['\"]?"
    r"([\w\-.~+/=]{12,})"
)

# Bearer <token> en headers pegados
BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/=]{20,}")

# user:password@ en URLs
URL_CREDS_RE = re.compile(r"https?://[^/\s:]+:[^/\s@]+@[^\s]+")

KNOWN_RE = re.compile("|".join(f"(?:{p})" for p in KNOWN_PREFIXES))

# token genérico largo: 40+ chars alfanuméricos densos (hashes, JWTs, session ids)
LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-+/=]{40,}\b")


def _shannon(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


@dataclass
class SecretsFilterResult:
    found: bool
    reasons: list[str] = field(default_factory=list)


def contains_secret(text: str) -> SecretsFilterResult:
    reasons: list[str] = []
    t = (text or "").strip()
    if not t:
        return SecretsFilterResult(False)

    m = KNOWN_RE.search(t)
    if m:
        # no loguear el secreto: solo prefijo cortado
        reasons.append(f"known_prefix:{m.group(0)[:8]}...")

    m2 = CRED_ASSIGN_RE.search(t)
    if m2:
        reasons.append(f"cred_assign:{m2.group(1).lower()}")

    if BEARER_RE.search(t):
        reasons.append("bearer_token")

    if URL_CREDS_RE.search(t):
        reasons.append("url_credentials")

    if not reasons:
        # genérico: token largo con entropía alta = probablemente secreto,
        # no un hash comentado ni un UUID de mentira
        for tok in LONG_TOKEN_RE.findall(t):
            core = tok.strip("=/_-+")
            if len(core) >= 32 and _shannon(core) > 4.0:
                reasons.append(f"high_entropy_token:{len(core)}chars")
                break

    return SecretsFilterResult(bool(reasons), reasons)


def redact(text: str, mask: str = "…") -> str:
    """Enmascara secretos para logs/previews. Nunca loguear el original."""
    out = KNOWN_RE.sub(lambda m: m.group(0)[:4] + mask * 8, text)
    out = CRED_ASSIGN_RE.sub(lambda m: f"{m.group(1)}=<redacted>", out)
    out = BEARER_RE.sub("bearer <redacted>", out)
    out = URL_CREDS_RE.sub(lambda m: re.sub(r"://[^/\s:]+:[^/\s@]+@", "://<redacted>@", m.group(0)), out)
    return out
