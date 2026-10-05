"""
Redvypr addresses are the base to identify and address redvypr data packets and their content.
see also the documentation here: :ref:`design_addressing`.

An address has a left side (the datakey, e.g. ``data['temp'][0]``) and a right side
(the filter, e.g. ``d:'cam' and i:'test'`` or ``data > 2``), separated by ``@``.

Implementation: the right side is parsed once (cached per string) into a small
filter tree that is evaluated directly on the packet, without eval(); the common
case, metadata equality joined by ``and``, is a list of (path, value) checks. The
left side is a key/index path traversed directly; other Python expressions on the
left side (slices, calculations) are evaluated with eval(). The address string is
generated from the tree and cached per format.
"""

import re
import copy
import logging
import sys
import operator
import typing
from datetime import datetime
from typing import Any, List, Optional, Union
import ast
import tokenize
import io

import pydantic
from pydantic_core import core_schema

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.base.redvypr_address')
logger.setLevel(logging.INFO)

metadata_address = "_redvypr_command@i:metadata"


# Address entries that identify a datastream (e.g. the key of the packet statistics).
# deviceid, sensor and sensorid are needed to separate devices with the same name;
# packets without them get the same address as before.
redvypr_standard_address_filter = ["i","p","d","h","u","a","di","s","si"]


# Exceptions
class FilterNoMatch(Exception):
    pass


class FilterFieldMissing(Exception):
    pass


class SoftPlaceholder:
    """Value of a missing field in a fallback (eval) filter: every comparison gives sm_value."""
    __slots__ = ("val",)

    def __init__(self, sm_value):
        self.val = sm_value

    def __eq__(self, other): return self.val
    def __ne__(self, other): return self.val
    def __lt__(self, other): return self.val
    def __le__(self, other): return self.val
    def __gt__(self, other): return self.val
    def __ge__(self, other): return self.val
    def __bool__(self): return self.val
    def __hash__(self): return 0
    def __call__(self, *args, **kwargs): return self


_MISSING = object()

_CMP_OPS = {ast.Eq: ("==", operator.eq), ast.NotEq: ("!=", operator.ne), ast.Lt: ("<", operator.lt),
            ast.LtE: ("<=", operator.le), ast.Gt: (">", operator.gt), ast.GtE: (">=", operator.ge),
            ast.In: ("in", lambda a, b: a in b), ast.NotIn: ("not in", lambda a, b: a not in b),
            ast.Is: ("is", operator.is_), ast.IsNot: ("is not", operator.is_not)}
_OP_FUNC = {sym: f for sym, f in _CMP_OPS.values()}

# Parsed strings: expr -> (left_expr, rhs tree, bracket style or None)
_PARSE_CACHE = {}
_PARSE_CACHE_MAX = 20000


def _parse_cache_put(key, value):
    if len(_PARSE_CACHE) >= _PARSE_CACHE_MAX:
        _PARSE_CACHE.clear()
    _PARSE_CACHE[key] = value


