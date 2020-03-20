#-----------------------------------------------------------------------------
# Copyright (c) 2012 - 2020, Anaconda, Inc., and Bokeh Contributors.
# All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
#-----------------------------------------------------------------------------
''' Provide a request handler that returns a page displaying a document.

'''

#-----------------------------------------------------------------------------
# Boilerplate
#-----------------------------------------------------------------------------
import logging # isort:skip
log = logging.getLogger(__name__)

#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------

# External imports
from tornado.web import RequestHandler, HTTPError

# Bokeh imports
from bokeh.settings import settings

#-----------------------------------------------------------------------------
# Globals and constants
#-----------------------------------------------------------------------------

__all__ = (
    'StaticHandler',
)

#-----------------------------------------------------------------------------
# General API
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# Dev API
#-----------------------------------------------------------------------------

class BlobHandler(RequestHandler):

    # blobs: Protocol(get: (str) => str)

    def __init__(self, tornado_app, *args, **kw):
        self.blobs = kw.pop("blobs")
        super().__init__(tornado_app, *args, **kw)

    def get(self, path):
        artifact_path = self.blobs.get(path)
        if artifact_path is not None:
            with open(artifact_path, "rb") as fp:
                self.set_header("Content-Type", "application/octet-stream")
                self.write(fp.read())
        else:
            raise HTTPError(404)

#-----------------------------------------------------------------------------
# Private API
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# Code
#-----------------------------------------------------------------------------
