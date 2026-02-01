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
import tokenize
import io

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


class SoftPlaceholder:
    """Returns soft_missing value for any comparison to avoid NameErrors and False negatives."""

    def __init__(self, sm_value):
        self.val = sm_value

    def __eq__(self, other): return self.val
    def __ne__(self, other): return self.val
    def __lt__(self, other): return self.val
    def __le__(self, other): return self.val
    def __gt__(self, other): return self.val
    def __ge__(self, other): return self.val
    def __bool__(self): return self.val

    def __call__(self, *args, **kwargs): return self


class RedvyprAddress:
    META_CONFIG = {
        "i": {"path": "packetid", "internal": "__packetid__"},
        "p": {"path": "publisher", "internal": "__publisher__"},
        "d": {"path": "device", "internal": "__device__"},
        "u": {"path": "host.uuid", "internal": "__host_uuid__"},
        "a": {"path": "host.addr", "internal": "__host_addr__"},
        "h": {"path": "host.host", "internal": "__host_host__"},
        "ul": {"path": "localhost.uuid", "internal": "__localhost_uuid__"},
        "al": {"path": "localhost.addr", "internal": "__localhost_addr__"},
        "hl": {"path": "localhost.host", "internal": "__localhost_host__"},
    }

    # Für deinen Parser (Regex-Ersetzung) extrahieren wir einfach:
    PREFIX_MAP = {k: v["internal"] for k, v in META_CONFIG.items()}

    # 1. PREFIX_MAP (Kurzformen -> __dunder__)
    # Ergebnis: {"i": "__packetid__", "d": "__device__", ...}
    PREFIX_MAP = {k: v["internal"] for k, v in META_CONFIG.items()}

    # 2. LONGFORM_MAP (Langformen -> __dunder__)
    # Hier korrigiert: Die Werte müssen auf die "__internal__" Namen zeigen!
    LONGFORM_MAP = {
        "packetid": "__packetid__",
        "publisher": "__publisher__",
        "device": "__device__",
        "uuid": "__host_uuid__",
        "host": "__host_host__",
        "addr": "__host_addr__",
        "uuid_local": "__localhost_uuid__",
        "host_local": "__localhost_host__",
        "addr_local": "__localhost_addr__",
    }

    # 3. Hilfs-Maps für die String-Repräsentation (Symmetrie)
    LONGFORM_TO_SHORT_MAP = {
        "packetid": "i", "publisher": "p", "device": "d",
        "uuid": "u", "host": "h", "addr": "a",
        "uuid_local": "ul", "host_local": "hl", "addr_local": "al",
    }

    # Erweiterte Map inklusive Datakey
    LONGFORM_TO_SHORT_MAP_DATAKEY = {
        "datakey": "k",
        **LONGFORM_TO_SHORT_MAP
    }

    # Umkehrung für to_address_string ( __dunder__ -> Kurzprefix )
    # Ergebnis: {"__device__": "d", "__packetid__": "i", ...}
    INTERNAL_TO_PREFIX = {v["internal"]: k for k, v in META_CONFIG.items()}


    common_address_formats = ['k,i', 'k,d,i', 'k', 'd', 'i', 'p', 'p,d', 'p,d,i', 'u,a,h,d,',
                            'u,a,h,d,i', 'k,u,a,h,d', 'k,u,a,h,d,i', 'a,h,d', 'a,h,d,i', 'a,h,p']

    REV_PREFIX_MAP = {v: k for k, v in PREFIX_MAP.items()}
    REV_LONGFORM_MAP = {v: k for k, v in LONGFORM_MAP.items()}
    REV_LONGFORM_TO_SHORT_MAP = {v: k for k, v in LONGFORM_TO_SHORT_MAP.items()}
    REV_LONGFORM_TO_SHORT_MAP_DATAKEY = {v: k for k, v in LONGFORM_TO_SHORT_MAP_DATAKEY.items()}

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
            _redvypr = expr.get("_redvypr", {})
            constraints = []

            # Wir iterieren über die zentrale META_CONFIG
            for cfg in self.META_CONFIG.values():
                path = cfg["path"]
                internal = cfg["internal"]

                # Pfad im Paket auflösen (z.B. "host.uuid")
                parts = path.split(".")
                val = _redvypr
                try:
                    for part in parts:
                        val = val[part]

                    # Wenn ein Wert gefunden wurde, Constraint hinzufügen
                    if val not in (None, ''):
                        # Wir speichern es direkt als Python-Vergleichs-String
                        # e.g. "__packetid__ == 'test'"
                        constraints.append(f"{internal} == {repr(val)}")
                except (KeyError, TypeError):
                    continue

            # Zu einem einzigen RHS-String zusammenfügen
            if constraints:
                self._rhs_str = " and ".join(constraints)
                self._rhs_ast = ast.parse(self._rhs_str, mode="eval")

        # String input
        elif isinstance(expr, str):
            left, right = self._split_left_right_tokens(expr)
            #print("left",left)
            #print("right", right)
            self.left_expr = left
            if right:
                self._rhs_ast = self._parse_rhs(right)


        # LHS via datakey
        if datakey is not None:
            self.left_expr = datakey

        # Keyword args
        kw_map = [
            ("packetid", packetid),
            ("device", device),
            ("publisher", publisher),
            ("host", host),  # Mappt via LONGFORM_MAP auf __host_host__
            ("uuid", uuid),  # Mappt via LONGFORM_MAP auf __host_uuid__
            ("addr", addr),  # Korrigiert: hieß oben 'address', sollte 'addr' sein
            ("host_local", host_local),
            ("uuid_local", uuid_local),
            ("addr_local", addr_local),
        ]
        for red_key, val in kw_map:
            if val not in (None, ''):
                # delete_filter nutzt jetzt auch die LONGFORM_MAP Auflösung
                self.delete_filter(red_key)
                self.add_filter(red_key, "eq", val)


        self._compiled_left = None
        self._compiled_rhs = None
        self._compile_expressions()

    def _compile_expressions(self):
        self._compiled_left = None
        self._compiled_rhs = None
        self._lhs_ast = None  # Neu: Speicher für den AST der linken Seite

        if self._rhs_ast:
            self._compiled_rhs = compile(self._rhs_ast, '<string>', 'eval')

        if self.left_expr and self.left_expr != "!":
            try:
                # Wir parsen den String erst in einen AST
                self._lhs_ast = ast.parse(self.left_expr, mode='eval')
            except SyntaxError as e:
                print(f"\n[LHS Debug] SyntaxError in left_expr")
                print(f"Content:  '{self.left_expr}'")
                print(f"Message:  {e.msg}")
                # e.offset tells us the character position where it failed
                if e.offset is not None:
                    indicator = " " * (e.offset - 1) + "^"
                    print(f"Position: {indicator} (offset: {e.offset})")
                print("-" * 30)

            except Exception as e:
                print(f"[LHS Debug] Unexpected Error: {e}")

            # Compile the stuff
            self._compiled_left = compile(self._lhs_ast, '<string>', 'eval')


    def _split_left_right_tokens(self, expr: str):
        """
        Split a Redvypr address string into (left, right) at the first @ outside quotes.
        Uses slicing on the original string to preserve formatting.
        """
        # Use io.StringIO to make the string compatible with the tokenizer
        readline = io.StringIO(expr).readline
        tokens = tokenize.generate_tokens(readline)

        for tok_type, tok_str, start, end, _ in tokens:
            # Check for the '@' operator
            if tok_type == tokenize.OP and tok_str == "@":
                # start[1] is the character offset where '@' begins
                split_at = start[1]

                left_part = expr[:split_at].strip() or None
                # split_at + 1 skips the '@' character itself
                right_part = expr[split_at + 1:].strip() or None

                return left_part, right_part

        # Fallback if no '@' is found outside of strings
        return expr.strip() or None, None


    # -------------------------
    # RHS AST Parsing
    # -------------------------
    import re
    import ast

    def _parse_rhs(self, rhs: str) -> ast.Expression:
        s = rhs.strip()
        if not s:
            return None

        # Pattern to catch quoted strings to avoid replacing keywords inside them
        STRING_PATTERN = r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')'

        def safe_sub(pattern, repl_func, text):
            combined = f"{STRING_PATTERN}|{pattern}"
            return re.sub(combined,
                          lambda m: m.group(1) if m.group(1) else repl_func(m), text)

        # 1. dt("ISO") literal conversion
        def repl_dt(m):
            iso = m.group(2) or m.group(3)
            return f"_dt({repr(iso)})"

        dt_pattern = r"dt\(\s*(?:['\"](.*?)['\"]|([0-9T:\-\.\+Z ]+))\s*\)"
        rhs = safe_sub(dt_pattern, repl_dt, rhs)

        # 2. Existence Check (key?:)
        def replace_exists(match):
            key = match.group(2)
            # Use the internal __dunder__ name if it exists in PREFIX_MAP
            target = self.PREFIX_MAP.get(key, key)
            self.filter_keys.setdefault(target, []).append("exists")
            # Optimization: We pass the RAW identifier for metadata
            # but keep repr() for root keys to ensure _exists handles both.
            # However, for our new logic, _exists(target) where target is Name works best.
            return f"_exists({repr(target)})"

        rhs = safe_sub(r'([A-Za-z0-9_]+)\?:', replace_exists, rhs)

        # 3. r: forms (Root keys - no dunder transformation)
        def repl_r_list(m):
            key, content = m.group(2), m.group(3)
            self.filter_keys.setdefault(key, []).append("in")
            return f"{key} in {self._list_to_python(content)}"

        rhs = safe_sub(r'r:([A-Za-z0-9_]+):\[((?:[^\]]*))\]', repl_r_list, rhs)

        def repl_r_regex(m):
            key, pat, flags = m.group(2), m.group(3), m.group(4) or ""
            self.filter_keys.setdefault(key, []).append("regex")
            return f"_regex({key}, {repr(pat)}, {repr(flags)})"

        rhs = safe_sub(r'r:([A-Za-z0-9_]+):~/(.*?)/([a-zA-Z]*)', repl_r_regex, rhs)

        def repl_r_eq(m):
            key, val = m.group(2), m.group(3)
            self.filter_keys.setdefault(key, []).append("eq")
            return f"{key} == {self._literal_to_python(val)}"

        rhs = safe_sub(r'r:([A-Za-z0-9_]+):(".*?"|\'.*?\'|[^\s()]+)', repl_r_eq, rhs)

        # 4. Prefixes (Metadata keys - transformed to __dunder__ names)
        prefixes = sorted(self.PREFIX_MAP.keys(), key=lambda x: -len(x))
        prefix_group = "|".join([re.escape(p) for p in prefixes])

        def repl_pref_list(m):
            key, content = m.group(2), m.group(3)
            internal_name = self.PREFIX_MAP.get(key, key)
            self.filter_keys.setdefault(internal_name, []).append("in")
            # Returns: (__packetid__ in [val1, val2])
            return f"{internal_name} in {self._list_to_python(content)}"

        rhs = safe_sub(rf'({prefix_group}):\[((?:[^\]]*))\]', repl_pref_list, rhs)

        def repl_pref_regex(m):
            key, pat, flags = m.group(2), m.group(3), m.group(4) or ""
            internal_name = self.PREFIX_MAP.get(key, key)
            self.filter_keys.setdefault(internal_name, []).append("regex")
            # Pass internal_name as a Variable (no quotes)
            return f"_regex({internal_name}, {repr(pat)}, {repr(flags)})"

        rhs = safe_sub(rf'({prefix_group}):~/(.*?)/([a-zA-Z]*)', repl_pref_regex, rhs)

        def repl_pref_eq(m):
            key, val = m.group(2), m.group(3)
            internal_name = self.PREFIX_MAP.get(key, key)
            py_val = self._literal_to_python(val)
            if py_val == '' or py_val is None:
                return 'True'
            self.filter_keys.setdefault(internal_name, []).append("eq")
            # Returns: (__packetid__ == 'test_val')
            return f"{internal_name} == {py_val}"

        rhs = safe_sub(rf'({prefix_group}):((".*?"|\'.*?\'|[^\s()]+))', repl_pref_eq,
                       rhs)

        #print(f"{rhs=}")
        return ast.parse(rhs, mode="eval")

    def _literal_to_python(self, token: str) -> str:
        """
        Converts a Domain Specific Language (DSL) token into a valid Python literal string.

        This method ensures that:
        1. Numeric strings are kept as raw numbers (int/float).
        2. Already quoted strings (e.g., "'value'") are returned as-is.
        3. Unquoted strings (e.g., "value") are safely wrapped in quotes.
        4. Empty inputs return None.

        Args:
            token (str): The raw string extracted from the address RHS.

        Returns:
            str: A string that can be safely embedded into a Python eval() expression.
        """
        t = token.strip()

        # 1. Handle empty input
        if not t:
            return None

        # 2. Check if it's already a quoted string ('...' or "...")
        # This prevents double-quoting which causes match failures
        if (t.startswith("'") and t.endswith("'")) or \
                (t.startswith('"') and t.endswith('"')):
            return t

        # 3. Check if it's a numeric literal (integer or float)
        if re.fullmatch(r'-?\d+(\.\d*)?', t):
            return t

        # 4. For everything else (bare words), turn it into a string literal
        # Using repr() is safer than f"'{t}'" as it handles internal escapes
        return repr(t)

    def _list_to_python(self, content: str) -> str:
        parts = [p.strip() for p in content.split(",")] if content.strip() else []
        return "[" + ",".join([self._literal_to_python(p) for p in parts]) + "]"

    # -------------------------
    # Eval helpers
    # -------------------------
    def matches_filter(self, packet, soft_missing=True):
        # 0. No Filter
        if self._rhs_ast is None:
            return True

        # 1. Daten normalisieren
        p_data = packet.to_redvypr_dict() if hasattr(packet,
                                                     "to_redvypr_dict") else packet

        # 2. Daten flachklopfen (Metadata -> __dunder__)
        flat_data = self._to_redvypr_dict_flat(p_data)

        # 3. Locals vorbereiten
        placeholder = SoftPlaceholder(soft_missing)
        # Erst alle Namen aus dem AST mit Placeholdern füllen
        locals_map = {node.id: placeholder for node in ast.walk(self._rhs_ast)
                      if isinstance(node, ast.Name)}

        # 4. WICHTIG: Die echten Daten müssen die Placeholder ÜBERSCHREIBEN
        locals_map.update(flat_data)

        # 5. Hilfsfunktionen laden (wie _dt)
        locals_map.update(self._build_eval_locals(p_data, soft_missing))


        try:
            if True:
                return bool(eval(self._compiled_rhs, {"__builtins__": {}}, locals_map))
            else:
                code = compile(self._rhs_ast, filename="<ast>", mode="eval")
                return bool(eval(code, {"__builtins__": {}}, locals_map))
        except Exception:
            return soft_missing

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

    def _build_eval_locals(self, packet: dict, soft_missing: bool):
        locals_map = {}
        INTERNAL_TO_PATH = {v["internal"]: v["path"] for v in self.META_CONFIG.values()}

        def _dt(iso):
            from datetime import datetime
            return datetime.fromisoformat(iso)

        def _resolve_val(k_or_v):
            """
            Hilfsfunktion: Wenn k_or_v ein SoftPlaceholder oder der Wert selbst ist,
            geben wir ihn zurück. Wenn es ein String-Pfad ist (altes System), lösen wir ihn auf.
            """
            if isinstance(k_or_v, SoftPlaceholder):
                return k_or_v
            # Wenn es ein String ist, der ein Key sein könnte (kein Dunder, keine Metadaten),
            # und er NICHT im Paket als Wert existiert, behandeln wir ihn als Pfad.
            # Aber im neuen System ist k_or_v meistens schon der fertige Wert aus der locals_map.
            return k_or_v

        # -------------------------
        # In / Regex / Exists
        # -------------------------
        def _in(val, list_obj):
            # val ist hier bereits der Wert der Variable (z.B. __packetid__)
            return val in list_obj

        def _regex(val, pat, flags=""):
            # val ist der Inhalt der Variable
            f = 0
            if "i" in flags: f |= re.IGNORECASE
            if "m" in flags: f |= re.MULTILINE
            if "s" in flags: f |= re.DOTALL
            return re.search(pat, str(val), f) is not None

        def _exists(name: str) -> bool:
            # Hier bleibt name ein String (z.B. '__device__'), da wir _exists('__device__') rufen
            if name in INTERNAL_TO_PATH:
                path = INTERNAL_TO_PATH[name]
                meta = packet.get('_redvypr', {})
                val = meta
                try:
                    for part in path.split('.'):
                        val = val[part]
                    return True
                except (KeyError, TypeError):
                    return False

            # Root-Key check
            return name in packet and name != '_redvypr'

        # -------------------------
        # Mapping
        # -------------------------
        locals_map.update({
            "_dt": _dt,
            "_in": _in,
            "_regex": _regex,
            "_exists": _exists,
            # Die alten _eq, _ne etc. werden eigentlich nicht mehr gebraucht,
            # da wir jetzt natives (a == b) im AST nutzen.
            # Wir lassen sie für Notfälle drin, mappen sie aber auf Standard-Logik:
            "_eq": lambda a, b: a == b,
            "True": True,
            "False": False,
            "None": None,
            "packet": packet,
        })

        return locals_map


    def _traverse_path(self, root: dict, parts: list):
        cur = root
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return False, None
            cur = cur[p]
        return True, cur

    def _get_val(self, packet, key, soft_missing_val=True):
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

        return SoftPlaceholder(soft_missing_val)
        #raise FilterFieldMissing(f"missing key '{key}'")

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
            address = RedvyprAddress(packet)
        else:
            address = packet

        # 1. RHS Filter check
        match_filter = self.matches_filter(packet, soft_missing=soft_missing)
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

        # 3. Specific key or Subsumption logic,
        # try if datakey(s) match, here also more complex datapackets are treated properly
        try:
            self.__call__(packet)
            return True
        except:
            # If this is a packet, the address is without a datakey, but the __call__ did not find any data
            # so it does not match
            if isinstance(packet, dict):
                return False
            else:
                pass

        # 4. Wildcard logic: If I don't care about the key, any key matches
        # (provided the filter above matched)
        if address.datakey is None:
            return True

        return False

    def __call__(self, packet, strict=True, soft_missing=True):
        if isinstance(packet, RedvyprAddress):
            packet = packet.to_redvypr_dict()
        if self.left_expr is None and self._rhs_ast is None:
            return packet
        SAFE_GLOBALS = {"__builtins__": {}, "True": True, "False": False, "None": None}
        locals_map = dict(packet)
        if self._rhs_ast and not self.matches_filter(packet,soft_missing=soft_missing):
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


            try:
                # 1. Evaluate the expression (e.g., "'test@i:test'" becomes "test@i:test")
                if self._compiled_left is not None:
                    val =  eval(self._compiled_left, SAFE_GLOBALS, locals_map)
                else:
                    val = eval(self.left_expr, SAFE_GLOBALS, locals_map)

                # 2. If the result is a string AND it's a key in our packet,
                # we probably want the value from the packet.
                if isinstance(val, str) and val in packet:
                    return packet[val]

                return val
            except (NameError, KeyError, TypeError) as e:
                # NameError: variable data3 doesn't exist
                # TypeError: e.g. trying to index something that isn't a list
                if strict:
                    raise KeyError(
                        f"Key or Expression {self.left_expr!r} failed: {e}")
                return None
            except Exception as e:
                if strict:
                    raise e
                return None

        return packet

    # -------------------------
    # Filter Manipulation (AST)
    # -------------------------
    def add_filter(self, key, op, value=None, flags=""):
        # 1. Den internen Dunder-Namen finden (__device__, etc.)
        internal_key = None
        if key in self.PREFIX_MAP:
            internal_key = self.PREFIX_MAP[key]
        elif key in self.LONGFORM_MAP:
            internal_key = self.LONGFORM_MAP[key]
        else:
            internal_key = key

        # 2. Den Python-Ausdruck basierend auf dem Operator bauen
        if op == "eq":
            expr_str = f"{internal_key} == {repr(value)}"
        elif op == "in":
            val_list = value if isinstance(value, list) else [value]
            expr_str = f"{internal_key} in {repr(val_list)}"
        elif op == "regex":
            expr_str = f"_regex({internal_key}, {repr(value)}, {repr(flags)})"
        elif op == "exists":
            expr_str = f"_exists({internal_key})"
        else:
            raise ValueError(f"Unsupported operation '{op}'")

        # parse erzeugt Knoten MIT lineno
        new_ast = ast.parse(expr_str, mode="eval")

        # 3. In den bestehenden RHS-AST integrieren
        if self._rhs_ast is None:
            self._rhs_ast = new_ast
        else:
            current_body = self._rhs_ast.body
            new_node = new_ast.body

            if isinstance(current_body, ast.BoolOp) and isinstance(current_body.op,
                                                                   ast.And):
                current_body.values.append(new_node)
            else:
                # WICHTIG: Manuell erstellte Knoten haben keine lineno!
                combined_body = ast.BoolOp(op=ast.And(),
                                           values=[current_body, new_node])
                self._rhs_ast = ast.Expression(body=combined_body)

        # 4. REPARATUR: Füllt lineno/col_offset rekursiv für alle Knoten nach
        ast.fix_missing_locations(self._rhs_ast)

        self._compile_expressions()

    def delete_filter(self, key):
        if not self._rhs_ast:
            return

        # Internen Namen ermitteln
        internal_target = self.PREFIX_MAP.get(key, self.LONGFORM_MAP.get(key, key))

        def _should_remove(node):
            # Fall A: Vergleich (__device__ == 'val')
            if isinstance(node, ast.Compare):
                if isinstance(node.left, ast.Name) and node.left.id == internal_target:
                    return True
            # Fall B: Funktionsaufruf (_regex(__device__, ...))
            elif isinstance(node, ast.Call):
                if node.args and isinstance(node.args[0], ast.Name) and node.args[
                    0].id == internal_target:
                    return True
            return False

        def _walk_and_filter(node):
            if isinstance(node, ast.BoolOp):
                new_vals = [nv for nv in (_walk_and_filter(v) for v in node.values) if
                            nv is not None]
                if not new_vals: return None
                if len(new_vals) == 1: return new_vals[0]
                node.values = new_vals
                return node

            return None if _should_remove(node) else node

        new_root = _walk_and_filter(self._rhs_ast.body)
        self._rhs_ast = ast.Expression(new_root) if new_root else None
        self._compile_expressions()

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

        self._compile_expressions()

    def delete_datakey(self):
        self.left_expr = None
        self._compile_expressions()

    # -------------------------
    # String / Dict Conversion
    # -------------------------
    def _to_redvypr_dict_flat(self, p_data: dict) -> dict:
        """
        Converts a nested packet dictionary into a flat dictionary for eval().
        Maps metadata fields to safe internal names (e.g., __packetid__)
        to prevent collisions with root user data.
        """
        # 1. Copy root data but exclude the metadata block itself
        flat_data = {k: v for k, v in p_data.items() if k != '_redvypr'}

        if '_redvypr' in p_data:
            meta = p_data['_redvypr']
            for cfg in self.META_CONFIG.values():
                path = cfg["path"]
                internal_name = cfg["internal"]

                # Path traversal for dot notation (e.g., "host.uuid")
                parts = path.split(".")
                current_val = meta
                try:
                    for part in parts:
                        current_val = current_val[part]
                    flat_data[internal_name] = current_val
                except (KeyError, TypeError):
                    continue
        return flat_data

    def to_redvypr_dict(self, include_datakey: bool = True) -> dict:
        """Führt die Strukturen von LHS und RHS zusammen."""
        # 1. Metadaten und Root initialisieren
        root = {}

        # 2. LHS verarbeiten (Struktur-Pfade)
        root = self.to_redvypr_dict_lhs()

        # 3. RHS verarbeiten (Constraints und Metadaten)
        root_rhs = self.to_redvypr_dict_rhs()

        # Einfaches Mergen der Top-Level Keys
        for k, v in root_rhs.items():
            if k == "_redvypr":
                # Metadaten zusammenführen, falls schon was da ist
                root.setdefault("_redvypr", {}).update(v)
            elif isinstance(v, dict) and k in root and isinstance(root[k], dict):
                # Tieferes Update für verschachtelte Strukturen im Root
                root[k].update(v)
            else:
                root[k] = v

        ## 4. Optional: Rohen Datakey-String hinzufügen
        #if include_datakey and self.left_expr:
        #    root['datakey'] = self.left_expr

        return root

    def to_redvypr_dict_lhs(self) -> dict:
        """
        Extrahiert die reine Pfadstruktur der linken Seite (LHS)
        und bildet sie als verschachteltes Dictionary ab.
        """
        result_root = {}

        def add_to_target(key_path, value, target):
            """Hilfsfunktion zum Aufbau verschachtelter Dicts."""
            cur = target
            for i in range(len(key_path) - 1):
                p = key_path[i]
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            cur[key_path[-1]] = value

        def get_path(node):
            """Extrahiert den Variablenpfad aus einem AST-Knoten."""
            # Falls der Baum in ein Expression-Objekt gewrappt ist
            if isinstance(node, ast.Expression):
                node = node.body

            if isinstance(node, ast.Name):
                return [node.id]
            if isinstance(node, ast.Attribute):
                base = get_path(node.value)
                return base + [node.attr] if base else [node.attr]
            if isinstance(node, ast.Subscript):
                base = get_path(node.value)
                try:
                    # Holt den Index/Key (z.B. 0 oder 'temp')
                    slc = node.slice
                    # Kompatibilität für verschiedene Python Versionen (Index vs Constant)
                    if isinstance(slc, ast.Index):
                        slc = slc.value
                    idx = ast.literal_eval(slc)
                    return base + [idx] if base else [idx]
                except:
                    return base
            return None

        # Verarbeiten des LHS AST
        if self._lhs_ast:
            # Wir holen den Pfad (z.B. data['temp'][0] -> ['data', 'temp', 0])
            path = get_path(self._lhs_ast)
            if path:
                # Wir markieren die Existenz dieses Pfades mit True
                add_to_target(path, True, result_root)

        return result_root

    def to_redvypr_dict_rhs(self, include_datakey: bool = True) -> dict:
        """
        Reverse process: Converts the AST back into a standard nested dictionary.
        Internal __dunder__ keys are moved back into the '_redvypr' block.
        """
        result_metadata = {}
        result_root = {}

        # Map internal names back to their original metadata paths
        # e.g., "__host_uuid__": "host.uuid"
        REVERSE_META = {v["internal"]: v["path"] for v in self.META_CONFIG.values()}

        def add_to_target(key_path, value, target):
            """Helper to build nested dictionaries from a list of path parts."""
            cur = target
            for i in range(len(key_path) - 1):
                p = key_path[i]
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            cur[key_path[-1]] = value

        def get_path(node):
            """Extracts the variable path from an AST node."""
            if isinstance(node, ast.Name): return [node.id]
            if isinstance(node, ast.Attribute):
                base = get_path(node.value)
                return base + [node.attr] if base else [node.attr]
            if isinstance(node, ast.Subscript):
                base = get_path(node.value)
                try:
                    idx = ast.literal_eval(node.slice)
                    return base + [idx] if base else [idx]
                except:
                    return base
            return None

        def process_node(node):
            """Walks the AST to find filter constraints."""
            if isinstance(node, ast.Compare):
                path = get_path(node.left)
                if not path: return

                try:
                    # Basic literal value extraction
                    comp = node.comparators[0]
                    val = ast.literal_eval(comp)

                    # Check if this is one of our internal metadata dunder names
                    if path[0] in REVERSE_META:
                        meta_path = REVERSE_META[path[0]].split(".")
                        add_to_target(meta_path, val, result_metadata)
                    elif path[0] == "_redvypr":
                        add_to_target(path[1:], val, result_metadata)
                    else:
                        add_to_target(path, val, result_root)
                except:
                    pass

            elif isinstance(node, ast.Call):
                # Handle special helper functions if they are still used in AST
                func_name = getattr(node.func, 'id', '')
                if func_name in ("_eq", "_regex", "_exists", "_in"):
                    try:
                        # In our new design, the first arg is often a Name node or string
                        arg0 = node.args[0]
                        key_str = arg0.id if isinstance(arg0,
                                                        ast.Name) else ast.literal_eval(
                            arg0)

                        val = True if func_name == "_exists" else ast.literal_eval(
                            node.args[1])

                        if key_str in REVERSE_META:
                            meta_path = REVERSE_META[key_str].split(".")
                            add_to_target(meta_path, val, result_metadata)
                        else:
                            add_to_target(key_str.split("."), val, result_root)
                    except:
                        pass

        # Walk through both LHS and RHS ASTs
        for tree in [self._lhs_ast, self._rhs_ast]:
            if tree:
                for node in ast.walk(tree):
                    process_node(node)

        return {"_redvypr": result_metadata, **result_root}

    def get_datakeyentries(self):
        expr = self.left_expr
        if not expr or expr == "!":
            return []

        try:
            # Parse the expression into an AST node
            node = ast.parse(expr.strip(), mode='eval').body

            path = []
            # Walk "down" the tree for expressions like foo['bar'][2]
            while isinstance(node, ast.Subscript):
                # The index is node.slice (Python 3.9+)
                index_node = node.slice
                if isinstance(index_node, ast.Constant):  # e.g., 'bar' or 2
                    path.append(index_node.value)
                elif isinstance(index_node, ast.Index):  # Older Python 3.x
                    if isinstance(index_node.value, ast.Constant):
                        path.append(index_node.value.value)

                node = node.value

            # Now we are at the "base" node (the left-most part)
            if isinstance(node, ast.Name):
                path.append(node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                path.append(node.value)
            else:
                # Fallback for unexpected node types
                path.append(ast.unparse(node) if hasattr(ast, 'unparse') else str(node))

            # Reverse the path because we walked from right to left
            return path[::-1]

        except Exception as e:
            # Fallback to your regex if AST fails, or raise a cleaner error
            raise ValueError(f"Could not parse data path from {expr!r}: {e}")

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
        """
        Erstellt die lesbare Adresse. Berücksichtigt:
        1. Filterung nach 'keys' (Pruning)
        2. Linke Seite (left_expr / datakey)
        3. Rückwandlung von Dunder-Namen zu Präfixen (i:, d: etc.)
        4. @-Symbol Symmetrie
        """
        # --- 1. Vorbereitung der Key-Filterung ---
        allowed_keys_set = None
        show_left = True

        if keys is not None:
            if isinstance(keys, str):
                allowed_keys = [k.strip() for k in keys.split(",") if k.strip()]
            else:
                allowed_keys = keys

            if len(allowed_keys) == 0:
                return "@"

            # Expand keys (Mapping von kurz zu lang/intern)
            expanded = set()
            for k in allowed_keys:
                if k in getattr(self, 'LONGFORM_MAP', {}):
                    expanded.add(self.LONGFORM_MAP[k])
                elif k in self.PREFIX_MAP:
                    expanded.add(self.PREFIX_MAP[k])
                elif k in getattr(self, 'REV_PREFIX_MAP', {}):
                    expanded.add(k)
                else:
                    expanded.add(k)

            allowed_keys_set = expanded
            # Wenn 'k' oder 'datakey' nicht explizit verlangt wird, linke Seite verstecken
            if not any(k in allowed_keys for k in ("k", "datakey")):
                show_left = False

        # --- 2. AST Pruning (Filterung der RHS) ---
        def prune_ast(node):
            if node is None: return None
            if isinstance(node, ast.Expression):
                node.body = prune_ast(node.body)
                return node if node.body else None

            if isinstance(node, ast.BoolOp):
                new_vals = [prune_ast(v) for v in node.values]
                new_vals = [v for v in new_vals if v is not None]
                if not new_vals: return None
                node.values = new_vals
                return node

            # Prüfung auf Name-Ebene (für __packetid__ etc) oder Call-Ebene
            target_key = None
            if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name):
                target_key = node.left.id
            elif isinstance(node, ast.Call) and node.args:
                try:
                    # Handhabt _exists('__device__') oder _regex(__device__, ...)
                    arg0 = node.args[0]
                    target_key = arg0.id if isinstance(arg0,
                                                       ast.Name) else ast.literal_eval(
                        arg0)
                except:
                    pass

            if allowed_keys_set and target_key and target_key not in allowed_keys_set:
                return None

            return node

        # --- 3. AST Transformation & Unparsing ---
        rhs_str = ""
        if self._rhs_ast:
            # Kopie ziehen und filtern
            working_ast = copy.deepcopy(self._rhs_ast)
            if allowed_keys_set:
                working_ast = prune_ast(working_ast)

            if working_ast:
                # Namen zurücktauschen (__device__ -> d)
                DUNDER_TO_PREFIX = {v["internal"]: k for k, v in
                                    self.META_CONFIG.items()}
                for node in ast.walk(working_ast):
                    if isinstance(node, ast.Name) and node.id in DUNDER_TO_PREFIX:
                        node.id = DUNDER_TO_PREFIX[node.id]

                # String generieren
                rhs_str = ast.unparse(working_ast)

                # Kosmetik
                rhs_str = rhs_str.replace("_dt(", "dt(")
                # d == 'val' -> d:'val'
                for prefix in DUNDER_TO_PREFIX.values():
                    rhs_str = re.sub(rf'\b({prefix})\s*==\s*', r'\1:', rhs_str)
                # Klammern um einfache Terme entfernen
                rhs_str = re.sub(r'\(([\w\.]+:[^()]+)\)', r'\1', rhs_str)
                rhs_str = rhs_str.strip()

        # --- 4. Finaler String-Zusammenbau ---
        left = self.left_expr if (self.left_expr and show_left) else ""

        if not rhs_str:
            # Kein Filter vorhanden oder weggefiltert
            return f"{left}" if (left and not keys) else (f"{left} @ " if left else "@")

        return f"{left} @ {rhs_str}" if left else f"@{rhs_str}"

    def to_address_string_newold(self, keys: Union[str, List[str]] = None) -> str:
        if not self._rhs_ast:
            return ""

        # 1. Vorbereitung für die Rückumwandlung der Dunder-Namen
        DUNDER_TO_PREFIX = {v["internal"]: k for k, v in self.META_CONFIG.items()}

        # 2. AST in einen String umwandeln
        # Wir arbeiten auf einer Kopie, falls wir den Baum transformieren wollen
        tree_copy = copy.deepcopy(self._rhs_ast)

        # Optional: Hier könnte ein NodeTransformer Namen anpassen
        # Für den Moment nutzen wir den direkten Weg:
        raw_str = ast.unparse(tree_copy)

        # 3. Aufräumen der internen Dunder-Namen und Operatoren
        # Wir wandeln "__device__ == 'hello'" -> "d:'hello'"
        for dunder, prefix in DUNDER_TO_PREFIX.items():
            # Ersetzt: __device__ == 'value' -> d:'value'
            raw_str = re.sub(rf'{dunder}\s*==\s*', f'{prefix}:', raw_str)
            # Ersetzt: __device__ (falls einzeln stehend) -> d
            raw_str = re.sub(rf'\b{dunder}\b', prefix, raw_str)

        # 4. Funktions-Namen zurückdrehen
        raw_str = raw_str.replace("_dt(", "dt(")

        # 5. DIE KLAMMERN ENTFERNEN
        # Wir entfernen Klammern um einfache Zuweisungen wie (manufacturer_sn == '0856')
        # aber NUR wenn sie innerhalb einer 'and/or' Kette stehen und kein komplexes Nesting haben
        # Dieser Regex sucht nach (Wort == Wert) und entfernt die Klammern
        raw_str = re.sub(r'\(([\w\.]+ == [^()]+)\)', r'\1', raw_str)

        # Falls d:hello immer noch in Klammern steht: (d:'hello') -> d:'hello'
        for prefix in DUNDER_TO_PREFIX.values():
            raw_str = re.sub(rf'\({prefix}:([^()]+)\)', rf'{prefix}:\1', raw_str)

        # 6. Doppelte Leerzeichen bereinigen, falls entstanden
        raw_str = re.sub(r'\s+', ' ', raw_str)

        return f"@{raw_str.strip()}"


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
        #print("\n__getattr__")
        # 1. Spezialfall für Datakey
        if name in ('datakey', 'k'):
            return self.left_expr

        # 2. Key-Auflösung (Kurzform oder Longform zu Dunder-Name)
        cls = type(self)
        if name in cls.PREFIX_MAP:
            internal_key = cls.PREFIX_MAP[name]
        elif name in cls.LONGFORM_MAP:
            internal_key = cls.LONGFORM_MAP[name]
        else:
            # Wenn es weder ein bekannter Präfix noch ein Dunder-Name ist
            raise AttributeError(
                f"{type(self).__name__!r} object has no attribute {name!r}")

        # 3. Wenn kein Filter da ist oder der Key nicht im Filter vorkommt
        if not self._rhs_ast:
            return None

        values = []
        #print(f"{name=},{internal_key=}")
        # 4. AST nach Werten für diesen internen Key durchsuchen
        # Wir suchen nach: key == value ODER key in [list]
        for node in ast.walk(self._rhs_ast):
            #print(f"{ast.dump(node)}")
            # Fall A: Vergleich (__device__ == 'cam')
            if isinstance(node, ast.Compare):
                # Prüfen ob die linke Seite unser gesuchter Key ist
                if isinstance(node.left, ast.Name) and node.left.id == internal_key:

                    for op, comparator in zip(node.ops, node.comparators):
                        try:
                            val = ast.literal_eval(comparator)
                            # Bei == fügen wir den Wert hinzu
                            if isinstance(op, ast.Eq):
                                values.append(val)
                            # Bei 'in' fügen wir die Elemente der Liste hinzu
                            elif isinstance(op, ast.In) and isinstance(val, list):
                                values.extend(val)
                        except (ValueError, SyntaxError):
                            # Falls es kein einfaches Literal ist (z.B. ein Funktionsaufruf)
                            continue

            # Fall B: Funktionsaufrufe (z.B. _in(__device__, ['a', 'b']))
            elif isinstance(node, ast.Call):
                func_name = getattr(node.func, 'id', '')
                if func_name in ('_in', '_eq') and node.args:
                    arg0 = node.args[0]
                    # Prüfen ob das erste Argument unser Key ist
                    target_match = False
                    if isinstance(arg0, ast.Name) and arg0.id == internal_key:
                        target_match = True
                    elif isinstance(arg0, ast.Constant) and arg0.value == internal_key:
                        target_match = True

                    if target_match and len(node.args) > 1:
                        try:
                            val = ast.literal_eval(node.args[1])
                            if func_name == '_in' and isinstance(val, list):
                                values.extend(val)
                            else:
                                values.append(val)
                        except (ValueError, SyntaxError):
                            continue

        # 5. Rückgabe-Logik
        if len(values) == 1:
            return values[0]
        elif values:
            return values
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



