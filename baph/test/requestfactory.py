# -*- coding: utf-8 -*-

from baph.utils.importing import import_attr
from django.conf import settings
from django.core.handlers.wsgi import WSGIRequest
from django.http import SimpleCookie
from django.utils.encoding import smart_str
from django.utils.http import urlencode
from django.utils.itercompat import is_iterable
import mimetypes
import os
import re
import urllib
from urlparse import urlparse

StringIO = import_attr(['cStringIO', 'StringIO'], 'StringIO')

BOUNDARY = 'BoUnDaRyStRiNg'
MULTIPART_CONTENT = 'multipart/form-data; boundary=%s' % BOUNDARY
CONTENT_TYPE_RE = re.compile('.*; charset=([\w\d-]+);?')


class FakePayload(object):
    """
    A wrapper around StringIO that restricts what can be read since data from
    the network can't be seeked and cannot be read outside of its content
    length. This makes sure that views can't do anything under the test client
    that wouldn't work in Real Life.
    """
    def __init__(self, content):
        self.__content = StringIO(content)
        self.__len = len(content)

    def read(self, num_bytes=None):
        if num_bytes is None:
            num_bytes = self.__len or 1
        assert self.__len >= num_bytes, "Cannot read more than the available bytes from the HTTP incoming data."
        content = self.__content.read(num_bytes)
        self.__len -= num_bytes
        return content


def encode_file(boundary, key, file):
    to_str = lambda s: smart_str(s, settings.DEFAULT_CHARSET)
    content_type = mimetypes.guess_type(file.name)[0]
    if content_type is None:
        content_type = 'application/octet-stream'
    return [
        '--' + boundary,
        'Content-Disposition: form-data; name="%s"; filename="%s"' \
            % (to_str(key), to_str(os.path.basename(file.name))),
        'Content-Type: %s' % content_type,
        '',
        file.read()
    ]


def encode_multipart(boundary, data):
    """
    Encodes multipart POST data from a dictionary of form values.

    The key will be used as the form data name; the value will be transmitted
    as content. If the value is a file, the contents of the file will be sent
    as an application/octet-stream; otherwise, str(value) will be sent.
    """
    lines = []
    to_str = lambda s: smart_str(s, settings.DEFAULT_CHARSET)

    # Not by any means perfect, but good enough for our purposes.
    is_file = lambda thing: hasattr(thing, "read") and callable(thing.read)

    # Each bit of the multipart form data could be either a form value or a
    # file, or a *list* of form values and/or files. Remember that HTTP field
    # names can be duplicated!
    for (key, value) in data.items():
        if is_file(value):
            lines.extend(encode_file(boundary, key, value))
        elif not isinstance(value, basestring) and is_iterable(value):
            for item in value:
                if is_file(item):
                    lines.extend(encode_file(boundary, key, item))
                else:
                    lines.extend([
                        '--' + boundary,
                        'Content-Disposition: form-data; name="%s"' % to_str(key),
                        '',
                        to_str(item)
                    ])
        else:
            lines.extend([
                '--' + boundary,
                'Content-Disposition: form-data; name="%s"' % to_str(key),
                '',
                to_str(value)
            ])

    lines.extend([
        '--' + boundary + '--',
        '',
    ])
    return '\r\n'.join(lines)


