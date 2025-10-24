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
from pydantic import BaseModel, Field, TypeAdapter
from pydantic_core import SchemaSerializer, core_schema

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.redvypr_address')
logger.setLevel(logging.DEBUG)

#metadata_address = '/d:/p:/i:metadata/k:_redvypr_command'
metadata_address = "_redvypr_command@i:metadata"


# redvypr_address.py
import re
import ast
import typing
from typing import Any, List, Tuple, Optional, Union
import pydantic
from pydantic_core import core_schema

# Exceptions
class FilterNoMatch(Exception):
    """Raised when a packet does not match the filter expression."""
    pass

class FilterFieldMissing(Exception):
    """Raised when a required key is missing in the packet."""
    pass


class RedvyprAddress:
    """
    RedvyprAddress parses a string address with optional filters and
    evaluates them against packets (dictionaries).
    """

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

    _REV_PREFIX_MAP = {v: k for k, v in PREFIX_MAP.items()}

    def __init__(
            self,
            expr: Union[str, "RedvyprAddress", dict, None] = None,
            *,
            datakey: Optional[str] = None,
            packetid: Optional[Any] = None,
            devicename: Optional[Any] = None,
            publisher: Optional[Any] = None,
            hostname: Optional[Any] = None,
            uuid: Optional[Any] = None,
            addr: Optional[Any] = None,
            local_hostname: Optional[Any] = None,
            local_uuid: Optional[Any] = None,
            local_addr: Optional[Any] = None,
    ):


        if expr == "":
            expr = None

        self._rhs_parts: List[Tuple[str, Optional[str], Optional[Any], str]] = []

        self.left_expr: Optional[str] = None
        self.right_expr: Optional[str] = None
        self.filter_expr: Optional[str] = None
        self.filter_keys: dict = {}

        if isinstance(expr, RedvyprAddress):
            src: RedvyprAddress = expr
            self.left_expr = src.left_expr
            self.right_expr = src.right_expr
            self.filter_expr = src.filter_expr
            self.filter_keys = {k: list(v) for k, v in src.filter_keys.items()}
            self._rhs_parts = [ (rk, op, val, frag) for (rk, op, val, frag) in getattr(src, "_rhs_parts", []) ]

        if isinstance(expr, dict):
            redvypr = expr.get("_redvypr", {})
            # bekannte Keys direkt mappen
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
                        # Unterkeys host/localhost
                        for subk, prefix in mapping[k].items():
                            if subk in v:
                                self.add_filter(prefix, "eq", v[subk])
                    else:
                        # einfache Key -> Präfix
                        self.add_filter(mapping[k], "eq", v)


        if isinstance(expr, str):
            if "@" in expr:
                left, right = map(str.strip, expr.split("@", 1))
            else:
                left, right = expr.strip(), None

            self.left_expr = left if left else None
            if right:
                right = right.strip()
                self.right_expr = right
                self.filter_expr = self._rewrite_rhs_to_python(right)
                self._rhs_parts.append(("__raw__", None, None, right))
            else:
                self.right_expr = None
                self.filter_expr = None

        if expr is None:
            pass

        if datakey is not None:
            self.left_expr = datakey

        kw_map = [
            ("packetid", packetid),
            ("device", devicename),
            ("publisher", publisher),
            ("hostname", hostname),
            ("uuid", uuid),
            ("address", addr),
            ("localhost.hostname", local_hostname),
            ("localhost.uuid", local_uuid),
            ("localhost.addr", local_addr),
        ]

        for red_key, val in kw_map:
            if val is not None:
                self.add_filter(red_key, "eq", val)

    # -------------------------
    # RHS → Python Expression
    # -------------------------
    def _rewrite_rhs_to_python(self, rhs: str) -> Optional[str]:
        if rhs is None:
            return None
        s = rhs.strip()
        if not s:
            return None

        out = s
        self.filter_keys = {}
        def add_key(key, op): self.filter_keys.setdefault(key, []).append(op)

        def _lit_to_python_local(token: str) -> str:
            return self._lit_to_python(token)

        def _list_to_python_local(content: str) -> str:
            return self._list_to_python(content)

        prefixes = sorted(self.PREFIX_MAP.keys(), key=lambda x: -len(x))
        prefix_group = "|".join([re.escape(p) for p in prefixes])

        def repl_r_list(m):
            add_key(m.group(1), "in")
            return f"_in({repr(m.group(1))},{_list_to_python_local(m.group(2))})"

        def repl_r_regex(m):
            add_key(m.group(1), "regex")
            return f"_regex({repr(m.group(1))},{repr(m.group(2))},{repr(m.group(3) or '')})"

        def repl_r_eq(m):
            add_key(m.group(1), "eq")
            return f"_eq({repr(m.group(1))},{_lit_to_python_local(m.group(2))})"

        def repl_exists(m):
            pref = m.group(1)
            red = self.PREFIX_MAP.get(pref, pref)
            add_key(red, "exists")
            return f"_exists({repr(red)})"

        def repl_pref_list(m):
            pref = m.group(1)
            red = self.PREFIX_MAP.get(pref, pref)
            add_key(red, "in")
            return f"_in({repr(red)},{_list_to_python_local(m.group(2))})"

        def repl_pref_regex(m):
            pref = m.group(1)
            red = self.PREFIX_MAP.get(pref, pref)
            add_key(red, "regex")
            return f"_regex({repr(red)},{repr(m.group(2))},{repr(m.group(3) or '')})"

        def repl_pref_eq(m):
            pref = m.group(1)
            red = self.PREFIX_MAP.get(pref, pref)
            add_key(red, "eq")
            return f"_eq({repr(red)},{_lit_to_python_local(m.group(2))})"

        # r: forms
        out = re.sub(r'r:([A-Za-z0-9_]+):\[((?:[^\]]*))\]', repl_r_list, out)
        out = re.sub(r'r:([A-Za-z0-9_]+):~/(.*?)/([a-zA-Z]*)', repl_r_regex, out)
        out = re.sub(r'r:([A-Za-z0-9_]+):(".*?"|\'.*?\'|[^\s()]+)', repl_r_eq, out)

        # -------------------
        # Fix Existenzprüfung für ALLE Präfixe, auch unbekannte
        exists_pat = re.compile(r'([A-Za-z0-9_]+)\?:')  # <-- fix
        out = exists_pat.sub(lambda m: repl_exists(m), out)

        # Listen, Regex, Eq für bekannte Präfixe
        pref_list_pat = re.compile(rf'({prefix_group}):\[((?:[^\]]*))\]')
        out = pref_list_pat.sub(lambda m: repl_pref_list(m), out)

        pref_regex_pat = re.compile(rf'({prefix_group}):~/(.*?)/([a-zA-Z]*)')
        out = pref_regex_pat.sub(lambda m: repl_pref_regex(m), out)

        pref_eq_pat = re.compile(rf'({prefix_group}):((".*?"|\'.*?\'|[^\s()]+))')
        out = pref_eq_pat.sub(lambda m: repl_pref_eq(m), out)

        return out

    def _lit_to_python(self, token: str) -> str:
        t = str(token).strip()
        if re.fullmatch(r'-?\d+\.\d*', t) or re.fullmatch(r'-?\d+', t):
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

    def _traverse_path(self, root: dict, parts: List[str]):
        cur = root
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return False, None
            cur = cur[p]
        return True, cur

    def _get_val(self, packet, key):
        if packet is None:
            raise FilterFieldMissing(f"_redvypr missing key '{key}'")
        parts = key.split(".") if isinstance(key, str) and "." in key else [key]
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
        parts = key.split(".") if isinstance(key, str) and "." in key else [key]
        if "_redvypr" in packet:
            found, _ = self._traverse_path(packet["_redvypr"], parts)
            if found:
                return True
        found, _ = self._traverse_path(packet, parts)
        return bool(found)

    def matches(self, packet):
        if not self.filter_expr:
            return True
        SAFE_GLOBALS = {"__builtins__": None, "True": True, "False": False, "None": None}
        try:
            return bool(eval(self.filter_expr, SAFE_GLOBALS, self._build_eval_locals(packet)))
        except FilterFieldMissing:
            return False

    def __call__(self, packet):
        """
        Evaluate the left-hand side (LHS) if the filter matches.

        Rules:
        - If both left_expr and filter_expr are None: return the whole packet.
        - If left_expr is present and filter matches: return its value.
        - If left_expr is not present but filter matches: return True.
        - Otherwise, raise FilterNoMatch.

        Missing keys return None and führen ggf. zu TypeError beim Zugriff.
        """

        if self.left_expr is None and self.filter_expr is None:
            return packet

        SAFE_GLOBALS = {"__builtins__": None, "True": True, "False": False, "None": None}

        # locals enthält direkt das Packet
        locals_map = dict(packet)

        # LHS auswerten
        result = None
        if self.left_expr:
            ## Einfachen Key-Check für die oberste Ebene
            top_key = self.left_expr.split("[")[0].split(".")[0]
            if top_key not in packet:
                raise KeyError(f"Key {top_key!r} missing in packet")
            try:
                result = eval(self.left_expr, SAFE_GLOBALS, locals_map)
            except Exception as e:
                raise(e)
                #result = None

        # Filter prüfen
        if self.matches(packet):
            if self.left_expr:
                return result
            else:
                return packet

        raise FilterNoMatch("Packet did not match filter")


    # -------------------------
    # Human-readable RHS helpers
    # -------------------------
    def _make_human_fragment(self, red_key: str, op: str, value: Any) -> str:
        prefix = self._REV_PREFIX_MAP.get(red_key)
        if isinstance(value, str):
            if re.search(r'\s|:|,|\/', value):
                vstr = repr(value)
            else:
                vstr = value
        else:
            vstr = repr(value)
        if prefix:
            return f"{prefix}:{vstr}"
        else:
            return f"r:{red_key}:{vstr}"

    def _rebuild_right_expr_from_parts(self):
        fragments = [frag for (_rk, _op, _val, frag) in self._rhs_parts if frag and frag.strip() != ""]
        self.right_expr = " and ".join(fragments) if fragments else None

    # -------------------------
    # Filter Manipulation
    # -------------------------
    def add_filter(self, key, op, value=None, flags=""):
        op = op.lower()
        red_key = self.PREFIX_MAP.get(key, key) if key is not None else key
        if op == "eq":
            new_py = f"_eq({repr(red_key)},{repr(value)})"
        elif op == "in":
            new_py = f"_in({repr(red_key)},{repr(value if isinstance(value, list) else [value])})"
        elif op == "regex":
            new_py = f"_regex({repr(red_key)},{repr(value)},{repr(flags)})"
        elif op == "exists":
            new_py = f"_exists({repr(red_key)})"
        else:
            raise ValueError(f"Unsupported operation '{op}'")
        if self.filter_expr:
            self.filter_expr = f"({self.filter_expr}) and ({new_py})"
        else:
            self.filter_expr = new_py
        self.filter_keys.setdefault(red_key, []).append(op)
        if op != "exists":
            human_frag = self._make_human_fragment(red_key, op, value)
        else:
            prefix = self._REV_PREFIX_MAP.get(red_key, None)
            human_frag = (prefix + "?:") if prefix else f"r:{red_key}?:"
        self._rhs_parts.append((red_key, op, value, human_frag))
        self._rebuild_right_expr_from_parts()

    def update_filter(self, key, new_value):
        red_key = self.PREFIX_MAP.get(key, key)
        if red_key not in self.filter_keys:
            raise KeyError(f"Filter key {key} not present")
        if self.filter_expr:
            pattern = re.compile(r'(_eq|_in)\(\s*' + re.escape(repr(red_key)) + r'\s*,.*?\)')
            def repl(m):
                func = m.group(1)
                if func == "_eq":
                    return f"_eq({repr(red_key)},{repr(new_value)})"
                elif func == "_in":
                    return f"_in({repr(red_key)},{repr(new_value if isinstance(new_value, list) else [new_value])})"
                return m.group(0)
            self.filter_expr = pattern.sub(repl, self.filter_expr)
        changed = False
        new_parts = []
        for (rk, op, val, frag) in self._rhs_parts:
            if rk == red_key and op in ("eq", "in"):
                new_frag = self._make_human_fragment(rk, op, new_value)
                new_parts.append((rk, op, new_value, new_frag))
                changed = True
            else:
                new_parts.append((rk, op, val, frag))
        if changed:
            self._rhs_parts = new_parts
            self._rebuild_right_expr_from_parts()

    def delete_filter(self, key):
        red_key = self.PREFIX_MAP.get(key, key)
        if red_key not in self.filter_keys:
            raise KeyError(f"Filter key {key} not present")
        pattern = re.compile(r'(_eq|_in|_regex|_exists)\(\s*' + re.escape(repr(red_key)) + r'\s*,?.*?\)')
        expr = pattern.sub("", self.filter_expr or "")
        def clean_expr(e):
            prev = None
            while prev != e:
                prev = e
                e = re.sub(r'\(\s*\)', '', e)
                e = re.sub(r'\(\s*(and|or)\s+', '(', e)
                e = re.sub(r'\s+(and|or)\s*\)', ')', e)
                e = re.sub(r'^\s*(and|or)\s+', '', e)
                e = re.sub(r'\s+(and|or)\s*$', '', e)
                e = re.sub(r'\s+', ' ', e)
            return e.strip()
        self.filter_expr = clean_expr(expr) if expr.strip() else None
        self._rhs_parts = [(rk, op, val, frag) for (rk, op, val, frag) in self._rhs_parts if rk != red_key]
        self._rebuild_right_expr_from_parts()
        self.filter_keys.pop(red_key, None)

    def add_datakey(self, datakey: str, overwrite: bool = True):
        """
        Adds or replaces the left-hand expression (datakey) of the address.

        Args:
            datakey: The new left-hand expression (e.g., a path or key in the packet).
            overwrite: If False, the datakey is only set if none exists yet.

        Raises:
            ValueError: If the datakey contains an '@' character.
        """
        if "@" in datakey:
            raise ValueError("datakey must not contain '@'.")

        if self.left_expr is None or overwrite:
            self.left_expr = datakey

    def delete_datakey(self):
        """
        Removes the left-hand expression (datakey) from the address.
        After deletion, the address will only contain the filter part (if any).
        """
        self.left_expr = None

    # -------------------------
    # Filter extraction / subset
    # -------------------------
    def extract(self, keys: Union[str, List[str]], string_only: bool = False):
        """
        Return a new RedvyprAddress (or just RHS string) containing only filters
        for the given prefixes (e.g. 'i,d,u,al').

        This preserves the logical structure of AND/OR expressions.

        Args:
            keys: Comma-separated string or list of filter prefixes to keep.
            string_only: If True, return only RHS string, else a new RedvyprAddress.
        """


        if isinstance(keys, str):
            wanted = [k.strip() for k in keys.split(",") if k.strip()]
        else:
            wanted = [k.strip() for k in keys if k.strip()]

        print("wanted",wanted)
        if "k" in wanted:
            left_expr = self.left_expr
        else:
            left_expr = None

        print("Left expr",left_expr)

        # mapping prefix → red_key
        allowed_red_keys = {
            self.PREFIX_MAP.get(k, k)
            for k in wanted
        }

        if not self.filter_expr:
            return "" if string_only else RedvyprAddress(self.left_expr or None)

        # Parse filter_expr AST
        tree = ast.parse(self.filter_expr, mode="eval")

        def is_wanted_call(node: ast.AST) -> bool:
            """Check if this is a function call with a desired key."""
            if isinstance(node, ast.Call) and len(node.args) >= 1:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and arg.value in allowed_red_keys:
                    return True
            return False

        def prune(node: ast.AST) -> Optional[ast.AST]:
            """Recursively remove unwanted subtrees."""
            if isinstance(node, ast.BoolOp):
                # process all sub-nodes
                new_vals = [prune(v) for v in node.values]
                new_vals = [v for v in new_vals if v is not None]
                if not new_vals:
                    return None
                if len(new_vals) == 1:
                    return new_vals[0]
                node.values = new_vals
                return node
            elif isinstance(node, ast.UnaryOp):
                new_operand = prune(node.operand)
                if new_operand is None:
                    return None
                node.operand = new_operand
                return node
            elif isinstance(node, ast.BinOp):
                left = prune(node.left)
                right = prune(node.right)
                if left is None and right is None:
                    return None
                if left is None:
                    return right
                if right is None:
                    return left
                node.left = left
                node.right = right
                return node
            elif isinstance(node, ast.Compare):
                return node  # should not occur, but just keep
            elif isinstance(node, ast.Call):
                # function call like _eq('packetid', 'x')
                if is_wanted_call(node):
                    return node
                return None
            elif isinstance(node, ast.Constant):
                return node
            elif isinstance(node, ast.Expr):
                val = prune(node.value)
                if val is None:
                    return None
                node.value = val
                return node
            elif isinstance(node, ast.Expression):
                val = prune(node.body)
                if val is None:
                    return None
                node.body = val
                return node
            else:
                return node

        new_tree = prune(tree)
        if new_tree is None:
            return "" if string_only else RedvyprAddress(self.left_expr or None)

        new_rhs = ast.unparse(new_tree.body)

        # Optional: beautify logical operators for readability
        # (convert _eq() etc. back to prefixes)
        # For now: reuse existing human fragments if available
        new_rhs_human = []
        for (rk, op, val, frag) in self._rhs_parts:
            if rk in allowed_red_keys:
                new_rhs_human.append(frag)
        rhs_str = " and ".join(new_rhs_human) if new_rhs_human else ""

        if string_only:
            if left_expr is not None:
                return f"{left_expr}@{rhs_str}" if rhs_str else ""
            else:
                return f"@{rhs_str}" if rhs_str else ""

        # Return new RedvyprAddress
        new_addr = RedvyprAddress()
        new_addr.left_expr = left_expr
        new_addr.filter_expr = new_rhs
        new_addr.right_expr = rhs_str
        new_addr._rhs_parts = [
            (rk, op, val, frag)
            for (rk, op, val, frag) in self._rhs_parts
            if rk in allowed_red_keys
        ]
        new_addr.filter_keys = {
            k: v for k, v in self.filter_keys.items() if k in allowed_red_keys
        }
        return new_addr

    def get_str(self, keys: Union[str, List[str]]):
        return self.extract(keys,string_only=True)
    # -------------------------
    # Address string / __repr__
    # -------------------------
    def _filter_expr_to_rhs(self):
        return self.right_expr

    def to_address_string(self):
        left = self.left_expr if self.left_expr else ""
        right = self._filter_expr_to_rhs() if self.filter_expr else self.right_expr
        return f"{left}@{right}" if right else left or "@"

    def to_redvypr_dict(self) -> dict:
        """
        Reconstructs a minimal `_redvypr` dictionary from the stored filters.
        Only equality ("eq") and membership ("in") filters can be represented
        as actual data fields in a packet structure.

        Returns:
            dict: A dictionary of the form {"_redvypr": {...}} suitable for use
                  as the _redvypr section of a packet.
        """
        result = {}

        for (red_key, op, value, _frag) in self._rhs_parts:
            # Only EQ and IN operations represent real data values
            # Regex or existence checks cannot be inserted into a packet meaningfully
            if op not in ("eq", "in"):
                continue

            # Example red_key formats:
            #   "publisher"
            #   "device"
            #   "host.uuid"
            # We support hierarchical structures by splitting on "."
            parts = red_key.split(".")
            cur = result
            # Build nested dictionaries if needed
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})

            # For IN filters we store the list, for EQ a simple scalar
            if op == "eq":
                cur[parts[-1]] = value
            else:  # op == "in"
                cur[parts[-1]] = value if isinstance(value, list) else [value]

        return {"_redvypr": result}


    def __repr__(self):
        return self.to_address_string()

    # Merge kurz + lang in __getattr__
    def __getattr__(self, name):

        # Prüfe Kurz-Form
        if name in self.PREFIX_MAP:
            red_key = self.PREFIX_MAP[name]
        # Prüfe Lang-Form
        elif name in self.LONGFORM_MAP:
            red_key = self.LONGFORM_MAP[name]
        else:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

        filter_keys = self.__dict__.get("filter_keys", {})
        filter_expr = self.__dict__.get("filter_expr", "")
        if not filter_expr or red_key not in filter_keys:
            return None

        values = []

        # _eq pattern
        eq_pattern = re.compile(r"_eq\(\s*'{}'\s*,\s*(.*?)\s*\)".format(re.escape(red_key)))
        for m in eq_pattern.finditer(filter_expr):
            val = m.group(1)
            try:
                val_eval = eval(val)
            except Exception:
                val_eval = val
            values.append(val_eval)

        # _in pattern
        in_pattern = re.compile(r"_in\(\s*'{}'\s*,\s*(.*?)\s*\)".format(re.escape(red_key)))
        for m in in_pattern.finditer(filter_expr):
            val = m.group(1)
            try:
                val_eval = eval(val)
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

    # -------------------------
    # Pydantic integration (unchanged)
    # -------------------------
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: typing.Any,
        _handler: pydantic.GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        """
        Pydantic core schema so that:
        - strings are parsed into RedvyprAddress instances
        - RedvyprAddress instances are passed through
        - serialization returns a str (human-readable)
        """
        def validate_from_str(value: str) -> "RedvyprAddress":
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



