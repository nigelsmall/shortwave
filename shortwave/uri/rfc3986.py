#!/usr/bin/env python
# coding: utf-8

# Copyright 2011-2016, Nigel Small
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
An implementation of URIs from RFC 3986 (URI Generic Syntax).

See: http://www.ietf.org/rfc/rfc3986.txt
"""

from re import compile as re_compile

from shortwave.util.compat import bstr, xstr, quote, unquote

# RFC 3986 § 2.2.
general_delimiters = ":/?#[]@"
subcomponent_delimiters = "!$&'()*+,;="
reserved = general_delimiters + subcomponent_delimiters

# RFC 3986 § 2.3.
unreserved = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
              "abcdefghijklmnopqrstuvwxyz"
              "0123456789-._~")

# Section 3.1.
scheme_pattern = re_compile(b"[A-Za-z][+\-.0-9A-Za-z]*$")


# RFC 3986 § 2.1.
def percent_encode(data, safe=None):
    """ Percent encode a string of data, optionally keeping certain characters
    unencoded.

    """
    if data is None:
        return None
    if isinstance(data, (tuple, list, set)):
        return b"&".join(
            percent_encode(value, safe=safe)
            for value in data
        )
    if isinstance(data, dict):
        return b"&".join(
            bstr(key) + b"=" + percent_encode(value, safe=safe)
            for key, value in data.items()
        )
    return quote(bstr(data), safe or b"").encode("utf-8")


def percent_decode(data):
    """ Percent decode a string of data.

    """
    if data is None:
        return None
    return unquote(xstr(data))


def parse_uri(uri):
    scheme = auth = path = query = fragment = None

    if uri is not None:

        if not isinstance(uri, bytes):
            uri = bstr(uri)

        # Scheme
        q = uri.find(b":")
        if q == -1:
            start = 0
        elif scheme_pattern.match(uri, 0, q):
            scheme = uri[:q]
            start = q + 1
        else:
            start = 0
        end = len(uri)

        # Fragment
        q = uri.find(b"#", start)
        if q != -1:
            fragment = uri[(q + 1):]
            end = q

        # Query
        q = uri.find(b"?", start)
        if start <= q < end:
            query = uri[(q + 1):end]
            end = q

        # Authority and path
        p = start + 2
        if uri[start:p] == b"//":
            q = uri.find(b"/", p)
            if q == -1:
                auth = uri[p:end]
                path = b""
            else:
                auth = uri[p:q]
                path = uri[q:end]
        else:
            path = uri[start:end]

    return scheme, auth, path, query, fragment


def build_uri(scheme=None, authority=None, path=None, query=None, fragment=None, **parts):
    """ Build a URI object from named parts. The part names available are:

    - uri
    - hierarchical_part
    - absolute_path_reference
    - authority
    - host_port
    - scheme
    - user_info
    - host
    - port
    - path
    - query
    - fragment

    See: RFC 3986, section 5.3
    """
    s, a, p, q, f = parse_uri(parts.get("uri"))
    _authority = build_authority(authority=authority, **parts)
    if parts.get("hierarchical_part") is not None:
        _, a, p, _, _ = parse_uri(parts["hierarchical_part"])
    if parts.get("absolute_path_reference") is not None:
        _, _, p, q, f = parse_uri(parts["absolute_path_reference"])
    if scheme is not None:
        s = bstr(scheme)
    if _authority:
        a = _authority
    if path is not None:
        p = bstr(path)
    if query is not None:
        q = bstr(query)
    if fragment is not None:
        f = bstr(fragment)

    result = []
    if s is not None:
        result += [s, b":"]
    if a is not None:
        result += [b"//", a]
    result += [p or b""]
    if q is not None:
        result += [b"?", q]
    if f is not None:
        result += [b"#", f]
    return b"".join(result)


def resolve_uri(base_uri, ref_uri, strict=True):
    """ RFC 3986, section 5.2.2
    """
    if ref_uri is None:
        return None
    base_scheme, base_auth, base_path, base_query, base_fragment = parse_uri(base_uri)
    ref_scheme, ref_auth, ref_path, ref_query, ref_fragment = parse_uri(ref_uri)
    if not strict and ref_scheme == base_scheme:
        reference_scheme = None
    else:
        reference_scheme = ref_scheme
    if reference_scheme is not None:
        target_scheme = reference_scheme
        target_auth = ref_auth
        target_path = remove_dot_segments(ref_path)
        target_query = ref_query
    else:
        if ref_auth is not None:
            target_auth = ref_auth
            target_path = remove_dot_segments(ref_path)
            target_query = ref_query
        else:
            if not ref_path:
                target_path = base_path
                if ref_query is not None:
                    target_query = ref_query
                else:
                    target_query = base_query
            else:
                if ref_path.startswith(b"/"):
                    target_path = remove_dot_segments(ref_path)
                else:
                    target_path = merge_paths(base_auth, base_path, ref_path)
                    target_path = remove_dot_segments(target_path)
                target_query = ref_query
            target_auth = base_auth
        target_scheme = base_scheme
    target_fragment = ref_fragment
    return build_uri(scheme=target_scheme, authority=target_auth, path=target_path,
                     query=target_query, fragment=target_fragment)


def parse_authority(authority):
    user_info = host = port = None

    if authority is not None:

        if not isinstance(authority, bytes):
            authority = bstr(authority)

        # User info
        p = authority.rfind(b"@")
        if p != -1:
            user_info = authority[:p]

        # Host and port
        p += 1
        q = authority.find(b":", p)
        if q == -1:
            host = authority[p:]
        else:
            host = authority[p:q]
            q += 1
            port = int(authority[q:])

    return user_info, host, port


def build_authority(user_info=None, host=None, port=None, **parts):
    """ Build a URI authority

    - authority
    - host_port
    - user_info
    - host
    - port

    authority   = [ userinfo "@" ] host [ ":" port ]

    Section 3.2.
    """
    u, h, p = parse_authority(parts.get("authority"))
    if parts.get("host_port") is not None:
        _, h, p = parse_authority(parts["host_port"])
    if user_info is not None:
        u = bstr(user_info)
    if host is not None:
        h = bstr(host)
    if port is not None:
        p = int(port)

    result = []
    if u is not None:
        result += [u, b"@"]
    result += [h or b""]
    if p is not None:
        result += [b":", bstr(p)]
    return b"".join(result)


def parse_path(path):
    if path is None:
        return None
    if not isinstance(path, bytes):
        path = bstr(path)
    return list(map(percent_decode, path.split(b"/")))


def build_path(segments):
    return b"/".join(map(percent_encode, segments))


def merge_paths(base_auth, base_path, ref_path):
    """ Section 5.2.3
    """
    if base_auth is not None and not base_path:
        return b"/" + ref_path
    elif b"/" in base_path:
        segments = parse_path(base_path)[:-1] + [b""]
        return build_path(segments) + ref_path
    else:
        return ref_path


def remove_dot_segments(path):
    """ 5.2.4.  Remove Dot Segments

    Interpret and remove the special "." and ".." complete path
    segments from a referenced path.
    """
    if not isinstance(path, bytes):
        path = bstr(path)
    new_path = b""
    while path:
        if path.startswith(b"../"):
            path = path[3:]
        elif path.startswith(b"./"):
            path = path[2:]
        elif path.startswith(b"/./"):
            path = path[2:]
        elif path == b"/.":
            path = b"/"
        elif path.startswith(b"/../"):
            path = path[3:]
            new_path = new_path.rpartition(b"/")[0]
        elif path == b"/..":
            path = b"/"
            new_path = new_path.rpartition(b"/")[0]
        elif path in (b".", b".."):
            path = b""
        else:
            if path.startswith(b"/"):
                path = path[1:]
                new_path += b"/"
            seg, slash, path = path.partition(b"/")
            new_path += seg
            path = slash + path
    return new_path


def parse_parameters(parameters, item_separator=b"&", key_separator=b"="):
    if parameters is None:
        return None
    if not isinstance(parameters, bytes):
        parameters = bstr(parameters)
    parsed = []
    if parameters:
        if not isinstance(item_separator, bytes):
            item_separator = bstr(item_separator)
        if not isinstance(key_separator, bytes):
            key_separator = bstr(key_separator)
        parts = parameters.split(item_separator)
        for part in parts:
            if key_separator in part:
                key, _, value = map(percent_decode, part.partition(key_separator))
            else:
                key, value = None, percent_decode(part)
            parsed.append((key, value))
    return parsed
