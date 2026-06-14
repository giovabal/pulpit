"""Generic parameterised-token machinery shared by network measures and community strategies.

Both subsystems let the user request an *ordered* list of items, some of which take tunable
parameters and may therefore appear *more than once* with different settings — e.g.
``DIFFUSIONLAG(window=30)`` alongside ``DIFFUSIONLAG(window=90)`` for measures, or
``LEIDEN_CPM(resolution=0.01)`` alongside ``LEIDEN_CPM(resolution=0.05)`` for community
strategies. Each parameterised instance maps to a distinct, parameter-suffixed output key so two
instances of the same item never overwrite each other's column / partition.

This module holds the registry-agnostic core: the parameter/spec/instance dataclasses, the token
parser, and the key canonicaliser. Each subsystem supplies its own registry (``name -> TokenSpec``)
and a thin ``TokenInstance`` subclass exposing a domain-friendly name accessor and a ``spec`` lookup.

Token grammar (keyword args in parentheses; a historical positional form like
``MODULEROLE(LEIDEN_DIRECTED)`` is still accepted, mapping to the i-th declared parameter)::

    PAGERANK                       # parameter-free
    DIFFUSIONLAG(window=90)        # keyword
    LEIDEN_CPM(resolution=0.05)    # keyword (float)
    MODULEROLE(LEIDEN)             # legacy positional → basis=LEIDEN
"""

import re
from dataclasses import dataclass

# NAME or NAME(args). Case-insensitive: the CLI/config path upper-cases whole tokens, so a keyword
# like ``runs=2000`` may arrive as ``RUNS=2000``; the name and parameter names are normalised
# (upper / lower) after the match so either spelling round-trips. Digits are allowed in the name so
# DB-keyed dynamic tokens like ``LABELGROUP5`` (a community strategy / MODULEROLE basis selecting
# the partition induced by LabelGroup pk 5) parse.
TOKEN_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*(?:\(\s*(.*?)\s*\))?\s*$")


@dataclass(frozen=True)
class TokenParam:
    """One tunable parameter.

    ``kind`` is ``"int"``, ``"float"`` or ``"enum"``. ``default`` is used when the token omits the
    parameter (a command may override numeric defaults from a global flag). An empty-string default
    on an ``enum`` means "auto-resolve at compute time". ``choices`` lists the valid enum values.
    """

    name: str
    kind: str
    default: object
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()
    label: str = ""
    help: str = ""


@dataclass(frozen=True)
class TokenSpec:
    """Declarative description of a parameterised token.

    ``primary_keys`` are the numeric node-attribute keys that become sortable columns; ``aux_keys``
    are categorical / count companions written onto the node but surfaced separately. Both are the
    *base* keys — the per-instance parameter suffix is appended at compute time.
    """

    key: str
    label: str
    params: tuple[TokenParam, ...] = ()
    primary_keys: tuple[str, ...] = ()
    aux_keys: tuple[str, ...] = ()


def coerce_value(param: TokenParam, raw: str) -> object:
    """Validate and convert a raw token value for ``param``. Raises ``ValueError`` on bad input."""
    raw = raw.strip()
    if param.kind == "str":
        # Free-form token (upper-cased to match the token convention). Validation against the
        # *available* values happens later at the call site — used for the MODULEROLE ``basis``,
        # whose valid values include DB-dynamic ``LABELGROUP<id>`` tokens that no static
        # ``choices`` tuple can enumerate. ``choices`` may still be set for UI hinting.
        return raw.upper()
    if param.kind == "enum":
        val = raw.upper()
        if val not in param.choices:
            raise ValueError(f"{param.name}={raw!r} is not a valid choice. Choose from {param.choices}.")
        return val
    if param.kind in ("int", "float"):
        try:
            num = int(raw) if param.kind == "int" else float(raw)
        except ValueError as exc:
            raise ValueError(f"{param.name}={raw!r} is not a valid {param.kind}.") from exc
        if param.minimum is not None and num < param.minimum:
            raise ValueError(f"{param.name}={num} is below the minimum {param.minimum}.")
        if param.maximum is not None and num > param.maximum:
            raise ValueError(f"{param.name}={num} is above the maximum {param.maximum}.")
        return num
    raise ValueError(f"Unknown parameter kind {param.kind!r}.")


