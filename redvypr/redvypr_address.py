"""
Redvypr addresses are the base to identify and address redvypr data packets.
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
        "h": "host.hostname",
        "ul": "localhost.uuid",
        "al": "localhost.addr",
        "hl": "localhost.hostname",
    }

    LONGFORM_MAP = {
        "packetid": "packetid",
        "publisher": "publisher",
        "device": "device",
        "uuid": "host.uuid",
        "hostname": "host.hostname",
        "addr": "host.addr",
        "uuid_localhost": "localhost.uuid",
        "hostname_localhost": "localhost.hostname",
        "addr_localhost": "localhost.addr",
    }

    LONGFORM_TO_SHORT_MAP = {
        "packetid": "i",
        "publisher": "p",
        "device": "d",
        "uuid": "u",
        "hostname": "h",
        "addr": "a",
        "uuid_localhost": "ul",
        "hostname_localhost": "hl",
        "addr_localhost": "al",
    }
    LONGFORM_TO_SHORT_MAP_DATAKEY = {
        "datakey": "k",
        "packetid": "i",
        "publisher": "p",
        "device": "d",
        "uuid": "u",
        "hostname": "h",
        "addr": "a",
        "uuid_localhost": "ul",
        "hostname_localhost": "hl",
        "addr_localhost": "al",
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
                 hostname: Optional[Any] = None,
                 uuid: Optional[Any] = None,
                 addr: Optional[Any] = None,
                 hostname_localhost: Optional[Any] = None,
                 uuid_localhost: Optional[Any] = None,
                 addr_localhost: Optional[Any] = None):
        self.left_expr: Optional[str] = None
        self._rhs_ast: Optional[ast.Expression] = None
        self.filter_keys: Dict[str, list] = {}

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
                "host": {"hostname": "h", "addr": "a", "uuid": "u"},
                "localhost": {"hostname": "hl", "addr": "al", "uuid": "ul"},
            }
            for k, v in redvypr.items():
                if k in mapping:
                    if isinstance(mapping[k], dict):
                        for subk, prefix in mapping[k].items():
                            if subk in v:
                                self.add_filter(prefix, "eq", v[subk])
                    else:
                        self.add_filter(mapping[k], "eq", v)

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
            ("hostname", hostname),
            ("uuid", uuid),
            ("address", addr),
            ("localhost.hostname", hostname_localhost),
            ("localhost.uuid", uuid_localhost),
            ("localhost.addr", addr_localhost),
        ]
        for red_key, val in kw_map:
            if val is not None:
                self.add_filter(red_key, "eq", val)

    # -------------------------
    # RHS AST Parsing
    # -------------------------
    def _parse_rhs(self, rhs: str) -> ast.Expression:
        s = rhs.strip()
        if not s:
            return None

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
            self.filter_keys.setdefault(red, []).append("eq")
            return f"_eq({repr(red)}, {self._lit_to_python(val)})"

        rhs = re.sub(rf'({prefix_group}):((".*?"|\'.*?\'|[^\s()]+))', repl_pref_eq, rhs)

        return ast.parse(rhs, mode="eval")

    def _lit_to_python(self, token: str) -> str:
        t = token.strip()
        if re.fullmatch(r'-?\d+(\.\d*)?', t):
            return t
        return repr(t)

    def _list_to_python(self, content: str) -> str:
        parts = [p.strip() for p in content.split(",")] if content.strip() else []
        return "[" + ",".join([self._lit_to_python(p) for p in parts]) + "]"

    # -------------------------
    # Eval helpers
    # -------------------------
    def _build_eval_locals(self, packet: dict):
        locals_map = {}
        def _eq(k, v): return self._get_val(packet, k) == v
        def _in(k, l): return self._get_val(packet, k) in l
        def _regex(k, pat, flags=""):
            v = self._get_val(packet, k)
            f = 0
            for ch in flags:
                if ch == "i": f |= re.IGNORECASE
                if ch == "m": f |= re.MULTILINE
                if ch == "s": f |= re.DOTALL
            return re.search(pat, str(v), f) is not None
        def _exists(k): return self._exists_val(packet, k)
        locals_map.update({"_eq": _eq, "_in": _in, "_regex": _regex, "_exists": _exists, "packet": packet})
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
                return val
        found, val = self._traverse_path(packet, parts)
        if found:
            return val
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
    def matches(self, packet: Union[dict, "RedvyprAddress"], soft_missing: bool = True):
        """
        Check whether a packet matches this address.

        soft_missing:
            - True: missing keys for _eq/_in/_regex are treated as True (soft matching)
            - False: missing keys result in False (strict matching)
        """
        if isinstance(packet, RedvyprAddress):
            packet = packet.to_redvypr_dict()
        if not self._rhs_ast:
            return True

        SAFE_GLOBALS = {"__builtins__": None, "True": True, "False": False, "None": None}

        # Evaluation helpers
        def _eq(k, v):
            try:
                val = self._get_val(packet, k)
                return val == v
            except FilterFieldMissing:
                return soft_missing

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

        locals_map = {"_eq": _eq, "_in": _in, "_regex": _regex, "_exists": _exists, "packet": packet}
        if isinstance(packet, dict):
            locals_map["_redvypr"] = packet.get("_redvypr")
            for k, v in packet.items():
                if k not in locals_map:
                    locals_map[k] = v

        try:
            return bool(eval(compile(self._rhs_ast, filename="<ast>", mode="eval"),
                             SAFE_GLOBALS, locals_map))
        except FilterFieldMissing:
            return False


    def matches_legacy(self, packet: Union[dict, "RedvyprAddress"]):
        if isinstance(packet, RedvyprAddress):
            packet = packet.to_redvypr_dict()
        if not self._rhs_ast:
            return True
        SAFE_GLOBALS = {"__builtins__": None, "True": True, "False": False, "None": None}
        try:
            return bool(eval(compile(self._rhs_ast, filename="<ast>", mode="eval"),
                             SAFE_GLOBALS, self._build_eval_locals(packet)))
        except FilterFieldMissing:
            return False

    def __call__(self, packet):
        if isinstance(packet, RedvyprAddress):
            packet = packet.to_redvypr_dict()
        if self.left_expr is None and self._rhs_ast is None:
            return packet
        SAFE_GLOBALS = {"__builtins__": None, "True": True, "False": False, "None": None}
        locals_map = dict(packet)
        if self._rhs_ast and not self.matches(packet):
            raise FilterNoMatch("Packet did not match filter")
        if self.left_expr:
            top_key = self.left_expr.split("[")[0].split(".")[0]
            if top_key not in packet:
                raise KeyError(f"Key {top_key!r} missing in packet")
            return eval(self.left_expr, SAFE_GLOBALS, locals_map)
        return packet

    # -------------------------
    # Filter Manipulation (AST)
    # -------------------------
    def add_filter(self, key, op, value=None, flags=""):
        red_key = self.PREFIX_MAP.get(key, key)
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
        if not self._rhs_ast:
            return
        red_key = self.PREFIX_MAP.get(key, key)
        # AST neu erstellen ohne den key
        old_expr = ast.unparse(self._rhs_ast.body)
        pattern = re.compile(rf'_((eq|in|regex|exists))\(\s*{repr(red_key)}.*?\)')
        new_expr = pattern.sub('', old_expr)
        if new_expr.strip():
            self._rhs_ast = ast.parse(new_expr, mode="eval")
        else:
            self._rhs_ast = None
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
    def to_address_string_legacy(self):
        left = self.left_expr or ""
        right = ast.unparse(self._rhs_ast.body) if self._rhs_ast else ""
        return f"{left}@{right}" if right else left or "@"

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
            return {top: 0}

        value, depth = self._build_from_rest(rest, current_depth=1)
        return {top: value}

    def _build_from_rest(self, rest: str, current_depth: int):
        rest = rest.strip()

        # slicing
        if re.match(r"\[\s*(-?\d*)?\s*:\s*(-?\d*)?\s*(:\s*(-?\d*)?)?\s*\]", rest):
            return [1, 2, 3, 4, 5], current_depth + 1

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
        """AST → menschenlesbarer Redvypr-String mit Kurzpräfixen"""
        if node is None:
            return ""

        if isinstance(node, ast.Expression):
            return self._ast_to_rhs_string(node.body)

        elif isinstance(node, ast.BoolOp):
            op_str = ' and ' if isinstance(node.op, ast.And) else ' or '
            flat_vals = [self._ast_to_rhs_string(v) for v in node.values]
            return op_str.join(flat_vals)

        elif isinstance(node, ast.Call):
            func_name = node.func.id
            key = ast.literal_eval(node.args[0])
            val = node.args[1] if len(node.args) > 1 else None

            # Kurzpräfix verwenden
            field_prefix = self.REV_PREFIX_MAP.get(key, key)

            if func_name == "_eq":
                val_str = ast.literal_eval(val) if isinstance(val, ast.Constant) else ast.unparse(val)
                return f"{field_prefix}:{val_str}"
            elif func_name == "_in":
                lst = ast.literal_eval(val) if isinstance(val, ast.List) else [val]
                lst_str = ",".join(str(v) for v in lst)
                return f"{field_prefix}:[{lst_str}]"
            elif func_name == "_regex":
                pat = ast.literal_eval(val)
                flags = ast.literal_eval(node.args[2]) if len(node.args) > 2 else ""
                return f"{field_prefix}:~/{pat}/{flags}"
            elif func_name == "_exists":
                return f"{field_prefix}?:"
        else:
            return ast.unparse(node)

    def to_address_string(self, keys: Union[str, List[str]] = None) -> str:
        """Readable version of the address, optionally filtered by keys"""
        if not self._rhs_ast:
            return f"{self.left_expr}@" if self.left_expr else "@"

        # Prepare the allowed keys set
        allowed_keys_set = None
        if keys is not None:
            if isinstance(keys, str):
                allowed_keys = [k.strip() for k in keys.split(",") if k.strip()]
            else:
                allowed_keys = keys
            allowed_keys_set = set(self.PREFIX_MAP.get(k, k) for k in allowed_keys)

        import copy

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

        if self.left_expr:
            return f"{self.left_expr} @ {rhs_str}" if rhs_str else self.left_expr
        return f"@{rhs_str}" if rhs_str else "@"

    def to_address_string_legacy(self, keys: Union[str, List[str]] = None) -> str:
        """Lesbare Version der Adresse, optional gefiltert nach Keys"""
        if not self._rhs_ast:
            return f"{self.left_expr}@" if self.left_expr else "@"

        allowed_keys = None
        if keys is not None:
            if isinstance(keys, str):
                allowed_keys = [k.strip() for k in keys.split(",") if k.strip()]
            else:
                allowed_keys = keys

        # AST filtern nach Keys → Kopie benutzen, damit Original nicht verändert wird
        import copy
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
                key = ast.literal_eval(node.args[0])
                if not allowed_keys or key in [self.PREFIX_MAP.get(k, k) for k in allowed_keys]:
                    return node
                return None
            else:
                return node

        filtered_ast = prune_ast(copy.deepcopy(self._rhs_ast)) if allowed_keys else self._rhs_ast
        rhs_str = self._ast_to_rhs_string(filtered_ast) if filtered_ast else ""

        if self.left_expr:
            return f"{self.left_expr} @ {rhs_str}" if rhs_str else self.left_expr
        return f"@{rhs_str}" if rhs_str else "@"

    def to_address_string_pure_python(self, keys: Union[str, List[str]] = None) -> str:
        """
        Liefert eine Python-kompatible Version der Adresse:
        - i:test -> _redvypr['packetid'] == 'test'
        - d:cam -> _redvypr['device'] == 'cam'
        Optional: nur bestimmte Keys berücksichtigen.
        """
        if not self._rhs_ast:
            return f"{self.left_expr}@" if self.left_expr else "@"

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
            elif isinstance(node, ast.Call):
                func_name = node.func.id
                key = ast.literal_eval(node.args[0])
                if allowed_keys and key not in [self.PREFIX_MAP.get(k, k) for k in allowed_keys]:
                    return ""
                # verschachtelte Dicts erzeugen
                key_parts = key.split(".")
                dict_access = "_redvypr"
                for part in key_parts:
                    dict_access += f"['{part}']"
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
            'h': self.hostname,
            'd': self.device,
            'i': self.packetid,
            'p': self.publisher,
            'k': self.datakey,
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






class RedvyprAddress_legacy:
    """
    """
    address_str: str
    def __init__(self, addrstr=None, local_hostinfo=None, datakey=None, devicename=None, hostname=None, addr=None, uuid=None, publisher=None, compare=None, packetid=None):
        # Some definitions
        self.__regex_symbol_start = '{'
        self.__regex_symbol_end = '}'
        self.add_entries_short = {'k': 'datakey', 'd': 'devicename', 'i': 'packetid', 'a': 'addr', 'u': 'uuid', 'h': 'hostname', 'p': 'publisher', 'c': 'compare'}
        self.addr_entries_short_r = {'datakey': 'k', 'devicename': 'd' , 'packetid': 'i', 'addr': 'a', 'uuid': 'u' , 'hostname': 'h', 'publisher': 'p', 'compare': 'c'}
        self.addr_entries = ['datakey', 'devicename', 'packetid', 'addr', 'uuid', 'hostname', 'publisher', 'compare']
        self.addr_entries_expand = ['datakeyexpand', 'deviceexpand', 'packetidexpand', 'addrexpand', 'uuidexpand', 'hostexpand', 'publisherexpand', 'compareexpand']
        self.__delimiter_parts = '/'
        self.__delimiter_id = ':'

        # Try to convert redvypr_address to dict
        self._common_address_formats = ['/i/k', '/d/i/k','/k/','/d/','/i/','/p/','/p/d/','/p/d/i','/u/a/h/d/','/u/a/h/d/i', '/u/a/h/d/k/', '/u/a/h/d/k/i', '/a/h/d/', '/a/h/d/i', '/a/h/p/']
        if addrstr is not None: # Address from addrstr
            #print('addrstr',type(addrstr),type(self))
            if type(addrstr) == type(self): # If addrstr is redvypr_address, convert it to str
                self.address_str = addrstr.address_str
            #elif type(addrstr) == dict:  # Address from datapacket # This does not work with inherited classes like redvypr_address
            elif isinstance(addrstr, dict):  # Addressstr is a redvypr datapacket # This should work with dict and inherited classes like redvypr_address
                try:
                    publisher_packet = addrstr['_redvypr']['publisher']
                except:
                    publisher_packet = None

                try:
                    packetid = addrstr['_redvypr']['packetid']
                except:
                    packetid = None
                try:
                    devicename_packet = addrstr['_redvypr']['device']
                except:
                    devicename_packet = None

                if True:
                    try:
                        addr_packet = addrstr['_redvypr']['host']['addr']
                    except:
                        addr_packet = None

                try:
                    hostname_packet = addrstr['_redvypr']['host']['hostname']
                except:
                    hostname_packet = None
                try:
                    uuid_packet = addrstr['_redvypr']['host']['uuid']
                except:
                    uuid_packet = None

                self.address_str = self.create_addrstr(datakey=datakey,
                                                       packetid=packetid,
                                                       devicename=devicename_packet,
                                                       hostname=hostname_packet,
                                                       addr=addr_packet,
                                                       uuid=uuid_packet,
                                                       publisher=publisher_packet,
                                                       local_hostinfo=local_hostinfo)

            elif addrstr == '*':
                self.address_str = self.create_addrstr()
            elif addrstr.startswith('RedvyprAddress(') and addrstr.endswith(')'):
                # string that can be evaluated
                redvypr_address_tmp = eval(addrstr)
                self.address_str = redvypr_address_tmp.address_str
            else:
                self.address_str = addrstr

            # Replace potentially given arguments
            #if any([addrstr, local_hostinfo, datakey, devicename, hostname, addr, uuid, publisher]):
            if any([packetid, publisher, local_hostinfo, datakey, devicename, hostname, addr, uuid, publisher]):
                #print('Replacing string with new stuff')
                (parsed_addrstr, parsed_addrstr_expand) = self.parse_addrstr(self.address_str)
                if packetid is not None:
                    parsed_addrstr['packetid'] = packetid
                if addr is not None:
                    parsed_addrstr['addr'] = addr
                if datakey is not None:
                    parsed_addrstr['datakey'] = datakey
                if devicename is not None:
                    parsed_addrstr['devicename'] = devicename
                if hostname is not None:
                    parsed_addrstr['hostname'] = hostname
                if uuid is not None:
                    parsed_addrstr['uuid'] = uuid
                if publisher is not None:
                    parsed_addrstr['publisher'] = publisher
                # new
                if compare is not None:
                    parsed_addrstr['compare'] = compare
                # new
                if local_hostinfo is not None:
                    parsed_addrstr['local_hostinfo'] = local_hostinfo

                #self.address_str = self.create_addrstr(parsed_addrstr['datakey'], parsed_addrstr['devicename'], parsed_addrstr['hostname'], parsed_addrstr['addr'], parsed_addrstr['uuid'], parsed_addrstr['publisher'], local_hostinfo=local_hostinfo)
                self.address_str = self.create_addrstr(**parsed_addrstr)

        else:  # addrstr from single ingredients
            self.address_str = self.create_addrstr(datakey=datakey,
                                                   packetid=packetid,
                                                   devicename=devicename,
                                                   hostname=hostname,
                                                   addr=addr,
                                                   uuid=uuid,
                                                   publisher=publisher,
                                                   local_hostinfo=local_hostinfo,
                                                   compare=compare)
            # print('Address string',self.address_str)

        (parsed_addrstr,parsed_addrstr_expand) = self.parse_addrstr(self.address_str)
        self.parsed_addrstr = parsed_addrstr
        self.parsed_addrstr_expand = parsed_addrstr_expand

        # Add the attributes to the object and an explicit address string

        self.explicit_format = '/'
        for addr_id in self.addr_entries:
            addr_entry = parsed_addrstr[addr_id]
            if addr_entry is None:
                addr_entry = '*'
            setattr(self,addr_id,addr_entry)
            expand_attribute = addr_id + 'expand'
            setattr(self, expand_attribute, parsed_addrstr_expand[addr_id])
            if addr_entry != '*':
                addr_id_short = self.addr_entries_short_r[addr_id]
                self.explicit_format += addr_id_short + '/'

        self.address_str_explicit = self.get_str(self.explicit_format)
        self.datakeyeval = parsed_addrstr_expand['datakeyeval']
        # Check if address has a regular expression
        self.datakeyregex = False
        if self.datakey.startswith(self.__regex_symbol_start) and self.datakey.endswith(self.__regex_symbol_end) and len(
            self.datakey) > 1:
            self.datakeyregex = True

    def get_datakeyentries(self):
        if self.parsed_addrstr_expand['datakeyentries'] is None:
            return [self.datakey]
        else:
            return self.parsed_addrstr_expand['datakeyentries']

    def get_common_address_formats(self):
        return self._common_address_formats
    def create_addrstr(self, datakey=None, packetid=None, devicename=None, hostname=None, addr=None, uuid=None, publisher=None, local_hostinfo=None, compare=None, ignore_expand=True):
        """
            Creates an address string from given ingredients
            Args:
                datakey:
                packetid:
                devicename:
                hostname:
                addr:
                uuid:
                local_hostinfo:
                compare:

            Returns:

            """

        if local_hostinfo is not None:
            uuid = local_hostinfo['uuid']
            addr = local_hostinfo['addr']
            hostname = local_hostinfo['hostname']

        address_str = ''
        if compare is not None:
            if compare != '*' or ignore_expand:
                address_str += self.addr_entries_short_r['compare'] + self.__delimiter_id + compare + self.__delimiter_parts
        if uuid is not None:
            if uuid != '*' or ignore_expand:
                address_str += self.addr_entries_short_r['uuid'] + self.__delimiter_id + uuid + self.__delimiter_parts
        if addr is not None:
            if addr != '*' or ignore_expand:
                address_str += self.addr_entries_short_r['addr'] + self.__delimiter_id + addr + self.__delimiter_parts
        if hostname is not None:
            if hostname != '*' or ignore_expand:
                address_str += self.addr_entries_short_r['hostname'] + self.__delimiter_id + hostname + self.__delimiter_parts
        if publisher is not None:
            if publisher != '*' or ignore_expand:
                address_str += self.addr_entries_short_r['publisher'] + self.__delimiter_id + publisher + self.__delimiter_parts
        if devicename is not None:
            if devicename != '*' or ignore_expand:
                address_str += self.addr_entries_short_r['devicename'] + self.__delimiter_id + devicename + self.__delimiter_parts
        if packetid is not None:
            if packetid != '*' or ignore_expand:
                address_str += self.addr_entries_short_r['packetid'] + self.__delimiter_id + packetid + self.__delimiter_parts
        if datakey is not None:
            if datakey != '*' or ignore_expand:
                address_str += self.addr_entries_short_r['datakey'] + self.__delimiter_id + datakey + self.__delimiter_parts

        if len(address_str)>0:
            address_str = self.__delimiter_parts + address_str
        else:
            address_str += self.addr_entries_short_r['datakey'] + self.__delimiter_id + '*' + self.__delimiter_parts

        return address_str

    def get_data(self, datapacket):
        """Returns the part of the data in the datapacket that fits
        with the address

        """
        if datapacket in self:
            if self.datakeyexpand == True: # Return the time
                return datapacket['_redvypr']['t']
            elif self.datakey.startswith(self.__regex_symbol_start) and self.datakey.endswith(self.__regex_symbol_end) and len(self.datakey) > 1:
                # Regular expression
                for k in datapacket.keys():
                    if self.compare_address_substrings(k,self.datakey):
                        return datapacket[k]
            else: # Just a datakey
                if self.datakey.startswith('[') and self.datakey.endswith(']'):
                    evalstr = 'datapacket' + self.datakey
                    # data = self
                    data = eval(evalstr, None)
                    return data
                else:
                    #print(datapacket)
                    #print(self.datakey)
                    return datapacket[self.datakey]
        else:
            return None

    def parse_addrstr(self, addrstr):
        """ Parses a redvypr address string

        """

        # Create blank parsed_addrstr
        parsed_addrstr = {}
        parsed_addrstr_expand = {}
        # Split string into parts separated by the slash
        # Use regex to account for quoted strings
        #https://stackoverflow.com/questions/2785755/how-to-split-but-ignore-separators-in-quoted-strings-in-python
        regex_str = '''{}(?=(?:[^'"]|'[^']*'|"[^"]*")*$)'''.format(self.__delimiter_parts)
        #print('Regex str',regex_str)
        addrsplit_re = re.compile(regex_str)
        addr_parts = addrsplit_re.split(addrstr)
        #print('addrstr',addrstr,'addr_parts',addr_parts,len(addr_parts))
        for addr_part in addr_parts:
            #print('Part',addr_part)
            if len(addr_part) > 0:
                #print('split test', addr_part)
                if addr_part.startswith('['):  # Test if an eval is found, if so treat special as it might contain the ":"
                    addr_part_sp = [addr_part]
                else:
                    addr_part_sp = addr_part.split(self.__delimiter_id,1)
                #print('addr_part_sp 1', addr_part_sp)
                # Check if there is a single string, if so interprete as datakey entry
                if len(addr_part_sp) == 1 and len(addr_parts) == 1:
                    #print('Single entry, interpreting as datakey')
                    parsed_addrstr['datakey'] = addr_parts[0]
                elif len(addr_part_sp) >= 2:
                    addr_part_id = addr_part_sp[0]
                    addr_part_content = addr_part_sp[1]
                    #print('part',addr_part_id,addr_part_content)
                    # Try to add to parsed addrstr
                    try:
                        addr_part_id_decoded = self.add_entries_short[addr_part_id]
                        parsed_addrstr[addr_part_id_decoded] = addr_part_content
                    except:
                        pass
                else:
                    raise ValueError('Format needs to be <ID>{}<content>, not: {}'.format(self.__delimiter_id,str(addr_part_sp)))

        #print(parsed_addrstr)
        # Check for expansion and fill not explicitly defined ids with *
        #for addr_id,addr_idexpand in zip(self.__addr_ids,self.__addr_idsexpand):
        for addr_id in self.addr_entries:
            try:
                addr_content = parsed_addrstr[addr_id]
            except:
                addr_content = '*'
                parsed_addrstr[addr_id] = None

            # Check if an expansion (*) should be done
            if addr_content == '*':
                parsed_addrstr_expand[addr_id] = True
            else:
                parsed_addrstr_expand[addr_id] = False

        parsed_addrstr_expand['datakeyeval'] = False
        parsed_addrstr_expand['datakeyentries'] = None
        parsed_addrstr_expand['datakeyentries_str'] = None
        if parsed_addrstr['datakey'] is not None:
            if parsed_addrstr['datakey'].startswith('[') and parsed_addrstr['datakey'].endswith(']'):
                parsed_addrstr_expand['datakeyeval'] = True
                # Parse the entries
                #https://stackoverflow.com/questions/2403122/regular-expression-to-extract-text-between-square-brackets
                # and
                # https://stackoverflow.com/questions/7317043/regex-not-operator#7317087
                # TODO: regex string is not optimally working with quoted strings and square brackets ...
                regex_str = r'(?<=\[).+?(?=\])'
                #print('Parsed address string',parsed_addrstr['datakey'])
                datakeyentries_str = re.findall(regex_str, parsed_addrstr['datakey'])
                datakeyentries = [eval(x,None) for x in datakeyentries_str]
                parsed_addrstr_expand['datakeyentries_str'] = datakeyentries_str # The str values can be used to reconstruct the original str
                parsed_addrstr_expand['datakeyentries'] = datakeyentries

        #print(parsed_addrstr)
        return parsed_addrstr,parsed_addrstr_expand

    def get_fullstr(self):
        address_format = '/u/a/h/d/p/i/k/'
        return self.get_str(address_format)


    def get_expand_explicit_str(self, address_format = '/u/a/h/d/p/i/k/'):
        r"""
        Returns a string that searches explicitly for the expandsymbol.
        This is useful to match with addresses with the expandsymbol defined but
        not with addresses that have a real value in the address entry::

            r1 = RedvyprAddress('/d:test/k:*')
            r2 = RedvyprAddress('/d:test/k:somekey')
            r1.get_expand_explicit_str('/d/k') # yields '/d:test/k:{\\*}/'
            r1_exp = RedvyprAddress(r1.get_expand_explicit_str('/d/k'))
            print("r1: {}".format(r1)) # r1: RedvyprAddress('''/d:test/k:*''')
            print("r1_exp: {}".format(r1_exp)) # r1_exp: RedvyprAddress('''/d:test/k:{\*}/''')
            print("r2: {}".format(r2)) # r2: RedvyprAddress('''/d:test/k:somekey''')
            print("r2 in r1: {}".format(r2 in r1)) # r2 in r1: True
            print("r2 in r1_exp: {}".format(r2 in r1_exp)) # r2 in r1_exp: False

        :return:
        """
        address_str = self.__delimiter_parts
        addr_ids = address_format.split(self.__delimiter_parts)
        for a_id in addr_ids:
            if len(a_id) > 0:
                addr_id = self.add_entries_short[a_id]
                addr_id_data = self.parsed_addrstr[addr_id]
                if (addr_id_data is None) or (addr_id_data == '*'):
                    addr_id_data = r'{\*}'
                address_str += a_id + self.__delimiter_id + addr_id_data + self.__delimiter_parts

        return address_str


    def get_str(self, address_format = '/u/a/h/d/p/i/k/'):
        funcname = __name__ + '.get_str():'
        address_str = self.__delimiter_parts
        addr_ids = address_format.split(self.__delimiter_parts)
        for a_id in addr_ids:
            if len(a_id) > 0:
                if ':==' in a_id:
                    addr_id_addon = '=='
                    a_id = a_id.replace(':==','')
                else:
                    addr_id_addon = ''
                addr_id = self.add_entries_short[a_id]
                addr_id_data = self.parsed_addrstr[addr_id]
                if addr_id_data is not None:
                    address_str += a_id + self.__delimiter_id + addr_id_addon + addr_id_data + self.__delimiter_parts

        return address_str

    def get_str_from_format(self, address_format='/{u}/{a}/{h}/{d}/{p}/{i}/{k}/'):
        """ Returns a string of the redvypr address from format string.
        """
        funcname = __name__ + '.get_str_from_format():'
        retstr = address_format.format(u='u:' + self.uuid,
                                       a='a:' + self.addr,
                                       h='h:' + self.hostname,
                                       d='d:' + self.devicename,
                                       i='i:' + self.packetid,
                                       p='p:' + self.publisher,
                                       c='c:' + self.compare,
                                       k='k:' + self.datakey)
        return retstr

    def compare_address_substrings(self, str1, str2):
        #if str1 == '' and str2 == '':
        #    return True
        #elif str1 == '' or str2 == '':
        #    return False
        if str1 is None:
            str1 = ''
        if str2 is None:
            str2 = ''
        ## Check if a direct comparison is wished
        flag_compare = False
        if str1.startswith('=='):
            str1 = str1[2:]
            flag_compare = True
        if str2.startswith('=='):
            str2 = str2[2:]
            flag_compare = True

        if (str1 == '*' or str2 == '*') and flag_compare == False:
            return True
        elif str1.startswith(self.__regex_symbol_start) and str1.endswith(self.__regex_symbol_end) and len(str1) > 1:
            if str2.startswith(self.__regex_symbol_start) and str2.endswith(self.__regex_symbol_end):
                return str1 == str2
            else:
                flag_re = re.fullmatch(str1[1:-1], str2) is not None
                return flag_re
        elif str2.startswith(self.__regex_symbol_start) and str2.endswith(self.__regex_symbol_end) and len(str2) > 1:
            flag_re = re.fullmatch(str2[1:-1], str1) is not None
            return flag_re
        else:
            flag_cmp = str1 == str2
            return flag_cmp

    def __repr__(self):
        #astr2 = self.get_str('<key>/<device>:<host>@<addr>')
        astr2 = self.address_str
        astr = "RedvyprAddress('''" + astr2 + "''')"
        return astr

    def __hash__(self):
        astr2 = self.address_str
        astr = "RedvyprAddress('''" + astr2 + "''')"
        return hash(astr)

    def __len__(self):
        return len(self.address_str)

    def __eq__(self, addr):
        """
        Compares a second redvypr_address with this one by comparing the
        address_str, if they are equal the redvypr_addresses are defined as equal.
        If a string is given, the string is compared to self.address_str, otherwise
        False is returned
        Args:
            addr:

        Returns:

        """
        if type(addr) == RedvyprAddress:
            streq = self.address_str == addr.address_str
            return streq
        elif type(addr) == str:
            streq = self.address_str == addr
            return streq
        else:
            return False


    def __contains__(self, data):
        """ Depending on the type of data
        - it checks if address is in data, if data is a redvypr data structure (datapacket)
        - it checks if addresses match between self and data, if data is a redvypr_address
        - it converts a string into a RedvyprAddress and checks if the addresses match
        """
        if isinstance(data, dict): # check if data is a dictionary or an inherited type like redvypr.data_packets.datapacket
            datapacket = data
            deviceflag = self.compare_address_substrings(self.devicename,datapacket['_redvypr']['device'])
            packetidflag = self.compare_address_substrings(self.packetid, datapacket['_redvypr']['packetid'])
            hostflag = self.compare_address_substrings(self.hostname, datapacket['_redvypr']['host']['hostname'])
            addrflag = self.compare_address_substrings(self.addr, datapacket['_redvypr']['host']['addr'])
            uuidflag = self.compare_address_substrings(self.uuid, datapacket['_redvypr']['host']['uuid'])
            pubflag = self.compare_address_substrings(self.publisher, datapacket['_redvypr']['publisher'])
            # Test the comparison
            compareflag = True
            if self.compare is not None:
                if self.compare != '*':
                    evalstr = 'data' + self.compare
                    #print('Evalstr',evalstr)
                    try:
                        compareflag = eval(evalstr)
                        #print('Compareflag',compareflag)
                    except:
                        logger.info('Eval did not work out',exc_info=True)
                        compareflag = False
            #self.compare
            #locpubflag = self.compare_address_substrings(self.uuid, datapacket['_redvypr']['host']['locpub'])
            # Loop over all datakeys in the packet
            if(len(self.datakey) > 0):
                if self.datakey == '*': # always valid
                    pass
                elif len(self.datakey)>1 and self.datakey.startswith(self.__regex_symbol_start) and self.datakey.endswith(self.__regex_symbol_end): # Regular expression
                    for k in datapacket.keys(): # Test every key
                        if self.compare_address_substrings(self.datakey,k):
                            break
                elif (self.datakey in datapacket.keys()): # Datakey (standard) in list of datakeys
                    pass
                elif rtest.match(self.datakey): # check if key is of the form ['TAR'][0] with a regular expression
                    try:
                        evalstr = 'datapacket' + self.datakey
                        data = eval(evalstr, None)
                        #print('data',data)
                    except:
                        #logger.debug('Eval comparison {}'.format(evalstr),exc_info=True)
                        return False

                else:  # If the key does not fit, return False
                    return False

            #if (deviceflag and uuidflag):
            #    return True
            #elif (deviceflag and hostflag and addrflag and uuidflag):
            #    return True
            #elif (deviceflag and uuidflag):
            #    return True

            matchflag3 = deviceflag and hostflag and addrflag and uuidflag and pubflag and compareflag and packetidflag

            return matchflag3

        elif(type(data) == RedvyprAddress):
            addr = data
            # If there is et least one eval address, compare the datakeyentries one by one
            # This is resulting in two list, that are compared element by element
            if self.datakeyeval or addr.datakeyeval:
                datakeyflag = self.get_datakeyentries() == addr.get_datakeyentries()
            else:
                datakeyflag = self.compare_address_substrings(self.datakey, addr.datakey)

            packetidflag = self.compare_address_substrings(self.packetid, addr.packetid)
            deviceflag = self.compare_address_substrings(self.devicename, addr.devicename)
            hostflag = self.compare_address_substrings(self.hostname, addr.hostname)
            addrflag = self.compare_address_substrings(self.addr, addr.addr)
            uuidflag = self.compare_address_substrings(self.uuid, addr.uuid)
            pubflag = self.compare_address_substrings(self.publisher, addr.publisher)
            matchflag3 = datakeyflag and packetidflag and deviceflag and hostflag and addrflag and uuidflag and pubflag

            return matchflag3  # 1 or matchflag2

        # string, convert to RedvyprAddress first
        elif type(data) == str:
            raddr = RedvyprAddress(str(data))
            contains = raddr in self
            return contains
        else:
            raise ValueError('Unknown data type')


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
                lambda instance: instance.address_str
            ),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls, _core_schema: core_schema.CoreSchema, handler: pydantic.GetJsonSchemaHandler
    ) -> pydantic.json_schema.JsonSchemaValue:
        # Use the same schema that would be used for `str`
        return handler(core_schema.str_schema())









