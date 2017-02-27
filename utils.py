#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""

    Utility functions.

    Copyright (c) 2017 Oliver Lau <oliver@ersatzworld.net>
    All rights reserved.

"""

import urllib3


class easydict(dict):
    def __missing__(self, key):
        self[key] = easydict()
        return self[key]


def get_image_from_url(url, username, password):
    error_msg = None
    response = None
    try:
        http = urllib3.PoolManager()
        headers = urllib3.util.make_headers(basic_auth="{}:{}".format(username, password)) if username and password else None
        response = http.request("GET", url, headers=headers)
    except urllib3.exceptions.HTTPError as e:
        error_msg = e.reason
    return response, error_msg