def _copy_struct(obj):
    """Fast copy of nested dicts/lists (to_redvypr_dict results)."""
    if isinstance(obj, dict):
        return {k: _copy_struct(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_copy_struct(v) for v in obj]
    return obj


class RedvyprAddress:
    """
    Representation and parser for Redvypr addressing, routing, and filtering.

    This class serves as the core mechanism to identify, address, and filter
    Redvypr data packets and their nested content. It parses addressing string
    expressions containing both logical data keys (Left-Hand Side / LHS) and
    metadata constraints (Right-Hand Side / RHS), such as host, device, and
    publisher attributes.

    Parameters
    ----------
    expr : str, RedvyprAddress, dict, or None, optional
        The input expression to initialize or copy the address.

        - If `str`: Parsed into its LHS datakey expression and RHS filter, separated
          by an `@` boundary.
        - If `RedvyprAddress`: Copy of the address.
        - If `dict`: The `_redvypr` header of a packet (device, packetid, host, ...)
          becomes equality filters.
        - If `None` or `""`: An empty address.
    datakey : str, optional
        Sets the Left-Hand Side (LHS) datakey, overriding any datakey of `expr`.
    hostinfo : dict, optional
        Sets the filterkeys of the host (host, uuid, addr) with a hostinfo dictionary,
        as created with `redvypr.create_hostinfo()`
    **kwargs
        Longform metadata keys of `META_CONFIG` (e.g. ``device="my_device"``,
        ``publisher="pub_1"``, ``uuid="..."``): equality filters, replacing existing
        filters of that key. Other keywords are ignored.

    Notes
    -----
    Filter syntax of the right side:

    - metadata: ``d:cam``, ``i:'test'``, ``i:42``, lists ``i:[a,b,3]``, existence ``d?:``,
      regular expressions ``i:~/^ch\\d+$/i``
    - packet content: ``data > 2``, ``payload['x'] <= 1.5``, ``td == dt(2000-01-01)``,
      existence ``lon?:``
    - combined with ``and``, ``or``, ``not`` and parentheses

    Examples
    --------
    >>> addr = RedvyprAddress("temp_degC @ d:sensor_hub and h:local_node")
    >>> addr.left_expr
    'temp_degC'
    >>> addr = RedvyprAddress(datakey="pressure", device="pump_01", host="cluster_a")
    >>> addr.to_address_string()
    "pressure @ d:'pump_01' and h:'cluster_a'"
    """
    # Maps short prefixes to internal dunder representation and API-facing longforms.
    META_CONFIG = {
        "d": {"path": "device", "longform": "device", "internal": "__device__"},
        "di": {"path": "deviceid", "longform": "deviceid", "internal": "__deviceid__"},
        "p": {"path": "publisher", "longform": "publisher", "internal": "__publisher__"},
        "i": {"path": "packetid", "longform": "packetid", "internal": "__packetid__"},
        "s": {"path": "sensor", "longform": "sensor", "internal": "__sensor__"},
        "si": {"path": "sensorid", "longform": "sensorid", "internal": "__sensorid__"},
        "u": {"path": "host.uuid", "longform": "uuid", "internal": "__host_uuid__"},
        "a": {"path": "host.addr", "longform": "addr", "internal": "__host_addr__"},
        "h": {"path": "host.host", "longform": "host", "internal": "__host_host__"},
        "ul": {"path": "localhost.uuid", "longform": "uuid_local", "internal": "__localhost_uuid__"},
        "al": {"path": "localhost.addr", "longform": "addr_local", "internal": "__localhost_addr__"},
        "hl": {"path": "localhost.host", "longform": "host_local", "internal": "__localhost_host__"},
    }

    # Short prefixes -> internal dunder names, e.g. {"i": "__packetid__", ...}
    PREFIX_MAP = {k: v["internal"] for k, v in META_CONFIG.items()}
    # Longforms -> internal names, e.g. {"packetid": "__packetid__", ...}
    LONGFORM_MAP = {v["longform"]: v["internal"] for v in META_CONFIG.values()}
    # Internal names -> short prefixes
    INTERNAL_TO_PREFIX = {v["internal"]: k for k, v in META_CONFIG.items()}
    # Internal names -> path in the _redvypr header, e.g. "__host_uuid__": ("host", "uuid")
    INTERNAL_TO_PATH = {v["internal"]: tuple(v["path"].split(".")) for v in META_CONFIG.values()}
    # Order of the header fields (from a packet)
    _META_ORDER = tuple((v["internal"], tuple(v["path"].split("."))) for v in META_CONFIG.values())

    common_address_formats = ['k,i', 'k,i,si', 'k,d,i', 'k', 'd', 'i', 'p', 'p,d', 'p,d,i', 'u,a,h,d',
                              'u,a,h,d,i', 'k,u,a,h,d', 'k,u,a,h,d,i', 'a,h,d', 'a,h,d,i', 'a,h,p']

    def __init__(self,
                 expr: Union[str, "RedvyprAddress", dict, None] = None,
                 *,
                 datakey: Optional[str] = None,
                 hostinfo: Optional[dict] = None,
                 **kwargs):
        self.left_expr: Optional[str] = None
        self._rhs = None                  # filter tree (tuples), None = no filter
        self.strict_no_datakey = False
        self._bracket_style = None        # {"quote", "key"} of "['f'][1]" datakeys
        self._use_bracket_style = False

        if expr == "":
            expr = None

        if isinstance(expr, RedvyprAddress):
            self.left_expr = expr.left_expr
            self._rhs = expr._rhs
            self._bracket_style = expr._bracket_style
            self._use_bracket_style = expr._use_bracket_style
            if datakey is not None:
                self._use_bracket_style = False
        elif isinstance(expr, dict):
            self._rhs = self._rhs_from_header(expr.get("_redvypr") or {})
        elif isinstance(expr, str):
            cached = _PARSE_CACHE.get(expr)
            if cached is None:
                cached = self._parse_string(expr)
                _parse_cache_put(expr, cached)
            self.left_expr, self._rhs, self._bracket_style = cached
            self._use_bracket_style = self._bracket_style is not None
        elif expr is not None:
            raise TypeError(f"RedvyprAddress from {type(expr).__name__} not supported")

        if datakey is not None:
            self.left_expr = datakey
            self._bracket_style = None
            self._use_bracket_style = False
            self._apply_bracket_style()

        for cfg in self.META_CONFIG.values():
            longform = cfg["longform"]
            # as before: a value of hostinfo wins over the keyword argument
            for val in (kwargs.get(longform), hostinfo.get(longform) if hostinfo is not None else None):
                if val not in (None, ''):
                    self._replace_eq(cfg["internal"], val)

        self._compile_left()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def _rhs_from_header(cls, rv):
        leaves = []
        for internal, path in cls._META_ORDER:
            val = rv
            for part in path:
                if not isinstance(val, dict):
                    val = None
                    break
                val = val.get(part)
                if val is None:
                    break
            if val not in (None, ''):
                leaves.append(("eqm", internal, path, val))
        if not leaves:
            return None
        return leaves[0] if len(leaves) == 1 else ("and", tuple(leaves))

    def _parse_string(self, expr):
        left, right = self._split_left_right_tokens(expr)
        rhs = None
        if right:
            py_ast = self._parse_rhs(right)
            rhs = self._to_node(py_ast.body) if py_ast is not None else None
        self.left_expr = left
        self._bracket_style = None
        self._apply_bracket_style()
        return self.left_expr, rhs, self._bracket_style

    def _apply_bracket_style(self):
        """"['f'][1]" is stored as "f[1]" and printed in the original style."""
        if self.left_expr is not None and self.left_expr.startswith("[") and self.left_expr.count("]") >= 1:
            match = re.match(r"^\[(['\"])([a-zA-Z0-9_]+)\1\](.*)", self.left_expr)
            if match:
                self.left_expr = f"{match.group(2)}{match.group(3)}"
                self._bracket_style = {"quote": match.group(1), "key": match.group(2)}
                self._use_bracket_style = True

    def _compile_left(self):
        """Left side: a key/index path (fast) or a compiled Python expression."""
        self._left_path = None
        self._left_code = None
        self._left_const = None
        self._lhs_ast = None
        self._cache = {}
        if not self.left_expr or self.left_expr == "!":
            return
        try:
            tree = ast.parse(self.left_expr, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid datakey expression {self.left_expr!r}: {e.msg}") from None
        self._lhs_ast = tree
        node = tree.body
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            self._left_const = node.value
            return
        path = self._path_of(node)
        if path is not None:
            self._left_path = tuple(path)
        else:
            self._left_code = compile(tree, "<redvypr_address>", "eval")

    @staticmethod
    def _path_of(node):
        """[key, index, ...] of a Name/Subscript chain with constant keys, None otherwise."""
        keys = []
        while isinstance(node, ast.Subscript):
            slc = node.slice
            if isinstance(slc, ast.Constant) and not isinstance(slc.value, (bool, type(None))):
                keys.append(slc.value)
            elif (isinstance(slc, ast.UnaryOp) and isinstance(slc.op, ast.USub)
                  and isinstance(slc.operand, ast.Constant) and isinstance(slc.operand.value, int)):
                keys.append(-slc.operand.value)
            else:
                return None
            node = node.value
        if isinstance(node, ast.Name):
            keys.append(node.id)
            return keys[::-1]
        return None

    # ------------------------------------------------------------------
    # RHS: python AST -> filter tree
    # ------------------------------------------------------------------
    def _operand(self, node):
        """Operand of a comparison: ("m", internal, path) | ("p", keys, src) | ("l", value, src)."""
        if isinstance(node, ast.Name):
            if node.id in self.INTERNAL_TO_PATH:
                return ("m", node.id, self.INTERNAL_TO_PATH[node.id])
            if node.id in ("True", "False", "None"):
                return ("l", {"True": True, "False": False, "None": None}[node.id], node.id)
            return ("p", (node.id,), node.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_dt" \
                and len(node.args) == 1 and isinstance(node.args[0], ast.Constant):
            iso = node.args[0].value
            return ("l", datetime.fromisoformat(str(iso).replace("Z", "+00:00")), f"dt({iso!r})")
        path = self._path_of(node)
        if path is not None:
            return ("p", tuple(path), ast.unparse(node))
        try:
            val = ast.literal_eval(node)
        except (ValueError, SyntaxError, TypeError):
            return None
        return ("l", val, ast.unparse(node))

    def _to_node(self, node):
        if isinstance(node, ast.BoolOp):
            kind = "and" if isinstance(node.op, ast.And) else "or"
            children = []
            for v in node.values:
                c = self._to_node(v)
                if c[0] == kind:
                    children.extend(c[1])
                else:
                    children.append(c)
            return (kind, tuple(children))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return ("not", self._to_node(node.operand))
        if isinstance(node, ast.Compare):
            operands = [self._operand(x) for x in [node.left] + list(node.comparators)]
            if all(o is not None for o in operands) and all(type(op) in _CMP_OPS for op in node.ops):
                ops = tuple(_CMP_OPS[type(op)][0] for op in node.ops)
                left, right = operands[0], operands[-1]
                if len(operands) == 2 and left[0] == "m" and right[0] == "l":
                    if ops[0] == "==":
                        try:
                            hash(right[1])
                            return ("eqm", left[1], left[2], right[1])
                        except TypeError:
                            pass
                    elif ops[0] == "in" and isinstance(right[1], (list, tuple)):
                        return ("inm", left[1], left[2], tuple(right[1]))
                return ("cmp", tuple(operands), ops)
            return self._py_node(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fname = node.func.id
            if fname == "_exists" and len(node.args) == 1:
                arg = node.args[0]
                key = arg.value if isinstance(arg, ast.Constant) else getattr(arg, "id", None)
                if isinstance(key, str):
                    if key in self.INTERNAL_TO_PATH:
                        return ("ex", ("m", key, self.INTERNAL_TO_PATH[key]))
                    return ("ex", ("p", (key,), key))
            if fname == "_regex" and len(node.args) >= 2:
                target = self._operand(node.args[0])
                try:
                    pat = ast.literal_eval(node.args[1])
                    flags = ast.literal_eval(node.args[2]) if len(node.args) > 2 else ""
                except (ValueError, SyntaxError):
                    target = None
                if target is not None and target[0] in ("m", "p"):
                    return ("re", target, self._compile_regex(pat, flags), pat, flags)
        if isinstance(node, ast.Constant) and node.value is True:
            return ("true",)
        operand = self._operand(node)
        if operand is not None and operand[0] in ("m", "p"):
            return ("truthy", operand)
        return self._py_node(node)

    @staticmethod
    def _compile_regex(pat, flags):
        f = 0
        if "i" in flags:
            f |= re.IGNORECASE
        if "m" in flags:
            f |= re.MULTILINE
        if "s" in flags:
            f |= re.DOTALL
        return re.compile(pat, f)

    def _py_node(self, node):
        """Fallback: any other expression, evaluated with eval() like before."""
        expr = ast.Expression(body=node)
        ast.fix_missing_locations(expr)
        names = tuple({n.id for n in ast.walk(expr) if isinstance(n, ast.Name)})
        return ("py", compile(expr, "<redvypr_address>", "eval"), ast.unparse(node), names)

    # ------------------------------------------------------------------
    # Parsing of the address string (DSL -> python expression)
    # ------------------------------------------------------------------
    def _split_left_right_tokens(self, expr: str):
        """
        Split a Redvypr address string into (left, right) at the first @ outside quotes.
        Uses slicing on the original string to preserve formatting.
        """
        if "@" not in expr:
            return expr.strip() or None, None
        if "'" not in expr and '"' not in expr:
            split_at = expr.index("@")
            return expr[:split_at].strip() or None, expr[split_at + 1:].strip() or None
        readline = io.StringIO(expr).readline
        try:
            for tok_type, tok_str, start, end, _ in tokenize.generate_tokens(readline):
                if tok_type == tokenize.OP and tok_str == "@":
                    split_at = start[1]
                    return expr[:split_at].strip() or None, expr[split_at + 1:].strip() or None
        except (tokenize.TokenError, IndentationError):
            pass
        return expr.strip() or None, None

    def _parse_rhs(self, rhs: str):
        s = rhs.strip()
        if not s:
            return None

        # Pattern to catch quoted strings to avoid replacing keywords inside them
        STRING_PATTERN = r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')'

        def safe_sub(pattern, repl_func, text):
            combined = f"{STRING_PATTERN}|{pattern}"
            return re.sub(combined, lambda m: m.group(1) if m.group(1) else repl_func(m), text)

        # 1. dt("ISO") literal conversion
        def repl_dt(m):
            iso = m.group(2) or m.group(3)
            return f"_dt({repr(iso)})"

        rhs = safe_sub(r"dt\(\s*(?:['\"](.*?)['\"]|([0-9T:\-\.\+Z ]+))\s*\)", repl_dt, rhs)

        # 2. Existence check (key?:)
        def replace_exists(match):
            key = match.group(2)
            return f"_exists({repr(self.PREFIX_MAP.get(key, key))})"

        rhs = safe_sub(r'([A-Za-z0-9_]+)\?:', replace_exists, rhs)

        # 3. Prefixes (metadata keys -> __dunder__ names)
        prefixes = sorted(self.PREFIX_MAP.keys(), key=lambda x: -len(x))
        prefix_group = "|".join([re.escape(p) for p in prefixes])

        def repl_pref_list(m):
            key, content = m.group(2), m.group(3)
            return f"{self.PREFIX_MAP.get(key, key)} in {self._list_to_python(content)}"

        rhs = safe_sub(rf'\b({prefix_group}):\[((?:[^\]]*))\]', repl_pref_list, rhs)

        def repl_pref_regex(m):
            key, pat, flags = m.group(2), m.group(3), m.group(4) or ""
            return f"_regex({self.PREFIX_MAP.get(key, key)}, {repr(pat)}, {repr(flags)})"

        rhs = safe_sub(rf'\b({prefix_group}):~/(.*?)/([a-zA-Z]*)', repl_pref_regex, rhs)

        def repl_pref_eq(m):
            key, val = m.group(2), m.group(3)
            py_val = self._literal_to_python(val)
            if py_val == '' or py_val is None:
                return 'True'
            return f"{self.PREFIX_MAP.get(key, key)} == {py_val}"

        rhs = safe_sub(rf'\b({prefix_group}):((".*?"|\'.*?\'|[^\s()]+))', repl_pref_eq, rhs)
        try:
            return ast.parse(rhs, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid address filter {s!r}: {e.msg}") from None

    def _literal_to_python(self, token: str) -> str:
        """
        Converts a token of the address syntax into a Python literal string: numbers stay
        numbers, quoted strings stay as they are, bare words become quoted strings.
        """
        t = token.strip()
        if not t:
            return None
        if (t.startswith("'") and t.endswith("'")) or (t.startswith('"') and t.endswith('"')):
            return t
        if re.fullmatch(r'-?\d+(\.\d*)?', t):
            return t
        return repr(t)

    def _list_to_python(self, content: str) -> str:
        parts = [p.strip() for p in content.split(",")] if content.strip() else []
        return "[" + ",".join([self._literal_to_python(p) for p in parts]) + "]"

    # ------------------------------------------------------------------
    # Evaluation of the filter
    # ------------------------------------------------------------------
    @staticmethod
    def _meta_get(rv, path):
        val = rv
        for part in path:
            if not isinstance(val, dict) or part not in val:
                return _MISSING
            val = val[part]
        return val

    @staticmethod
    def _path_get(root, keys):
        val = root
        for k in keys:
            try:
                val = val[k]
            except (KeyError, IndexError, TypeError):
                return _MISSING
        return val

    def _value(self, operand, pkt, rv):
        kind = operand[0]
        if kind == "m":
            return self._meta_get(rv, operand[2])
        if kind == "p":
            return self._path_get(pkt, operand[1])
        return operand[1]

    def _eval(self, node, pkt, rv, soft):
        kind = node[0]
        if kind == "eqm":
            val = self._meta_get(rv, node[2])
            return soft if val is _MISSING else val == node[3]
        if kind == "and":
            for c in node[1]:
                if not self._eval(c, pkt, rv, soft):
                    return False
            return True
        if kind == "or":
            for c in node[1]:
                if self._eval(c, pkt, rv, soft):
                    return True
            return False
        if kind == "not":
            return not self._eval(node[1], pkt, rv, soft)
        if kind == "inm":
            val = self._meta_get(rv, node[2])
            return soft if val is _MISSING else val in node[3]
        if kind == "cmp":
            operands, ops = node[1], node[2]
            left = self._value(operands[0], pkt, rv)
            for op, operand in zip(ops, operands[1:]):
                right = self._value(operand, pkt, rv)
                if left is _MISSING or right is _MISSING:
                    return soft
                try:
                    if not _OP_FUNC[op](left, right):
                        return False
                except Exception:
                    return soft
                left = right
            return True
        if kind == "ex":
            operand = node[1]
            if operand[0] == "m":
                found = self._meta_get(rv, operand[2]) is not _MISSING
            else:
                key = operand[1][0]
                found = key in pkt and key != "_redvypr"
            return found or (soft and len(node) > 2)
        if kind == "re":
            val = self._value(node[1], pkt, rv)
            if val is _MISSING:
                return False
            return node[2].search(str(val)) is not None
        if kind == "truthy":
            val = self._value(node[1], pkt, rv)
            return soft if val is _MISSING else bool(val)
        if kind == "true":
            return True
        if kind == "py":
            return self._eval_py(node, pkt, rv, soft)
        raise ValueError(f"unknown filter node {kind!r}")

    def _eval_py(self, node, pkt, rv, soft):
        """Fallback filter expression: eval() with the packet content and the metadata fields."""
        placeholder = SoftPlaceholder(soft)
        locals_map = {name: placeholder for name in node[3]}
        locals_map.update({k: v for k, v in pkt.items() if k != "_redvypr"})
        for internal, path in self._META_ORDER:
            val = self._meta_get(rv, path)
            if val is not _MISSING:
                locals_map[internal] = val
        locals_map.update({"_dt": lambda iso: datetime.fromisoformat(str(iso).replace("Z", "+00:00")),
                           "True": True, "False": False, "None": None, "packet": pkt})
        try:
            return bool(eval(node[1], {"__builtins__": {}}, locals_map))
        except Exception:
            return soft

    def matches_packetfilter(self, packet, soft_missing=True):
        """True if the filter (right side) matches the packet (or the dict of an address)."""
        rhs = self._rhs
        if rhs is None:
            return True
        if isinstance(packet, RedvyprAddress):
            packet = packet._redvypr_dict(True)
        elif not isinstance(packet, dict):
            packet = packet.to_redvypr_dict() if hasattr(packet, "to_redvypr_dict") else packet
        rv = packet.get("_redvypr") or {}
        if rhs[0] == "eqm":
            val = self._meta_get(rv, rhs[2])
            return soft_missing if val is _MISSING else val == rhs[3]
        return bool(self._eval(rhs, packet, rv, soft_missing))

    # ------------------------------------------------------------------
    # Matching & LHS
    # ------------------------------------------------------------------
    def matches(self, packet: Union[dict, "RedvyprAddress"], soft_missing: bool = True):
        """
        Determines if this Address (the Subject/Filter) matches the provided
        packet or Address (the Target).

        1. Filter consistency: the filter (right side) must match, otherwise False.
        2. A filter with no datakey acts as a wildcard for its packets:
           ``RedvyprAddress("@d:test_device").matches(RedvyprAddress("sine[0]"))`` is True.
        3. Parent-child: ``"sine@d:test_device"`` matches the target ``"sine[0]"``.
        4. Specificity: ``"sine@d:test_device"`` does not match ``"sine[0]@d:test_device"``
           as a filter of ``"sine"`` (the target only provides ``sine[0]``).

        Parameters
        ----------
        packet : dict or RedvyprAddress
            The data packet or address to test against.
        soft_missing : bool
            If True, a filter field missing in the target counts as a match.
        """
        if not self.matches_packetfilter(packet, soft_missing=soft_missing):
            return False

        if self.left_expr == "!":
            try:
                self.__call__(packet, strict=True)
                return True
            except (KeyError, FilterNoMatch):
                return False

        try:
            self.__call__(packet)
            return True
        except Exception:
            # A packet without the data of the datakey does not match
            if isinstance(packet, dict):
                return False

        # Wildcard: the target has no datakey (filter matched above)
        return getattr(packet, "left_expr", None) is None

    def __call__(self, packet, strict=True, soft_missing=True):
        """
        Evaluates the address on a packet: checks the filter (right side) and returns
        the data of the datakey (left side).

        Parameters
        ----------
        packet : dict or RedvyprAddress or str
            The packet. An address (or address string) is converted with `to_redvypr_dict()`.
        strict : bool, optional
            If True, raise an exception if the filter does not match (FilterNoMatch) or the
            datakey is missing (KeyError); otherwise return None.
        soft_missing : bool, optional
            If True, filter fields missing in the packet count as a match.

        Returns
        -------
        - no datakey and no filter: the packet
        - filter only: the packet (if the filter matches)
        - ``"!"``: the packet if it has no data keys (True for an address)
        - otherwise the data of the datakey; a string result that is a key of the packet
          returns the value of that key

        Examples
        --------
        >>> addr = RedvyprAddress("temperature@d:device1")
        >>> packet = {"temperature": 25.5, "_redvypr": {"device": "device1"}}
        >>> addr(packet)
        25.5
        """
        redvypr_address = None
        if isinstance(packet, RedvyprAddress):
            redvypr_address = packet
            packet = packet.to_redvypr_dict()
        elif isinstance(packet, str):
            redvypr_address = packet
            packet = RedvyprAddress(packet).to_redvypr_dict()
        if self.left_expr is None and self._rhs is None:
            return packet
        if self._rhs is not None and not self.matches_packetfilter(packet, soft_missing=soft_missing):
            if strict:
                raise FilterNoMatch("Packet did not match filter")
            return None
        if not self.left_expr:
            return packet
        if self.left_expr == "!":
            if any(k != "_redvypr" for k in packet.keys()):
                if strict:
                    raise KeyError("Found datakeys '!' (no-data) was requested")
                return None
            return True if redvypr_address else packet

        if self._left_path is not None:
            val = packet
            try:
                for k in self._left_path:
                    val = val[k]
            except (KeyError, TypeError) as e:
                if strict:
                    raise KeyError(f"Key or Expression {self.left_expr!r} failed: {e!r}") from None
                return None
            except IndexError:
                if strict:
                    raise
                return None
        elif self._left_const is not None:
            val = self._left_const
        else:
            try:
                val = eval(self._left_code, {"__builtins__": {}, "True": True, "False": False, "None": None},
                           dict(packet))
            except (NameError, KeyError, TypeError) as e:
                if strict:
                    raise KeyError(f"Key or Expression {self.left_expr!r} failed: {e}") from None
                return None
            except Exception:
                if strict:
                    raise
                return None
        if isinstance(val, str):
            try:
                if val in packet:
                    return packet[val]
            except TypeError:
                pass
        return val

    # ------------------------------------------------------------------
    # Filter manipulation
    # ------------------------------------------------------------------
    def _internal(self, key):
        return self.PREFIX_MAP.get(key, self.LONGFORM_MAP.get(key, key))

    def _append(self, leaf):
        if self._rhs is None:
            self._rhs = leaf
        elif self._rhs[0] == "and":
            self._rhs = ("and", self._rhs[1] + (leaf,))
        else:
            self._rhs = ("and", (self._rhs, leaf))
        self._cache = {}

    def _replace_eq(self, internal, value):
        self._remove(internal)
        self._append(("eqm", internal, self.INTERNAL_TO_PATH[internal], value))

    def add_filter(self, key, op, value=None, flags=""):
        """Adds a filter (and): op in 'eq', 'in', 'regex', 'exists'."""
        internal = self._internal(key)
        meta = internal in self.INTERNAL_TO_PATH
        operand = ("m", internal, self.INTERNAL_TO_PATH[internal]) if meta else ("p", (internal,), internal)
        if op == "eq":
            if meta:
                leaf = ("eqm", internal, operand[2], value)
            else:
                leaf = ("cmp", (operand, ("l", value, repr(value))), ("==",))
        elif op == "in":
            vals = tuple(value) if isinstance(value, (list, tuple)) else (value,)
            leaf = ("inm", internal, operand[2], vals) if meta else \
                ("cmp", (operand, ("l", list(vals), repr(list(vals)))), ("in",))
        elif op == "regex":
            leaf = ("re", operand, self._compile_regex(value, flags), value, flags)
        elif op == "exists":
            # As before: add_filter(..., "exists") counts a missing field as a match with
            # soft_missing (unlike "key?:" in an address string)
            leaf = ("ex", operand, "soft")
        else:
            raise ValueError(f"Unsupported operation '{op}'")
        self._append(leaf)

    @staticmethod
    def _target(node):
        """Internal name / root key a leaf filters on (None: not a single key)."""
        kind = node[0]
        if kind in ("eqm", "inm"):
            return node[1]
        if kind in ("ex", "re", "truthy"):
            operand = node[1]
            return operand[1] if operand[0] == "m" else (operand[1][0] if len(operand[1]) == 1 else None)
        if kind == "cmp":
            first = node[1][0]
            if first[0] == "m":
                return first[1]
            if first[0] == "p" and len(first[1]) == 1:
                return first[1][0]
        return None

    def _remove(self, internal):
        def walk(node):
            if node[0] in ("and", "or"):
                children = tuple(c for c in (walk(v) for v in node[1]) if c is not None)
                if not children:
                    return None
                return children[0] if len(children) == 1 else (node[0], children)
            return None if self._target(node) == internal else node

        if self._rhs is not None:
            self._rhs = walk(self._rhs)
        self._cache = {}

    def delete_filter(self, key):
        """Removes all filters of key (prefix, longform or root key)."""
        self._remove(self._internal(key))

    @property
    def filter_keys(self) -> dict:
        """{internal name or root key: [ops]} of the filter."""
        result = {}
        ops = {"eqm": "eq", "inm": "in", "ex": "exists", "re": "regex", "cmp": "cmp", "truthy": "truthy"}

        def walk(node):
            if node[0] in ("and", "or"):
                for c in node[1]:
                    walk(c)
            elif node[0] == "not":
                walk(node[1])
            else:
                target = self._target(node)
                if target is not None:
                    result.setdefault(target, []).append(ops.get(node[0], node[0]))

        if self._rhs is not None:
            walk(self._rhs)
        return result

    # ------------------------------------------------------------------
    # LHS manipulation
    # ------------------------------------------------------------------
    def add_datakey(self, datakey: str, overwrite: bool = True):
        if "@" in datakey:
            raise ValueError("datakey must not contain '@'.")
        if self.left_expr is None or overwrite:
            self.left_expr = datakey
            self._bracket_style = None
            self._use_bracket_style = False
            self._apply_bracket_style()
        self._compile_left()

    def delete_datakey(self):
        self.left_expr = None
        self._bracket_style = None
        self._use_bracket_style = False
        self._compile_left()

    # ------------------------------------------------------------------
    # Dict conversion
    # ------------------------------------------------------------------
    def to_redvypr_dict(self, include_datakey: bool = True) -> dict:
        """
        Creates a redvypr dictionary: the path of the datakey (values True) and the filter
        values in the '_redvypr' header (metadata) or the root (packet content).

        >>> RedvyprAddress("payload['y'] @ i:42").to_redvypr_dict()
        {'payload': {'y': True}, '_redvypr': {'packetid': 42}}
        >>> RedvyprAddress("payload['y'] @ i:42").to_redvypr_dict(include_datakey=False)
        {'_redvypr': {'packetid': 42}}
        """
        return _copy_struct(self._redvypr_dict(include_datakey))

    def _redvypr_dict(self, include_datakey):
        """Cached (not copied) dict of to_redvypr_dict()."""
        key = ("dict", include_datakey)
        try:
            return self._cache[key]
        except KeyError:
            pass
        root = self._lhs_dict() if include_datakey else {}
        meta, root_rhs = {}, {}

        def add(path, value, target):
            cur = target
            for p in path[:-1]:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            cur[path[-1]] = value

        def add_operand(operand, value):
            if operand[0] == "m":
                add(list(operand[2]), value, meta)
            elif operand[0] == "p":
                keys = list(operand[1])
                if keys[0] == "_redvypr" and len(keys) > 1:
                    add(keys[1:], value, meta)
                else:
                    add(keys, value, root_rhs)

        def walk(node):
            kind = node[0]
            if kind in ("and", "or"):
                for c in node[1]:
                    walk(c)
            elif kind == "not":
                walk(node[1])
            elif kind == "eqm":
                add(list(node[2]), node[3], meta)
            elif kind == "inm":
                add(list(node[2]), list(node[3]), meta)
            elif kind == "cmp" and node[1][0][0] in ("m", "p") and node[1][1][0] == "l"                     and not node[1][1][2].startswith("dt("):          # as before: no dt() values
                value = node[1][1][1]
                add_operand(node[1][0], list(value) if isinstance(value, tuple) else value)
            elif kind == "ex":
                add_operand(node[1], True)
            elif kind == "re":
                add_operand(node[1], node[3])

        if self._lhs_ast is not None and not isinstance(self._lhs_ast.body, (ast.Name, ast.Subscript)):
            # A comparison as datakey (e.g. "payload['x'] > 1.5") adds its value like a filter
            for n in ast.walk(self._lhs_ast):
                if isinstance(n, ast.Compare):
                    try:
                        walk(self._to_node(n))
                    except Exception:
                        pass
        if self._rhs is not None:
            walk(self._rhs)
        result = {"_redvypr": meta, **root_rhs}
        for k, v in result.items():
            if k == "_redvypr":
                if not isinstance(root.get("_redvypr"), dict):
                    root["_redvypr"] = {}
                root["_redvypr"].update(v)
            elif isinstance(v, dict) and k in root:
                if not isinstance(root[k], dict):
                    root[k] = {}
                root[k].update(v)
            else:
                root[k] = v
        self._cache[key] = root
        return root

    def _lhs_dict(self):
        """Nested dict of the datakey path: data['temp'][0] -> {'data': {'temp': {0: True}}}."""
        if self._lhs_ast is None:
            return {}
        path = self._lhs_path_loose(self._lhs_ast.body)
        if not path:
            return {}
        root = cur = {}
        for p in path[:-1]:
            cur[p] = {}
            cur = cur[p]
        cur[path[-1]] = True
        return root

    @staticmethod
    def _lhs_path_loose(node):
        """Path of the datakey; a non constant index (slice) ends the path."""
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, ast.Attribute):
            base = RedvyprAddress._lhs_path_loose(node.value)
            return base + [node.attr] if base else [node.attr]
        if isinstance(node, ast.Subscript):
            base = RedvyprAddress._lhs_path_loose(node.value)
            try:
                idx = ast.literal_eval(node.slice)
                return base + [idx] if base else [idx]
            except Exception:
                return base
        return None

    def get_datakeyentries(self):
        """Keys of the datakey path: "data['temp'][0]" -> ['data', 'temp', 0]."""
        if not self.left_expr or self.left_expr == "!":
            return []
        node = self._lhs_ast.body
        path = []
        while isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Constant):
                path.append(node.slice.value)
            node = node.value
        if isinstance(node, ast.Name):
            path.append(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            path.append(node.value)
        else:
            path.append(ast.unparse(node))
        return path[::-1]

    # ------------------------------------------------------------------
    # Address string
    # ------------------------------------------------------------------
    def _operand_str(self, operand):
        if operand[0] == "m":
            return self.INTERNAL_TO_PREFIX[operand[1]]
        return operand[2]

    def _node_str(self, node, parent=None):
        kind = node[0]
        if kind in ("and", "or"):
            text = f" {kind} ".join(self._node_str(c, kind) for c in node[1])
            if (parent == "and" and kind == "or") or parent == "not":
                return f"({text})"
            return text
        if kind == "not":
            return f"not {self._node_str(node[1], 'not')}"
        if kind == "eqm":
            return f"{self.INTERNAL_TO_PREFIX[node[1]]}:{node[3]!r}"
        if kind == "inm":
            return f"{self.INTERNAL_TO_PREFIX[node[1]]}:{list(node[3])!r}"
        if kind == "cmp":
            pieces = [self._operand_str(node[1][0])]
            for op, operand in zip(node[2], node[1][1:]):
                pieces += [op, self._operand_str(operand)]
            return " ".join(pieces)
        if kind == "ex":
            operand = node[1]
            name = self.INTERNAL_TO_PREFIX[operand[1]] if operand[0] == "m" else operand[2]
            return f"{name}?:"
        if kind == "re":
            return f"{self._operand_str(node[1])}:~/{node[3]}/{node[4]}"
        if kind == "truthy":
            return self._operand_str(node[1])
        if kind == "true":
            return "True"
        if kind == "py":
            return node[2]
        return "?"

    def _prune(self, node, allowed):
        if node[0] in ("and", "or"):
            children = tuple(c for c in (self._prune(v, allowed) for v in node[1]) if c is not None)
            if not children:
                return None
            return children[0] if len(children) == 1 else (node[0], children)
        if node[0] == "not":
            inner = self._prune(node[1], allowed)
            return None if inner is None else ("not", inner)
        target = self._target(node)
        if target is not None and target not in allowed:
            return None
        return node

    def to_address_string(self, keys: Union[str, List[str]] = None) -> str:
        """
        The address string: datakey and filter, separated by ``@``.

        Parameters
        ----------
        keys : str or list of str, optional
            Prefixes (e.g. ``"d,i"``) or longforms of the metadata to keep; ``"k"`` keeps
            the datakey. Default: everything.

        >>> addr = RedvyprAddress("temperature @ d:sensor_01 and h:local_node")
        >>> addr.to_address_string()
        "temperature @ d:'sensor_01' and h:'local_node'"
        >>> addr.to_address_string("d")
        "@d:'sensor_01'"
        """
        cache_key = keys if isinstance(keys, (str, type(None))) else tuple(keys)
        try:
            return self._cache[("str", cache_key)]
        except (KeyError, TypeError):
            pass
        result = self._to_address_string(keys)
        try:
            self._cache[("str", cache_key)] = result
        except TypeError:
            pass
        return result

    def _to_address_string(self, keys):
        allowed = None
        show_left = True
        if keys is not None:
            allowed_keys = [k.strip() for k in keys.split(",") if k.strip()] if isinstance(keys, str) else keys
            if len(allowed_keys) == 0:
                return "@"
            allowed = {self._internal(k) for k in allowed_keys}
            if not any(k in allowed_keys for k in ("k", "datakey")):
                show_left = False

        rhs_str = ""
        if self._rhs is not None:
            rhs = self._rhs if allowed is None else self._prune(self._rhs, allowed)
            if rhs is not None:
                rhs_str = self._node_str(rhs)

        left = self.left_expr if (self.left_expr and show_left) else ""
        if self._use_bracket_style and left:
            key = self._bracket_style["key"]
            quote = self._bracket_style["quote"]
            if left.startswith(key):
                left = left.replace(key, f"[{quote}{key}{quote}]", 1)

        if not rhs_str:
            return f"{left}" if (left and not keys) else (f"{left} @ " if left else "@")
        return f"{left} @ {rhs_str}" if left else f"@{rhs_str}"

    def __repr__(self):
        return self.to_address_string()

    def get_common_address_formats(self):
        return self.common_address_formats

    # ------------------------------------------------------------------
    # Attributes: datakey and metadata values
    # ------------------------------------------------------------------
    def __getattr__(self, name):
        if name in ('datakey', 'k'):
            return self.__dict__.get("left_expr")
        if name.startswith("_"):
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        cls = type(self)
        internal = cls.PREFIX_MAP.get(name) or cls.LONGFORM_MAP.get(name)
        if internal is None:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        cache = self.__dict__.get("_cache")
        if cache is not None and ("attr", internal) in cache:
            return cache[("attr", internal)]
        values = []

        def walk(node):
            kind = node[0]
            if kind in ("and", "or"):
                for c in node[1]:
                    walk(c)
            elif kind == "eqm" and node[1] == internal:
                values.append(node[3])
            elif kind == "inm" and node[1] == internal:
                values.extend(node[3])
            elif kind == "cmp" and node[1][0][0] == "m" and node[1][0][1] == internal and node[1][1][0] == "l":
                if node[2][0] == "==":
                    values.append(node[1][1][1])
                elif node[2][0] == "in" and isinstance(node[1][1][1], (list, tuple)):
                    values.extend(node[1][1][1])

        rhs = self.__dict__.get("_rhs")
        if rhs is not None:
            walk(rhs)
        result = values[0] if len(values) == 1 else (values or None)
        if cache is not None:
            cache[("attr", internal)] = result
        return result

    def __deepcopy__(self, memo):
        return RedvyprAddress(self)

    def __copy__(self):
        return RedvyprAddress(self)

    def __getstate__(self):
        return {"address": self.to_address_string()}

    def __setstate__(self, state):
        self.__init__(state["address"])

    # ------------------------------------------------------------------
    # pydantic
    # ------------------------------------------------------------------
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: typing.Any,
        _handler: pydantic.GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        """
        strs are parsed as `RedvyprAddress` instances, instances are taken unchanged,
        serialization gives the address string.
        """

        def validate_from_str(value: str) -> "RedvyprAddress":
            return RedvyprAddress(value)

        from_str_schema = core_schema.chain_schema(
            [
                core_schema.str_schema(),
                core_schema.no_info_plain_validator_function(validate_from_str),
            ]
        )

        return core_schema.json_or_python_schema(
            json_schema=from_str_schema,
            python_schema=core_schema.union_schema(
                [
                    core_schema.is_instance_schema(RedvyprAddress),
                    from_str_schema,
                ]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda instance: instance.to_address_string()
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: core_schema.CoreSchema, handler: pydantic.GetJsonSchemaHandler
    ) -> pydantic.json_schema.JsonSchemaValue:
        return handler(core_schema.str_schema())
