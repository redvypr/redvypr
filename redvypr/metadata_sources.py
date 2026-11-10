"""
Metadata from several sources (design note doc/source/design_items.rst,
section "Metadata from several sources").

Sources are metadata storages ``{address: [entries]}``: the running redvypr
instance, item library files and databases (the metadata known when their
data were written). :func:`merge_storages` joins them into one storage:

* equal entries (same address, key, context and value, overlapping time) are
  joined; their sources are kept as a list in the constraint ``source``;
* entries with another value overlapping in time are a conflict: the entry of
  the stronger kind of source wins for the overlap (precedence per kind, one
  order for items and one for other metadata), the conflict is reported;
* within the same kind the entry with the later ``valid_from`` wins (like the
  merge rules of the storage: a later value ends an earlier one), without a
  conflict.

The constraint ``source`` (e.g. ``library:items.yaml``, ``db:nov.sqlite``) is
not part of the context (``redvypr.metadata.NON_CONTEXT_KEYS``). Its kind is
the part before the colon; entries without ``source`` of the instance are of
kind ``instance``. Entries of a database are always of kind ``db``, also if
they were written from a library (the original source is kept in the text).
"""

import copy
import datetime
import json
import logging
import os
import typing

import yaml

import redvypr.metadata as redvypr_metadata
import redvypr.items as redvypr_items

logger = logging.getLogger('redvypr.metadata_sources')

KINDS = ('library', 'instance', 'device', 'db')
# Strongest first
PRECEDENCE_ITEMS = ('library', 'instance', 'device', 'db')
PRECEDENCE_OTHER = ('device', 'instance', 'library', 'db')

_INF = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)
_NINF = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def source_kind(source) -> str:
    """Kind of a source text ('library:items.yaml' -> 'library'), of the first one of a list."""
    if isinstance(source, (list, tuple)):
        source = source[0] if source else None
    if not source:
        return 'instance'
    kind = str(source).split(':', 1)[0]
    return kind if kind in KINDS else 'instance'


def sources_of(constraints) -> list:
    s = (constraints or {}).get('source')
    if s is None:
        return []
    return list(s) if isinstance(s, (list, tuple)) else [s]


def _set_sources(constraints, sources):
    sources = list(dict.fromkeys(s for s in sources if s))
    if not sources:
        constraints.pop('source', None)
    elif len(sources) == 1:
        constraints['source'] = sources[0]
    else:
        constraints['source'] = sources


def tag_storage(storage: dict, source: str, force: bool = False) -> dict:
    """
    Copy of a storage whose entries carry the source. force: also entries that
    have a source already (the old one is kept in the text: 'db:x (library:y)').
    """
    out = {}
    for addr, entries in (storage or {}).items():
        if not isinstance(entries, list):
            continue
        new = []
        for e in entries:
            if not isinstance(e, dict) or 'key' not in e:
                continue
            e = copy.deepcopy(e)
            c = e.setdefault('constraints', {}) or {}
            e['constraints'] = c
            old = sources_of(c)
            if not old:
                c['source'] = source
            elif force:
                c['source'] = f"{source} ({', '.join(map(str, old))})"
            new.append(e)
        if new:
            out[addr] = new
    return out


def _interval(c):
    f = redvypr_metadata.to_datetime(c.get('valid_from')) or _NINF
    u = redvypr_metadata.to_datetime(c.get('valid_until')) or _INF
    return f, u


def _subtract(pieces, f, u):
    """Intervals of pieces without [f, u)."""
    out = []
    for a, b in pieces:
        if b <= f or a >= u:
            out.append((a, b))
            continue
        if a < f:
            out.append((a, f))
        if b > u:
            out.append((u, b))
    return out


def _iso(t):
    return None if t in (_INF, _NINF) else t.isoformat()