def slug_value(value: object) -> str:
    """Key-safe slug for a parameter value, used inside node-attribute keys.

    Lower-cases, then makes the result identifier-safe: ``.`` → ``_`` (floats such as ``0.01`` →
    ``0_01``) and ``-`` → ``m`` (negatives). Integers and enum strings contain neither, so their
    slug is just the lower-cased value — identical to the original measures suffixing.
    """
    return str(value).lower().replace(".", "_").replace("-", "m")


@dataclass(frozen=True)
class TokenInstance:
    """One requested token with its resolved parameters.

    ``params`` is an ordered tuple of ``(name, value)`` pairs (spec order), making the instance
    hashable so duplicates can be detected. Parameter-free tokens carry ``()``. Subclasses add a
    domain-friendly alias for ``name`` and a ``spec`` lookup against their own registry.
    """

    name: str
    params: tuple[tuple[str, object], ...] = ()

    @property
    def params_dict(self) -> dict[str, object]:
        return dict(self.params)

    def _visible_params(self) -> list[tuple[str, object]]:
        # Skip empty/auto values (e.g. an unresolved basis) — they neither appear in the token nor
        # contribute to the suffix.
        return [(k, v) for k, v in self.params if v not in (None, "")]

    def token(self) -> str:
        """Round-trip the instance to a CLI/config token, e.g. ``DIFFUSIONLAG(window=90)``."""
        vis = self._visible_params()
        if not vis:
            return self.name
        return f"{self.name}(" + ",".join(f"{k}={v}" for k, v in vis) + ")"

    def suffix(self) -> str:
        """Parameter suffix appended to every node key this instance writes (``""`` if none)."""
        vis = self._visible_params()
        if not vis:
            return ""
        return "_" + "_".join(f"{k}_{slug_value(v)}" for k, v in vis)

    def label_annotation(self) -> str:
        """Human-readable parameter annotation for table/column labels, e.g. `` (runs=2000)``."""
        vis = self._visible_params()
        if not vis:
            return ""
        parts = [f"{k}={str(v).lower() if isinstance(v, str) else v}" for k, v in vis]
        return " (" + ", ".join(parts) + ")"

    def key_for(self, base_key: str) -> str:
        return base_key + self.suffix()

    def resolved_with(self, **overrides: object) -> "TokenInstance":
        """Return a copy with some parameter values replaced (used to pin an auto-resolved value).

        Existing parameter order is preserved; any genuinely new keys are appended in override order.
        The copy keeps the runtime subclass, so ``.spec`` / domain accessors stay available.
        """
        merged = dict(self.params)
        new_keys = [k for k in overrides if k not in merged]
        merged.update(overrides)
        order = [k for k, _ in self.params] + new_keys
        return type(self)(self.name, tuple((k, merged[k]) for k in order))


def base_keys_for(registry: dict[str, TokenSpec]) -> tuple[str, ...]:
    """Every base output key owned by a registry's specs (primary + aux), longest first.

    Longest-first ordering lets :func:`canonical_key` strip the most specific base before a shorter
    prefix can match (e.g. ``leiden_cpm`` before ``leiden``).
    """
    return tuple(
        sorted(
            {bk for spec in registry.values() for bk in (*spec.primary_keys, *spec.aux_keys)},
            key=len,
            reverse=True,
        )
    )


def canonical_key(key: str, base_keys: tuple[str, ...]) -> str:
    """Strip a parameter suffix back to its base key. Keys matching no base are returned unchanged."""
    for base in base_keys:
        if key == base or key.startswith(base + "_"):
            return base
    return key


