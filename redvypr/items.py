"""
Items: physical things (a logger, an add-on board, a sensor, a cable) and
templates (setup profiles) kept in the redvypr metadata.

Design: doc/source/design_items.rst. An item lives at the metadata address
``@i:'item' and d:'<itemtype>' and di:'<id>'``; every field is its own
metadata key with its own validity period. Items form a tree: every item
names its ``parent`` (item reference ``<itemtype>/<id>``) and its ``slot``
on the parent. The root item names its data source (``deviceid``,
``sensorid`` or ``device``, like the address entries ``di``, ``si``, ``d``),
so the items of a datastream are found with :func:`get_items`.

The functions work on a metadata storage ``{address: [entries]}`` (the format
of ``deviceinfo_all['metadata']``, of ``Redvypr._copy_metadata()`` and of
``DbReader.metadata_storage()``).
"""

import logging
import typing

import pydantic

import redvypr.metadata as redvypr_metadata
from redvypr.redvypr_address import RedvyprAddress

logger = logging.getLogger('redvypr.items')

ITEM_PACKETID = 'item'
# Fields that are part of the address, not stored as metadata keys
ADDRESS_FIELDS = ('itemtype', 'id')
# Fields of an item naming its data source, with the address entry they match
SOURCE_FIELDS = (('deviceid', 'deviceid'), ('sensorid', 'sensorid'), ('device', 'device'))
# Maximum depth of the tree (protection against loops in parent references)
MAX_TREE_DEPTH = 32


class ItemError(Exception):
    pass


class Quantity(pydantic.BaseModel):
    """A value with unit, e.g. a measured resistor: {value: 10002.7, unit: Ohm}."""
    model_config = pydantic.ConfigDict(extra='allow')
    value: float
    unit: str = ''
    uncertainty: typing.Optional[float] = None
    method: typing.Optional[str] = None
    date: typing.Optional[str] = None


class Item(pydantic.BaseModel):
    """
    Generic item. Specific types derive from it, set ITEMTYPE and REVISION and
    are registered with :func:`register_item_type`. Unknown fields are kept
    (extra='allow'), so an item of an unknown type or of a newer revision is
    not lost.
    """
    model_config = pydantic.ConfigDict(extra='allow')

    ITEMTYPE: typing.ClassVar[str] = 'item'
    # Revision of the type: count up with every change of the fields. A new
    # optional field needs no migration; renamed fields or changed meanings
    # are handled in migrate().
    REVISION: typing.ClassVar[int] = 1

    itemtype: str = pydantic.Field(default='item', description='Type of the item')
    id: str = pydantic.Field(default='', description='Serial number or name, unique per item type')
    uuid: typing.Optional[str] = pydantic.Field(default=None, description='Optional globally unique id')
    type_revision: typing.Optional[int] = pydantic.Field(default=None,
                                                         description='Revision of the type the item was written with')
    name: typing.Optional[str] = None
    sn: typing.Optional[str] = pydantic.Field(default=None, description='Serial number of the thing, if not '
                                                                       'the id (e.g. sn of a norlog, id = hwid)')
    description: typing.Optional[str] = None
    location: typing.Optional[str] = pydantic.Field(default=None, description='Where the thing is or measures')
    manufacturer: typing.Optional[str] = None
    mpn: typing.Optional[str] = pydantic.Field(default=None, description='Manufacturer part number')
    batch: typing.Optional[str] = None
    hw_revision: typing.Optional[str] = pydantic.Field(default=None, description='Hardware revision of the thing')
    order: typing.Optional[dict] = pydantic.Field(default=None, description='Supplier, number, date, ...')
    parent: typing.Optional[str] = pydantic.Field(default=None, description='Item reference <itemtype>/<id>')
    slot: typing.Optional[str] = pydantic.Field(default=None, description='Where on the parent, e.g. a channel name')
    deviceid: typing.Optional[str] = pydantic.Field(default=None, description='Data source: deviceid of its packets')
    sensorid: typing.Optional[str] = pydantic.Field(default=None, description='Data source: sensorid of its packets')
    device: typing.Optional[str] = pydantic.Field(default=None, description='Data source: device name of its packets')
    status: typing.Optional[str] = pydantic.Field(default=None, description='e.g. retired')
    attachments: typing.Optional[list] = None
    comment: typing.Optional[str] = None

    @pydantic.model_validator(mode='before')
    @classmethod
    def _itemtype_of_class(cls, data):
        """A specific type gets its ITEMTYPE (the generic Item takes the given one)."""
        if isinstance(data, dict) and cls is not Item:
            if data.get('itemtype') not in (None, '', cls.ITEMTYPE):
                raise ValueError(f"itemtype {data.get('itemtype')!r} does not fit {cls.__name__} ({cls.ITEMTYPE})")
            data = dict(data)
            data['itemtype'] = cls.ITEMTYPE
        return data

    @classmethod
    def migrate(cls, fields: dict, from_revision: int) -> dict:
        """Convert the stored fields of an older revision of this type (default: unchanged)."""
        return fields

    @property
    def ref(self) -> str:
        return make_ref(self.itemtype, self.id)

    @property
    def address(self) -> str:
        return item_address(self.itemtype, self.id)