def merge_storages(sources: typing.Iterable[typing.Tuple[str, dict]],
                   precedence_items: typing.Sequence[str] = PRECEDENCE_ITEMS,
                   precedence_other: typing.Sequence[str] = PRECEDENCE_OTHER):
    """
    Joins tagged storages (see tag_storage()) into one storage.

    Parameters
    ----------
    sources : iterable of (name, storage)
        name is used in the conflict report only; the entries carry their source.
    precedence_items, precedence_other : kinds of sources, strongest first, for
        item addresses and for all other addresses.

    Returns
    -------
    (storage, conflicts) : the merged storage and a list of conflicts
        {address, key, context, valid_from, valid_until, winner: (source, value),
        loser: (source, value)}.
    """
    groups = {}
    order = []
    for _name, storage in sources:
        for addr, entries in (storage or {}).items():
            for e in entries or []:
                c = e.get('constraints') or {}
                ctx = json.dumps(redvypr_metadata.get_context(c), sort_keys=True, default=str)
                gk = (addr, e['key'], ctx)
                if gk not in groups:
                    groups[gk] = []
                    order.append(gk)
                groups[gk].append(e)

    merged = {}
    conflicts = []
    for gk in order:
        addr, key, _ctx = gk
        prec = precedence_items if redvypr_items.parse_item_address(addr) else precedence_other

        def rank(e):
            kind = source_kind(sources_of(e.get('constraints')))
            return prec.index(kind) if kind in prec else len(prec)

        def sort_key(e):
            # stronger kind first; within a kind the later valid_from first (it wins)
            f = _interval(e.get('constraints') or {})[0]
            return (rank(e), 1 if f == _NINF else 0, -(f - _NINF).total_seconds() if f != _NINF else 0)

        entries = sorted(groups[gk], key=sort_key)
        accepted = []   # [from, until, value, sources, rank, template entry]
        for e in entries:
            c = e.get('constraints') or {}
            f, u = _interval(c)
            r = rank(e)
            srcs = sources_of(c)
            pieces = [(f, u)]
            for a in accepted:
                af, au = a[0], a[1]
                if au <= f or af >= u:
                    continue
                of, ou = max(af, f), min(au, u)
                if a[2] == e['value']:
                    a[3].extend(s for s in srcs if s not in a[3])
                elif a[4] != r:
                    # still a conflict only for the part not yet resolved
                    for pf, pu in pieces:
                        cf, cu = max(pf, of), min(pu, ou)
                        if cf < cu:
                            conflicts.append({'address': addr, 'key': key,
                                              'context': redvypr_metadata.get_context(c),
                                              'valid_from': _iso(cf), 'valid_until': _iso(cu),
                                              'winner': (a[3][0] if a[3] else None, a[2]),
                                              'loser': (srcs[0] if srcs else None, e['value'])})
                pieces = _subtract(pieces, of, ou)
                if not pieces:
                    break
            for pf, pu in pieces:
                accepted.append([pf, pu, e['value'], list(srcs), r, e])

        out = merged.setdefault(addr, [])
        for pf, pu, value, srcs, _r, tmpl in sorted(accepted, key=lambda a: a[0]):
            e = copy.deepcopy(tmpl)
            c = e.setdefault('constraints', {}) or {}
            e['constraints'] = c
            e['value'] = value
            if pf == _NINF:
                c.pop('valid_from', None)
            else:
                c['valid_from'] = pf.isoformat()
            if pu == _INF:
                c.pop('valid_until', None)
            else:
                c['valid_until'] = pu.isoformat()
            _set_sources(c, srcs)
            out.append(e)
    return merged, conflicts


# --- item library files ---------------------------------------------------------------
#
# A library file holds items (all entries of item addresses) and calibrations (the entries
# with the key 'calibration', e.g. of the sensor manager at '@i:calibration ...'). Several
# files can be loaded (e.g. inventory_norlog.yaml, calibrations.yaml); an address belongs to
# the file it was loaded from (source 'library:<file name>'), see assign_library_entries().

LIBRARY_KINDS = ('item', 'itemtype', 'calibration')
# Section of each kind in a YAML library file
LIBRARY_SECTIONS = {'item': 'items', 'itemtype': 'item_types', 'calibration': 'calibrations'}


def library_entries(storage: dict) -> dict:
    """
    {address: (kind, entries)} of the library entries of a storage: items, item type
    definitions (redvypr.item_types) and calibrations.
    """
    import redvypr.item_types as ritem_types
    out = {}
    for addr, entries in (storage or {}).items():
        if not isinstance(entries, list):
            continue
        entries = [e for e in entries if isinstance(e, dict) and 'key' in e]
        if redvypr_items.parse_item_address(addr):
            if entries:
                out[addr] = ('item', entries)
            continue
        if ritem_types.parse_itemtype_address(addr):
            if entries:
                out[addr] = ('itemtype', entries)
            continue
        cal = [e for e in entries if e['key'] == 'calibration']
        if cal:
            out[addr] = ('calibration', cal)
    return out


