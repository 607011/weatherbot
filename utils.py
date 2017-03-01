#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""

    Utility functions.

    Copyright (c) 2017 Oliver Lau <oliver@ersatzworld.net>
    All rights reserved.

"""

import urllib3
import pickle, json, os, shutil


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


class PersistentDict(dict):
    def __init__(self, filename, flag='c', mode=None, format='json', *args, **kwds):
        self.flag = flag                    # r=readonly, c=create, or n=new
        self.mode = mode                    # None or an octal triple like 0644
        self.format = format                # 'json' or 'pickle'
        self.filename = filename
        if flag != 'n' and os.access(filename, os.R_OK):
            fileobj = open(filename, 'rb' if format=='pickle' else 'r')
            with fileobj:
                self.load(fileobj)
        dict.__init__(self, *args, **kwds)

    def sync(self):
        if self.flag == 'r':
            return
        filename = self.filename
        tempname = filename + '.tmp'
        fileobj = open(tempname, 'wb' if self.format=='pickle' else 'w')
        try:
            self.dump(fileobj)
        except Exception:
            os.remove(tempname)
            raise
        finally:
            fileobj.close()
        shutil.move(tempname, self.filename)    # atomic commit
        if self.mode is not None:
            os.chmod(self.filename, self.mode)

    def close(self):
        self.sync()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def dump(self, fileobj):
        if self.format == 'json':
            json.dump(self, fileobj, separators=(',', ':'))
        elif self.format == 'pickle':
            pickle.dump(dict(self), fileobj, 2)
        else:
            raise NotImplementedError('Unknown format: ' + repr(self.format))

    def load(self, fileobj):
        for loader in (pickle.load, json.load):
            fileobj.seek(0)
            try:
                return self.update(loader(fileobj))
            except Exception:
                pass
        raise ValueError('File not in a supported format')
