"""
Item types defined as data (design note doc/source/design_items.rst, section
"Item types as data").

An item type is usually a Python class (redvypr.items.Item and its
subclasses). A type can also be defined in the metadata, like the items
themselves, at ``@i:'itemtype' and d:'<type>'``, with one key per part of the
definition (``description``, ``base``, ``revision``, ``fields``, ``defaults``,
``renamed``). In an item library file the definitions are the section
``item_types``, e.g. in a file ``item_types.yaml``::

    item_types:
      calypso_CMI1018:
        description: Calypso Instruments ultrasonic wind meter CMI1018
        defaults: {manufacturer: Calypso Instruments, mpn: CMI1018}
        fields:
          heading_offset: {kind: quantity, unit: deg, description: Mounting offset to north}

(the short form ``<type>: {definition}`` is read as well as the storage format
with history). redvypr builds a pydantic model from every definition
(:func:`build_model`) and registers it like a Python type
(:func:`register_from_storage`). Rules:

* the base is ``Item`` or the type named in ``base`` (defined as data or in Python);
* a definition with the name of a Python type extends that type (more fields,
  descriptions, defaults); the Python fields stay;
* the definition valid now is used (types have no time dependence of their own;
  their history is kept);
* ``renamed`` ({old: new}) gives the migration of items of an older revision.

Lookup: if items of a type are loaded whose definition is not known, the
definition is searched in type directories (:func:`resolve_types`): every
YAML file with a section ``item_types`` in these directories and their
subdirectories (e.g. the directory of the loaded item library and the
configured ``item_type_paths``). Files are read once and again only after a
change. Only the definitions needed (and their bases) are registered; they
are not put into the metadata, so they are not written back.
"""

import datetime
import logging
import os
import typing

import pydantic
import yaml

import redvypr.metadata as redvypr_metadata
from redvypr.redvypr_address import RedvyprAddress
import redvypr.items as ritems

logger = logging.getLogger('redvypr.item_types')

ITEMTYPE_PACKETID = 'itemtype'
DEFINITION_KEYS = ('description', 'base', 'revision', 'fields', 'defaults', 'renamed', 'slots')

KINDS = {
    'str': str,
    'int': int,
    'float': float,
    'bool': bool,
    'quantity': ritems.Quantity,
    'ref': str,         # reference of another item, <itemtype>/<id>
    'list': list,
    'dict': dict,
}

# Python types as registered by the code, name -> class (the base of a data definition of the same name)
_PYTHON_TYPES: typing.Dict[str, typing.Type[ritems.Item]] = {}
# Names of the types registered from data
DATA_TYPES: typing.Dict[str, 'TypeDefinition'] = {}
# File a type definition was read from (library file or type directory), name -> path
TYPE_SOURCES: typing.Dict[str, str] = {}


class FieldDefinition(pydantic.BaseModel):
    """One field of an item type."""
    model_config = pydantic.ConfigDict(extra='allow')
    kind: str = pydantic.Field(default='str', description='str, int, float, bool, quantity, ref, list, dict')
    unit: typing.Optional[str] = pydantic.Field(default=None, description='Unit of a quantity')
    description: typing.Optional[str] = None
    default: typing.Any = None
    choices: typing.Optional[list] = None

    @pydantic.field_validator('kind')
    @classmethod
    def _known_kind(cls, v):
        if v not in KINDS:
            raise ValueError(f'unknown field kind {v!r}, one of {", ".join(KINDS)}')
        return v


class TypeDefinition(pydantic.BaseModel):
    """An item type defined as data."""
    model_config = pydantic.ConfigDict(extra='allow')
    name: str
    description: typing.Optional[str] = None
    base: typing.Optional[str] = pydantic.Field(default=None, description='Type whose fields are inherited')
    revision: int = 1
    fields: typing.Dict[str, FieldDefinition] = pydantic.Field(default_factory=dict)
    defaults: typing.Dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    renamed: typing.Dict[str, str] = pydantic.Field(default_factory=dict, description='old field -> new field')
    slots: typing.Dict[str, typing.Dict[str, typing.Any]] = pydantic.Field(
        default_factory=dict, description='slot -> {accepts: [item types], label}: suggestions for the slot of '
                                          'items mounted on this type')


