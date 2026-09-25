"""Deterministic recognizers used before any local model is considered."""

from __future__ import annotations

import ipaddress
import re
from datetime import date

from ..config import Policy
from ..models import Finding

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
_UUID_ANY = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

_RESOURCE_ID = re.compile(
    rf"(?P<resource>/subscriptions/(?P<subscription>{_UUID_ANY})/resourceGroups/"
    r"[A-Za-z0-9._-]+/providers/[A-Za-z0-9.]+(?:/[A-Za-z0-9._-]+){2,})",
    re.IGNORECASE,
)
_SUBSCRIPTION = re.compile(
    rf"(?P<prefix>/subscriptions/|\bsubscription(?:Id|_id)\s*[:=]\s*[\"']?)(?P<id>{_UUID_ANY})",
    re.IGNORECASE,
)
_TENANT = re.compile(
    rf"(?P<prefix>/tenants?/|\btenant(?:Id|_id)(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*[:=]\s*[\"']?|"
    rf"https?://login\.microsoftonline\.com/)(?P<id>{_UUID_ANY})",
    re.IGNORECASE,
)
_RESOURCE_NAME_KEY = re.compile(
    r"\b(?:name|resourceName|resourceGroup|vmName|computerName|logicAppName)"
    r"[\"']?\s*[:=]\s*[\"']?(?P<name>[A-Za-z0-9][A-Za-z0-9._-]{2,})",
    re.IGNORECASE,
)
_HOSTNAME = re.compile(
    r"(?<![\w@.-])(?P<host>(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(?![\w.-])"
)
_IPV4 = re.compile(r"(?<![\w.])(?P<ip>(?:\d{1,3}\.){3}\d{1,3})(?![\w.])")
_IPV6 = re.compile(r"(?<![\w:])(?P<ip>(?:[0-9A-Fa-f]{1,4}:){2,}[0-9A-Fa-f:]+)(?![\w:])")
_CONNECTION_STRING = re.compile(
    r"(?im)(?P<value>\b(?:DefaultEndpointsProtocol|Endpoint|Server|Data Source)\s*=\s*[^\r\n\"']+)"
)
_PASSWORD = re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*[^\s;]+")
_SECRET_KEY = re.compile(
    r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|client[_-]?secret|"
    r"storage[_-]?key)\s*[:=]\s*[^\s;\",'}]+"
)
_SAS_QUERY = re.compile(r"(?i)(?:\?|&)\w+=[^\s#]+")
_BEARER = re.compile(
    r"(?i)\bBearer\s+(?:[A-Za-z0-9_-]+\.){2}[A-Za-z0-9_-]+"
)
_JWT = re.compile(r"(?<![A-Za-z0-9_-])(?:ey[A-Za-z0-9_-]*\.){2}[A-Za-z0-9_-]+(?![A-Za-z0-9_-])")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]+ PRIVATE KEY-----.*?-----END [A-Z0-9 ]+ PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_LV_ID = re.compile(r"(?<!\d)(?P<id>\d{6}-?\d{5})(?!\d)")
_DK_ID = re.compile(r"(?<!\d)(?P<id>\d{6}-?\d{4})(?!\d)")
_IBAN = re.compile(r"(?<![A-Za-z0-9])(?P<iban>[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){10,30})(?![A-Za-z0-9])")
_EMAIL = re.compile(
    r"(?<![\w.+-])(?P<email>[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+)",
    re.IGNORECASE,
)
_PERSON_KEY = re.compile(
    r"(?im)\b(?:owner|contact|assignee|requested[ \t]+by)[ \t]*:[ \t]*"
    r"(?P<person>[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){1,2})"
    r"(?=[ \t]*(?:$|[,.;]|at\b))"
)
_ORG_KEY = re.compile(
    r"(?i)\b(?:organisation|organization|company|vendor)\s*:\s*"
    r"(?P<org>[A-Z][A-Za-z0-9& .'-]{2,})"
)


def _finding(entity_type: str, text: str, start: int, end: int, score: float = 1.0) -> Finding:
    return Finding(entity_type, text, start, end, "rules", score)


def _group_finding(match: re.Match[str], entity_type: str, group: str, score: float = 1.0) -> Finding:
    start, end = match.span(group)
    return _finding(entity_type, match.group(group), start, end, score)


def _valid_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    blocked_networks = (
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
        ipaddress.ip_network("::1/128"),
    )
    return not any(address in network for network in blocked_networks if address.version == network.version)


def _valid_lv_id(value: str) -> bool:
    digits = value.replace("-", "")
    if len(digits) != 11:
        return False
    try:
        day = int(digits[:2])
        month = int(digits[2:4])
        date(2000, month, day)
    except ValueError:
        return False
    weights = (1, 6, 3, 7, 9, 10, 5, 8, 4, 2, 1)
    return sum(int(digit) * weight for digit, weight in zip(digits, weights)) % 11 == 0


def _valid_dk_id(value: str) -> bool:
    digits = value.replace("-", "")
    if len(digits) != 10:
        return False
    try:
        date(2000, int(digits[2:4]), int(digits[:2]))
    except ValueError:
        return False
    return True


