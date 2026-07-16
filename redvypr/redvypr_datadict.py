import time
import copy
import logging
import sys
import re
import redvypr
from redvypr.redvypr_address import RedvyprAddress
import pydantic
import typing
from typing import Any, Dict, Optional, Union

logging.basicConfig(stream=sys.stderr)
logger = logging.getLogger('redvypr.base.redvypr_datadict')
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


# 3. Recursive merge helper function (deep update)
def deep_merge(target: dict, source: dict):
    """
    Recursively merge keys and values from a source dictionary into a target dictionary.

    This helper function traverses both dictionaries. If a key exists in both
    and its value on both sides is a dictionary, the function recurses deeper
    to merge their keys. Otherwise, the value in the `target` dictionary is
    directly overwritten by the value from the `source` dictionary.

    Parameters
    ----------
    target : dict
        The destination dictionary that will be mutated in-place.
    source : dict
        The dictionary containing updates, new keys, or nested structures
        to merge into the `target`.

    Returns
    -------
    None
        The `target` dictionary is modified in-place.

    Examples
    --------
    >>> target_dict = {
    ...     "device": "sensor_01",
    ...     "host": {"host": "host", "addr": "127.0.0.1"}
    ... }
    >>> source_dict = {
    ...     "host": {"host": "new_host", "uuid": "abc-123"}
    ... }
    >>> deep_merge(target_dict, source_dict)
    >>> target_dict
    {
        'device': 'sensor_01',
        'host': {
            'host': 'new_host',
            'addr': '127.0.0.1',
            'uuid': 'abc-123'
        }
    }
    """
    for key, value in source.items():
        if isinstance(value, dict) and key in target and isinstance(target[key], dict):
            # If both sides are dicts, descend one level deeper
            deep_merge(target[key], value)
        else:
            # Otherwise (value is a string, int, None, etc.), overwrite directly
            target[key] = value