# --- addresses ---------------------------------------------------------------------

def itemtype_address(name: str) -> str:
    """Metadata address of a type definition."""
    ritems._check_name('item type', name)
    return RedvyprAddress('@', packetid=ITEMTYPE_PACKETID, device=name).to_address_string()


def parse_itemtype_address(address) -> typing.Optional[str]:
    """Name of the type if address is the address of a type definition, else None."""
    try:
        raddr = address if isinstance(address, RedvyprAddress) else RedvyprAddress(address)
        if raddr.packetid != ITEMTYPE_PACKETID or not raddr.device or raddr.get_datakeyentries():
            return None
        if raddr.deviceid or raddr.sensorid or raddr.sensor is not None:
            return None
        return raddr.device
    except Exception:
        return None


# --- definitions <-> metadata ---------------------------------------------------------

def definition_entries(defn: TypeDefinition, valid_from=None) -> dict:
    """{address: [entries]} of a definition, one key per part, valid from valid_from (default now)."""
    if valid_from is None:
        valid_from = datetime.datetime.now(datetime.timezone.utc)
    data = defn.model_dump(exclude_none=True)
    data.pop('name')
    data['fields'] = {k: v.model_dump(exclude_none=True) for k, v in defn.fields.items()}
    for k in ('defaults', 'renamed', 'fields', 'slots'):
        if not data.get(k):
            data.pop(k, None)
    address = itemtype_address(defn.name)
    md = redvypr_metadata.create_metadata_dict(address, data, valid_from=valid_from)
    storage = {}
    redvypr_metadata.add_metadata_to_entries(md, storage)
    return storage


def add_definition(storage: dict, defn: TypeDefinition, valid_from=None) -> dict:
    """Writes a definition into a storage (new values from valid_from on); returns the storage."""
    for address, entries in definition_entries(defn, valid_from).items():
        for e in entries:
            md = redvypr_metadata.create_metadata_dict(address, {e['key']: e['value']},
                                                       valid_from=e['constraints'].get('valid_from'))
            redvypr_metadata.add_metadata_to_entries(md, storage)
    return storage


def short_form_to_storage(section: dict) -> dict:
    """
    The section 'item_types' of a library file as storage: keys that are addresses
    stay (storage format), a plain type name with a definition dict becomes its
    address (short form, valid always).
    """
    out = {}
    for key, value in (section or {}).items():
        if isinstance(key, str) and key.strip().startswith('@'):
            out[key] = value
            continue
        defn = TypeDefinition.model_validate(dict(value or {}, name=key))
        data = defn.model_dump(exclude_none=True)
        data.pop('name')
        data['fields'] = {k: v.model_dump(exclude_none=True) for k, v in defn.fields.items()}
        out[itemtype_address(key)] = {k: v for k, v in data.items() if v not in ({}, None)}
    return out


def definitions_from_storage(storage: dict, at_time=None) -> typing.Dict[str, TypeDefinition]:
    """The type definitions of a storage valid at a time (default now), name -> definition."""
    t = redvypr_metadata.to_datetime(at_time) if at_time is not None else \
        datetime.datetime.now(datetime.timezone.utc)
    out = {}
    for address, entries in (storage or {}).items():
        name = parse_itemtype_address(address)
        if not name:
            continue
        data = {}
        stamped = {}
        for e in entries or []:
            if not isinstance(e, dict) or e.get('key') not in DEFINITION_KEYS:
                continue
            c = e.get('constraints') or {}
            f = redvypr_metadata.to_datetime(c.get('valid_from'))
            u = redvypr_metadata.to_datetime(c.get('valid_until'))
            if (f is None or f <= t) and (u is None or t < u):
                # the later valid_from wins
                key = e['key']
                fs = f or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
                if key not in stamped or fs >= stamped[key]:
                    stamped[key] = fs
                    data[key] = e['value']
        if not data:
            continue
        try:
            out[name] = TypeDefinition.model_validate(dict(data, name=name))
        except pydantic.ValidationError:
            logger.warning(f'invalid definition of the item type {name}', exc_info=True)
    return out