ITEM_TYPES: typing.Dict[str, typing.Type[Item]] = {}


def register_item_type(cls: typing.Type[Item]) -> typing.Type[Item]:
    """Register an item type (usable as decorator); its ITEMTYPE is the name."""
    if not (isinstance(cls, type) and issubclass(cls, Item)):
        raise TypeError(f'{cls!r} is not a subclass of Item')
    ITEM_TYPES[cls.ITEMTYPE] = cls
    return cls


register_item_type(Item)


@register_item_type
class SetupItem(Item):
    """
    A setup profile: a template (id = its name, no physical thing) describing a
    measurement setup, e.g. a breakout board with sensors at the ADC of a logger.
    'channels' maps the channel names (datakeys) to their properties; 'slot' is
    the slot of the item measured by the channel (e.g. a terminal 'J2.3-4'), so
    items may name terminals instead of channel names. The device names its
    profile with the metadata key 'setup' (a name, or {packetid: name}).
    Device specific fields (norlog: 'sensor', 'sequence') are additional fields.
    """
    ITEMTYPE: typing.ClassVar[str] = 'setup'
    REVISION: typing.ClassVar[int] = 1
    title: typing.Optional[str] = pydantic.Field(default=None, description='Short title of the profile')
    board_type: typing.Optional[str] = pydantic.Field(default=None, description='Item type of the board')
    channels: typing.Optional[dict] = pydantic.Field(
        default=None, description='channel -> {slot, cal, unit, scale, scale_ref, hint, ...}')

    def channel_of_slot(self, slot: str) -> typing.Optional[str]:
        for ch, props in (self.channels or {}).items():
            if isinstance(props, dict) and props.get('slot') == slot:
                return ch
        return None

    def slot_of_channel(self, channel: str) -> typing.Optional[str]:
        props = (self.channels or {}).get(channel)
        return props.get('slot') if isinstance(props, dict) else None


# Templates registered in code (e.g. built-in setup profiles of a device module), ref -> item.
# get_item() returns them if the storage has no item of that reference.
BUILTIN_ITEMS: typing.Dict[str, Item] = {}


def register_builtin_item(item: Item) -> Item:
    """Register a built-in item (a template in code); an item of the same reference in the metadata wins."""
    make_ref(item.itemtype, item.id)
    BUILTIN_ITEMS[item.ref] = item
    return item


def get_item_type(itemtype: str) -> typing.Type[Item]:
    """The model of an item type; the generic Item for unknown types."""
    return ITEM_TYPES.get(itemtype, Item)


# --- references and addresses ------------------------------------------------------

def _check_name(what, value):
    if not isinstance(value, str) or not value or "'" in value or '"' in value:
        raise ItemError(f'{what} must be a non-empty string without quotes: {value!r}')


def make_ref(itemtype: str, item_id: str) -> str:
    """Item reference '<itemtype>/<id>'."""
    _check_name('itemtype', itemtype)
    _check_name('id', item_id)
    if '/' in itemtype:
        raise ItemError(f'itemtype must not contain "/": {itemtype!r}')
    return f'{itemtype}/{item_id}'


