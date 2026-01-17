"""
Redvypr addresses are the base to identify and address redvypr data packets and their content.
see also the documentation here: :ref:`design_addressing`.
"""

import re
import copy
import time
import logging
import sys
import yaml
import pydantic
import pydantic_core
import typing
from datetime import datetime
from typing import Any, List, Tuple, Optional, Union
from pydantic import BaseModel, Field, TypeAdapter
from pydantic_core import SchemaSerializer, core_schema
import ast

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.redvypr_address')
logger.setLevel(logging.DEBUG)

#metadata_address = '/d:/p:/i:metadata/k:_redvypr_command'
metadata_address = "_redvypr_command@i:metadata"


redvypr_standard_address_filter = ["i","p","d","h","u","a"]


# Exceptions
class FilterNoMatch(Exception):
    """Raised when a packet does not match the filter expression."""
    pass

class FilterFieldMissing(Exception):
    """Raised when a required key is missing in the packet."""
    pass



class RedvyprAddress:
    PREFIX_MAP = {
        "i": "packetid",
        "p": "publisher",
        "d": "device",
        "u": "host.uuid",
        "a": "host.addr",
        "h": "host.host",
        "ul": "localhost.uuid",
        "al": "localhost.addr",
        "hl": "localhost.host",
    }

    LONGFORM_MAP = {
        "packetid": "packetid",
        "publisher": "publisher",
        "device": "device",
        "uuid": "host.uuid",
        "host": "host.host",
        "addr": "host.addr",
        "uuid_local": "localhost.uuid",
        "host_local": "localhost.host",
        "addr_local": "localhost.addr",
    }

    LONGFORM_TO_SHORT_MAP = {
        "packetid": "i",
        "publisher": "p",
        "device": "d",
        "uuid": "u",
        "host": "h",
        "addr": "a",
        "uuid_local": "ul",
        "host_local": "hl",
        "addr_local": "al",
    }
    LONGFORM_TO_SHORT_MAP_DATAKEY = {
        "datakey": "k",
        "packetid": "i",
        "publisher": "p",
        "device": "d",
        "uuid": "u",
        "host": "h",
        "addr": "a",
        "uuid_local": "ul",
        "host_local": "hl",
        "addr_local": "al",
    }

    common_address_formats = ['k,i', 'k,d,i', 'k', 'd', 'i', 'p', 'p,d', 'p,d,i', 'u,a,h,d,',
                            'u,a,h,d,i', 'k,u,a,h,d', 'k,u,a,h,d,i', 'a,h,d', 'a,h,d,i', 'a,h,p']

    REV_PREFIX_MAP = {v: k for k, v in PREFIX_MAP.items()}
    REV_LONGFORM_MAP = {v: k for k, v in LONGFORM_MAP.items()}
    REV_LONGFORM_TO_SHORT_MAP = {v: k for k, v in LONGFORM_TO_SHORT_MAP.items()}
    REV_LONGFORM_TO_SHORT_MAP_DATAKEY = {v: k for k, v in LONGFORM_TO_SHORT_MAP_DATAKEY.items()}
    #LONGFORM_TO_SHORT_MAP = {}
    #for k, v in LONGFORM_MAP.items():
    #    LONGFORM_TO_SHORT_MAP[k] = REV_PREFIX_MAP[v]


    #LONGFORM_TO_SHORT_MAP_DATAKEY = dict(LONGFORM_TO_SHORT_MAP)  # Kopie
    #LONGFORM_TO_SHORT_MAP_DATAKEY["datakey"] = "k"


    def __init__(self,
                 expr: Union[str, "RedvyprAddress", dict, None] = None,
                 *,
                 datakey: Optional[str] = None,
                 packetid: Optional[Any] = None,
                 device: Optional[Any] = None,
                 publisher: Optional[Any] = None,
                 host: Optional[Any] = None,
                 uuid: Optional[Any] = None,
                 addr: Optional[Any] = None,
                 host_local: Optional[Any] = None,
                 uuid_local: Optional[Any] = None,
                 addr_local: Optional[Any] = None):
        self.left_expr: Optional[str] = None
        self._rhs_ast: Optional[ast.Expression] = None
        self.filter_keys: typing.Dict[str, list] = {}
        self.strict_no_datakey = False

        if expr == "":
            expr = None

        # Kopieren von einem RedvyprAddress
        if isinstance(expr, RedvyprAddress):
            self.left_expr = expr.left_expr
            self._rhs_ast = copy.deepcopy(expr._rhs_ast)
            self.filter_keys = {k: list(v) for k, v in expr.filter_keys.items()}

        # Dict input (_redvypr mapping)
        elif isinstance(expr, dict):
            redvypr = expr.get("_redvypr", {})
            mapping = {
                "packetid": "i",
                "publisher": "p",
                "device": "d",
                "host": {"host": "h", "addr": "a", "uuid": "u"},
                "localhost": {"host": "hl", "addr": "al", "uuid": "ul"},
            }

            for k, v in redvypr.items():
                if k not in mapping:
                    continue  # skip unknown keys

                map_val = mapping[k]

                # Nested dicts (host, localhost)
                if isinstance(map_val, dict) and isinstance(v, dict):
                    for subk, prefix in map_val.items():
                        val = v.get(subk)
                        if val not in (None, ''):  # skip empty values
                            self.add_filter(prefix, "eq", val)

                # Single values (packetid, device, publisher)
                elif v not in (None, ''):
                    self.add_filter(map_val, "eq", v)

        # String input
        elif isinstance(expr, str):
            if "@" in expr:
                left, right = map(str.strip, expr.split("@", 1))
                self.left_expr = left if left else None
                if right:
                    self._rhs_ast = self._parse_rhs(right)
            else:
                self.left_expr = expr.strip() or None

        # LHS via datakey
        if datakey is not None:
            self.left_expr = datakey

        # Keyword args
        kw_map = [
            ("packetid", packetid),
            ("device", device),
            ("publisher", publisher),
            ("host", host),
            ("uuid", uuid),
            ("address", addr),
            ("localhost.host", host_local),
            ("localhost.uuid", uuid_local),
            ("localhost.addr", addr_local),
        ]
        for red_key, val in kw_map:
            if val not in (None, ''):  # skip empty values
                self.delete_filter(red_key)
                self.add_filter(red_key, "eq", val)

    # -------------------------
    # RHS AST Parsing
    # -------------------------
    def _parse_rhs(self, rhs: str) -> ast.Expression:
        s = rhs.strip()
        if not s:
            return None

        # dt("ISO") literal

        def repl_dt(m):
            iso = m.group(1)
            return f"_dt({repr(iso)})"

        # allow dt(2026-01-14T16:15:15) and dt("2026-01-14T16:15:15")
        rhs = re.sub(
            r"dt\(\s*(?:['\"])?([0-9T:\-\.]+)(?:['\"])?\s*\)",
            repl_dt,
            rhs,
        )

        # Existenzprüfung
        def replace_exists(match):
            key = match.group(1)
            red = self.PREFIX_MAP.get(key, key)
            self.filter_keys.setdefault(red, []).append("exists")
            return f"_exists({repr(red)})"

        rhs = re.sub(r'([A-Za-z0-9_]+)\?:', replace_exists, rhs)

        # r: forms
        def repl_r_list(m):
            key, content = m.group(1), m.group(2)
            self.filter_keys.setdefault(key, []).append("in")
            return f"_in({repr(key)}, {self._list_to_python(content)})"

        rhs = re.sub(r'r:([A-Za-z0-9_]+):\[((?:[^\]]*))\]', repl_r_list, rhs)

        def repl_r_regex(m):
            key, pat, flags = m.group(1), m.group(2), m.group(3) or ""
            self.filter_keys.setdefault(key, []).append("regex")
            return f"_regex({repr(key)}, {repr(pat)}, {repr(flags)})"

        rhs = re.sub(r'r:([A-Za-z0-9_]+):~/(.*?)/([a-zA-Z]*)', repl_r_regex, rhs)

        def repl_r_eq(m):
            key, val = m.group(1), m.group(2)
            self.filter_keys.setdefault(key, []).append("eq")
            return f"_eq({repr(key)}, {self._lit_to_python(val)})"

        rhs = re.sub(r'r:([A-Za-z0-9_]+):(".*?"|\'.*?\'|[^\s()]+)', repl_r_eq, rhs)

        # Präfixe
        prefixes = sorted(self.PREFIX_MAP.keys(), key=lambda x: -len(x))
        prefix_group = "|".join([re.escape(p) for p in prefixes])

        def repl_pref_list(m):
            key, content = m.group(1), m.group(2)
            red = self.PREFIX_MAP.get(key, key)
            self.filter_keys.setdefault(red, []).append("in")
            return f"_in({repr(red)}, {self._list_to_python(content)})"

        rhs = re.sub(rf'({prefix_group}):\[((?:[^\]]*))\]', repl_pref_list, rhs)

        def repl_pref_regex(m):
            key, pat, flags = m.group(1), m.group(2), m.group(3) or ""
            red = self.PREFIX_MAP.get(key, key)
            self.filter_keys.setdefault(red, []).append("regex")
            return f"_regex({repr(red)}, {repr(pat)}, {repr(flags)})"

        rhs = re.sub(rf'({prefix_group}):~/(.*?)/([a-zA-Z]*)', repl_pref_regex, rhs)

        def repl_pref_eq(m):
            key, val = m.group(1), m.group(2)
            red = self.PREFIX_MAP.get(key, key)
            py_val = self._lit_to_python(val)
            if py_val == '' or py_val is None:
                return ''  # Node gar nicht einfügen
            self.filter_keys.setdefault(red, []).append("eq")
            return f"_eq({repr(red)}, {self._lit_to_python(val)})"

        rhs = re.sub(rf'({prefix_group}):((".*?"|\'.*?\'|[^\s()]+))', repl_pref_eq, rhs)

        return ast.parse(rhs, mode="eval")

    def _lit_to_python(self, token: str) -> str:
        t = token.strip()
        if t == '':
            return None          # skip empty strings
        if re.fullmatch(r'-?\d+(\.\d*)?', t):
            return t

        return repr(t)

    def _list_to_python(self, content: str) -> str:
        parts = [p.strip() for p in content.split(",")] if content.strip() else []
        return "[" + ",".join([self._lit_to_python(p) for p in parts]) + "]"

    # -------------------------
    # Eval helpers
    # -------------------------

    def _coerce_datetime(self, v):
        if hasattr(v, "year") and hasattr(v, "month") and hasattr(v, "day"):
            return v
        if isinstance(v, str):
            # cheap ISO-datetime heuristic
            # YYYY-MM-DD or YYYY-MM-DDTHH:MM
            if len(v) < 10 or v[4] != "-" or v[7] != "-":
                return v

            if "T" not in v and ":" not in v:
                return v
            try:
                return datetime.fromisoformat(v)
            except Exception:
                pass
        return v

    def _build_eval_locals(self, packet: dict):
        locals_map = {}

        # -------------------------
        # Datetime helper
        # -------------------------
        def _dt(iso):
            from datetime import datetime
            return datetime.fromisoformat(iso)

        def _cmp(op, k, v):
            lv = self._get_val(packet, k)
            rv = self._coerce_datetime(v)
            return op(lv, rv)

        # -------------------------
        # Comparison operators
        # -------------------------
        def _eq(k, v):
            return _cmp(lambda a, b: a == b, k, v)

        def _ne(k, v):
            return _cmp(lambda a, b: a != b, k, v)

        def _gt(k, v):
            return _cmp(lambda a, b: a > b, k, v)

        def _ge(k, v):
            return _cmp(lambda a, b: a >= b, k, v)

        def _lt(k, v):
            return _cmp(lambda a, b: a < b, k, v)

        def _le(k, v):
            return _cmp(lambda a, b: a <= b, k, v)

        # -------------------------
        # UNVERÄNDERT: in / regex / exists
        # -------------------------
        def _in(k, l):
            return self._get_val(packet, k) in l

        def _regex(k, pat, flags=""):
            v = self._get_val(packet, k)
            f = 0
            for ch in flags:
                if ch == "i": f |= re.IGNORECASE
                if ch == "m": f |= re.MULTILINE
                if ch == "s": f |= re.DOTALL
            return re.search(pat, str(v), f) is not None

        def _exists(k):
            return self._exists_val(packet, k)

        # -------------------------
        # Locals
        # -------------------------
        locals_map.update({
            "_dt": _dt,
            "_eq": _eq,
            "_ne": _ne,
            "_gt": _gt,
            "_ge": _ge,
            "_lt": _lt,
            "_le": _le,
            "_in": _in,
            "_regex": _regex,
            "_exists": _exists,
            "packet": packet,
        })

        if isinstance(packet, dict):
            locals_map["_redvypr"] = packet.get("_redvypr")
            for k, v in packet.items():
                if k not in locals_map:
                    locals_map[k] = v

        return locals_map

    def _traverse_path(self, root: dict, parts: list):
        cur = root
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return False, None
            cur = cur[p]
        return True, cur

    def _get_val(self, packet, key):
        if packet is None:
            raise FilterFieldMissing(f"_redvypr missing key '{key}'")
        parts = key.split(".") if "." in key else [key]
        if "_redvypr" in packet:
            found, val = self._traverse_path(packet["_redvypr"], parts)
            if found:
                return self._coerce_datetime(val)
        found, val = self._traverse_path(packet, parts)
        if found:
            return self._coerce_datetime(val)

        raise FilterFieldMissing(f"missing key '{key}'")

    def _exists_val(self, packet, key):
        if packet is None:
            return False
        parts = key.split(".") if "." in key else [key]
        if "_redvypr" in packet:
            found, _ = self._traverse_path(packet["_redvypr"], parts)
            if found:
                return True
        found, _ = self._traverse_path(packet, parts)
        return bool(found)

    # -------------------------
    # Matching & LHS
    # -------------------------
    def matches_filter(self, packet: Union[dict, "RedvyprAddress"],
                       soft_missing: bool = True):
        """
        Check whether a packet or RedvyprAddress matches with the filter part of this address.

        soft_missing:
            - True: missing keys for _eq/_in/_regex are treated as True (soft matching)
            - False: missing keys result in False (strict matching)
        """
        if isinstance(packet, RedvyprAddress):
            packet = packet.to_redvypr_dict()
        if not self._rhs_ast:
            return True

        SAFE_GLOBALS = {"__builtins__": None, "True": True, "False": False,
                        "None": None}

        # -------------------------
        # Datetime helper
        # -------------------------
        def _dt(iso):
            from datetime import datetime
            return datetime.fromisoformat(iso)

        def _cmp(op, k, v):
            try:
                lv = self._get_val(packet, k)
                rv = self._coerce_datetime(v)
                return op(lv, rv)
            except FilterFieldMissing:
                return soft_missing

        # -------------------------
        # Existing + extended operators
        # -------------------------
        def _eq(k, v):
            return _cmp(lambda a, b: a == b, k, v)

        def _ne(k, v):
            return _cmp(lambda a, b: a != b, k, v)

        def _gt(k, v):
            return _cmp(lambda a, b: a > b, k, v)

        def _ge(k, v):
            return _cmp(lambda a, b: a >= b, k, v)

        def _lt(k, v):
            return _cmp(lambda a, b: a < b, k, v)

        def _le(k, v):
            return _cmp(lambda a, b: a <= b, k, v)

        # -------------------------
        # UNVERÄNDERT: in / regex / exists
        # -------------------------
        def _in(k, l):
            try:
                val = self._get_val(packet, k)
                return val in l
            except FilterFieldMissing:
                return soft_missing

        def _regex(k, pat, flags=""):
            try:
                val = self._get_val(packet, k)
                f = 0
                for ch in flags:
                    if ch == "i": f |= re.IGNORECASE
                    if ch == "m": f |= re.MULTILINE
                    if ch == "s": f |= re.DOTALL
                return re.search(pat, str(val), f) is not None
            except FilterFieldMissing:
                return soft_missing

        def _exists(k):
            # remains strict
            return self._exists_val(packet, k)

        # -------------------------
        # Locals
        # -------------------------
        locals_map = {
            "_dt": _dt,
            "_eq": _eq,
            "_ne": _ne,
            "_gt": _gt,
            "_ge": _ge,
            "_lt": _lt,
            "_le": _le,
            "_in": _in,
            "_regex": _regex,
            "_exists": _exists,
            "packet": packet,
        }

        if isinstance(packet, dict):
            locals_map["_redvypr"] = packet.get("_redvypr")
            for k, v in packet.items():
                if k not in locals_map:
                    locals_map[k] = v

        try:
            return bool(eval(
                compile(self._rhs_ast, filename="<ast>", mode="eval"),
                SAFE_GLOBALS,
                locals_map,
            ))
        except FilterFieldMissing:
            return False


    def matches(self, packet: Union[dict, "RedvyprAddress"], soft_missing: bool = True):
        """
        Determines if this Address (the Subject/Filter) matches the provided
        packet or Address (the Target).

        The logic is based on Hierarchical Subsumption. It follows these rules:

        1. Filter Consistency:
           The Host, Device, and Publisher must match. If filter fails,
           the result is False immediately.

        2. Wildcard Logic (Broad Filter vs. Specific Data):
           A filter with no specific datakey acts as a wildcard for that device.
           Example:
           >>> a0 = RedvyprAddress("@d:test_device")
           >>> atest2 = RedvyprAddress("sine[0]")
           >>> a0.matches(atest2) # True (Device match is enough for a0)

        3. Parent-Child Compatibility:
           A filter for a parent key matches a target that is a specific child/index.
           Example:
           >>> a1 = RedvyprAddress("sine@d:test_device")
           >>> atest2 = RedvyprAddress("sine[0]")
           >>> a1.matches(atest2) # True (sine[0] is part of sine)

        4. Specificity Constraint (Specific Filter vs. Broad Data):
           A filter that is 'more specific' than the target will fail if the
           target cannot satisfy the structural requirement.
           Example:
           >>> atest0 = RedvyprAddress("sine@d:test_device")
           >>> a2 = RedvyprAddress("sine[0]@d:test_device")
           >>> atest0.matches(a2) # False (atest0 wants 'sine', but a2 only provides 'sine[0]')

        Test Matrix Summary:
        --------------------
        - atest0.matches(a0) -> True  (atest0: 'sine@dev' finds a0: '@dev' via filter)
        - atest0.matches(a1) -> True  (Exact match: 'sine' vs 'sine')
        - atest0.matches(a2) -> False (atest0: 'sine' is too broad for target a2: 'sine[0]')
        - a0.matches(atest2) -> True  (a0: '@dev' is a wildcard for any key on dev)
        - a1.matches(atest2) -> True  (a1: 'sine' subsumes target 'sine[0]')
        - a2.matches(atest2) -> True  (Exact index match)

        Parameters
        ----------
        packet : dict or RedvyprAddress
            The data packet or address to test against.
        soft_missing : bool
            If True, missing keys in evaluation return False instead of raising.

        Returns
        -------
        bool
            True if the Subject filter matches the Target.
        """

        if isinstance(packet, dict):
            address = RedvyprAddress(dict)
        else:
            address = packet

        # 1. RHS Filter check
        match_filter = self.matches_filter(packet)
        if match_filter == False:
            return False

        # 2. Handle the "Explicit No Data" case (!)
        if self.left_expr == "!":
            # We need to check if the target actually HAS data
            # If it has a key like 'data', this must return False
            try:
                self.__call__(packet, strict=True)
                return True
            except (KeyError, FilterNoMatch):
                return False

        # 3. Wildcard logic: If I don't care about the key, any key matches
        # (provided the filter above matched)
        if address.datakey is None:
            return True

        # 4. Specific key or Subsumption logic,
        # try if datakey(s) match, here also more complex datapackets are treated properly
        try:
            self.__call__(packet)
            return True
        except:
            return False

    def __call__(self, packet, strict=True):
        if isinstance(packet, RedvyprAddress):
            packet = packet.to_redvypr_dict()
        if self.left_expr is None and self._rhs_ast is None:
            return packet
        SAFE_GLOBALS = {"__builtins__": None, "True": True, "False": False, "None": None}
        locals_map = dict(packet)
        if self._rhs_ast and not self.matches_filter(packet):
            if strict:
                raise FilterNoMatch("Packet did not match filter")
            else:
                return None
        if self.left_expr:
            if self.left_expr == "!":
                # We check if the packet contains any data keys other than metadata.
                # In your system, 'no datakey' typically means that only
                # the metadata (_redvypr) is present.
                data_keys = [k for k in packet.keys() if k != "_redvypr"]
                if len(data_keys) > 0:
                    if strict:
                        raise KeyError(
                            "Found datakeys '!' (no-data) was requested")
                    return None
                return packet  # Empty
            top_key = self.left_expr.split("[")[0].split(".")[0]
            if top_key not in packet:
                if strict:
                    raise KeyError(f"Key {top_key!r} missing in packet")
                else:
                    return None
            return eval(self.left_expr, SAFE_GLOBALS, locals_map)
        return packet

    # -------------------------
    # Filter Manipulation (AST)
    # -------------------------
    def add_filter(self, key, op, value=None, flags=""):
        # Always normalize to SHORT key (u,d,i,p,...)
        if key in self.PREFIX_MAP:  # already short: u,d,i,...
            short = key
        elif key in self.LONGFORM_MAP:  # long → short
            short = self.LONGFORM_TO_SHORT_MAP[key]
        else:
            short = key  # fallback

        red_key = self.PREFIX_MAP.get(short, short)
        self.filter_keys.setdefault(red_key, []).append(op)
        if op == "eq":
            expr = f"_eq({repr(red_key)}, {repr(value)})"
        elif op == "in":
            expr = f"_in({repr(red_key)}, {repr(value if isinstance(value, list) else [value])})"
        elif op == "regex":
            expr = f"_regex({repr(red_key)}, {repr(value)}, {repr(flags)})"
        elif op == "exists":
            expr = f"_exists({repr(red_key)})"
        else:
            raise ValueError(f"Unsupported operation '{op}'")
        new_ast = ast.parse(expr, mode="eval")

        if self._rhs_ast is None:
            self._rhs_ast = new_ast
        else:
            # flach kombinieren ohne unnötige Klammern
            rhs_body = self._rhs_ast.body
            if isinstance(rhs_body, ast.BoolOp) and isinstance(rhs_body.op, ast.And):
                # rhs ist schon ein And → nur neue Call anhängen
                rhs_body.values.append(new_ast.body)
            else:
                # sonst normalen And-Baum erzeugen
                self._rhs_ast = ast.parse(f"({ast.unparse(rhs_body)}) and {expr}", mode="eval")

    def delete_filter(self, key):
        """
        Remove all RHS filter expressions that refer to the given key
        (long or short form).
        Works robustly with nested AND/OR ASTs.
        """

        if not self._rhs_ast:
            return

        # translate to canonical prefix version (e.g. uuid -> u)
        red_key = self.PREFIX_MAP.get(key, key)

        def _remove(node):
            # Remove matching _eq/_in/_regex/_exists on this key
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in (
                "_eq", "_in", "_regex", "_exists"):
                    # First argument is the key
                    try:
                        k = ast.literal_eval(node.args[0])
                        if k == red_key:
                            return None  # remove this leaf
                    except Exception:
                        pass
                return node

            # Recurse on boolean ops
            if isinstance(node, ast.BoolOp):
                new_vals = []
                for v in node.values:
                    nv = _remove(v)
                    if nv is not None:
                        new_vals.append(nv)

                # No children left → remove node
                if not new_vals:
                    return None
                # Only one child → collapse node to child
                if len(new_vals) == 1:
                    return new_vals[0]

                # Otherwise keep same BoolOp with filtered children
                node.values = new_vals
                return node

            return node

        # apply removal on AST root
        new_root = _remove(self._rhs_ast.body)

        # update or drop the AST
        if new_root is None:
            self._rhs_ast = None
        else:
            self._rhs_ast = ast.Expression(new_root)

        # and update filter_keys bookkeeping
        self.filter_keys.pop(red_key, None)

    def extract(self, keys: Optional[List[str]] = None) -> Optional["RedvyprAddress"]:
        if not self._rhs_ast:
            return None
        if keys is None:
            keys = list(self.filter_keys.keys())
        new_rva = RedvyprAddress()
        for k in keys:
            if k in self.filter_keys:
                for op in self.filter_keys[k]:
                    new_rva.add_filter(k, op)
        return new_rva

    # -------------------------
    # LHS Manipulation
    # -------------------------
    def add_datakey(self, datakey: str, overwrite: bool = True):
        if "@" in datakey:
            raise ValueError("datakey must not contain '@'.")
        if self.left_expr is None or overwrite:
            self.left_expr = datakey

    def delete_datakey(self):
        self.left_expr = None

    # -------------------------
    # String / Dict Conversion
    # -------------------------
    def to_redvypr_dict(self, include_datakey=True):
        """
        Liefert ein Dict mit '_redvypr', gefüllt aus den Filtern.
        - _eq: direkter Wert
        - _in: Liste
        - _regex: {"__regex__": pattern, "flags": flags}
        - _exists: {"__exists__": True}
        """
        result = {}
        result_datakey = {}
        depth = None
        if include_datakey:
            try:
                result_datakey = self.create_minimal_datakey_packet()
            except:
                pass

        if not self._rhs_ast:
            red_dict = {"_redvypr": result}
            red_dict.update(result_datakey)
            return red_dict

        def add_to_dict(key, value):
            """Schlüssel wie 'host.addr' in verschachtelte Dicts umwandeln"""
            parts = key.split(".")
            cur = result
            for p in parts[:-1]:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            cur[parts[-1]] = value

        def traverse(node):
            if isinstance(node, ast.Expression):
                traverse(node.body)
            elif isinstance(node, ast.BoolOp):
                for v in node.values:
                    traverse(v)
            elif isinstance(node, ast.Call):
                func_name = node.func.id
                key = ast.literal_eval(node.args[0])

                if func_name == "_eq":
                    val = ast.literal_eval(node.args[1])
                    add_to_dict(key, val)
                elif func_name == "_in":
                    vals = ast.literal_eval(node.args[1])
                    add_to_dict(key, vals)
                elif func_name == "_regex":
                    pat = ast.literal_eval(node.args[1])
                    flags = ast.literal_eval(node.args[2]) if len(node.args) > 2 else ""
                    add_to_dict(key, {"__regex__": pat, "flags": flags})
                elif func_name == "_exists":
                    add_to_dict(key, {"__exists__": True})

        traverse(self._rhs_ast)

        red_dict = {"_redvypr": result}
        red_dict.update(result_datakey)
        return red_dict


    def get_datakeyentries(self):
        """
        Parses an LHS expression like "foo['bar'][2]['baz']"
        and returns a list of path components:
        e.g., ["foo", "bar", 2, "baz"]
        """
        expr = self.left_expr
        entries = []
        if expr is None:
            return entries
        elif len(expr.strip()) == 0:
            return entries
        expr = expr.strip()

        # Extract top-level key
        m = re.match(r"([A-Za-z_][A-Za-z_0-9]*)", expr)
        if not m:
            raise ValueError(f"Cannot extract top-level key from expression {expr!r}")
        entries.append(m.group(1))
        rest = expr[m.end():]

        while rest:
            rest = rest.strip()
            # dict key ['key'] or ["key"]
            m_key = re.match(r"\[\s*(['\"])(.+?)\1\s*\]", rest)
            if m_key:
                entries.append(m_key.group(2))
                rest = rest[m_key.end():]
                continue
            # list index [n]
            m_index = re.match(r"\[\s*(-?\d+)\s*\]", rest)
            if m_index:
                entries.append(int(m_index.group(1)))
                rest = rest[m_index.end():]
                continue
            # slicing, we can store as string
            m_slice = re.match(r"\[\s*([-0-9]*)\s*:\s*([-0-9]*)\s*(:\s*([-0-9]*))?\s*\]", rest)
            if m_slice:
                entries.append(rest[:m_slice.end()])  # keep original slice string
                rest = rest[m_slice.end():]
                continue

            raise ValueError(f"Cannot parse remaining part of expression: {rest!r}")

        return entries

    def create_minimal_datakey_packet(self):
        """
        Create a nested dict/list structure from an expression like
        'data[0]', "payload['x']", 'foo["bar"][2]', or "data[::-1]".
        The resulting packet dict is suitable so that eval(expr, ..., packet)
        will return a valid value without KeyError.
        """
        expr = self.left_expr
        if expr is None:
            raise ValueError("Cannot create packet from None")
        elif len(expr.strip()) == 0:
            raise ValueError("Cannot create packet from empty expression")
        # Extract top-level key
        m = re.match(r"\s*([A-Za-z_][A-Za-z_0-9]*)", expr)
        if not m:
            raise ValueError(f"Cannot extract top-level key from expression {expr!r}")
        top = m.group(1)
        rest = expr[m.end():]

        if not rest:
            return {top: True}

        value, depth = self._build_from_rest(rest, current_depth=1)
        return {top: value}

    def _build_from_rest(self, rest: str, current_depth: int):
        rest = rest.strip()

        # slicing
        if re.match(r"\[\s*(-?\d*)?\s*:\s*(-?\d*)?\s*(:\s*(-?\d*)?)?\s*\]", rest):
            return [True, True, True, True, True], current_depth + 1

        # list index
        m_index = re.match(r"\[\s*(-?\d+)\s*\]", rest)
        if m_index:
            remainder = rest[m_index.end():]
            if remainder:
                subval, depth = self._build_from_rest(remainder, current_depth + 1)
                base = [subval]
                return base, depth
            else:
                return [0], current_depth + 1

        # dict key
        m_key = re.match(r"""\[\s*(['"])(.+?)\1\s*\]""", rest)
        if m_key:
            remainder = rest[m_key.end():]
            if remainder:
                subval, depth = self._build_from_rest(remainder, current_depth + 1)
                return {m_key.group(2): subval}, depth
            else:
                return {m_key.group(2): 0}, current_depth + 1

        raise ValueError(f"Cannot interpret structure from remainder={rest!r}")

    def __repr__(self):
        return self.to_address_string()


    # -------------------------
    # Lesbare RHS / get_str
    # -------------------------
    def _ast_to_rhs_string(self, node: ast.AST) -> str:
        """
        Converts an AST (Abstract Syntax Tree) back into a human-readable Redvypr address string.

        This function recursively traverses the AST nodes and converts them into a string
        representation that uses short prefixes for Redvypr fields. It supports the following:

        - `_eq`, `_in`, `_regex`, `_exists` function calls.
        - `_dt(...)` calls are converted into Python datetime objects.
        - Boolean operations (`and`, `or`) are handled recursively.
        - Comparison operations (`==`, `!=`, `<`, `<=`, `>`, `>=`) are handled.
        - Constant values and names are converted directly.

        Special notes:
        - `_dt('ISO_STRING')` inside a comparison (or as standalone) is replaced with
          a `datetime.datetime` object using `datetime.fromisoformat()`.
        - BoolOps are flattened into `and` / `or` joined strings.
        - Comparisons with multiple comparators (like `a < b < c`) are reconstructed
          in the correct order.

        Parameters
        ----------
        node : ast.AST
            The AST node to convert into a human-readable string.

        Returns
        -------
        str
            The reconstructed Redvypr address string.
        """
        if node is None:
            return ""

        # Expression → traverse to body
        if isinstance(node, ast.Expression):
            return self._ast_to_rhs_string(node.body)

        # Boolean operations: recursively handle each operand
        elif isinstance(node, ast.BoolOp):
            op_str = " and " if isinstance(node.op, ast.And) else " or "
            return op_str.join([self._ast_to_rhs_string(v) for v in node.values])

        # Call nodes: _eq, _in, _regex, _exists, _dt
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            func_name = node.func.id
            if func_name in ("_eq", "_in", "_regex", "_exists"):
                key = ast.literal_eval(node.args[0])
                field_prefix = self.REV_PREFIX_MAP.get(key, key)
                if func_name == "_eq":
                    val = ast.literal_eval(node.args[1])
                    return f"{field_prefix}:{val}"
                elif func_name == "_in":
                    vals = ast.literal_eval(node.args[1])
                    return f"{field_prefix}:[{','.join(map(str, vals))}]"
                elif func_name == "_regex":
                    pat = ast.literal_eval(node.args[1])
                    flags = ast.literal_eval(node.args[2]) if len(node.args) > 2 else ""
                    return f"{field_prefix}:~/{pat}/{flags}"
                elif func_name == "_exists":
                    return f"{field_prefix}?:"
            elif func_name == "_dt":
                val = ast.literal_eval(node.args[0])
                dt_obj = datetime.fromisoformat(val)
                dt_str = f"dt({dt_obj.isoformat()})"
                # return repr(dt_obj)
                return dt_str

        # Comparison nodes: e.g., calibration_date == _dt(...)
        elif isinstance(node, ast.Compare):
            left = self._ast_to_rhs_string(node.left)
            comparators = [self._ast_to_rhs_string(c) for c in node.comparators]
            ops = []
            for op in node.ops:
                if isinstance(op, ast.Eq):
                    ops.append("==")
                elif isinstance(op, ast.NotEq):
                    ops.append("!=")
                elif isinstance(op, ast.Lt):
                    ops.append("<")
                elif isinstance(op, ast.LtE):
                    ops.append("<=")
                elif isinstance(op, ast.Gt):
                    ops.append(">")
                elif isinstance(op, ast.GtE):
                    ops.append(">=")
                else:
                    ops.append("?")
            # reconstruct chained comparisons
            pieces = [left]
            for o, c in zip(ops, comparators):
                pieces.append(o)
                pieces.append(c)
            return " ".join(pieces)

        # Names and constants
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Constant):
            return repr(node.value)

        # fallback: unparse any other node
        else:
            return ast.unparse(node)

    def to_address_string(self, keys: Union[str, List[str]] = None) -> str:
        """Readable version of the address, optionally filtered by keys"""


        # Prepare the allowed keys set
        allowed_keys_set = None
        show_left = True
        if keys is not None:
            if isinstance(keys, str):
                allowed_keys = [k.strip() for k in keys.split(",") if k.strip()]
            else:
                allowed_keys = keys

            # expand both PREFIX_MAP and REV_PREFIX_MAP, so both short and long keys work
            expanded = set()
            for k in allowed_keys:
                if k in self.LONGFORM_MAP:  # short prefix like "p"
                    expanded.add(self.LONGFORM_MAP[k])
                elif k in self.PREFIX_MAP:  # short prefix like "p"
                    expanded.add(self.PREFIX_MAP[k])
                elif k in self.REV_PREFIX_MAP:  # long key like "publisher"
                    expanded.add(k)
                else:
                    expanded.add(k)

            allowed_keys_set = expanded
            #allowed_keys_set = set(self.PREFIX_MAP.get(k, k) for k in allowed_keys)
            if not any(k in allowed_keys for k in ("k", "datakey")):
                show_left = False  # hide left_expr if not requested explicitly

            if len(allowed_keys) == 0:
                return "@"

        if not self._rhs_ast:
            if self.left_expr and show_left:
                return f"{self.left_expr}"
            else:
                return "@"

        def prune_ast(node: ast.AST) -> Optional[ast.AST]:
            if isinstance(node, ast.Expression):
                node.body = prune_ast(node.body)
                return node if node.body else None

            elif isinstance(node, ast.BoolOp):
                new_vals = [prune_ast(v) for v in node.values]
                new_vals = [v for v in new_vals if v is not None]
                if not new_vals:
                    return None
                node.values = new_vals
                return node

            elif isinstance(node, ast.Call):
                try:
                    key = ast.literal_eval(node.args[0])
                except Exception:
                    return None  # Discard nodes with invalid literals

                # Discard node if the key is None
                if key is None:
                    return None

                # Filter by allowed keys
                if allowed_keys_set and key not in allowed_keys_set:
                    return None

                # Optionally check other arguments (value/content) for None
                for arg in node.args[1:]:
                    try:
                        val = ast.literal_eval(arg)
                        if val is None:
                            return None
                    except Exception:
                        continue  # Ignore non-evaluable arguments

                return node

            else:
                return node

        filtered_ast = prune_ast(copy.deepcopy(self._rhs_ast)) if allowed_keys_set else self._rhs_ast
        rhs_str = self._ast_to_rhs_string(filtered_ast) if filtered_ast else ""

        if self.left_expr and show_left:
            return f"{self.left_expr} @ {rhs_str}" if rhs_str else self.left_expr
        return f"@{rhs_str}" if rhs_str else "@"

    def to_address_string_pure_python(self, keys: Union[str, List[str]] = None) -> str:
        """
        Returns a Python-evaluable version of the Redvypr address.

        Converts Redvypr-style filters into Python expressions that can be evaluated.
        Examples:
            - i:test -> _redvypr['packetid'] == 'test'
            - d:cam  -> _redvypr['device'] == 'cam'

        Optional:
            Only include certain keys if `keys` is provided.

        Additionally:
            - Any `_dt('ISO_STRING')` in the AST is converted to a `datetime.datetime(...)` object.
        """
        if not self._rhs_ast:
            return f"{self.left_expr}@" if self.left_expr else "@"

        # Process allowed keys if specified
        allowed_keys = None
        if keys is not None:
            if isinstance(keys, str):
                allowed_keys = [k.strip() for k in keys.split(",") if k.strip()]
            else:
                allowed_keys = keys

        def ast_to_python(node: ast.AST) -> str:
            if node is None:
                return ""

            if isinstance(node, ast.Expression):
                return ast_to_python(node.body)

            elif isinstance(node, ast.BoolOp):
                op_str = ' and ' if isinstance(node.op, ast.And) else ' or '
                return op_str.join([ast_to_python(v) for v in node.values])

            elif isinstance(node, ast.Compare):
                left = ast_to_python(node.left)
                comparators = [ast_to_python(c) for c in node.comparators]
                ops = []
                for op in node.ops:
                    if isinstance(op, ast.Eq):
                        ops.append("==")
                    elif isinstance(op, ast.NotEq):
                        ops.append("!=")
                    elif isinstance(op, ast.Lt):
                        ops.append("<")
                    elif isinstance(op, ast.LtE):
                        ops.append("<=")
                    elif isinstance(op, ast.Gt):
                        ops.append(">")
                    elif isinstance(op, ast.GtE):
                        ops.append(">=")
                    else:
                        ops.append("?")
                pieces = [left]
                for o, c in zip(ops, comparators):
                    pieces.append(o)
                    pieces.append(c)
                return " ".join(pieces)

            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                func_name = node.func.id
                key = ast.literal_eval(node.args[0])

                # skip keys not allowed
                if allowed_keys and key not in [self.PREFIX_MAP.get(k, k) for k in
                                                allowed_keys]:
                    return ""

                # nested dictionary access
                key_parts = key.split(".")
                dict_access = "_redvypr"
                for part in key_parts:
                    dict_access += f"['{part}']"

                # handle standard Redvypr operators
                if func_name == "_eq":
                    val = ast.literal_eval(node.args[1])
                    return f"{dict_access} == {repr(val)}"
                elif func_name == "_in":
                    vals = ast.literal_eval(node.args[1])
                    return f"{dict_access} in {repr(vals)}"
                elif func_name == "_regex":
                    pat = ast.literal_eval(node.args[1])
                    flags = ast.literal_eval(node.args[2]) if len(node.args) > 2 else ""
                    return f"re.search({repr(pat)}, str({dict_access}), {repr(flags)})"
                elif func_name == "_exists":
                    return f"'{key_parts[-1]}' in {dict_access.rsplit('[', 1)[0]}"
                elif func_name == "_dt":
                    # convert _dt('ISO_STRING') to datetime.datetime(...)
                    val = ast.literal_eval(node.args[0])
                    return f"datetime.fromisoformat('{val}')"

            elif isinstance(node, ast.Name):
                return node.id
            elif isinstance(node, ast.Constant):
                return repr(node.value)

            else:
                return ast.unparse(node)

        rhs_python = ast_to_python(self._rhs_ast)
        if self.left_expr:
            return f"{self.left_expr} @ {rhs_python}" if rhs_python else self.left_expr
        return f"@{rhs_python}" if rhs_python else "@"


    def get_common_address_formats(self):
        return self.common_address_formats

    def get_str_from_format(self, address_format='{k}@{u} and {a} and {h} and {d} and {p} and {i}'):
        """ Returns a string of the redvypr address from a format string.
        """
        funcname = __name__ + '.get_str_from_format():'
        vals = {
            'u': self.uuid,
            'a': self.addr,
            'h': self.host,
            'd': self.device,
            'i': self.packetid,
            'p': self.publisher,
            'k': self.datakey,
            'uuid': self.uuid,
            'address': self.addr,
            'host': self.host,
            'device': self.device,
            'packetid': self.packetid,
            'publisher': self.publisher,
            'datakey': self.datakey,
        }

        #filtered_vals = {k: f"{k}:{v}" for k, v in vals.items() if v is not None}
        # Treat None as empty string
        filtered_vals = {}
        for k, v in vals.items():
            if v is not None:
                v_print = v
            else:
                v_print = ""
            filtered_vals[k] = f"{k}:{v_print}"
        #print("Address format",address_format,filtered_vals)
        retstr = address_format.format(**filtered_vals)
        return retstr

    def __getattr__(self, name):
        if name in ('datakey','k'):
            return self.left_expr

        cls = type(self)
        if name in cls.PREFIX_MAP:
            red_key = cls.PREFIX_MAP[name]
        elif name in cls.LONGFORM_MAP:
            red_key = cls.LONGFORM_MAP[name]
        else:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

        if not self._rhs_ast or red_key not in self.filter_keys:
            return None

        filter_expr = ast.unparse(self._rhs_ast)

        values = []

        eq_pattern = re.compile(r"_eq\(\s*['\"]{}['\"]\s*,\s*(.*?)\s*\)".format(re.escape(red_key)))
        for m in eq_pattern.finditer(filter_expr):
            val = m.group(1)
            try:
                val_eval = ast.literal_eval(val)
            except Exception:
                val_eval = val
            values.append(val_eval)

        in_pattern = re.compile(r"_in\(\s*['\"]{}['\"]\s*,\s*(.*?)\s*\)".format(re.escape(red_key)))
        for m in in_pattern.finditer(filter_expr):
            val = m.group(1)
            try:
                val_eval = ast.literal_eval(val)
            except Exception:
                val_eval = val
            if isinstance(val_eval, list):
                values.extend(val_eval)
            else:
                values.append(val_eval)

        if len(values) == 1:
            return values[0]
        elif values:
            return values
        else:
            return None

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: typing.Any,
        _handler: pydantic.GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        """
        Modified from here:
        https://docs.pydantic.dev/latest/concepts/types/#handling-third-party-types
        We return a pydantic_core.CoreSchema that behaves in the following ways:

        * strs will be parsed as `RedvyprAddress` instances
        * `RedvyprAddress` instances will be parsed as `RedvyprAddress` instances without any changes
        * Nothing else will pass validation
        * Serialization will always return just a str
        """

        def validate_from_str(value: str) -> RedvyprAddress:
            result = RedvyprAddress(value)
            return result

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
                    # check if it's an instance first before doing any further work
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
        # Use the same schema that would be used for `str`
        return handler(core_schema.str_schema())






