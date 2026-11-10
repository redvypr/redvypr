"""
Attachments of items (photos, test reports, data sheets), design note
doc/source/design_items.rst, section "Sensors, calibrations and the sensor manager".

The files are copied into an attachment folder::

    <attachments>/<itemtype>/<id>/<uuid>/<file name>

(default: the folder ``attachments`` next to the first item library, e.g. in
the inventory repository; configuration ``item_attachments_path``). The item
lists them in its field ``attachments`` (one entry per file: uuid, file name,
description, size, sha256, time added), so the list has a history like every
field.
"""

import datetime
import hashlib
import mimetypes
import os
import shutil
import typing
import uuid as uuidlib

import pydantic

import redvypr.items as ritems

DEFAULT_FOLDER = 'attachments'


class AttachmentMetadata(pydantic.BaseModel):
    """One attached file of an item."""
    model_config = pydantic.ConfigDict(extra='allow')
    attachment_uuid: str = pydantic.Field(default_factory=lambda: str(uuidlib.uuid4()))
    file_name: str
    description: typing.Optional[str] = None
    mime_type: str = 'application/octet-stream'
    file_size_bytes: int = 0
    sha256: str = ''
    added: typing.Optional[str] = None

    @pydantic.field_validator('attachment_uuid', mode='before')
    @classmethod
    def _uuid_text(cls, v):
        return str(v)


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def attachments_of(item: ritems.Item) -> typing.List[AttachmentMetadata]:
    """The attachments of an item (field attachments; entries that are no attachments are skipped)."""
    out = []
    for a in getattr(item, 'attachments', None) or []:
        try:
            out.append(a if isinstance(a, AttachmentMetadata) else
                       AttachmentMetadata.model_validate(a.model_dump(mode='json') if hasattr(a, 'model_dump') else a))
        except (pydantic.ValidationError, TypeError):
            continue
    return out


def attachment_dir(base: str, item: ritems.Item, attachment_uuid: str) -> str:
    return os.path.join(base, item.itemtype, item.id, str(attachment_uuid))


def attachment_path(base: str, item: ritems.Item, att: AttachmentMetadata) -> str:
    return os.path.join(attachment_dir(base, item, att.attachment_uuid), att.file_name)


def _as_field(atts: typing.List[AttachmentMetadata]) -> list:
    return [a.model_dump(exclude_none=True) for a in atts]


def add_attachment(redvypr_instance, item: ritems.Item, source_path: str, base: str,
                   description: typing.Optional[str] = None, valid_from=None) -> AttachmentMetadata:
    """Copies a file into the attachment folder and adds it to the field attachments of the item."""
    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)
    now = datetime.datetime.now(datetime.timezone.utc)
    att = AttachmentMetadata(
        file_name=os.path.basename(source_path), description=description or None,
        mime_type=mimetypes.guess_type(source_path)[0] or 'application/octet-stream',
        file_size_bytes=os.path.getsize(source_path), sha256=sha256_of(source_path),
        added=now.isoformat())
    target = attachment_dir(base, item, att.attachment_uuid)
    os.makedirs(target, exist_ok=True)
    shutil.copy2(source_path, os.path.join(target, att.file_name))
    atts = attachments_of(item) + [att]
    redvypr_instance.add_item(item, valid_from=valid_from or now, fields={'attachments': _as_field(atts)})
    return att


def remove_attachment(redvypr_instance, item: ritems.Item, attachment_uuid: str, base: str,
                      delete_file: bool = True, valid_from=None) -> bool:
    """Removes an attachment from the field attachments of the item (and its file)."""
    atts = attachments_of(item)
    keep = [a for a in atts if a.attachment_uuid != str(attachment_uuid)]
    if len(keep) == len(atts):
        return False
    if delete_file:
        folder = attachment_dir(base, item, attachment_uuid)
        if os.path.isdir(folder):
            shutil.rmtree(folder)
    when = valid_from or datetime.datetime.now(datetime.timezone.utc)
    redvypr_instance.add_item(item, valid_from=when, fields={'attachments': _as_field(keep)})
    return True