def parse_ref(ref: str) -> typing.Tuple[str, str]:
    """(itemtype, id) of an item reference; the id may contain '/'."""
    if not isinstance(ref, str) or '/' not in ref:
        raise ItemError(f'item reference must be <itemtype>/<id>: {ref!r}')
    itemtype, item_id = ref.split('/', 1)
    _check_name('itemtype', itemtype)
    _check_name('id', item_id)
    return itemtype, item_id


def item_address(itemtype: str, item_id: str) -> str:
    """Metadata address of an item."""
    _check_name('itemtype', itemtype)
    _check_name('id', item_id)
    raddr = RedvyprAddress('@', packetid=ITEM_PACKETID, device=itemtype, deviceid=item_id)
    return raddr.to_address_string()


def _item_id_of(raddr) -> typing.Optional[str]:
    """
    Id ('di') of a parsed item address, None without an id, '' if the address is no item
    address (other id entries like 'si' or a sensor name).
    """
    if raddr.sensor is not None or raddr.sensorid:
        return ''
    return raddr.deviceid or None


def parse_item_address(address) -> typing.Optional[typing.Tuple[str, str]]:
    """(itemtype, id) if address is the address of an item, else None."""
    try:
        raddr = address if isinstance(address, RedvyprAddress) else RedvyprAddress(address)
        if raddr.packetid != ITEM_PACKETID or not raddr.device:
            return None
        if raddr.get_datakeyentries():
            return None
        item_id = _item_id_of(raddr)
        if not item_id:
            return None
        return raddr.device, item_id
    except Exception:
        return None


# --- writing ------------------------------------------------------------------------

def item_fields(item: Item) -> dict:
    """The metadata keys of an item: all set fields except type and id, with the type revision."""
    fields = item.model_dump(mode='json', exclude_none=True)
    for k in ADDRESS_FIELDS:
        fields.pop(k, None)
    cls = type(item)
    if cls is Item:
        # generic model (also for unknown types): keep the stored revision
        fields['type_revision'] = item.type_revision or 1
    else:
        if item.type_revision is not None and item.type_revision > cls.REVISION:
            raise ItemError(f'{item.ref} has revision {item.type_revision}, newer than {cls.REVISION} '
                            f'of this redvypr: not written')
        fields['type_revision'] = cls.REVISION
    return fields


def item_metadata_dict(item: Item, valid_from=None, hostinfo=None, fields: typing.Optional[dict] = None) -> dict:
    """
    Metadata of an item in the storage format {address: [entries]}, one entry
    per field. fields: only these keys (e.g. one changed field), default all.
    """
    make_ref(item.itemtype, item.id)        # checks type and id
    values = item_fields(item) if fields is None else dict(fields)
    return redvypr_metadata.create_metadata_dict(item_address(item.itemtype, item.id), values,
                                                 hostinfo=hostinfo, valid_from=valid_from)


def add_item(storage: dict, item: Item, valid_from=None, hostinfo=None, fields=None) -> bool:
    """
    Write an item into a metadata storage. Unchanged fields add nothing
    (merge rules of the storage); a changed field ends its previous entry at
    valid_from. Writing the whole item (fields=None) also ends the entries of
    fields it does not have any more (a cleared field, a field renamed by a
    migration). fields: write only these keys. Returns True if the storage changed.
    """
    md = item_metadata_dict(item, valid_from=valid_from, hostinfo=hostinfo, fields=fields)
    status = redvypr_metadata.add_metadata_to_entries(md, storage)
    changed = status['metadata_changed']
    if fields is None:
        address, entries = next(iter(md.items()))
        keys = {e['key'] for e in entries}
        t_from = redvypr_metadata.to_datetime(entries[0]['constraints']['valid_from']) if entries else None
        for e in storage.get(address, []):
            c = e.setdefault('constraints', {})
            if e['key'] in keys or redvypr_metadata.get_context(c) or t_from is None:
                continue
            e_from = redvypr_metadata.to_datetime(c.get('valid_from'))
            e_until = redvypr_metadata.to_datetime(c.get('valid_until'))
            if (e_from is None or e_from < t_from) and (e_until is None or e_until > t_from):
                c['valid_until'] = t_from.isoformat()
                changed = True
    return changed


