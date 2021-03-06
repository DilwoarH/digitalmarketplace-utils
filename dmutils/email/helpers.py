# -*- coding: utf-8 -*-
"""Email helpers."""
import base64
import hashlib
import six


def hash_string(string):
    """Hash a given string."""
    m = hashlib.sha256(six.text_type(string).encode('utf-8'))
    return base64.urlsafe_b64encode(m.digest()).decode('utf-8')