# --- models ------------------------------------------------------------------------------

def _python_type(name):
    """The Python class of a type name (as registered by the code), None if none."""
    if name in _PYTHON_TYPES:
        return _PYTHON_TYPES[name]
    cls = ritems.ITEM_TYPES.get(name)
    if cls is not None and getattr(cls, 'ORIGIN', 'python') == 'python':
        _PYTHON_TYPES[name] = cls
        return cls
    return None


def _quantity_validator(unit):
    def check(value):
        if value is None:
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return ritems.Quantity(value=value, unit=unit or '')
        if isinstance(value, ritems.Quantity):
            value = value.model_dump(exclude_none=True)
        if isinstance(value, dict):
            value = dict(value)
            if unit:
                given = value.get('unit') or ''
                if given and given != unit:
                    raise ValueError(f'unit {given!r}, expected {unit!r}')
                value['unit'] = unit
            return ritems.Quantity.model_validate(value)
        raise ValueError(f'a number or {{value, unit}} expected, got {value!r}')
    return check


def _choices_validator(choices):
    def check(value):
        if value is not None and value not in choices:
            raise ValueError(f'{value!r} is not one of {choices}')
        return value
    return check


def build_model(defn: TypeDefinition, base: typing.Type[ritems.Item]) -> typing.Type[ritems.Item]:
    """A pydantic item model of a definition, derived from base."""
    fields = {}
    validators = {}
    for fname, fd in defn.fields.items():
        if not fname.isidentifier() or fname in ritems.ADDRESS_FIELDS:
            raise ValueError(f'invalid field name {fname!r} in the item type {defn.name}')
        extra = {'unit': fd.unit} if fd.unit else None
        fields[fname] = (typing.Optional[KINDS[fd.kind]],
                         pydantic.Field(default=fd.default, description=fd.description,
                                        json_schema_extra=extra))
        if fd.kind == 'quantity':
            validators[f'_q_{fname}'] = pydantic.field_validator(fname, mode='before')(
                staticmethod(_quantity_validator(fd.unit)))
        if fd.choices:
            validators[f'_c_{fname}'] = pydantic.field_validator(fname, mode='after')(
                staticmethod(_choices_validator(list(fd.choices))))
    for fname, value in defn.defaults.items():
        if fname in fields or fname in ritems.ADDRESS_FIELDS:
            continue
        finfo = base.model_fields.get(fname)
        annotation = finfo.annotation if finfo is not None else typing.Any
        description = finfo.description if finfo is not None else None
        fields[fname] = (annotation, pydantic.Field(default=value, description=description))

    renamed = dict(defn.renamed)
    revision = max(defn.revision, getattr(base, 'REVISION', 1)) if base.ITEMTYPE == defn.name else defn.revision

    def migrate(cls, data: dict, from_revision: int) -> dict:
        if base is not ritems.Item:
            data = base.migrate(data, from_revision)
        data = dict(data)
        if from_revision < cls.REVISION:
            for old, new in renamed.items():
                if old in data and new not in data:
                    data[new] = data.pop(old)
        return data

    namespace = {'__doc__': defn.description or f'Item type {defn.name} (defined as data)'}
    model = pydantic.create_model(
        f'ItemType_{defn.name}', __base__=base, __validators__=validators or None,
        __module__=__name__, **fields)
    model.ITEMTYPE = defn.name
    model.REVISION = revision
    model.ORIGIN = 'data'
    model.DEFINITION = defn
    # the slots of the base stay, the definition adds to them and overrides slots of the same name
    model.SLOTS = dict(getattr(base, 'SLOTS', None) or {}, **(defn.slots or {}))
    model.__doc__ = namespace['__doc__']
    model.migrate = classmethod(migrate)
    return model