def _valid_iban(value: str) -> bool:
    compact = re.sub(r"[ -]", "", value).upper()
    if not (15 <= len(compact) <= 34 and compact[:2].isalpha() and compact[2:4].isdigit()):
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = ""
    for character in rearranged:
        numeric += str(ord(character) - ord("A") + 10) if character.isalpha() else character
    return int(numeric) % 97 == 1


def _sas_findings(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for query_match in re.finditer(r"(?i)(?:\?|\&)[^\s]+", text):
        query = query_match.group(0)
        names = {
            match.group("name").lower()
            for match in re.finditer(
                r"(?i)(?:^|[?&])(?P<name>[A-Za-z0-9_]+)=[^&\s#]*", query
            )
        }
        if len(names & {"sig", "sv", "se"}) >= 2:
            findings.append(_finding("SAS_TOKEN", query, query_match.start(), query_match.end(), 1.0))
    return findings


def _presidio_findings(text: str) -> list[Finding]:
    """Use Presidio's built-ins when its local NLP runtime is available.

    The deterministic recognizers remain the source of truth for formats and this
    optional bridge allows the standard PERSON/ORGANIZATION recognizers to contribute
    when a workstation has a configured Presidio NLP model.
    """

    try:
        from presidio_analyzer import AnalyzerEngine

        results = AnalyzerEngine().analyze(
            text=text,
            language="en",
            entities=["PERSON", "ORGANIZATION"],
        )
    except Exception:  # noqa: BLE001 - an optional local NLP backend must fail closed
        return []
    return [
        _finding(
            "PERSON" if result.entity_type == "PERSON" else "ORG_NAME",
            text[result.start : result.end],
            result.start,
            result.end,
            float(result.score),
        )
        for result in results
    ]


def detect(text: str, policy: Policy) -> list[Finding]:
    """Return deterministic findings with offsets into *text*.

    Validation-heavy formats are checked after matching their shape, so a bad IBAN
    check digit or an impossible national-ID date is not treated as sensitive data.
    """

    findings: list[Finding] = []

    for match in _RESOURCE_ID.finditer(text):
        findings.append(_group_finding(match, "AZURE_RESOURCE_ID", "resource"))
        name_start = match.start("resource") + match.group("resource").rfind("/") + 1
        name = match.group("resource")[match.group("resource").rfind("/") + 1 :]
        findings.append(_finding("AZURE_RESOURCE_NAME", name, name_start, name_start + len(name), 0.98))
    for match in _SUBSCRIPTION.finditer(text):
        findings.append(_group_finding(match, "AZURE_SUBSCRIPTION_ID", "id"))
    for match in _TENANT.finditer(text):
        findings.append(_group_finding(match, "AZURE_TENANT_ID", "id"))
    for match in _RESOURCE_NAME_KEY.finditer(text):
        findings.append(_group_finding(match, "AZURE_RESOURCE_NAME", "name", 0.90))

    for match in _HOSTNAME.finditer(text):
        value = match.group("host")
        if not re.fullmatch(r"[0-9.]+", value) and not value.lower().startswith("microsoft.") and not value.lower().endswith(
            (".exe", ".dll", ".json", ".yaml", ".yml", ".md", ".py")
        ):
            findings.append(_group_finding(match, "HOSTNAME", "host", 0.95))

    for pattern in (_IPV4, _IPV6):
        for match in pattern.finditer(text):
            if _valid_public_ip(match.group("ip")):
                findings.append(_group_finding(match, "PUBLIC_IP", "ip"))

    findings.extend(_group_finding(match, "CONNECTION_STRING", "value") for match in _CONNECTION_STRING.finditer(text))
    findings.extend(_finding("PASSWORD", match.group(0), match.start(), match.end()) for match in _PASSWORD.finditer(text))
    findings.extend(_finding("SECRET_KEY", match.group(0), match.start(), match.end()) for match in _SECRET_KEY.finditer(text))
    findings.extend(_sas_findings(text))
    findings.extend(_finding("BEARER_TOKEN", match.group(0), match.start(), match.end()) for match in _BEARER.finditer(text))
    findings.extend(_finding("BEARER_TOKEN", match.group(0), match.start(), match.end()) for match in _JWT.finditer(text))
    findings.extend(_finding("PRIVATE_KEY", match.group(0), match.start(), match.end()) for match in _PRIVATE_KEY.finditer(text))

    for match in _LV_ID.finditer(text):
        if _valid_lv_id(match.group("id")):
            findings.append(_group_finding(match, "NATIONAL_ID_LV", "id"))
    for match in _DK_ID.finditer(text):
        if _valid_dk_id(match.group("id")):
            findings.append(_group_finding(match, "NATIONAL_ID_DK", "id"))
    for match in _IBAN.finditer(text):
        if _valid_iban(match.group("iban")):
            findings.append(_group_finding(match, "IBAN", "iban"))

    findings.extend(_group_finding(match, "EMAIL_ADDRESS", "email") for match in _EMAIL.finditer(text))
    findings.extend(_group_finding(match, "PERSON", "person", 0.90) for match in _PERSON_KEY.finditer(text))
    findings.extend(_group_finding(match, "ORG_NAME", "org", 0.90) for match in _ORG_KEY.finditer(text))
    findings.extend(_presidio_findings(text))
    return sorted(findings, key=lambda finding: (finding.start, -(finding.end - finding.start), finding.entity_type))