def library_owner(entries) -> typing.Optional[str]:
    """File name of the library the entries were loaded from ('library:<name>'), else None."""
    for e in entries or []:
        for s in sources_of(e.get('constraints')):
            s = str(s)
            if s.startswith('library:'):
                return s[len('library:'):].split(' (', 1)[0]
    return None


# File of the new entries of a kind if no library holds that kind yet (next to the first library)
DEFAULT_LIBRARY_FILES = {'calibration': 'calibrations.yaml'}


def assign_library_entries(storage: dict, libraries: typing.List[str],
                           defaults: typing.Optional[typing.Dict[str, str]] = None) -> dict:
    """
    {library path: [addresses]}: where every library address of a storage is saved. An
    address goes back to the file it was loaded from; a new one (not from a library) to the
    first library already holding entries of its kind (item or calibration), else to the
    file defaults[kind] (e.g. calibrations.yaml), else to the first library. Addresses of a
    library file not in the list are left out.
    """
    libraries = list(libraries or [])
    defaults = dict(defaults or {})
    by_name = {}
    for path in libraries:
        by_name.setdefault(os.path.basename(path), path)
    lib = library_entries(storage)
    out = {path: [] for path in libraries}
    new = []
    kinds_of = {path: set() for path in libraries}
    for addr, (kind, entries) in lib.items():
        owner = library_owner(entries)
        if owner is None:
            new.append((addr, kind))
        elif owner in by_name:
            out[by_name[owner]].append(addr)
            kinds_of[by_name[owner]].add(kind)
    for addr, kind in new:
        target = next((p for p in libraries if kind in kinds_of[p]), None)
        if target is None:
            target = defaults.get(kind) or (libraries[0] if libraries else None)
        if target is not None:
            out.setdefault(target, []).append(addr)
    return out