# =========================
# RedvyprAddress
# =========================
class RedvyprAddress_legacy3:
    """
    RedvyprAddress parses a string address with optional filters and
    evaluates them against packets (dictionaries).

    Initialization modes:
    - RedvyprAddress("data[::-1] @ i:test")        # parse expr string
    - RedvyprAddress()                            # empty -> returns whole packet
    - RedvyprAddress(existing_addr)               # copy constructor
    - RedvyprAddress(datakey="data", packetid="test", devicename="cam")
                                                  # build from kwargs (eq-only)

    Notes:
    - expr == "" is treated like expr is None
    - datakey replaces the LHS always (even if expr had one)
    - RHS (filters) are stored human-readable (e.g. "i:test and d:cam")
      in self.right_expr and as python expression in self.filter_expr.
    """

    # Mapping of single-character prefixes to internal keys
    PREFIX_MAP = {"i": "packetid", "a": "address", "p": "publisher", "d": "device", "u": "uuid", "h": "hostname"}
    SINGLE_PREFIXES = set(PREFIX_MAP.keys())

    # Reverse mapping (internal key -> prefix char), useful when building human-readable RHS
    _REV_PREFIX_MAP = {v: k for k, v in PREFIX_MAP.items()}

    def __init__(
        self,
        expr: Union[str, "RedvyprAddress", dict, None] = None,
        *,
        datakey: Optional[str] = None,
        packetid: Optional[Any] = None,
        devicename: Optional[Any] = None,
        publisher: Optional[Any] = None,
        hostname: Optional[Any] = None,
        uuid: Optional[Any] = None,
        addr: Optional[Any] = None,
        compare: Optional[Any] = None,
    ):
        """
        Flexible constructor:

        - If expr is a RedvyprAddress -> copy constructor.
        - If expr is a string -> parse LHS and RHS; RHS converted to python filter_expr
          and right_expr is set to a human-readable version (initially the raw RHS).
        - If expr is None or "" -> empty address (no LHS, no RHS).
        - Keyword args (packetid/devicename/...) are appended as eq-filters (and preserve insertion order).
        - datakey always overwrites LHS if provided.
        """
        # Normalize empty string to None
        if expr == "":
            expr = None

        # Initialize RHS parts list that we maintain in insertion order.
        # Each element is a tuple: (red_key, op, value, human_fragment)
        # - red_key: internal key name (e.g. "packetid", "device") or "__raw__" for raw RHS chunk
        # - op: "eq", "in", "regex", "exists" or None for raw
        # - value: the provided value
        # - human_fragment: string like "i:test" or raw chunk
        self._rhs_parts: List[Tuple[str, Optional[str], Optional[Any], str]] = []

        # Default state
        self.left_expr: Optional[str] = None
        self.right_expr: Optional[str] = None    # human-readable RHS
        self.filter_expr: Optional[str] = None   # python-evaluable RHS
        self.filter_keys: dict = {}

        # Copy-constructor: clone internal state
        if isinstance(expr, RedvyprAddress):
            src: RedvyprAddress = expr
            self.left_expr = src.left_expr
            self.right_expr = src.right_expr
            self.filter_expr = src.filter_expr
            # shallow copy is fine for lists/dicts; keep independent structures
            self.filter_keys = {k: list(v) for k, v in src.filter_keys.items()}
            self._rhs_parts = [ (rk, op, val, frag) for (rk, op, val, frag) in getattr(src, "_rhs_parts", []) ]


        if isinstance(expr, dict):
            # Initialize from a packet dict
            redvypr = expr.get("_redvypr", {})
            for key, val in redvypr.items():
                # Only use known filter keys
                if key in self.PREFIX_MAP.values():
                    self.add_filter(key, "eq", val)


        # If expr is a string, parse into LHS and RHS first
        if isinstance(expr, str):
            if "@" in expr:
                left, right = map(str.strip, expr.split("@", 1))
            else:
                left, right = expr.strip(), None

            self.left_expr = left if left else None
            # If there is an RHS in the string, keep its raw human-readable form as a single chunk
            if right:
                right = right.strip()
                self.right_expr = right
                # Convert RHS to python filter expression (this also populates filter_keys)
                self.filter_expr = self._rewrite_rhs_to_python(right)
                # Keep the original RHS as a raw chunk so we don't try to re-parse it later
                self._rhs_parts.append(("__raw__", None, None, right))
            else:
                self.right_expr = None
                self.filter_expr = None

        # If expr is None -> empty initialization (do nothing more)
        if expr is None:
            # handle datakey and kwargs below (they may add stuff)
            pass

        # Now handle keyword parameters (they are always appended as eq filters).
        # datakey is special: it always replaces LHS if provided.
        # The rest produce eq-filters in insertion order.
        if datakey is not None:
            # datakey always replaces LHS (explicit user choice)
            self.left_expr = datakey

        # Helper to add keyword filters in the right mapping
        kw_map = [
            ("packetid", packetid),
            ("device", devicename),
            ("publisher", publisher),
            ("hostname", hostname),
            ("uuid", uuid),
            ("address", addr),
        ]
        for red_key, val in kw_map:
            if val is not None:
                # add_filter knows how to update both filter_expr (python) and _rhs_parts
                self.add_filter(red_key, "eq", val)

        # optional 'compare' parameter is not explicitly used in your previous code;
        # if you want it treated as e.g. additional LHS or RHS, you can extend here.
        # For now we'll ignore `compare` if present (keeps backward compatibility).

    # -------------------------
    # RHS → Python Expression
    # -------------------------
    def _rewrite_rhs_to_python(self, rhs: str) -> Optional[str]:
        """
        Convert RHS filter string into a Python-evaluable expression.
        Populates self.filter_keys with operations per key.

        We do NOT try to normalize the human-readable RHS here; we just build the
        Python expression used for evaluation. The human-readable RHS is kept in
        self._rhs_parts (initially as a raw chunk).
        """
        if rhs is None:
            return None
        s = rhs.strip()
        if not s:
            return None

        out = s
        self.filter_keys = {}
        def add_key(key, op): self.filter_keys.setdefault(key, []).append(op)

        # Replacement functions for regex substitution
        def repl_r_list(m):
            add_key(m.group(1), "in")
            return f"_in({repr(m.group(1))},{self._list_to_python(m.group(2))})"

        def repl_r_regex(m):
            add_key(m.group(1), "regex")
            return f"_regex({repr(m.group(1))},{repr(m.group(2))},{repr(m.group(3) or '')})"

        def repl_r_eq(m):
            add_key(m.group(1), "eq")
            return f"_eq({repr(m.group(1))},{self._lit_to_python(m.group(2))})"

        def repl_exists(m):
            add_key(self.PREFIX_MAP[m.group(1)], "exists")
            return f"_exists({repr(self.PREFIX_MAP[m.group(1)])})"

        def repl_s_list(m):
            add_key(self.PREFIX_MAP[m.group(1)], "in")
            return f"_in({repr(self.PREFIX_MAP[m.group(1)])},{self._list_to_python(m.group(2))})"

        def repl_s_regex(m):
            add_key(self.PREFIX_MAP[m.group(1)], "regex")
            return f"_regex({repr(self.PREFIX_MAP[m.group(1)])},{repr(m.group(2))},{repr(m.group(3) or '')})"

        def repl_s_eq(m):
            add_key(self.PREFIX_MAP[m.group(1)], "eq")
            return f"_eq({repr(self.PREFIX_MAP[m.group(1)])},{self._lit_to_python(m.group(2))})"

        # Apply replacements in a careful order
        out = re.sub(r'r:([A-Za-z0-9_]+):\[((?:[^\]]*))\]', repl_r_list, out)
        out = re.sub(r'r:([A-Za-z0-9_]+):~/(.*?)/([a-zA-Z]*)', repl_r_regex, out)
        out = re.sub(r'r:([A-Za-z0-9_]+):(".*?"|\'.*?\'|[^\s()]+)', repl_r_eq, out)
        out = re.sub(r'([{}])\?:'.format(''.join(self.SINGLE_PREFIXES)), repl_exists, out)
        out = re.sub(r'([{}]):\[((?:[^\]]*))\]'.format(''.join(self.SINGLE_PREFIXES)), repl_s_list, out)
        out = re.sub(r'([{}]):~/(.*?)/([a-zA-Z]*)'.format(''.join(self.SINGLE_PREFIXES)), repl_s_regex, out)
        out = re.sub(r'([{}]):(".*?"|\'.*?\'|[^\s()]+)'.format(''.join(self.SINGLE_PREFIXES)), repl_s_eq, out)
        return out

    def _lit_to_python(self, token: str) -> str:
        """Convert literal string or number to Python format."""
        t = str(token).strip()
        if re.fullmatch(r'-?\d+\.\d*', t) or re.fullmatch(r'-?\d+', t):
            return t
        return repr(t)

    def _list_to_python(self, content: str) -> str:
        """Convert a comma-separated string into a Python list."""
        parts = [p.strip() for p in content.split(",")] if content.strip() else []
        return "[" + ",".join([self._lit_to_python(p) for p in parts]) + "]"

    # -------------------------
    # Eval helpers
    # -------------------------
    def _build_eval_locals(self, packet: dict):
        """
        Build local variables for evaluating the filter expression.
        Provides _eq, _in, _regex, _exists functions.
        """
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
            locals_map.update({k: v for k, v in packet.items() if k not in locals_map})
        return locals_map

    def _get_val(self, packet, key):
        """Retrieve value from _redvypr or packet."""
        if "_redvypr" in packet and key in packet["_redvypr"]:
            return packet["_redvypr"][key]
        if key in packet:
            return packet[key]
        raise FilterFieldMissing(f"_redvypr missing key '{key}'")

    def _exists_val(self, packet, key):
        """Check if key exists in packet or _redvypr."""
        return ("_redvypr" in packet and key in packet["_redvypr"]) or key in packet

    # -------------------------
    # Matching and calling
    # -------------------------
    def matches(self, packet):
        """Return True if packet matches filter. If no filter_expr -> True."""
        if not self.filter_expr:
            return True
        SAFE_GLOBALS = {"__builtins__": None, "True": True, "False": False, "None": None}
        return bool(eval(self.filter_expr, SAFE_GLOBALS, self._build_eval_locals(packet)))

    def __call__(self, packet):
        """
        Evaluate LHS if filter matches.
        - If both left_expr and filter_expr are None: return whole packet.
        - If left_expr is present and filter matches: evaluate and return its value.
        - If left_expr is not present but filter matches: return True.
        - Otherwise raise FilterNoMatch.
        """
        if self.left_expr is None and self.filter_expr is None:
            return packet

        SAFE_GLOBALS = {"__builtins__": None, "True": True, "False": False, "None": None}
        locals_map = {"packet": packet, **(packet or {})}
        result = eval(self.left_expr, SAFE_GLOBALS, locals_map) if self.left_expr else None
        if self.matches(packet):
            return result if self.left_expr else True
        raise FilterNoMatch("Packet did not match filter")

    # -------------------------
    # Human-readable RHS helpers
    # -------------------------
    def _make_human_fragment(self, red_key: str, op: str, value: Any) -> str:
        """
        Build a human-readable fragment like "i:test" or "r:location:lab1"
        Only eq is currently supported for keyword initialization / add_filter.
        """
        prefix = self._REV_PREFIX_MAP.get(red_key)
        # Choose representation for value: prefer bare token for simple strings/numbers
        if isinstance(value, str):
            # if contains whitespace or special chars, use quoted repr to be safe
            if re.search(r'\s|:|,|\/', value):
                vstr = repr(value)
            else:
                vstr = value
        else:
            vstr = repr(value)
        if prefix:
            return f"{prefix}:{vstr}"
        else:
            # use r: for non-standard keys
            return f"r:{red_key}:{vstr}"

    def _rebuild_right_expr_from_parts(self):
        """
        Rebuild human-readable self.right_expr from internal _rhs_parts (in insertion order).
        Simple join with " and " (Variant A from your request).
        """
        fragments = [frag for (_rk, _op, _val, frag) in self._rhs_parts if frag and frag.strip() != ""]
        self.right_expr = " and ".join(fragments) if fragments else None

    # -------------------------
    # Filter Manipulation
    # -------------------------
    def add_filter(self, key, op, value=None, flags=""):
        """
        Add a new filter dynamically.

        - key: internal key name (e.g. "device") or a prefix char (e.g. "d")
               If a prefix char is given and exists in PREFIX_MAP, it will be mapped.
        - op: "eq", "in", "regex", "exists"  (we support eq/in/regex/exists in python part)
        - value: value for eq/in/regex
        - flags: regex flags for regex op
        """
        op = op.lower()
        # allow passing single-char prefix as key too
        red_key = self.PREFIX_MAP.get(key, key) if key is not None else key

        # Build python-side fragment
        if op == "eq":
            new_py = f"_eq({repr(red_key)},{repr(value)})"
        elif op == "in":
            # ensure list
            new_py = f"_in({repr(red_key)},{repr(value if isinstance(value, list) else [value])})"
        elif op == "regex":
            new_py = f"_regex({repr(red_key)},{repr(value)},{repr(flags)})"
        elif op == "exists":
            new_py = f"_exists({repr(red_key)})"
        else:
            raise ValueError(f"Unsupported operation '{op}'")

        # Update python filter_expr (combine with existing using and)
        if self.filter_expr:
            self.filter_expr = f"({self.filter_expr}) and ({new_py})"
        else:
            self.filter_expr = new_py

        # Update filter_keys
        self.filter_keys.setdefault(red_key, []).append(op)

        # Build and append human-readable fragment (we track it in _rhs_parts)
        human_frag = self._make_human_fragment(red_key, op, value) if op != "exists" else (self._REV_PREFIX_MAP.get(red_key, f"r:{red_key}")+"?:")
        self._rhs_parts.append((red_key, op, value, human_frag))
        # Rebuild the visible right_expr
        self._rebuild_right_expr_from_parts()

    def update_filter(self, key, new_value):
        """
        Update all _eq/_in occurrences for a given key in the python expression,
        and update human-readable RHS fragments we own (but not raw chunks).
        """
        red_key = self.PREFIX_MAP.get(key, key)
        if red_key not in self.filter_keys:
            raise KeyError(f"Filter key {key} not present")

        # Update python _eq/_in occurrences
        pattern = re.compile(r'(_eq|_in)\(\s*' + re.escape(repr(red_key)) + r'\s*,.*?\)')
        def repl(m):
            func = m.group(1)
            if func == "_eq":
                return f"_eq({repr(red_key)},{repr(new_value)})"
            elif func == "_in":
                return f"_in({repr(red_key)},{repr(new_value if isinstance(new_value, list) else [new_value])})"
            return m.group(0)
        self.filter_expr = pattern.sub(repl, self.filter_expr) if self.filter_expr else None

        # Update human-readable parts we created (do NOT touch raw chunks)
        changed = False
        new_parts = []
        for (rk, op, val, frag) in self._rhs_parts:
            if rk == red_key and op in ("eq", "in"):
                new_frag = self._make_human_fragment(rk, op, new_value)
                new_parts.append((rk, op, new_value, new_frag))
                changed = True
            else:
                new_parts.append((rk, op, val, frag))
        if changed:
            self._rhs_parts = new_parts
            self._rebuild_right_expr_from_parts()

    def delete_filter(self, key):
        """
        Delete filter conditions for a given key.
        Removes python-side occurrences (_eq/_in/_regex/_exists) and
        removes any human-readable parts we own for that key.
        """
        red_key = self.PREFIX_MAP.get(key, key)
        if red_key not in self.filter_keys:
            raise KeyError(f"Filter key {key} not present")

        # Remove python function occurrences
        pattern = re.compile(r'(_eq|_in|_regex|_exists)\(\s*' + re.escape(repr(red_key)) + r'\s*,?.*?\)')
        expr = pattern.sub("", self.filter_expr or "")

        # Clean up dangling operators and empty parentheses (robust loop)
        def clean_expr(e):
            prev = None
            while prev != e:
                prev = e
                e = re.sub(r'\(\s*\)', '', e)
                e = re.sub(r'\(\s*(and|or)\s+', '(', e)
                e = re.sub(r'\s+(and|or)\s*\)', ')', e)
                e = re.sub(r'^\s*(and|or)\s+', '', e)
                e = re.sub(r'\s+(and|or)\s*$', '', e)
                e = re.sub(r'\s+', ' ', e)
            return e.strip()

        self.filter_expr = clean_expr(expr) if expr.strip() else None

        # Remove human-readable parts we own (leave raw chunks untouched)
        self._rhs_parts = [(rk, op, val, frag) for (rk, op, val, frag) in self._rhs_parts if rk != red_key]

        # Rebuild visible RHS
        self._rebuild_right_expr_from_parts()

        # Remove from filter_keys
        self.filter_keys.pop(red_key, None)

    # -------------------------
    # Address string / __repr__
    # -------------------------
    def _filter_expr_to_rhs(self):
        """
        Convert existing python filter_expr back to a best-effort human-readable RHS.
        We prefer to show the already-built right_expr (which we maintain),
        otherwise return None.
        """
        return self.right_expr

    def to_address_string(self):
        """Rebuild the original address string from LHS and RHS (human-readable)."""
        left = self.left_expr if self.left_expr else ""
        right = self._filter_expr_to_rhs() if self.filter_expr else self.right_expr
        return f"{left}@{right}" if right else left or "@"

    def __repr__(self):
        return self.to_address_string()

    def __getattr__(self, name):
        """
        Dynamic attribute access for PREFIX_MAP keys and their target values.
        Returns filter values if present, else None.
        """
        # Determine the redvypr key
        if name in self.PREFIX_MAP:
            red_key = self.PREFIX_MAP[name]
        elif name in self.PREFIX_MAP.values():
            red_key = name
        else:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

        filter_keys = self.__dict__.get("filter_keys", {})
        filter_expr = self.__dict__.get("filter_expr", "")
        if not filter_expr or red_key not in filter_keys:
            return None

        pattern = re.compile(r"_eq\(\s*'{}'\s*,\s*(.*?)\s*\)".format(re.escape(red_key)))
        values = []
        for m in pattern.finditer(filter_expr):
            val = m.group(1)
            try:
                val_eval = eval(val)
            except Exception:
                val_eval = val
            values.append(val_eval)

        if len(values) == 1:
            return values[0]
        elif values:
            return values
        else:
            return None


    # -------------------------
    # Pydantic integration (unchanged)
    # -------------------------
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: typing.Any,
        _handler: pydantic.GetCoreSchemaHandler,
    ) -> core_schema.CoreSchema:
        """
        Pydantic core schema so that:
        - strings are parsed into RedvyprAddress instances
        - RedvyprAddress instances are passed through
        - serialization returns a str (human-readable)
        """
        def validate_from_str(value: str) -> "RedvyprAddress":
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