def register_definitions(defs: typing.Dict[str, TypeDefinition],
                         sources: typing.Optional[typing.Dict[str, str]] = None) -> typing.List[str]:
    """
    Builds and registers the models of definitions (bases first); a definition of a
    Python type extends it. sources: name -> file the definition was read from.
    Returns the names registered; errors are logged.
    """
    for name, path in (sources or {}).items():
        if name in defs and path:
            TYPE_SOURCES[name] = path
    done = []
    pending = dict(defs)
    for _round in range(len(pending) + 1):
        progress = False
        for name, defn in list(pending.items()):
            py = _python_type(name)
            if defn.base and defn.base != name:
                if defn.base in pending:
                    continue          # base later
                base = ritems.ITEM_TYPES.get(defn.base)
                if base is None:
                    logger.warning(f'item type {name}: unknown base {defn.base!r}, using Item')
                    base = ritems.Item
                if py is not None:
                    logger.warning(f'item type {name}: a Python type of that name exists, base {defn.base} ignored')
                    base = py
            else:
                base = py if py is not None else ritems.Item
            try:
                model = build_model(defn, base)
            except Exception:
                logger.warning(f'could not build the item type {name}', exc_info=True)
                pending.pop(name)
                continue
            ritems.ITEM_TYPES[name] = model
            DATA_TYPES[name] = defn
            done.append(name)
            pending.pop(name)
            progress = True
        if not pending or not progress:
            break
    for name in pending:
        logger.warning(f'item type {name}: base {pending[name].base!r} not resolvable (loop?)')
    return done


def register_from_storage(storage: dict, at_time=None, source: typing.Optional[str] = None) -> typing.List[str]:
    """Registers the type definitions of a storage (see register_definitions()); source: its file."""
    defs = definitions_from_storage(storage, at_time=at_time)
    if not defs:
        return []
    return register_definitions(defs, sources={n: source for n in defs} if source else None)


# --- lookup in type directories ---------------------------------------------------------

_FILE_CACHE: typing.Dict[str, typing.Tuple[float, typing.Dict[str, TypeDefinition]]] = {}
_FOUND_IN: typing.Dict[str, str] = {}
TYPE_FILE_SUFFIXES = ('.yaml', '.yml')


def type_files(paths) -> typing.List[str]:
    """YAML files of a list of directories (with subdirectories) and files, sorted, without duplicates."""
    out = []
    for p in paths or []:
        if not p:
            continue
        p = os.path.abspath(str(p))
        if os.path.isfile(p):
            out.append(p)
        elif os.path.isdir(p):
            for dirpath, dirnames, filenames in os.walk(p):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith('.'))
                out.extend(os.path.join(dirpath, f) for f in sorted(filenames)
                           if f.lower().endswith(TYPE_FILE_SUFFIXES))
    seen = set()
    return [f for f in out if not (f in seen or seen.add(f))]