def _plain_value(value):
    """A value as plain YAML/JSON data (datetimes as ISO text, numpy as lists, models as dicts)."""
    def conv(v):
        if isinstance(v, dict):
            return {str(k): conv(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [conv(x) for x in v]
        if isinstance(v, datetime.datetime):
            return v.isoformat()
        if isinstance(v, (str, int, float, bool, type(None))):
            return v
        if hasattr(v, 'model_dump'):
            return conv(v.model_dump(mode='json'))
        if hasattr(v, 'tolist'):         # numpy
            return v.tolist()
        return str(v)
    return conv(value)

SQLITE_SUFFIXES = ('.sqlite', '.sqlite3', '.db')

_SQLITE_METADATA_TABLE = """
    CREATE TABLE IF NOT EXISTS redvypr_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        redvypr_address TEXT NOT NULL,
        uuid TEXT NOT NULL,
        packetid TEXT,
        device TEXT,
        host TEXT,
        metadata TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (redvypr_address, uuid)
    )"""


def is_sqlite_library(path: str) -> bool:
    """True if an item library file is an SQLite database (by its suffix)."""
    return os.path.splitext(str(path))[1].lower() in SQLITE_SUFFIXES


def _read_sqlite_items(path: str) -> dict:
    """{address: content} of the library addresses in the table redvypr_metadata of an SQLite file."""
    import sqlite3
    from redvypr.serialize import deserialize_json
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        try:
            rows = con.execute('SELECT redvypr_address, metadata FROM redvypr_metadata').fetchall()
        except sqlite3.OperationalError:     # no metadata table: no items
            rows = []
    finally:
        con.close()
    data = {}
    for address, content in rows:
        content = deserialize_json(content) if isinstance(content, str) else content
        if isinstance(content, dict) and '_redvypr' in content:
            continue
        part = redvypr_metadata.normalize_metadata({address: content})
        for a, entries in part.items():
            data.setdefault(a, []).extend(entries)
    return data


def _write_sqlite_items(path: str, out: dict):
    """
    Replaces the library addresses (items, calibrations) in the table redvypr_metadata of
    an SQLite file (created if missing) by out {address: [entries]}; other metadata and
    tables stay.
    """
    import sqlite3
    from redvypr.serialize import serialize_json
    con = sqlite3.connect(path)
    try:
        with con:
            con.execute(_SQLITE_METADATA_TABLE)
            old = [r[0] for r in con.execute('SELECT DISTINCT redvypr_address FROM redvypr_metadata')]
            for address in old:
                if redvypr_items.parse_item_address(address) or address in out:
                    con.execute('DELETE FROM redvypr_metadata WHERE redvypr_address = ?', (address,))
            # calibrations stored at their address together with other keys: keep the other keys
            # (rare; the sensor manager writes one address per calibration)
            for address, entries in out.items():
                con.execute('INSERT INTO redvypr_metadata (redvypr_address, uuid, metadata, packetid, device, host) '
                            'VALUES (?, ?, ?, ?, ?, ?)',
                            (address, '', serialize_json(entries),
                             redvypr_items.ITEM_PACKETID if redvypr_items.parse_item_address(address) else None,
                             None, None))
    finally:
        con.close()


def read_library_storage(path: str) -> dict:
    """
    The library entries of a file (YAML or SQLite) as storage, without source tags and
    without registering types (e.g. to change a file and write it again).
    """
    if is_sqlite_library(path):
        data = _read_sqlite_items(path)
    else:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        sections = tuple(LIBRARY_SECTIONS.values())
        if isinstance(data, dict) and any(k in data for k in sections) and \
                all(isinstance(data.get(k) or {}, dict) for k in sections):
            import redvypr.item_types as ritem_types
            joined = {}
            for k in sections:
                part = data.get(k) or {}
                if k == 'item_types':
                    part = ritem_types.short_form_to_storage(part)
                joined.update(part)
            data = joined
    storage = redvypr_metadata.normalize_metadata(data)
    return {a: e for a, (_k, e) in library_entries(storage).items()}


def load_item_library(path: str, type_paths=None) -> dict:
    """
    Storage of an item library file, entries tagged 'library:<file name>'. Only
    item addresses are taken. YAML (storage format {address: [entries]} or simple
    format {address: {key: value}}) or an SQLite file (suffix .sqlite, .sqlite3,
    .db; table redvypr_metadata as written by redvypr, e.g. an inventory database).
    """
    storage = read_library_storage(path)
    # item types defined in the file: usable right away; types of its items not known yet
    # are searched in the directory of the file and in type_paths
    import redvypr.item_types as ritem_types
    ritem_types.register_from_storage(storage, source=path)
    ritem_types.resolve_types(storage, [os.path.dirname(os.path.abspath(path))] + list(type_paths or []))
    return tag_storage(storage, f'library:{os.path.basename(path)}', force=True)


def save_item_library(path: str, storage: dict, addresses=None) -> int:
    """
    Writes the library entries of a storage (items and calibrations) into a library
    file (storage format, without hostinfo and source), YAML or SQLite by the suffix
    (see load_item_library(); in an SQLite file only these addresses are replaced).
    addresses: only these (e.g. from assign_library_entries()), default all.
    Returns the number of addresses written.
    """
    lib = library_entries(storage)
    sections = {kind: {} for kind in LIBRARY_KINDS}
    for addr in sorted(lib):
        if addresses is not None and addr not in addresses:
            continue
        kind, src = lib[addr]
        entries = []
        for e in src:
            c = {k: v for k, v in (e.get('constraints') or {}).items() if k not in ('hostinfo', 'source')}
            entries.append({'key': e['key'], 'value': _plain_value(e['value']), 'constraints': _plain_value(c)})
        entries.sort(key=lambda e: (e['key'], str(e['constraints'].get('valid_from'))))
        sections[kind][addr] = entries
    n = sum(len(v) for v in sections.values())
    if is_sqlite_library(path):
        out = {}
        for part in sections.values():
            out.update(part)
        _write_sqlite_items(path, out)
        return n
    doc = {}
    for kind in LIBRARY_KINDS:
        if sections[kind]:
            doc[LIBRARY_SECTIONS[kind]] = sections[kind]
    if not doc:
        doc['items'] = {}
    tmp = path + '.tmp'
    # always LF line ends (files in git shared between operating systems)
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write('# redvypr item library (design note design_items.rst)\n')
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
    os.replace(tmp, path)
    return n