class RedvyprAddress_legacy2:
    """
    RedvyprAddress parses a string address with optional filters and
    evaluates them against packets (dictionaries).

    Examples:

    >>> pkt = {"_redvypr": {"packetid": "test", "device": "cam"}, "data": [1,2,3]}
    >>> addr = RedvyprAddress("data[::-1] @ i:test")
    >>> addr.matches(pkt)
    True
    >>> addr(pkt)
    [3, 2, 1]

    Dynamic filter manipulation:

    >>> addr = RedvyprAddress("@i:test")
    >>> addr.add_filter("device", "eq", "cam")
    >>> addr.matches(pkt)
    True
    >>> addr.delete_filter("device")
    >>> addr.matches(pkt)
    True
    """

    PREFIX_MAP = {"i": "packetid", "a": "address", "p": "publisher", "d": "device", "u": "uuid", "h": "hostname"}
    SINGLE_PREFIXES = set(PREFIX_MAP.keys())

    def __init__(self, expr: typing.Union[str, "RedvyprAddress",None]):
        print("EXPR",expr)
        if expr is None:
            # Empty init
            self.left_expr = None
            self.right_expr = None
            self.filter_expr = None
            self.filter_keys = {}
            return

        if isinstance(expr, RedvyprAddress):
            self.left_expr = expr.left_expr
            self.right_expr = expr.right_expr
            self.filter_expr = expr.filter_expr
            self.filter_keys = expr.filter_keys.copy()
            return
        """Initialize from a string like 'data @ i:test'."""
        if "@" in expr:
            left, right = map(str.strip, expr.split("@", 1))
        else:
            left, right = expr.strip(), None

        self.left_expr = left if left else None
        self.right_expr = right if right else None
        self.filter_keys = {}  # Tracks keys in filter
        self.filter_expr = self._rewrite_rhs_to_python(right) if right else None

    # -------------------------
    # RHS → Python Expression
    # -------------------------
    def _rewrite_rhs_to_python(self, rhs: str):
        """
        Convert RHS filter string into Python expression.
        Populates self.filter_keys with operations per key.

        Examples:

        >>> RedvyprAddress("data @ i:[test,foo]").filter_expr
        "_in('packetid',['test','foo'])"
        """
        if rhs is None: return None
        s = rhs.strip()
        if not s: return None
        out = s
        self.filter_keys = {}

        def add_key(key, op):
            self.filter_keys.setdefault(key, []).append(op)

        # Replacement functions for regex substitution
        def repl_r_list(m):
            add_key(m.group(1), "in")
            return f"_in({repr(m.group(1))},{self._list_to_python(m.group(2))})"

        def repl_r_regex(m):
            add_key(m.group(1), "regex")
            return f"_regex({repr(m.group(1))},{repr(m.group(2))},{repr(m.group(3) or '')})"

        def repl_r_eq(m):
            add_key(m.group(1), "eq")
            return f"_eq({repr(m.group(1))},{self._lit_to_python(m.group(2))})"

        def repl_exists(m):
            add_key(self.PREFIX_MAP[m.group(1)], "exists")
            return f"_exists({repr(self.PREFIX_MAP[m.group(1)])})"

        def repl_s_list(m):
            add_key(self.PREFIX_MAP[m.group(1)], "in")
            return f"_in({repr(self.PREFIX_MAP[m.group(1)])},{self._list_to_python(m.group(2))})"

        def repl_s_regex(m):
            add_key(self.PREFIX_MAP[m.group(1)], "regex")
            return f"_regex({repr(self.PREFIX_MAP[m.group(1)])},{repr(m.group(2))},{repr(m.group(3) or '')})"

        def repl_s_eq(m):
            add_key(self.PREFIX_MAP[m.group(1)], "eq")
            return f"_eq({repr(self.PREFIX_MAP[m.group(1)])},{self._lit_to_python(m.group(2))})"

        # Apply regex replacements
        out = re.sub(r'r:([A-Za-z0-9_]+):\[((?:[^\]]*))\]', repl_r_list, out)
        out = re.sub(r'r:([A-Za-z0-9_]+):~/(.*?)/([a-zA-Z]*)', repl_r_regex, out)
        out = re.sub(r'r:([A-Za-z0-9_]+):(".*?"|\'.*?\'|[^\s()]+)', repl_r_eq, out)
        out = re.sub(r'([{}])\?:'.format(''.join(self.SINGLE_PREFIXES)), repl_exists, out)
        out = re.sub(r'([{}]):\[((?:[^\]]*))\]'.format(''.join(self.SINGLE_PREFIXES)), repl_s_list, out)
        out = re.sub(r'([{}]):~/(.*?)/([a-zA-Z]*)'.format(''.join(self.SINGLE_PREFIXES)), repl_s_regex, out)
        out = re.sub(r'([{}]):(".*?"|\'.*?\'|[^\s()]+)'.format(''.join(self.SINGLE_PREFIXES)), repl_s_eq, out)
        return out

    def _lit_to_python(self, token: str):
        """Convert literal string or number to Python format."""
        t = str(token).strip()
        if re.fullmatch(r'-?\d+\.\d*', t) or re.fullmatch(r'-?\d+', t):
            return t
        return repr(t)

    def _list_to_python(self, content: str):
        """Convert a comma-separated string into a Python list."""
        parts = [p.strip() for p in content.split(",")] if content.strip() else []
        return "[" + ",".join([self._lit_to_python(p) for p in parts]) + "]"

    # -------------------------
    # Eval helpers
    # -------------------------
    def _build_eval_locals(self, packet: dict):
        """
        Build local variables for evaluating the filter expression.
        Provides _eq, _in, _regex, _exists functions.
        """
        locals_map = {}

        def _eq(k, v):
            return self._get_val(packet, k) == v

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

        locals_map.update({
            "_eq": _eq, "_in": _in, "_regex": _regex, "_exists": _exists, "packet": packet
        })
        if isinstance(packet, dict):
            locals_map["_redvypr"] = packet.get("_redvypr")
            locals_map.update({k: v for k, v in packet.items() if k not in locals_map})
        return locals_map

    def _get_val(self, packet, key):
        """Retrieve value from _redvypr or packet."""
        if "_redvypr" in packet and key in packet["_redvypr"]:
            return packet["_redvypr"][key]
        if key in packet:
            return packet[key]
        raise FilterFieldMissing(f"_redvypr missing key '{key}'")

    def _exists_val(self, packet, key):
        """Check if key exists in packet or _redvypr."""
        return ("_redvypr" in packet and key in packet["_redvypr"]) or key in packet

    # -------------------------
    # Matching and calling
    # -------------------------
    def matches(self, packet):
        """Return True if packet matches filter."""
        if not self.filter_expr: return True
        SAFE_GLOBALS = {"__builtins__": None, "True": True, "False": False, "None": None}
        return bool(eval(self.filter_expr, SAFE_GLOBALS, self._build_eval_locals(packet)))

    def __call__(self, packet):
        """
               Evaluate LHS if filter matches.
               - If no LHS, return True if filter matches.
               - If empty initialization and no filter, return whole packet.
               - Raises FilterNoMatch otherwise.
        """
        if self.left_expr is None and self.filter_expr is None:
            # Empty object returns full packet
            return packet
        SAFE_GLOBALS = {"__builtins__": None, "True": True, "False": False, "None": None}
        locals_map = {"packet": packet, **(packet or {})}
        result = eval(self.left_expr, SAFE_GLOBALS, locals_map) if self.left_expr else None
        if self.matches(packet):
            return result if self.left_expr else True
        raise FilterNoMatch("Packet did not match filter")

    # -------------------------
    # Dynamic filter manipulation
    # -------------------------
    def add_filter(self, key, op, value=None, flags=""):
        """Add a new filter dynamically. Examples:

        >>> addr = RedvyprAddress("@i:test")
        >>> addr.add_filter("device","eq","cam")
        """
        op = op.lower()
        red_key = self.PREFIX_MAP.get(key, key)
        if op == "eq":
            new_filter = f"_eq({repr(red_key)},{repr(value)})"
        elif op == "in":
            new_filter = f"_in({repr(red_key)},{repr(value if isinstance(value, list) else [value])})"
        elif op == "regex":
            new_filter = f"_regex({repr(red_key)},{repr(value)},{repr(flags)})"
        elif op == "exists":
            new_filter = f"_exists({repr(red_key)})"
        else:
            raise ValueError(f"Unsupported operation '{op}'")
        self.filter_expr = f"({self.filter_expr}) and ({new_filter})" if self.filter_expr else new_filter
        self.filter_keys.setdefault(red_key, []).append(op)

    def update_filter(self, key, new_value):
        """Update _eq/_in filters for a given key.

        >>> addr.update_filter("device","gps")
        """
        red_key = self.PREFIX_MAP.get(key, key)
        if red_key not in self.filter_keys:
            raise KeyError(f"Filter key {key} not present")
        pattern = re.compile(r'(_eq|_in)\(\s*' + re.escape(repr(red_key)) + r'\s*,.*?\)')

        def repl(m):
            func = m.group(1)
            if func == "_eq":
                return f"_eq({repr(red_key)},{repr(new_value)})"
            elif func == "_in":
                return f"_in({repr(red_key)},{repr(new_value if isinstance(new_value, list) else [new_value])})"

        self.filter_expr = pattern.sub(repl, self.filter_expr)

    def delete_filter(self, key):
        """Delete filter for a key and clean dangling operators.

        >>> addr.delete_filter("device")
        """
        red_key = self.PREFIX_MAP.get(key, key)
        if red_key not in self.filter_keys:
            raise KeyError(f"Filter key {key} not present")
        pattern = re.compile(r'(_eq|_in|_regex|_exists)\(\s*' + re.escape(repr(red_key)) + r'\s*,?.*?\)')
        expr = pattern.sub("", self.filter_expr)

        # Clean empty parentheses and dangling AND/OR
        def clean_expr(e):
            prev = None
            while prev != e:
                prev = e
                e = re.sub(r'\(\s*\)', '', e)
                e = re.sub(r'\(\s*(and|or)\s+', '(', e)
                e = re.sub(r'\s+(and|or)\s*\)', ')', e)
                e = re.sub(r'^\s*(and|or)\s+', '', e)
                e = re.sub(r'\s+(and|or)\s*$', '', e)
                e = re.sub(r'\s+', ' ', e)
            return e.strip()

        self.filter_expr = clean_expr(expr)
        self.filter_keys.pop(red_key)

    # -------------------------
    # Address string / __repr__
    # -------------------------
    def to_address_string(self):
        """Rebuild address string from LHS and RHS."""
        left = self.left_expr if self.left_expr else ""
        right = self.right_expr if self.filter_expr is None else self.filter_expr
        return f"{left}@{right}" if right else left or "@"

    def __repr__(self):
        return self.to_address_string()

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


RedvyprAddressStr_legacy = typing.Annotated[
    str,
    pydantic.WithJsonSchema({'type': 'string'}, mode='serialization'),
    'RedvyprAddressStr'
]


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









