"""Deterministic, structure-preserving stand-ins and their local reverse map."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from pathlib import Path

from .models import Finding

_ORG_NAMES = ("alpha", "bravo", "meridian", "northstar", "cedar", "harbor", "summit", "orbit")
_PEOPLE = (
    ("Mira", "Voss"),
    ("Jonas", "Keller"),
    ("Elin", "Sato"),
    ("Niko", "Berg"),
    ("Asta", "Lind"),
    ("Theo", "Marek"),
    ("Iris", "Nolan"),
    ("Marek", "Vale"),
)
_ALPHANUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_LV_WEIGHTS = (1, 6, 3, 7, 9, 10, 5, 8, 4, 2, 1)
_STRUCTURAL_TOKENS = frozenset(
    {
        "app",
        "api",
        "db",
        "func",
        "kv",
        "la",
        "logic",
        "nic",
        "rg",
        "rmq",
        "sql",
        "stg",
        "storage",
        "subnet",
        "vm",
        "vnet",
        "web",
    }
)


def _normalise(value: str) -> str:
    return " ".join(value.lower().split())


def _casing(value: str, replacement: str) -> str:
    if value.isupper():
        return replacement.upper()
    if value[:1].isupper() and value[1:].islower():
        return replacement.capitalize()
    return replacement


def _seed(key: bytes, finding: Finding, counter: int = 0) -> bytes:
    message = f"{finding.entity_type}|{_normalise(finding.text)}|{counter}".encode()
    return hmac.new(key, message, hashlib.sha256).digest()


def _digits(seed: bytes, length: int) -> str:
    return "".join(str(byte % 10) for byte in seed[:length])


def _preserve_separators(original: str, tokens: list[str]) -> str:
    separators = re.findall(r"[^A-Za-z0-9]+", original)
    if not separators:
        return "".join(tokens)
    output = tokens[0]
    for index, token in enumerate(tokens[1:]):
        output += separators[min(index, len(separators) - 1)] + token
    return output


def _resource_name(seed: bytes, original: str) -> str:
    suffix_match = re.search(r"(?i)([-_](?:dev|test|qa|uat|prd|prod))$", original)
    suffix = suffix_match.group(1) if suffix_match else ""
    base = original[: -len(suffix)] if suffix else original
    tokens = re.split(r"([._-]+)", base)
    word_indexes = [
        index
        for index, token in enumerate(tokens)
        if token and re.fullmatch(r"[A-Za-z0-9]+", token)
    ]
    if not word_indexes:
        return original
    rebuilt: list[str] = []
    for index, token in enumerate(tokens):
        if index not in word_indexes or (
            index != word_indexes[0] and token.lower() in _STRUCTURAL_TOKENS
        ):
            rebuilt.append(token)
            continue
        token_seed = hmac.new(seed, f"{index}|{token.lower()}".encode(), hashlib.sha256).digest()
        position = int.from_bytes(token_seed[:2], "big") % len(_ORG_NAMES)
        if _ORG_NAMES[position] == token.lower():
            position = (position + 1) % len(_ORG_NAMES)
        rebuilt.append(_casing(token, _ORG_NAMES[position]))
    return "".join(rebuilt) + suffix


def _hostname(seed: bytes, original: str) -> str:
    labels = original.split(".")
    if len(labels) < 2:
        return original
    lowered = original.lower()
    if lowered.endswith(".cloudapp.azure.com"):
        suffix_length = 4 if len(labels) > 4 else 3
    elif lowered.endswith(".azurewebsites.net"):
        suffix_length = 2
    else:
        suffix_length = 1
    identifying = labels[: len(labels) - suffix_length]
    suffix = labels[len(labels) - suffix_length :] if suffix_length > 1 else ["invalid"]
    replacements = [
        _resource_name(hmac.new(seed, str(index).encode(), hashlib.sha256).digest(), label)
        for index, label in enumerate(identifying)
    ]
    return ".".join([*replacements, *suffix])


def _public_ip(seed: bytes) -> str:
    ranges = (("192.0.2", 1), ("198.51.100", 1))
    network, _ = ranges[seed[0] % len(ranges)]
    host = 1 + int.from_bytes(seed[1:3], "big") % 253
    return f"{network}.{host}"


def _iban(seed: bytes, original: str) -> str:
    compact = re.sub(r"[ -]", "", original).upper()
    country = compact[:2]
    body_length = len(compact) - 4
    body = "".join(_ALPHANUM[byte % len(_ALPHANUM)] for byte in seed[:body_length])
    rearranged = country + "00" + body
    numeric = "".join(
        str(ord(char) - ord("A") + 10) if char.isalpha() else char
        for char in rearranged[4:] + rearranged[:4]
    )
    check = f"{98 - (int(numeric) % 97):02d}"
    generated = country + check + body
    if " " in original:
        groups = [original[index : index + 4] for index in range(0, len(original), 4)]
        output = []
        cursor = 0
        for group in groups:
            width = len(re.sub(r"[^A-Za-z0-9]", "", group))
            output.append(generated[cursor : cursor + width])
            cursor += width
        return " ".join(output)
    return generated


def _national_id(seed: bytes, original: str, latvian: bool) -> str:
    digits_length = 11 if latvian else 10
    sequence = list(_digits(seed, digits_length - 7))
    prefix = "000000" + "".join(sequence)
    if latvian:
        for _ in range(10):
            check = sum(int(digit) * weight for digit, weight in zip(prefix, _LV_WEIGHTS[:-1]))
            remainder = (-check) % 11
            if remainder < 10:
                prefix += str(remainder)
                break
            sequence[-1] = str((int(sequence[-1]) + 1) % 10)
            prefix = "000000" + "".join(sequence)
    else:
        prefix += _digits(seed[digits_length:], 1)
    if "-" in original:
        return f"{prefix[:6]}-{prefix[6:]}"
    return prefix


def _generate(seed: bytes, finding: Finding) -> str:
    original = finding.text
    entity_type = finding.entity_type
    if entity_type in {"AZURE_SUBSCRIPTION_ID", "AZURE_TENANT_ID"}:
        return str(uuid.UUID(bytes=seed[:16], version=4))
    if entity_type == "PUBLIC_IP":
        return _public_ip(seed)
    if entity_type == "HOSTNAME":
        return _hostname(seed, original)
    if entity_type == "AZURE_RESOURCE_NAME":
        return _resource_name(seed, original)
    if entity_type == "ORG_NAME":
        return _casing(original, _ORG_NAMES[int.from_bytes(seed[:2], "big") % len(_ORG_NAMES)])
    if entity_type == "PERSON":
        first, last = _PEOPLE[int.from_bytes(seed[:2], "big") % len(_PEOPLE)]
        return f"{first} {last}"
    if entity_type == "EMAIL_ADDRESS":
        return f"person{1 + int.from_bytes(seed[:2], 'big') % 9999:04d}@example.invalid"
    if entity_type == "IBAN":
        return _iban(seed, original)
    if entity_type == "NATIONAL_ID_LV":
        return _national_id(seed, original, latvian=True)
    if entity_type == "NATIONAL_ID_DK":
        return _national_id(seed, original, latvian=False)
    digest = hashlib.sha256(seed).hexdigest()[:16]
    return f"swap-{digest}"


class Vault:
    """A keyed local mapping from detector findings to deterministic stand-ins."""

    def __init__(
        self, key: bytes, path: Path | None = None, initial_pairs: dict[str, str] | None = None
    ):
        self._key = key
        self.path = path or Path.home() / ".airlock" / "vault-session.json"
        self._pairs: dict[str, str] = {}
        self._originals: dict[tuple[str, str], str] = {}
        self._known_originals: dict[str, str] = {}
        self._load()
        for stand_in, original in (initial_pairs or {}).items():
            current = self._pairs.get(stand_in)
            if current is not None and current != original:
                raise ValueError("stand-in mapping collision")
            self._pairs[stand_in] = original
        self._known_originals = {
            _normalise(original): stand_in for stand_in, original in self._pairs.items()
        }

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            pairs = data.get("pairs", {})
            if isinstance(pairs, dict):
                self._pairs = {str(key): str(value) for key, value in pairs.items()}
        except (OSError, json.JSONDecodeError, AttributeError):
            self._pairs = {}
        self._known_originals = {
            _normalise(original): stand_in for stand_in, original in self._pairs.items()
        }

    def stand_in(self, finding: Finding) -> str:
        identity = (finding.entity_type, _normalise(finding.text))
        existing = self._originals.get(identity)
        if existing:
            return existing
        known = self._known_originals.get(_normalise(finding.text))
        if known:
            self._originals[identity] = known
            return known
        if finding.entity_type == "AZURE_RESOURCE_ID":
            stand_in = self._resource_id(finding.text)
            current = self._pairs.get(stand_in)
            if current is not None and current != finding.text:
                raise ValueError("resource ID stand-in collision")
            self._pairs[stand_in] = finding.text
            self._originals[identity] = stand_in
            self._known_originals[_normalise(finding.text)] = stand_in
            return stand_in
        counter = 0
        while counter < 128:
            stand_in = _generate(_seed(self._key, finding, counter), finding)
            original_folded = finding.text.casefold()
            stand_in_folded = stand_in.casefold()
            if stand_in_folded == original_folded or (
                finding.entity_type in {"PERSON", "ORG_NAME"}
                and (stand_in_folded in original_folded or original_folded in stand_in_folded)
            ):
                counter += 1
                continue
            current = self._pairs.get(stand_in)
            if current is None or current == finding.text:
                self._pairs[stand_in] = finding.text
                self._originals[identity] = stand_in
                self._known_originals[_normalise(finding.text)] = stand_in
                return stand_in
            counter += 1
        raise ValueError("could not produce a non-overlapping stand-in")

    @staticmethod
    def _resource_components(original: str) -> list[tuple[str, str, int]]:
        segments = original.split("/")
        if (
            len(segments) < 9
            or segments[0]
            or segments[1].lower() != "subscriptions"
            or segments[3].lower() != "resourcegroups"
            or segments[5].lower() != "providers"
            or (len(segments) - 7) % 2 != 0
        ):
            raise ValueError("invalid Azure resource ID")
        components = [
            ("AZURE_SUBSCRIPTION_ID", segments[2], 2),
            ("AZURE_RESOURCE_NAME", segments[4], 4),
        ]
        components.extend(
            ("AZURE_RESOURCE_NAME", segments[index], index) for index in range(8, len(segments), 2)
        )
        return components

    def _resource_id(self, original: str) -> str:
        segments = original.split("/")
        for entity_type, value, index in self._resource_components(original):
            child = Finding(entity_type, value, 0, len(value), "rules", 1.0)
            segments[index] = self.stand_in(child)
        return "/".join(segments)

    def related_pairs(self, finding: Finding) -> dict[str, str]:
        """Return the full stand-in and any resource-ID component aliases."""

        originals = {finding.text}
        if finding.entity_type == "AZURE_RESOURCE_ID":
            originals.update(value for _, value, _ in self._resource_components(finding.text))
        return {
            stand_in: original
            for stand_in, original in self._pairs.items()
            if original in originals
        }

    def original(self, stand_in: str) -> str | None:
        return self._pairs.get(stand_in)

    def known_originals(self) -> list[str]:
        """Normalised originals this vault already maps, including preloaded pairs."""

        return list(self._known_originals)

    def known_entity_type(self, text: str) -> str | None:
        """The entity type an original was first mapped as, if seen in this session."""

        normalised = _normalise(text)
        return next(
            (entity for entity, value in self._originals if value == normalised),
            None,
        )

    def pairs(self) -> dict[str, str]:
        return dict(self._pairs)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"pairs": self._pairs}, indent=2, sort_keys=True)
        self.path.write_text(payload + "\n", encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