# --- reading ------------------------------------------------------------------------

def _query(storage, address, at_time, mode='merge'):
    return redvypr_metadata.get_metadata({'metadata': storage}, address=address, mode=mode, at_time=at_time)


def item_keys(storage: dict) -> dict:
    """
    The item addresses of a storage: {(itemtype, id): [address strings]}, with the defaults
    (None, None) for '@i:'item'' (all items) and (itemtype, None) for '@i:'item' and d:'<type>''.
    Other address forms are not item addresses. The parsed addresses are cached, so one pass is cheap.
    """
    keys = {}
    for astr in list(storage.keys()):
        try:
            raddr = redvypr_metadata._parsed_address(astr)[0]
        except Exception:
            continue
        if raddr.packetid != ITEM_PACKETID or raddr.get_datakeyentries():
            continue
        item_id = _item_id_of(raddr)
        if item_id == '' or (item_id and not raddr.device):
            continue
        keys.setdefault((raddr.device or None, item_id), []).append(astr)
    return keys


def _fields_at(storage: dict, addresses, at_time) -> dict:
    """Values of the entries at these addresses valid at a time (default now); later entries win."""
    t = redvypr_metadata.to_datetime(at_time) if at_time is not None else \
        redvypr_metadata.to_datetime(__import__('time').time())
    fields = {}
    for astr in addresses or []:
        for e in storage.get(astr) or []:
            c = e.get('constraints') or {}
            f = redvypr_metadata.to_datetime(c.get('valid_from'))
            u = redvypr_metadata.to_datetime(c.get('valid_until'))
            if (f is None or f <= t) and (u is None or t < u):
                fields[e['key']] = e['value']
    return fields


def item_from_fields(itemtype: str, item_id: str, fields: dict) -> Item:
    """
    Model of an item from its stored fields: migrated from an older revision
    of its type, the generic Item if the type is unknown or the fields do not
    validate.
    """
    cls = get_item_type(itemtype)
    fields = dict(fields)
    rev = fields.get('type_revision') or 1
    if cls is not Item and rev < cls.REVISION:
        try:
            fields = cls.migrate(fields, rev)
        except Exception:
            logger.warning(f'could not migrate {itemtype}/{item_id} from revision {rev}', exc_info=True)
    elif cls is not Item and rev > cls.REVISION:
        logger.warning(f'{itemtype}/{item_id} has revision {rev}, newer than {cls.REVISION} of this redvypr')
    fields.update(itemtype=itemtype, id=item_id)
    try:
        return cls.model_validate(fields)
    except pydantic.ValidationError:
        logger.warning(f'{itemtype}/{item_id} does not validate as {cls.__name__}, using Item', exc_info=True)
        return Item.model_validate(fields)


def get_item(storage: dict, ref_or_type: str, item_id: typing.Optional[str] = None,
             at_time=None, builtin: bool = True, keys: typing.Optional[dict] = None) -> typing.Optional[Item]:
    """
    An item at a time (default now): get_item(storage, 'breakout_board_v01/BO-003') or
    get_item(storage, 'breakout_board_v01', 'BO-003'). None if it has no fields at that time;
    then a built-in item of that reference if builtin (register_builtin_item()).

    The item reads the entries at its own address and the defaults at '@i:'item'' (all items) and
    '@i:'item' and d:'<type>'' (its type): all items, then the type, then the item; the more specific
    wins. It exists only if its own address has fields at that time. keys: result of item_keys().
    """
    itemtype, item_id = parse_ref(ref_or_type) if item_id is None else (ref_or_type, item_id)
    make_ref(itemtype, item_id)
    keys = item_keys(storage) if keys is None else keys
    own = _fields_at(storage, keys.get((itemtype, item_id)), at_time)
    if not own:
        return BUILTIN_ITEMS.get(make_ref(itemtype, item_id)) if builtin else None
    fields = _fields_at(storage, keys.get((None, None)), at_time)
    fields.update(_fields_at(storage, keys.get((itemtype, None)), at_time))
    fields.update(own)
    return item_from_fields(itemtype, item_id, fields)