class RedvyprDatadict(dict):
    """
    An extension of the built-in `dict` class that implements Redvypr data packets.

    This class wraps standard payload dictionaries and automatically injects,
    manages, and updates metadata structures under the ``_redvypr`` key.
    It facilitates seamless data retrieval and address resolution using
    ``RedvyprAddress`` representations.

    Examples
    --------
    >>> from redvypr import RedvyprDatadict, RedvyprAddress
    >>> ar = RedvyprDatadict({'a': [[2, 3, 4], 2, 3, 4]})
    >>> addr = RedvyprAddress('["a"][0]@')
    >>> ar[addr]
    [2, 3, 4]

    Attributes
    ----------
    address : RedvyprAddress
        An address object associated with the data packet, initialized
        dynamically from the packet's current contents.
    """
    def __init__(self, *args,
                 device=None,
                 packetid=None,
                 raddress: Optional[Union[str, RedvyprAddress]] = None,
                 hostinfo: Optional[Dict[str, Any]] = None,
                 **kwargs):
        """
        Initialize a new instance of the RedvyprDatadict class.

        Parameters
        ----------
        *args : tuple
            Variable length argument list. If the first argument is a dictionary,
            it is used to initialize the underlying dictionary content.
        device : str, optional
            The source device associated with this packet. Used to populate or
            override the underlying ``_redvypr`` metadata. Default is None.
        packetid : str or int, optional
            A unique identifier for the packet. Used to populate or override
            the underlying ``_redvypr`` metadata. Default is None.
        raddress : str or RedvyprAddress, optional
            An address containing metadata query contexts. If provided, its
            filter dimensions are parsed and integrated into the packet.
            Default is None.
        hostinfo : dict, optional
            Dictionary containing host system properties (e.g., hostnames, IPs).
            Default is None.
        **kwargs : dict
            Additional keyword arguments parsed directly as root-level payload
            keys in the dictionary.

        Notes
        -----
        If the data packet is initialized without an existing ``_redvypr`` key,
        one is automatically generated using the `create_redvypr_dict` helper.
        Otherwise, existing metadata is safely updated in place.
        """

        if len(args)>0:
            # Check if the datapacket is created from a dictionary, without kwargs
            if isinstance(args[0],dict):
                dict.__init__(self, *args, **kwargs)

        else:
            dict.__init__(self)

        self._cache = {} # For calculated datakeys, etc. ...

        if '_redvypr' not in self.keys():
            #create_datadict(data=None, datakey=None, packetid=None, tu=None, device=None, publisher=None, hostinfo=None)
            dataself = create_redvypr_dict(packetid=packetid, device=device, hostinfo=hostinfo, raddress=raddress)
            self.update(dataself)
        else: # Update the redvypr dict
            if raddress is not None:
                rdict = raddress.to_redvypr_dict(include_datakey=False)
                deep_merge(self['_redvypr'], rdict.get('_redvypr', {}))
            if hostinfo is not None: # Update hostinfo, if present
                self['_redvypr']['host'] = hostinfo
            if device is not None:
                self['_redvypr']['device'] = device
            if packetid is not None:
                self['_redvypr']['packetid'] = packetid

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
        >>> ar = RedvyprDatadict({'a': [[2, 3, 4], 2, 3, 4]})
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

    def datakeys_info(self) -> dict:
        """
        Analyze nested packet keys and extract data stream relations and hierarchies.

        This method inspects all expanded keys within the data packet to determine
        the underlying structure, timestamp relations, and structural nesting of data
        streams. It identifies standard single values, arrays with a single timestamp,
        concatenated data streams, and structural iterables (lists or dicts) that act
        as containers by tracking their child nodes.

        The resulting metadata dictionary is registered inside the instance `self._cache`
        to bypass heavy re-calculation over unchanged structures.

        Returns
        -------
        dict
            A dictionary where keys match the expanded bracket notations (e.g.,
            '["sensors"]["analog"][0]["data"]') and values are dictionaries containing:

            - "type" (str): The identified stream variant. Possible choices:
              `"standard"`, `"concatenated"`, `"single_t_array"`, `"timestamp_list"`,
              `"timestamp_single"`, `"iterable_list"`, or `"iterable_dict"`.
            - "is_concatenated" (bool): True if the element represents or is bound
              to a multi-point concatenated array stream.
            - "timestamp_address" (str or None): The explicit path to the matching
              temporal identifier '["t"]' within the structural hierarchy level.
            - "children" (list of str, optional): Included only if the element is an
              iterable container and not concatenated. Contains exact paths of direct
              subsidiary structural nodes.
        """

        # Define a stable and distinct cache token mapping
        cache_key = "datakeys_info_payload"

        # Cache Hit: Instantly yield structural lookup maps if available
        if cache_key in self._cache:
            return self._cache[cache_key]

        info = {}
        # Build strict filtering boundaries using the pre-defined framework layout keys
        filter_set = set(redvypr_data_keys)

        # We first build our own complete tree map (including containers) to be fully independent
        all_nodes = {}

        def _scan_packet_recursive(node, parent_path="", level=0):
            # Use isinstance to correctly support subclasses like Datapacket
            if isinstance(node, dict):
                for k, v in node.items():
                    if level == 0 and k in filter_set:
                        continue

                    # Formatting path string
                    strformat = str(k) if level == 0 else (f"[{k}]" if isinstance(k, int) else f"['{k}']")
                    current_path = f"{parent_path}{strformat}" if level > 0 else strformat

                    all_nodes[current_path] = (current_path, type(v), v)
                    _scan_packet_recursive(v, current_path, level + 1)

            elif isinstance(node, list):
                for idx, v in enumerate(node):
                    strformat = f"[{idx}]"
                    current_path = f"{parent_path}{strformat}"

                    all_nodes[current_path] = (current_path, type(v), v)
                    _scan_packet_recursive(v, current_path, level + 1)

        # Start the independent object scanner
        _scan_packet_recursive(self)

        # Baseline assignment loop
        for current_key, (path_str, data_type, value) in all_nodes.items():
            info[current_key] = {
                "type": "standard",
                "data_type": data_type.__name__,
                "is_concatenated": False,
                "timestamp_address": None
            }

            # 1. Evaluate Timestamp relations for lists or indexed objects
            if data_type is list or '[' in current_key:
                parent_match = re.match(r'(.*)\["?[^"\]]+"?\]$', current_key)
                expected_t_key = None

                if current_key.endswith("']") or current_key.endswith('"]'):
                    local_t_key = current_key[:-2] + '_t' + current_key[-2:]
                    if local_t_key in all_nodes:
                        expected_t_key = local_t_key
                # B) for keys on root-level: look for 'sensors_t' with 'sensors'
                elif '[' not in current_key:
                    local_t_key = f"{current_key}_t"
                    if local_t_key in all_nodes:
                        expected_t_key = local_t_key

                # if no f"{current_key}_t" was found, look for "t"
                if not expected_t_key and parent_match:
                    parent_path = parent_match.group(1)
                    expected_t_key = f'{parent_path}["t"]' if parent_path.endswith(']') else f'{parent_path}["t"]'

                # Fallback to root 't' if no sub-level timestamp is declared
                root_t = '["t"]' if '["t"]' in all_nodes else ('t' if 't' in all_nodes else None)
                if not expected_t_key or expected_t_key not in all_nodes:
                    expected_t_key = root_t

                if expected_t_key and expected_t_key in all_nodes:
                    t_type = all_nodes[expected_t_key][1]
                    try:
                        t_value = self[expected_t_key]
                        # Matching conditions for compressed multi-point streams
                        if t_type is list and isinstance(t_value, list) and len(t_value) == len(value):
                            info[current_key]["type"] = "concatenated"
                            info[current_key]["is_concatenated"] = True
                            info[current_key]["timestamp_address"] = expected_t_key
                            if isinstance(value, list) and len(value) > 0:
                                inner_type = type(value[0]).__name__
                                info[current_key]["data_type"] = f"[{inner_type}]"
                            else:
                                info[current_key]["data_type"] = "[]"
                        # We have a list, but only one time stamp, that means that each data point is a single datastream
                        elif isinstance(value, list):
                            info[current_key]["type"] = "single_t_array"
                            info[current_key]["is_concatenated"] = False
                            info[current_key]["timestamp_address"] = expected_t_key
                            if isinstance(value, list) and len(value) > 0:
                                inner_type = type(value[0]).__name__
                                info[current_key]["data_type"] = f"[{inner_type}]"
                            else:
                                info[current_key]["data_type"] = "[]"
                        else:
                            info[current_key]["type"] = "standard"
                            info[current_key]["is_concatenated"] = False
                            info[current_key]["timestamp_address"] = expected_t_key
                    except Exception:
                        pass

            # 2. Specialize non-concatenated iterable containers
            if not info[current_key]["is_concatenated"] and data_type in (list, dict):
                info[current_key]["type"] = "iterable_list" if data_type is list else "iterable_dict"
                info[current_key]["children"] = []

        # 3. Precise Hierarchical Child Mapping
        for current_key, item in info.items():
            if "children" in item:
                # We extract direct keys depending on whether it's a dict or list
                _, data_type, actual_obj = all_nodes[current_key]

                if data_type is dict:
                    for k in actual_obj.keys():
                        strformat = f"[{k}]" if isinstance(k, int) else f"['{k}']"
                        child_path = f"{current_key}{strformat}"
                        if child_path in info:
                            item["children"].append(child_path)
                elif data_type is list:
                    for idx in range(len(actual_obj)):
                        child_path = f"{current_key}[{idx}]"
                        if child_path in info:
                            item["children"].append(child_path)

        # 4. Refine tracking configurations for any temporal identifier keys explicitly
        for current_key, item in list(info.items()):
            if current_key == 't' or current_key == '["t"]' or current_key.endswith('["t"]'):
                is_shared_concat = any(
                    v.get("timestamp_address") == current_key and v.get("is_concatenated") for v in info.values())
                item["type"] = "timestamp_list" if is_shared_concat else "timestamp_single"
                item["is_concatenated"] = is_shared_concat
                item["timestamp_address"] = current_key

        # Commit final structure evaluation to instance cache
        self._cache[cache_key] = info
        return info

    @classmethod
    def get_datakey_info_from_dict(cls, data: dict = None, datakey: str = None) -> dict:
        """
        Extract structural information for a specific key out of a dictionary or instance.

        This method supports raw data dictionaries (triggering an on-the-fly calculation),
        pre-calculated 'datakeys_info' blocks extracted from device statistics, or
        direct instance calls if the data object is omitted.

        Parameters
        ----------
        data : dict or Datapacket, optional
            The raw data packet, a Datapacket instance, OR a pre-calculated
            'datakeys_info' sub-dictionary fetched from device statistics.
            If None, a ValueError is raised unless invoked via the instance wrapper.
        datakey : str
            The specific expanded key string to query (e.g., "multisensor[0]").

        Returns
        -------
        dict
            The structural metadata dictionary for the specified key containing
            'type', 'is_concatenated', 'timestamp_address', and optionally 'children'.
            Returns a fallback standard layout if the key is missing.

        Raises
        ------
        ValueError
            If both data and instance context are missing.

        Examples
        --------
        >>> # Example A: High-performance lookup inside a QTree Widget (using pre-calculated stats)
        >>> stats_info = device_stats.get('datakeys_info', {})
        >>> meta = RedvyprDatadict.get_datakey_info_from_dict(stats_info, "multisensor[0]")

        >>> # Example B: On-the-fly fallback calculation using a raw data dictionary
        >>> raw_packet = {"t": 1700000000, "multisensor": [10, 20]}
        >>> meta = RedvyprDatadict.get_datakey_info_from_dict(raw_packet, "multisensor[0]")

        >>> # Example C: Direct instance call using the shortcut method
        >>> packet = RedvyprDatadict(raw_packet)
        >>> meta = packet.get_datakey_info("multisensor[0]")
        """
        if data is None:
            raise ValueError("A valid data dictionary or instance context must be provided.")

        # Case 1: 'data' is already the pre-calculated 'datakeys_info' dict from stats.
        # Detected if the requested datakey is found as a direct top-level key inside it.
        if datakey in data and isinstance(data[datakey], dict) and "type" in data[datakey]:
            return data[datakey]

        # Case 2: 'data' is the entire device statistics root dictionary ('device_redvypr').
        if isinstance(data, dict) and "datakeys_info" in data:
            return data["datakeys_info"].get(datakey, {
                "type": "standard", "is_concatenated": False, "timestamp_address": None
            })

        # Case 3: 'data' is a raw packet dictionary or an active instance.
        # Compute on-the-fly using a temporary instance if it's a raw dict.
        if not isinstance(data, cls):
            packet_instance = cls(data)
        else:
            packet_instance = data

        return packet_instance.datakeys_info().get(datakey, {
            "type": "standard", "is_concatenated": False, "timestamp_address": None
        })

    def get_datakey_info(self, datakey: str) -> dict:
        """
        Convenience instance shortcut to extract structural metadata.

        Maps directly to the classmethod, automatically passing 'self'
        as the data source.

        Parameters
        ----------
        datakey : str
            The specific expanded key string to query (e.g., "multisensor[0]").

        Returns
        -------
        dict
            The structural metadata dictionary for the specified key.
        """
        return self.get_datakey_info_from_dict(data=self, datakey=datakey)


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
        return RedvyprDatadict.datastreams_from_datakeys(
            datakeys_payload=payload,
            base_address=self.address,
            return_type=return_type,
            expand=expand,
            fallback_types=fallback_types
        )


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

    def set_filterkeys(self, **kwargs):
        set_filterkeys(self, **kwargs)

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