def definitions_in_file(path: str) -> typing.Dict[str, TypeDefinition]:
    """The type definitions of a YAML file (section item_types), cached until the file changes."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    cached = _FILE_CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    defs = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        if 'item_types' in text:
            data = yaml.safe_load(text)
            section = data.get('item_types') if isinstance(data, dict) else None
            if isinstance(section, dict) and section:
                storage = redvypr_metadata.normalize_metadata(short_form_to_storage(section))
                defs = definitions_from_storage(storage)
    except Exception:
        logger.warning(f'could not read item types from {path}', exc_info=True)
    _FILE_CACHE[path] = (mtime, defs)
    return defs


def find_definitions(names, paths) -> typing.Dict[str, TypeDefinition]:
    """
    Definitions of the types names (and of their bases not known yet) in the type
    directories/files paths; the first file (in the order of paths) wins.
    """
    wanted = set(n for n in names if n)
    found = {}
    files = type_files(paths)
    for _depth in range(ritems.MAX_TREE_DEPTH):
        missing = wanted - set(found)
        if not missing:
            break
        for path in files:
            for name, defn in definitions_in_file(path).items():
                if name in missing and name not in found:
                    found[name] = defn
                    _FOUND_IN[name] = path
        bases = {d.base for d in found.values()
                 if d.base and d.base not in found and d.base not in ritems.ITEM_TYPES}
        if not bases - wanted:
            break
        wanted |= bases
    return found


def used_types(storage: dict) -> typing.Set[str]:
    """Item types used by the items of a storage."""
    return {t for (t, i) in ritems.item_keys(storage) if t and i}


def resolve_types(storage: dict, paths) -> typing.List[str]:
    """
    Registers the definitions of the item types used in a storage that are not
    defined as data yet (unknown types, and Python types a definition may extend),
    searched in paths (see find_definitions()). Returns the names registered.
    """
    needed = [t for t in used_types(storage) if type_origin(t) != 'data']
    if not needed or not paths:
        return []
    defs = find_definitions(needed, paths)
    registered = register_definitions(defs, sources={n: _FOUND_IN.get(n) for n in defs}) if defs else []
    unknown = sorted(t for t in needed if t not in ritems.ITEM_TYPES)
    if unknown:
        logger.info(f'no definition found for the item types {unknown} (generic Item)')
    return registered


# --- editing (type editor of the Items window) ---------------------------------------------

def write_definition(path: str, defn: TypeDefinition, valid_from=None) -> str:
    """
    Writes a definition into a library file (new values from valid_from, default now;
    the history stays). The other contents of the file (other types, items,
    calibrations) are kept; a missing file is created. Returns the path.
    """
    import os as _os
    import redvypr.metadata_sources as ms
    storage = {}
    if _os.path.exists(path):
        storage = ms.read_library_storage(path)
    add_definition(storage, defn, valid_from=valid_from)
    ms.save_metadata_library(path, storage)
    _FILE_CACHE.pop(_os.path.abspath(path), None)
    _FILE_CACHE.pop(path, None)
    return path


def python_fields(cls: typing.Type[ritems.Item]) -> typing.Dict[str, str]:
    """Fields of a model with their description (for showing inherited fields)."""
    return {k: (f.description or '') for k, f in cls.model_fields.items()}


def _kind_of_value(value) -> typing.Tuple[str, typing.Optional[str]]:
    """(kind, unit) of a field value of an item."""
    if isinstance(value, bool):
        return 'bool', None
    if isinstance(value, int):
        return 'int', None
    if isinstance(value, float):
        return 'float', None
    if isinstance(value, ritems.Quantity):
        return 'quantity', value.unit or None
    if isinstance(value, dict) and isinstance(value.get('value'), (int, float)) and 'unit' in value:
        return 'quantity', value.get('unit') or None
    if isinstance(value, dict):
        return 'dict', None
    if isinstance(value, list):
        return 'list', None
    return 'str', None


def definition_from_item(item: ritems.Item, name: typing.Optional[str] = None) -> TypeDefinition:
    """
    A definition proposed from an item: its additional fields (not in its model) become
    fields of the type (kind and unit from the values), manufacturer and mpn defaults.
    """
    fields = {}
    for key, value in (item.model_extra or {}).items():
        kind, unit = _kind_of_value(value)
        fields[key] = FieldDefinition(kind=kind, unit=unit)
    defaults = {k: getattr(item, k) for k in ('manufacturer', 'mpn') if getattr(item, k, None)}
    return TypeDefinition(name=name or item.itemtype, description=item.description, fields=fields,
                          defaults=defaults)


def definition_of(name: str) -> typing.Optional[TypeDefinition]:
    """The data definition of a registered type, None for a type defined only in Python."""
    return DATA_TYPES.get(name)


def type_origin(name: str) -> str:
    """'python', 'data' (defined as data, possibly extending a Python type) or 'unknown'."""
    cls = ritems.ITEM_TYPES.get(name)
    if cls is None:
        return 'unknown'
    return getattr(cls, 'ORIGIN', 'python')


def remember_python_types():
    """Notes the Python types registered so far (called on import; later ones are found on use)."""
    for name, cls in ritems.ITEM_TYPES.items():
        if getattr(cls, 'ORIGIN', 'python') == 'python':
            _PYTHON_TYPES.setdefault(name, cls)


remember_python_types()