def item_addresses(storage: dict, itemtype: typing.Optional[str] = None,
                   keys: typing.Optional[dict] = None) -> typing.List[typing.Tuple[str, str]]:
    """(itemtype, id) of all items in a storage (at any time), sorted."""
    keys = item_keys(storage) if keys is None else keys
    return sorted(k for k in keys if k[0] and k[1] and (itemtype is None or k[0] == itemtype))


def list_items(storage: dict, itemtype: typing.Optional[str] = None, at_time=None,
               keys: typing.Optional[dict] = None) -> typing.List[Item]:
    """All items existing at a time (default now), optionally of one type."""
    keys = item_keys(storage) if keys is None else keys
    items = []
    for t, i in item_addresses(storage, itemtype, keys=keys):
        item = get_item(storage, t, i, at_time=at_time, builtin=False, keys=keys)
        if item is not None:
            items.append(item)
    return items


def get_item_history(storage: dict, ref: str) -> typing.List[dict]:
    """All stored entries of an item (key, value, constraints), sorted by key and valid_from."""
    itemtype, item_id = parse_ref(ref)
    entries = []
    for astr in item_keys(storage).get((itemtype, item_id), []):
        for e in storage.get(astr) or []:
            e = dict(e)
            e['source_address'] = astr
            entries.append(e)
    return sorted(entries, key=lambda e: (e['key'], str(e.get('constraints', {}).get('valid_from'))))


def find_by_uuid(storage: dict, uuid: str, at_time=None) -> typing.Optional[Item]:
    for item in list_items(storage, at_time=at_time):
        if item.uuid == uuid:
            return item
    return None


def children(storage: dict, ref: str, at_time=None, items=None) -> typing.List[Item]:
    """Items whose parent is ref at a time."""
    items = list_items(storage, at_time=at_time) if items is None else items
    return [it for it in items if it.parent == ref]


# --- resolving the items of a datastream ----------------------------------------------

def _datakey_candidates(datakey: str) -> typing.List[str]:
    """The datakey and its prefixes without '_suffix' ('ntc0_raw' -> 'ntc0')."""
    cands = [datakey]
    while '_' in datakey:
        datakey = datakey.rsplit('_', 1)[0]
        if datakey:
            cands.append(datakey)
    return cands


def source_items(storage: dict, address, at_time=None, items=None) -> typing.List[Item]:
    """Items naming the data source of an address (deviceid, sensorid or device)."""
    raddr = address if isinstance(address, RedvyprAddress) else RedvyprAddress(address)
    items = list_items(storage, at_time=at_time) if items is None else items
    found = []
    for it in items:
        for field, attr in SOURCE_FIELDS:
            value = getattr(it, field, None)
            if value is not None and getattr(raddr, attr, None) == value:
                found.append(it)
                break
    return found