class RequestFactory(object):
    '''Class that lets you create mock Request objects for use in testing.

    Usage:

    rf = RequestFactory()
    get_request = rf.get('/hello/')
    post_request = rf.post('/submit/', {'foo': 'bar'})

    Once you have a request object you can pass it to any view function,
    just as if that view had been hooked up using a URLconf.
    Copied from Django SVN, revision 14191.
    '''
    def __init__(self, **defaults):
        self.defaults = defaults
        self.cookies = SimpleCookie()
        self.errors = StringIO()

    def _base_environ(self, **request):
        """
        The base environment for a request.
        """
        environ = {
            'HTTP_COOKIE':       self.cookies.output(header='', sep='; '),
            'PATH_INFO':         '/',
            'QUERY_STRING':      '',
            'REMOTE_ADDR':       '127.0.0.1',
            'REQUEST_METHOD':    'GET',
            'SCRIPT_NAME':       '',
            'SERVER_NAME':       'testserver',
            'SERVER_PORT':       '80',
            'SERVER_PROTOCOL':   'HTTP/1.1',
            'wsgi.version':      (1,0),
            'wsgi.url_scheme':   'http',
            'wsgi.errors':       self.errors,
            'wsgi.multiprocess': True,
            'wsgi.multithread':  False,
            'wsgi.run_once':     False,
        }
        environ.update(self.defaults)
        environ.update(request)
        return environ

    def request(self, **request):
        "Construct a generic request object."
        return WSGIRequest(self._base_environ(**request))

    def get(self, path, data={}, **extra):
        "Construct a GET request"

        parsed = urlparse(path)
        r = {
            'CONTENT_TYPE':    'text/html; charset=utf-8',
            'PATH_INFO':       urllib.unquote(parsed[2]),
            'QUERY_STRING':    urlencode(data, doseq=True) or parsed[4],
            'REQUEST_METHOD': 'GET',
            'wsgi.input':      FakePayload('')
        }
        r.update(extra)
        return self.request(**r)

    def post(self, path, data={}, content_type=MULTIPART_CONTENT,
             **extra):
        "Construct a POST request."

        if content_type is MULTIPART_CONTENT:
            post_data = encode_multipart(BOUNDARY, data)
        else:
            # Encode the content so that the byte representation is correct.
            match = CONTENT_TYPE_RE.match(content_type)
            if match:
                charset = match.group(1)
            else:
                charset = settings.DEFAULT_CHARSET
            post_data = smart_str(data, encoding=charset)

        parsed = urlparse(path)
        r = {
            'CONTENT_LENGTH': len(post_data),
            'CONTENT_TYPE':   content_type,
            'PATH_INFO':      urllib.unquote(parsed[2]),
            'QUERY_STRING':   parsed[4],
            'REQUEST_METHOD': 'POST',
            'wsgi.input':     FakePayload(post_data),
        }
        r.update(extra)
        return self.request(**r)

    def head(self, path, data={}, **extra):
        "Construct a HEAD request."

        parsed = urlparse(path)
        r = {
            'CONTENT_TYPE':    'text/html; charset=utf-8',
            'PATH_INFO':       urllib.unquote(parsed[2]),
            'QUERY_STRING':    urlencode(data, doseq=True) or parsed[4],
            'REQUEST_METHOD': 'HEAD',
            'wsgi.input':      FakePayload('')
        }
        r.update(extra)
        return self.request(**r)

    def options(self, path, data={}, **extra):
        "Constrict an OPTIONS request"

        parsed = urlparse(path)
        r = {
            'PATH_INFO':       urllib.unquote(parsed[2]),
            'QUERY_STRING':    urlencode(data, doseq=True) or parsed[4],
            'REQUEST_METHOD': 'OPTIONS',
            'wsgi.input':      FakePayload('')
        }
        r.update(extra)
        return self.request(**r)

    def put(self, path, data={}, content_type=MULTIPART_CONTENT,
            **extra):
        "Construct a PUT request."

        if content_type is MULTIPART_CONTENT:
            post_data = encode_multipart(BOUNDARY, data)
        else:
            post_data = data

        # Make `data` into a querystring only if it's not already a string. If
        # it is a string, we'll assume that the caller has already encoded it.
        query_string = None
        if not isinstance(data, basestring):
            query_string = urlencode(data, doseq=True)

        parsed = urlparse(path)
        r = {
            'CONTENT_LENGTH': len(post_data),
            'CONTENT_TYPE':   content_type,
            'PATH_INFO':      urllib.unquote(parsed[2]),
            'QUERY_STRING':   query_string or parsed[4],
            'REQUEST_METHOD': 'PUT',
            'wsgi.input':     FakePayload(post_data),
        }
        r.update(extra)
        return self.request(**r)

    def delete(self, path, data={}, **extra):
        "Construct a DELETE request."

        parsed = urlparse(path)
        r = {
            'PATH_INFO':       urllib.unquote(parsed[2]),
            'QUERY_STRING':    urlencode(data, doseq=True) or parsed[4],
            'REQUEST_METHOD': 'DELETE',
            'wsgi.input':      FakePayload('')
        }
        r.update(extra)
        return self.request(**r)
