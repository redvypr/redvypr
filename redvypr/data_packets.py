import copy
import time
import logging
import sys
import re
import numpy as np
import redvypr
#import redvypr.redvypr_address as redvypr_address
from redvypr.redvypr_address import RedvyprAddress, redvypr_standard_address_filter
import collections
import pydantic
import typing
from typing import Any, Dict, Optional, Union

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.base.data_packets')
logger.setLevel(logging.DEBUG)

regex_symbol_start = '{'
regex_symbol_end = '}'

#device_redvypr_statdict = {'_redvypr': {}, 'datakeys': [], '_deviceinfo': {},'_keyinfo': {},'packets_received':0,'packets_published':0,'packets_droped':0}
redvypr_data_keys = ['_redvypr','_redvypr_command','_deviceinfo','_keyinfo','_metadata']

# Defintions for common metadata types
class RedvyprMetadata(pydantic.BaseModel):
    address: typing.Dict[RedvyprAddress, typing.Any] = {}
class RedvyprDeviceMetadata(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")
    location: str = ''
    comment: str = ''

class RedvyprDatastreamMetadata(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="allow")
    unit: str = ''
    comment: str = ''

class RedvyprMetadataGeneral(pydantic.BaseModel):
    address: typing.Dict[str, typing.Any] = {}

class Datapacket(dict):
    """
    The `Datapacket` class extends the built-in `dict` class to include additional functionality for managing
    data packets, including initialization with specific parameters and automatic generation of metadata that is
    used by redvypr to identify a datapacket.
    A main functionality is to retrieve data using redvypr addresses.

    Examples
    --------
    >>> from redvypr import Datapacket
    >>> from redvypr import RedvyprAddress
    >>> ar = Datapacket({'a': [[2, 3, 4], 2, 3, 4]})
    >>> addr = RedvyprAddress('/k:["a"][0]')
    >>> ar[addr]
    [2, 3, 4]

    Attributes
    ----------
    address : RedvyprAddress
        An address object associated with the data packet, initialized using the data packet's contents.

    Methods
    -------
    __init__(self, *args, device=None, packetid=None, **kwargs):
        Initializes a new instance of the Datapacket class.

    Notes
    -----
    The `Datapacket` class is designed to work with the `redvypr` framework, utilizing helper functions like
    `create_datadict` to populate initial data and `RedvyprAddress` to manage addressing.
    """
    def __init__(self, *args, device=None, packetid=None, **kwargs):
        """
        Initializes a new instance of the Datapacket class.

        Parameters
        ----------
        *args : tuple
            Variable length argument list. If the first argument is a dictionary, it is used to initialize
            the data packet.
        device : str, optional
            The device associated with the data packet. Used to populate the '_redvypr' metadata.
        packetid : str, optional
            A unique identifier for the data packet. Used to populate the '_redvypr' metadata.
        **kwargs : dict
            Additional keyword arguments that can be used to initialize the data packet.

        Notes
        -----
        If the data packet does not contain the key '_redvypr', it is automatically populated using the
        `create_datadict` function. The `address` attribute is also initialized using the data packet's contents.
        """
        if len(args)>0:
            # Check if the datapacket is created from a dictionary, without kwargs
            if isinstance(args[0],dict):
                dict.__init__(self, *args,**kwargs)

        else:
            dict.__init__(self)


        self._cache = {} # For calculated datakeys, etc. ...

        if '_redvypr' not in self.keys():
            #create_datadict(data=None, datakey=None, packetid=None, tu=None, device=None, publisher=None, hostinfo=None)
            dataself = create_datadict(packetid=packetid, device=device)
            self.update(dataself)

        self.address = RedvyprAddress(self)

    def __getitem__(self, key):
        # Check if the key is a string but is a RedvyprAddress
        if isinstance(key,str):
            addr = RedvyprAddress(key)
            data = addr(dict(self),strict=False)
            return data
        # Check if the key is a RedvyprAddress
        elif isinstance(key, RedvyprAddress):
            data = key(dict(self))
            return data
        else:
            return super().__getitem__(key)

    def __setitem__(self, key, value):
        """
        Sets an item securely. Supports deep nested keys using bracket notation (e.g., '["a"][0]["b"]')
        or RedvyprAddress objects, safely evaluating paths without dangerous execution functions.
        """
        self._cache.clear()
        # Extract the datakey string if a RedvyprAddress is passed
        if isinstance(key, RedvyprAddress):
            key = key.datakey

        if isinstance(key, str) and key.startswith('[') and key.endswith(']'):
            # Safely extract all tokens inside brackets: matches either "strings" or integers
            # Example: '["sensors"][0]["temperature"]' -> [('sensors', ''), ('', '0'), ('temperature', '')]
            tokens = re.findall(r'\[(?:["\'](.*?)["\']|(\d+))\]', key)

            if not tokens:
                return super().__setitem__(key, value)

            # Sanitize extracted tokens into valid string keys or integer indices
            path = [t[0] if t[0] else int(t[1]) for t in tokens]

            # Traverse down the nested dictionary structure safely
            current = self
            try:
                for node in path[:-1]:
                    current = current[node]

                # Assign the target value to the final element natively
                current[path[-1]] = value
            except (KeyError, IndexError, TypeError) as e:
                logger.error(f"Failed to resolve nested assignment path '{key}': {e}")
                raise

        else:
            # Fallback for standard key-value assignments
            return super().__setitem__(key, value)

    def update(self, *args, **kwargs):
        self._cache.clear()
        super().update(*args, **kwargs)

    def clear(self):
        self._cache.clear()
        super().clear()

    # --- Core Logic Methods ---
    def datakeys(self, datakeys=None, expand=False, return_type='dict'):
        """
        Retrieves the data keys from the data packet, with options to expand and format the output.
        If expand==True the datakeys are in a format that can be used within an index to the datapacket.

        Examples
        --------
        >>> ar = Datapacket({'a': [[2, 3, 4], 2, 3, 4]})
        >>> ar.datakeys(expand=False)
        ['a']

        >>> ar.datakeys(datakeys=["['a'][1]"], expand=True, return_type='dict')
        {"['a'][1]": ("['a'][1]", int)}

        >>> ar.datakeys(datakeys=["['a'][0]"], expand=True)
        (["['a'][0][0]", "['a'][0][1]", "['a'][0][2]"], {"['a'][0][0]": ("['a'][0][0]", int), "['a'][0][1]": ("['a'][0][1]", int), "['a'][0][2]": ("['a'][0][2]", int)})

        Parameters
        ----------
        datakeys : list or str or RedvyprAddress, optional
            A list of specific data keys to retrieve. If None, all root keys in the data packet
            will be evaluated. If type is str or RedvyprAddress, it is mapped into a predictable key array.
        expand : bool or int, optional
            If True, recursively expands nested dictionary, list, or array structures up to
            a default depth of 100. If an integer is provided, it dictates the custom recursion limit.
            Default is False.
        return_type : str, optional
            The format in which to return the data keys. Options are:
            - 'list': Returns the data keys as a flattened list of bracket strings.
            - 'dict': Returns a map containing paths linked to (path, data_type) metadata tuples.
            - Any other value: Returns a combined JSON-friendly list structure containing [list, dict].
            Default is 'dict'.

        Returns
        -------
        list or dict or tuple
            The target data key map or list in the requested return_type format.
        """
        # Formulate a stable cache hash key. Lists are unhashable, so map collections to a immutable tuple
        cache_key = (
            tuple(datakeys) if isinstance(datakeys, list) else datakeys,
            expand,
            return_type
        )

        # Cache Hit: Instantly return reference if structure hasn't muted
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Cache Miss: Calculate output arrays
        if datakeys is None:
            keys = list(self.keys())
        else:
            if isinstance(datakeys, str):
                datakeys = [RedvyprAddress(datakeys)]
            elif isinstance(datakeys, RedvyprAddress):
                datakeys = [datakeys]
            elif not isinstance(datakeys, list):
                raise ValueError(
                    'datakeys must be None, str, RedvyprAddress or list')

            keys = []
            for k in datakeys:
                if isinstance(k, RedvyprAddress):
                    keys.append(k.left_expr)
                else:
                    keys.append(k)

        # High-performance O(1) set comprehension removal of metadata keys
        filter_set = set(redvypr_data_keys)
        keys = [k for k in keys if k not in filter_set]

        # Fast exit if recursive resolution is bypassed
        if not expand:
            self._cache[cache_key] = keys
            return keys

        # Set maximum iteration boundary
        max_level = 100 if isinstance(expand, bool) else expand
        keys_expand = []
        keys_dict_expand = {"":(self.address.to_address_string(),dict)}

        # Trigger safe recursive tree scanner
        self.__expand_datakeys_recursive__(
            self, keys, level=0, parent_key='',
            key_list=keys_expand, key_dict=keys_dict_expand, max_level=max_level
        )

        # Align return payload format
        if return_type == 'list':
            result = keys_expand
        elif return_type == 'dict':
            result = keys_dict_expand
        else:
            result = [keys_expand, keys_dict_expand]

        # Register result in cache map before passing back to execution path
        self._cache[cache_key] = result
        return result

    def datakeys(self, datakeys=None, expand=False, return_type='dict'):
        """
        Retrieves the data keys from the data packet, with options to expand and format the output.
        If expand==True the datakeys are in a format that can be used within an index to the datapacket.

        Examples
        --------
        >>> ar = Datapacket({'a': [[2, 3, 4], 2, 3, 4]})
        >>> ar.datakeys(expand=False)
        ['a']

        >>> ar.datakeys(datakeys=["['a'][1]"], expand=True, return_type='dict')
        {"['a'][1]": ("['a'][1]", int)}

        >>> ar.datakeys(datakeys=["['a'][0]"], expand=True)
        (["['a'][0][0]", "['a'][0][1]", "['a'][0][2]"], {"['a'][0][0]": ("['a'][0][0]", int), "['a'][0][1]": ("['a'][0][1]", int), "['a'][0][2]": ("['a'][0][2]", int)})

        Parameters
        ----------
        datakeys : list or str or RedvyprAddress, optional
            A list of specific data keys to retrieve. If None, all root keys in the data packet
            will be evaluated. If type is str or RedvyprAddress, it is mapped into a predictable key array.
        expand : bool or int, optional
            If True, recursively expands nested dictionary, list, or array structures up to
            a default depth of 100. If an integer is provided, it dictates the custom recursion limit.
            Default is False.
        return_type : str, optional
            The format in which to return the data keys. Options are:
            - 'list': Returns the data keys as a flattened list of bracket strings.
            - 'dict': Returns a map containing paths linked to (path, data_type) metadata tuples.
            - Any other value: Returns a combined JSON-friendly list structure containing [list, dict].
            Default is 'dict'.

        Returns
        -------
        list or dict or tuple
            The target data key map or list in the requested return_type format.
        """
        # Formulate a stable cache hash key. Lists are unhashable, so map collections to an immutable tuple
        cache_key = (
            tuple(datakeys) if isinstance(datakeys, list) else datakeys,
            expand,
            return_type
        )

        # Cache Hit: Instantly return reference if structure hasn't mutated
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Cache Miss: Calculate output arrays
        if datakeys is None:
            keys = list(self.keys())
        else:
            if isinstance(datakeys, str):
                datakeys = [RedvyprAddress(datakeys)]
            elif isinstance(datakeys, RedvyprAddress):
                datakeys = [datakeys]
            elif not isinstance(datakeys, list):
                raise ValueError(
                    'datakeys must be None, str, RedvyprAddress or list')

            keys = []
            for k in datakeys:
                if isinstance(k, RedvyprAddress):
                    keys.append(k.left_expr)
                else:
                    keys.append(k)

        # High-performance O(1) set comprehension removal of metadata keys
        filter_set = set(redvypr_data_keys)
        keys = [k for k in keys if k not in filter_set]

        # Fast exit if recursive resolution is bypassed
        if not expand:
            self._cache[cache_key] = keys
            return keys

        # Set maximum iteration boundary
        max_level = 100 if isinstance(expand, bool) else expand
        keys_expand = []
        keys_dict_expand = {"": (self.address.to_address_string(), dict)}

        # Trigger safe recursive tree scanner
        self.__expand_datakeys_recursive__(
            self, keys, level=0, parent_key='',
            key_list=keys_expand, key_dict=keys_dict_expand, max_level=max_level
        )

        # Align return payload format
        if return_type == 'list':
            result = keys_expand
        elif return_type == 'dict':
            result = keys_dict_expand
        else:
            result = [keys_expand, keys_dict_expand]

        # Register result in cache map before passing back to execution path
        self._cache[cache_key] = result
        return result

    @staticmethod
    def datastreams_from_datakeys(datakeys_payload, base_address=None,
                                  return_type='address', expand=True,
                                  fallback_types=None):
        """
        Generates datastreams from a pre-calculated datakeys payload (list or dict).
        Automatically extracts the base address if a dict payload is provided.

        Parameters
        ----------
        datakeys_payload : list or dict
            The result from a previous call to `datakeys()`.
        base_address : RedvyprAddress or str, optional
            The base address of the datapacket. If a dict payload containing a root
            key "" is provided, this parameter is automatically resolved.
        return_type : str, optional
            The format of the elements in the returned list. Options are:
            - 'address': Returns a list of pure `RedvyprAddress` objects.
            - 'address_type': Returns a list of lists containing `[RedvyprAddress, data_type]`.
            Default is 'address'.
        expand : bool or int, optional
            Dictates how deep the nested payload structures will be traversed.
            If True, recursively unpacks up to a depth of 100. If an integer is
            provided, it sets a custom recursion limit. Default is True.
        fallback_types : dict, optional
            A dictionary mapping flat keys to their types. Only used if
            datakeys_payload is a flat list and return_type is 'address_type'.

        Returns
        -------
        list of RedvyprAddress or list of list
            A list containing either validated `RedvyprAddress` objects or
            `[RedvyprAddress, type]` arrays representing addressable tracks.
        """
        # If a dictionary is provided, extract the base address from the root "" key
        #print("datakeys payload",datakeys_payload)
        if isinstance(datakeys_payload, dict) and "" in datakeys_payload:
            # The tuple structure is (address_string, data_type) -> extract the string
            base_address = datakeys_payload[""][0]

        # Establish maximum iteration boundary
        max_level = 100 if isinstance(expand, bool) else expand
        if expand is False:
            max_level = 0

        if return_type == 'address_type':
            # Fast-exit fallback: payload is a flat list (e.g., when expand=False during generation)
            if isinstance(datakeys_payload, list):
                if base_address is None:
                    raise ValueError(
                        "base_address is required when payload is a flat list.")
                fallback_types = fallback_types or {}
                return [
                    [RedvyprAddress(base_address, datakey=k),
                     fallback_types.get(k, type(None))]
                    for k in datakeys_payload
                ]

            # Standard tree traversal with depth limitation
            flat_items = []

            def _extract_items(d, level=0):
                if level > max_level:
                    return
                if isinstance(d, dict):
                    for k, v in d.items():
                        if k == "":
                            continue  # Skip container root metadata node
                        if isinstance(v, tuple):
                            flat_items.append(v)
                        else:
                            _extract_items(v, level + 1)

            _extract_items(datakeys_payload, level=0)

            return [
                [RedvyprAddress(base_address, datakey=path), dtype]
                for path, dtype in flat_items
            ]

        else:
            # Fallback/Default: Only pure addresses are requested ('address')
            if isinstance(datakeys_payload, dict):
                flat_keys = []

                def _extract_keys(d, level=0):
                    if level > max_level:
                        return
                    if isinstance(d, dict):
                        for k, v in d.items():
                            if k == "":
                                continue
                            if isinstance(v, tuple):
                                flat_keys.append(v[0])
                            else:
                                _extract_keys(v, level + 1)

                _extract_keys(datakeys_payload, level=0)
                expanded_keys = flat_keys
            else:
                expanded_keys = datakeys_payload

            if base_address is None:
                raise ValueError(
                    "base_address is required if it cannot be extracted from the payload.")

            return [RedvyprAddress(base_address, datakey=d) for d in expanded_keys]

    def datastreams(self, datakeys=None, expand=True, return_type='address'):
        """
        Retrieves the datastreams from the data packet as a list of RedvyprAddress objects
        or as pairs of addresses and their corresponding data types.
        Uses the internal static helper for mapping.

        Parameters
        ----------
        datakeys : list or str or RedvyprAddress, optional
            Target parameter array routed directly to the internal `datakeys` helper.
        expand : bool or int, optional
            Recursion depth indicator routed to the internal `datakeys` helper. Default is True.
        return_type : str, optional
            The format of the elements in the returned list. Options are:
            - 'address': Returns a list of pure `RedvyprAddress` objects.
            - 'address_type': Returns a list of lists containing `[RedvyprAddress, data_type]`.
            Default is 'address'.

        Returns
        -------
        list of RedvyprAddress or list of list
            A list containing either validated `RedvyprAddress` objects or
            `[RedvyprAddress, type]` arrays representing addressable tracks.
        """
        # Fetch the payload utilizing the instance cache mechanisms
        if return_type == 'address_type':
            payload = self.datakeys(datakeys=datakeys, expand=expand,
                                    return_type='dict')
        else:
            payload = self.datakeys(datakeys=datakeys, expand=expand,
                                    return_type='list')

        # Special fallback handler: if expand resolves to a flat list,
        # map types directly via instance lookup using type(self[k])
        fallback_types = None
        if return_type == 'address_type' and isinstance(payload, list):
            fallback_types = {k: type(self[k]) for k in payload}

        # Delegate execution path to the static helper method
        return Datapacket.datastreams_from_datakeys(
            datakeys_payload=payload,
            base_address=self.address,
            return_type=return_type,
            expand=expand,
            fallback_types=fallback_types
        )

    def datastreams_legacy(self, datakeys=None, expand=True, return_type='address'):
        """
        Retrieves the datastreams from the data packet.
        Now uses the static helper method.
        """
        # 1. Hol dir den Payload (Nutzt das Caching in self.datakeys)
        requested_return = 'dict' if return_type == 'address_type' and expand else 'list'

        # Um deinen originalen Code exakt zu spiegeln:
        if return_type == 'address_type':
            payload = self.datakeys(datakeys=datakeys, expand=expand,
                                    return_type='dict')
        else:
            payload = self.datakeys(datakeys=datakeys, expand=expand,
                                    return_type='list')

        # Für den Spezialfall: expand=False UND return_type='address_type'
        # braucht die statische Methode die Typen aus dem aktuellen Packet
        fallback_types = None
        if return_type == 'address_type' and isinstance(payload, list):
            fallback_types = {k: type(self[k]) for k in payload}

        # 2. Delegiere an die statische Methode
        return Datapacket.datastreams_from_datakeys(
            datakeys_payload=payload,
            base_address=self.address,
            return_type=return_type,
            fallback_types=fallback_types
        )

    @staticmethod
    def datastreams_from_datakeys_legacy(datakeys_payload, base_address=None,
                                  return_type='address', fallback_types=None):
        """
        Generates datastreams from a pre-calculated datakeys payload.
        Automatically extracts the base address if a dict payload is provided.
        """
        # Falls ein Dict übergeben wurde, ziehen wir die Basis-Adresse direkt aus dem ""-Key
        if isinstance(datakeys_payload, dict) and "" in datakeys_payload:
            # Das Tuple ist (address_string, data_type) -> wir nehmen den String
            base_address = datakeys_payload[""][0]

        if return_type == 'address_type':
            # Fast-Exit Fallback: Payload ist eine flache Liste (expand=False)
            if isinstance(datakeys_payload, list):
                if base_address is None:
                    raise ValueError(
                        "base_address is required when payload is a flat list.")
                fallback_types = fallback_types or {}
                return [
                    [RedvyprAddress(base_address, datakey=k),
                     fallback_types.get(k, type(None))]
                    for k in datakeys_payload
                ]

            # Normaler Baum-Durchlauf (expand=True)
            flat_items = []

            def _extract_items(d):
                if isinstance(d, dict):
                    for k, v in d.items():
                        if k == "":
                            continue  # Überspringe die Root-Metadaten
                        if isinstance(v, tuple):
                            flat_items.append(v)
                        else:
                            _extract_items(v)

            _extract_items(datakeys_payload)

            return [
                [RedvyprAddress(base_address, datakey=path), dtype]
                for path, dtype in flat_items
            ]

        else:
            # Fallback/Default: Es werden nur reine Adressen gewünscht ('address')
            if isinstance(datakeys_payload, dict):
                flat_keys = []

                def _extract_keys(d):
                    if isinstance(d, dict):
                        for k, v in d.items():
                            if k == "":
                                continue
                            if isinstance(v, tuple):
                                flat_keys.append(v[0])
                            else:
                                _extract_keys(v)

                _extract_keys(datakeys_payload)
                expanded_keys = flat_keys
            else:
                expanded_keys = datakeys_payload

            if base_address is None:
                raise ValueError(
                    "base_address is required if it cannot be extracted from the payload.")

            return [RedvyprAddress(base_address, datakey=d) for d in expanded_keys]

    def __expand_datakeys_recursive__(self, data, keys, level=0, parent_key='',
                                      key_list=None, key_dict=None, max_level=100):
        """
        Recursively scans compound types to record explicit access paths and data typings.
        """
        if key_list is None: key_list = []
        if key_dict is None: key_dict = {}

        for k in keys:
            data_k = data[k]

            # Map structural formats cleanly based on key instance types
            if level == 0:
                strformat = str(k)
            else:
                strformat = f"[{k}]" if isinstance(k, int) else f"['{k}']"

            # Rebuild compound string components using optimized string interpolation
            parent_key_new = f"{parent_key}{strformat}" if level > 0 else strformat

            # Tree traversal phase
            if level < max_level:
                if isinstance(data_k, list):
                    # Maintain structural mirroring inside key_dict depending on context layout
                    if isinstance(key_dict, dict):
                        key_dict[k] = {"": (parent_key_new, list)}
                        #key_dict[k] = {}
                    elif isinstance(key_dict, list):
                        key_dict.append({"": (parent_key_new, list)})
                        #key_dict.append({})

                    target = key_dict[k] if isinstance(key_dict, dict) else \
                    key_dict[-1]

                    self.__expand_datakeys_recursive__(
                        data_k, range(len(data_k)), level=level + 1,
                        parent_key=parent_key_new, key_list=key_list,
                        key_dict=target, max_level=max_level
                    )
                    continue

                elif isinstance(data_k, dict):
                    if isinstance(key_dict, dict):
                        key_dict[k] = {"": (parent_key_new, dict)}
                        #key_dict[k] = {}
                    elif isinstance(key_dict, list):
                        key_dict.append({"": (parent_key_new, dict)})
                        #key_dict.append({})

                    target = key_dict[k] if isinstance(key_dict, dict) else \
                    key_dict[-1]

                    self.__expand_datakeys_recursive__(
                        data_k, data_k.keys(), level=level + 1,
                        parent_key=parent_key_new, key_list=key_list,
                        key_dict=target, max_level=max_level
                    )
                    continue

            # Leaf processing phase (Executed if maximum depth is hit or data element is non-iterable)
            key_list.append(parent_key_new)
            leaf_metadata = (parent_key_new, type(data_k))

            if isinstance(key_dict, dict):
                key_dict[k] = leaf_metadata
            elif isinstance(key_dict, list):
                key_dict.append(leaf_metadata)


    def get_addressstr(self,addrformat='k,i'):
        return self.address.to_address_string(addrformat)

    @staticmethod
    def create_expanded_datadict(t,data,datakey,raddress,address_format='k,i,h,d,p'):
        """
        Options
        1:
            t: float,int
            data: Anything
            format: 0d
        2:
            t: list
            data: float/int/str/binary
            format: 0d
        3:
            t: list
            data: list same length as t
            format: 0d_stacked

        Parameters
        ----------
        t
        data
        datakey
        raddress
        address_format

        Returns
        -------

        """
        data_expanded_tmp = {'format': '0d'}  # can be 0d:one point,0d_stacked: points in a list with time of the same length
        data_expanded_tmp['address'] = RedvyprAddress(raddress, datakey=datakey).to_address_string(address_format)
        try:
            lent = len(t)
            t0 = t[0]
        except:
            lent = -1
            t0 = t
        # print(f"{k=},{data_tmp=}")
        if isinstance(data, list):
            if lent == len(data):
                data_expanded_tmp['t'] = t
                data_expanded_tmp['format'] = '0d_stacked'
            else:
                data_expanded_tmp['t'] = t0

            data_expanded_tmp['data'] = data
            data_expanded_tmp['key'] = datakey
        elif isinstance(data, dict):
            # Here a recursive approach could be done
            data_expanded_tmp['t'] = t0
            data_expanded_tmp['data'] = data
            data_expanded_tmp['key'] = datakey
        else:
            data_expanded_tmp['t'] = t0
            data_expanded_tmp['data'] = data
            data_expanded_tmp['key'] = datakey


        return data_expanded_tmp


    def expand_data(self, expansion_level=1, address_format='k,i,h,d,p'):
        """
        Expands data

        """
        data_tmp = self
        datakeys = self.datakeys()
        data_return = {}
        try:
            t = data_tmp['t']
        except:
            t = data_tmp['_redvypr'].get('t',-1)

        # Get rid of the time
        try:
            datakeys.remove('t')
        except:
            pass

        for k in datakeys:
            data_tmp = self[k]
            data_expanded_tmp = self.create_expanded_datadict(t,data_tmp,k,self.address)
            data_return[data_expanded_tmp['address']] = data_expanded_tmp

        #print(f"{data_return=}")
        return data_return

    @staticmethod
    def get_structure_hash(data):
        """
        Computes a stable, structural fingerprint (hash) of any nested data structure.
        It evaluates dictionary keys and sequence types while completely ignoring
        the volatile values themselves.

        Parameters
        ----------
        data : any
            The nested structure (dict, list, primitive) to fingerprint.

        Returns
        -------
        int
            A deterministic hash integer representing the data layout's skeleton.
        """

        def _fingerprint(node):
            if isinstance(node, dict):
                # Sort keys to ensure consistent order independent of transmission sequence
                return tuple((k, _fingerprint(v)) for k, v in sorted(node.items()))
            elif isinstance(node, list):
                # Sample the first element's structural type if available, otherwise mark empty
                return tuple([_fingerprint(node[0])]) if node else ()
            else:
                # Store the type name as the structural anchor for primitive values
                return type(node).__name__

        # Convert the structural tuple representation into a Python built-in hash integer
        return hash(_fingerprint(data))





def create_datadict(
        data: Optional[Any] = None,
        datakey: Optional[str] = None,
        packetid: Optional[Union[str, int]] = None,
        tu: Optional[float] = None,
        device: Optional[str] = None,
        publisher: Optional[str] = None,
        hostinfo: Optional[Dict[str, Any]] = None,
        random_host: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Creates a datadict dictionary used as the internal data structure in redvypr.

    This function wraps payload data and adds a standardized metadata header
    under the ``_redvypr`` key. If no timestamp is provided, the current
    system time is used.

    :param data: The actual payload data to be stored.
                 If provided, it is stored under the key specified by ``datakey``.
    :type data: Any, optional

    :param datakey: The dictionary key used for the payload data.
                    Defaults to 'data' if ``data`` is present but ``datakey`` is None.
    :type datakey: str, optional

    :param packetid: Unique identifier for the packet.
                     Defaults to the value of ``device`` if None.
    :type packetid: str or int, optional

    :param tu: Unix timestamp (time units) for the packet.
               Defaults to ``time.time()`` if None.
    :type tu: float, optional

    :param device: Identifier of the source device.
    :type device: str, optional

    :param publisher: Identifier of the publishing entity.
    :type publisher: str, optional

    :param hostinfo: Dictionary containing host-related information.
                     Uses ``redvypr.hostinfo_blank`` if None.
    :type hostinfo: dict, optional

    :param random_host: If True, generates a randomized host information
                        using ``redvypr.create_hostinfo``.
    :type random_host: bool, optional

    :return: A dictionary containing the ``_redvypr`` metadata header and
             the optional payload data.
    :rtype: dict[str, Any]

    .. note::
       The resulting dictionary structure is:

       .. code-block:: python

          {
              '_redvypr': {
                  't': float,
                  'device': str,
                  'packetid': str,
                  'publisher': str,
                  'host': dict
              },
              'datakey_name': data_payload  # optional
          }
    """
    if tu is None:
        tu = time.time()

    # Initialize the metadata structure
    datadict: Dict[str, Any] = {'_redvypr': {'t': tu}}

    # Set device and packetid logic
    datadict['_redvypr']['device'] = device
    if packetid is None:
        datadict['_redvypr']['packetid'] = device
    else:
        datadict['_redvypr']['packetid'] = packetid

    datadict['_redvypr']['publisher'] = publisher

    # Handle host information
    if hostinfo is not None:
        datadict['_redvypr']['host'] = hostinfo
    else:
        # Assuming redvypr is available in the namespace
        datadict['_redvypr']['host'] = redvypr.hostinfo_blank

    if random_host is not None:
        datadict['_redvypr']['host'] = redvypr.create_hostinfo(random_host)

    # Insert payload data if present
    if data is not None:
        if datakey is None:
            datakey = 'data'
        datadict[datakey] = data

    return datadict


def create_datadict_legacy(data=None,
                    datakey=None,
                    packetid=None,
                    tu=None,
                    device=None,
                    publisher=None,
                    hostinfo=None,
                    random_host=None):
    """ Creates a datadict dictionary used as internal datastructure in redvypr
    """
    if(tu == None):
        tu = time.time()

    datadict = {'_redvypr':{'t':tu}}
    datadict['_redvypr']['device'] = device
    if (packetid is None):
            datadict['_redvypr']['packetid'] = device
    else:
        datadict['_redvypr']['packetid'] = packetid

    datadict['_redvypr']['publisher'] = publisher
    if (hostinfo is not None):
        datadict['_redvypr']['host'] = hostinfo
    else:
        datadict['_redvypr']['host'] = redvypr.hostinfo_blank
    if random_host is not None:
        datadict['_redvypr']['host'] = redvypr.create_hostinfo(random_host)

    if(data is not None):
        if (datakey == None):
            datakey = 'data'
        datadict[datakey] = data

    return datadict


def create_metadatapacket(metadict=None):
    datapacket = {}
    datapacket['_metadata'] = {}
    for addr,metadata in metadict.items():
        if isinstance(addr,str):
            try:
                RedvyprAddress(addr) # Test if this is a valid RedvyprAddress
            except:
                raise ValueError(f"key {str(addr)} of metadict dictionary must be valid RedvyprAddress string")

            datapacket['_metadata'][addr] = metadata
        else:
            raise ValueError(
                f"key {str(addr)} of metadict dictionary must be valid RedvyprAddress string")



    return datapacket

def add_metadata2datapacket(datapacket, address=None, datakey=None,
                            metakey=None, metadata=None, metadict=None):
    """

    Args:add_metad
        datapacket:
        datakey:
        metakey:
        metadata:

    Returns:

    """
    if True:
        #print('Datapacket',datapacket)
        if address is not None:
            raddress = RedvyprAddress(address)
        if datakey is not None:
            try: # Try first to create a RedvyprAddress from the datapacket itself
                raddress = RedvyprAddress(datapacket, datakey=datakey)
            except:
                logger.info('Could not create address',exc_info=True)
                raddress = RedvyprAddress(datakey=datakey)

        #address_str = raddress.to_address_string(redvypr_standard_address_filter)
        address_str = raddress.to_address_string()
        try:
            datapacket['_metadata']
        except:
            datapacket['_metadata'] = {}

        try:
            datapacket['_metadata'][address_str]
        except:
            datapacket['_metadata'][address_str] = {}

        if (metadata is not None):
            datapacket['_metadata'][address_str][metakey] = metadata

        # If a dictionary with metakeys is given
        if (metadict is not None):
            datapacket['_metadata'][address_str].update(metadict)

    #print('Metadata datapacket',datapacket)
    #print('---done----')
    return datapacket



def commandpacket(command='stop',device_uuid='',thread_uuid='',packetid=None,devicename=None,publisher=None,host=None,comdata=None,devicemodulename=None):
    """

    Args:
        command: 'stop'
        device: The device the command was sent from
        device_uuid:
        thread_uuid:

    Returns:
         compacket: A redvypr dictionary with the command
    """
    compacket = create_datadict({'command':command}, datakey='_redvypr_command') # The command
    if packetid is not None:
        compacket['_redvypr']['packetid'] = packetid  # The device the command was sent from
    if devicename is not None:
        compacket['_redvypr']['device'] = devicename  # The device the command was sent from
    if publisher is not None:
        compacket['_redvypr']['publisher'] = publisher
    if host is not None:
        compacket['_redvypr']['host'] = host
    if devicemodulename is not None:
        compacket['_redvypr']['devicemodulename'] = devicemodulename  # The device the command was sent from
    compacket['_redvypr_command']['device_uuid'] = device_uuid  # The uuid of the device the command is for
    compacket['_redvypr_command']['thread_uuid'] = thread_uuid  # The uuid of the thread of device the command is for
    compacket['_redvypr_command']['data'] = comdata

    return compacket


def deviceinfopacket(deviceadress,statusdict):
    """
    deviceinfopacket for a device thread
    Returns:
         stauspacket: A redvypr statuspacket dictionary
    """
    comdata = {}
    comdata['deviceaddr'] = deviceadress
    comdata['devicestatus'] = statusdict  # This is the status of the device
    datapacket = commandpacket(command='device_status', device_uuid='', thread_uuid='', devicename=None,
                                            host=None, comdata=comdata)
    return datapacket


def statuspacket(deviceadress,statusdict):
    """
    statuspacket for a device thread
    Returns:
         statuspacket: A redvypr statuspacket dictionary
    """
    comdata = {}
    comdata['deviceaddr'] = deviceadress
    comdata['devicestatus'] = statusdict  # This is the status of the device
    datapacket = commandpacket(command='device_status', device_uuid='', thread_uuid='', devicename=None,
                                            host=None, comdata=comdata)
    return datapacket

def check_for_command(datapacket=None,uuid=None,thread_uuid=None,add_data=False):
    """

    Args:
        datapacket:
        uuid: if set, compare uuid of the command with given uuid, return command only of uuid match
        add_data: adds the command dictionary

    Returns:
        command: content of the field 'redvypr_device_command', typically a string
    """
    flags = {}
    if '_redvypr_command' not in datapacket.keys():
        if(add_data):
            return [None,None]
        else:
            return None
    else:
        FLAG_COM1 = 'command' in datapacket['_redvypr_command'].keys()
        FLAG_COM2 = 'device_uuid' in datapacket['_redvypr_command'].keys()
        FLAG_COM3 = 'thread_uuid' in datapacket['_redvypr_command'].keys()
        command = None
        flags['com'] = FLAG_COM1
        if FLAG_COM1:

            if(uuid is not None):
                FLAG_UUID = datapacket['_redvypr_command']['device_uuid'] == uuid
            else:
                FLAG_UUID = True

            if (thread_uuid is not None):
                FLAG_TUUID = datapacket['_redvypr_command']['thread_uuid'] == thread_uuid
            else:
                FLAG_TUUID = True

            flags['device_uuid'] = FLAG_UUID
            flags['thread_uuid'] = FLAG_TUUID
            command = datapacket['_redvypr_command']['command']

        if(add_data):
            return [command,{'command_data':datapacket['_redvypr_command'],'flags':flags}]
        else:
            return command


def set_packetid(datapacket,packetid):
    """
    Sets the packetid of a dictionary or a redypr datapacket
    Parameters
    ----------
    datapacket
    packetid

    Returns
    -------

    """
    datapacket["_redvypr"]["packetid"] = packetid
    return datapacket


def set_device(datapacket,device):
    """
    Sets the device of a dictionary or a redypr datapacket
    Parameters
    ----------
    datapacket
    device

    Returns
    -------

    """
    datapacket["_redvypr"]["device"] = device
    return datapacket

#__rdvpraddr__ = redvypr_address('tmp')
#addresstypes  = __rdvpraddr__.get_strtypes() # A list of all addresstypes