def get_items(storage: dict, address, at_time=None) -> typing.Dict[str, Item]:
    """
    The items of a datastream at a time (default now), as {role: item}.

    1. A key 'items' ({role: item reference}) at the data address itself
       overrides the tree (devices without a tree).
    2. Otherwise the item naming the data source of the address is the
       'device'; in its tree (children by 'parent', valid at the time) the
       item whose 'slot' equals the datakey (or the datakey without a
       '_suffix', 'ntc0_raw' -> 'ntc0') is the 'sensor', its parent the
       'board' (if it is not the device itself). If no item has that slot and
       the device names a setup profile (metadata 'setup'), the slot the
       profile gives the channel is used (e.g. a terminal 'J2.3-4'); the
       profile is returned as 'setup'.
    Returns {} if nothing is found.
    """
    raddr = address if isinstance(address, RedvyprAddress) else RedvyprAddress(address)
    # 1. Explicit assignment at the data address
    md = _query(storage, raddr, at_time)
    refs = md.get('items') if isinstance(md, dict) else None
    if isinstance(refs, dict) and refs:
        result = {}
        keys = item_keys(storage)
        for role, ref in refs.items():
            try:
                item = get_item(storage, ref, at_time=at_time, keys=keys)
            except ItemError:
                logger.warning(f'invalid item reference {ref!r} at {raddr}')
                continue
            if item is not None:
                result[role] = item
        return result

    # 2. Tree of the device
    keys = item_keys(storage)
    items = list_items(storage, at_time=at_time, keys=keys)
    devices = source_items(storage, raddr, at_time=at_time, items=items)
    if not devices:
        return {}
    if len(devices) > 1:
        logger.warning(f'several items name the source of {raddr}: {[d.ref for d in devices]}, using the first')
    device = devices[0]
    result = {'device': device}
    datakey = raddr.datakey
    if not datakey:
        return result

    by_parent = {}
    for it in items:
        if it.parent:
            by_parent.setdefault(it.parent, []).append(it)
    # breadth first through the tree of the device
    descendants = []
    level = [device]
    seen = {device.ref}
    for _ in range(MAX_TREE_DEPTH):
        nxt = []
        for it in level:
            for ch in by_parent.get(it.ref, []):
                if ch.ref not in seen:
                    seen.add(ch.ref)
                    descendants.append(ch)
                    nxt.append(ch)
        if not nxt:
            break
        level = nxt

    # 3. slots: the datakey itself, 4. else the slot the setup profile gives the channel
    setup = setup_of(storage, raddr, at_time=at_time, metadata=md, keys=keys)
    if setup is not None:
        result['setup'] = setup
    slots = []
    for cand in _datakey_candidates(str(datakey)):
        slots.append(cand)
    if setup is not None:
        for cand in _datakey_candidates(str(datakey)):
            slot = setup.slot_of_channel(cand)
            if slot and slot not in slots:
                slots.append(slot)
    for slot in slots:
        matches = [it for it in descendants if it.slot == slot]
        if matches:
            if len(matches) > 1:
                logger.warning(f'several items in slot {slot!r} of {device.ref}: {[m.ref for m in matches]}')
            sensor = matches[0]
            result['sensor'] = sensor
            if sensor.parent and sensor.parent != device.ref:
                board = next((it for it in descendants if it.ref == sensor.parent), None)
                if board is not None:
                    result['board'] = board
            break
    return result


def setup_name(metadata: dict, packetid=None) -> typing.Optional[str]:
    """Name of the setup profile in the metadata of a data address: key 'setup', a name or {packetid: name}."""
    value = (metadata or {}).get('setup')
    if isinstance(value, dict):
        value = value.get(packetid) if packetid is not None else None
    return value if isinstance(value, str) and value else None


def setup_of(storage: dict, address, at_time=None, metadata=None, keys=None) -> typing.Optional[SetupItem]:
    """The setup profile item a datastream names at a time (metadata 'setup' of its device), or None."""
    raddr = address if isinstance(address, RedvyprAddress) else RedvyprAddress(address)
    md = _query(storage, raddr, at_time) if metadata is None else metadata
    name = setup_name(md, raddr.packetid)
    if not name:
        return None
    try:
        item = get_item(storage, SetupItem.ITEMTYPE, name, at_time=at_time, keys=keys)
    except ItemError:
        return None
    return item if isinstance(item, SetupItem) else None


# --- parameters of items (e.g. a calibration taking R_ref from the board) ------------------

def param_value(value) -> typing.Optional[float]:
    """Number of a field value: a number, a Quantity or a dict with 'value'; else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Quantity):
        return float(value.value)
    if isinstance(value, dict) and isinstance(value.get('value'), (int, float)):
        return float(value['value'])
    return None


def resolve_param(storage: dict, address, role: str, key: str, at_time=None,
                  found: typing.Optional[dict] = None):
    """
    A parameter of the item in a role of a datastream at a time, e.g.
    resolve_param(storage, "ntc0 @ i:'adc_brd' and di:'0xA1B2'", 'board', 'R1').
    found: result of get_items() for this address and time (avoids a second resolution).
    Returns (number or None, item or None).
    """
    found = get_items(storage, address, at_time=at_time) if found is None else found
    item = found.get(role)
    if item is None:
        return None, None
    return param_value(getattr(item, key, None)), item