def create_redvypr_dict(
        data: Optional[Any] = None,
        datakey: Optional[str] = None,
        packetid: Optional[Union[str, int]] = None,
        tu: Optional[float| int | bool] = True,
        device: Optional[str] = None,
        publisher: Optional[str] = None,
        raddress: Optional[Union[str, RedvyprAddress]] = None,
        hostinfo: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a datadict dictionary used as the internal data structure in redvypr.

    This function wraps payload data and attaches a standardized metadata header
    under the ``_redvypr`` key. If no explicit timestamp is provided, the current
    system epoch time is used by default.

    Parameters
    ----------
    data : Any, optional
        The actual payload data to be stored. If provided and `datakey` is set,
        it is stored under the specified key. If `data` is a dictionary and
        no `datakey` is specified, its keys are merged directly into the root level
        of the output dictionary (excluding any existing ``_redvypr`` metadata).
        Default is None.
    datakey : str, optional
        The dictionary key used for the payload data. Defaults to ``'data'``
        if `data` is present but `datakey` is None, unless `data` is a dictionary.
        Default is None.
    packetid : str or int, optional
        Unique identifier for the data packet. If None, it defaults to the
        value of `device`. Default is None.
    tu : float, int, or bool, optional
        Unix timestamp (time units) for the packet. If set to ``True``, it defaults
        to the current system time using ``time.time()``. Default is True.
    device : str, optional
        Identifier of the source device. Default is None.
    publisher : str, optional
        Identifier of the publishing entity. Default is None.
    raddress : str or RedvyprAddress, optional
        An address string or `RedvyprAddress` object used to populate missing
        metadata fields (such as `packetid`, `device`, `deviceid`, or `publisher`).
        Default is None.
    hostinfo : dict, optional
        Dictionary containing host-related information. If None, falls back to
        ``redvypr.hostinfo_blank``. Default is None.

    Returns
    -------
    dict
        A structured dictionary containing the ``_redvypr`` metadata header block
        and the optional payload data.

    Notes
    -----
    The resulting dictionary structure conforms to:

    .. code-block:: python

        {
            '_redvypr': {
                't': float,
                'device': str,
                'packetid': str,
                'publisher': str,
                'host': dict
            },
            'datakey_name': data_payload  # optional root-level payload
        }

    Examples
    --------
    Create a basic data dictionary with default metadata and payload:

    >>> create_redvypr_dict(data=23.5, datakey="temperature", device="sensor_01")
    {
        '_redvypr': {
            't': 1718123456.789,
            'device': 'sensor_01',
            'packetid': 'sensor_01',
            'publisher': None,
            'host': {...}
        },
        'temperature': 23.5
    }
    """

    if tu is True:
        tu = time.time()

    # Initialize the metadata structure
    datadict: Dict[str, Any] = {'_redvypr': {'t': tu}}

    # Add the input from the redvypr-address
    if raddress is not None:
        if isinstance(raddress, str):
            raddress = RedvyprAddress(raddress)
            if packetid is None:
                packetid = raddress.packetid
            if device is None:
                device = raddress.device
            if publisher is None:
                publisher = raddress.publisher
        rdict = raddress.to_redvypr_dict(include_datakey=False)
        datadict.update(rdict)

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


    # Insert payload data if present
    if data is not None:
        if isinstance(data, dict) and datakey is None:
            data_copy = copy.deepcopy(data)
            data_copy.pop('_redvypr',None)
            datadict.update(data_copy)
        else:
            if datakey is None:
                datakey = 'data'
            datadict[datakey] = copy.deepcopy(data)

    return datadict

def create_redvypr_dict_random_host(hostname=None, random_host=True):
    if random_host is not None:
        datadict['_redvypr']['host'] = redvypr.create_hostinfo(random_host)



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
    compacket = create_redvypr_dict({'command':command}, datakey='_redvypr_command') # The command
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


def set_filterkeys(datapacket: dict, **kwargs) -> dict:
    """
    Sets metadata filter keys inside the nested '_redvypr' block of a data packet,
    safely merging nested dictionaries (like 'host') instead of overwriting them.
    """
    # 1. Use RedvyprAddress to generate the new metadata dict.
    #    to_redvypr_dict(include_datakey=False) yields e.g., {'_redvypr': {'host': {'host': 'peter'}}}
    from_address = RedvyprAddress(**kwargs).to_redvypr_dict(include_datakey=False)
    new_metadata = from_address.get('_redvypr', {})

    # 2. Ensure the '_redvypr' header exists in the target packet
    if '_redvypr' not in datapacket:
        datapacket['_redvypr'] = {}

    target_metadata = datapacket['_redvypr']

    # Execute the recursive update on the '_redvypr' level
    deep_merge(target_metadata, new_metadata)

    return datapacket