def parse_tokens(
    tokens: list[str],
    *,
    registry: dict[str, TokenSpec],
    known_tokens: frozenset[str] | set[str],
    all_tokens: list[str],
    instance_cls: type[TokenInstance] = TokenInstance,
    defaults: dict[str, dict[str, object]] | None = None,
    noun: str = "token",
) -> list[TokenInstance]:
    """Parse an ordered token list into de-duplicated ``instance_cls`` objects.

    ``ALL`` expands to ``all_tokens`` with default parameters. ``registry`` maps a token name to its
    :class:`TokenSpec`; names absent from it are parameter-free (drop-once). ``defaults`` supplies
    per-token parameter overrides for omitted values (so a bare token can inherit a global flag).

    Raises ``ValueError`` on an unknown token, an unknown / ill-typed / out-of-range parameter,
    parameters on a parameter-free token, a repeated parameter-free token, or two instances of the
    same token with identical parameters.
    """
    defaults = defaults or {}
    if any(t.strip().upper() == "ALL" for t in tokens):
        # Expand ALL in place into default-parameter instances of every token family
        # not explicitly listed. Replacing the whole list (the old behaviour) would
        # silently drop explicit parameterised instances — "DIFFUSIONLAG(window=90),ALL"
        # must keep window=90 (and not also add the default-window instance).
        explicit_names: set[str] = set()
        for t in tokens:
            stripped = t.strip()
            if not stripped or stripped.upper() == "ALL":
                continue
            m = TOKEN_RE.match(stripped)
            if m:
                explicit_names.add(m.group(1).upper())
        expanded: list[str] = []
        all_seen = False
        for t in tokens:
            if t.strip().upper() == "ALL":
                if not all_seen:
                    expanded.extend(a for a in all_tokens if a.strip().upper() not in explicit_names)
                    all_seen = True
                continue
            expanded.append(t)
        tokens = expanded

    instances: list[TokenInstance] = []
    seen: set[TokenInstance] = set()
    for raw_token in tokens:
        token = raw_token.strip()
        if not token:
            continue
        m = TOKEN_RE.match(token)
        if not m:
            raise ValueError(f"Could not parse {noun} token {raw_token!r}.")
        name, argstr = m.group(1).upper(), (m.group(2) or "").strip()
        if name not in known_tokens:
            valid = sorted(known_tokens) + ["ALL"]
            raise ValueError(f"Unknown {noun} {name!r}. Choose from {valid}.")

        spec = registry.get(name)
        if argstr and spec is None:
            raise ValueError(f"{noun.capitalize()} {name} takes no parameters, but got {argstr!r}.")

        if spec is None:
            instance = instance_cls(name)
        else:
            values: dict[str, object] = {p.name: p.default for p in spec.params}
            values.update(defaults.get(name, {}))
            for i, piece in enumerate([p for p in argstr.split(",") if p.strip()]):
                if "=" in piece:
                    pname, raw = piece.split("=", 1)
                    pname = pname.strip().lower()  # tolerate the CLI/config upper-casing of tokens
                    param = next((p for p in spec.params if p.name == pname), None)
                    if param is None:
                        raise ValueError(f"{name} has no parameter {pname!r}. Valid: {[p.name for p in spec.params]}.")
                else:  # positional → map to the i-th declared parameter (legacy BRIDGING(STRATEGY))
                    if i >= len(spec.params):
                        raise ValueError(f"{name} accepts {len(spec.params)} positional parameter(s).")
                    param, raw = spec.params[i], piece
                values[param.name] = coerce_value(param, str(raw))
            instance = instance_cls(name, tuple((p.name, values[p.name]) for p in spec.params))

        if instance in seen:
            if spec is None:
                raise ValueError(f"{noun.capitalize()} {name} is listed more than once.")
            raise ValueError(
                f"{noun.capitalize()} {instance.token()} is listed more than once with identical parameters."
            )
        seen.add(instance)
        instances.append(instance)
    return instances
