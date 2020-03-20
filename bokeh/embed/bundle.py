#-----------------------------------------------------------------------------
# Copyright (c) 2012 - 2020, Anaconda, Inc., and Bokeh Contributors.
# All rights reserved.
#
# The full license is in the file LICENSE.txt, distributed with this software.
#-----------------------------------------------------------------------------
'''

'''

#-----------------------------------------------------------------------------
# Boilerplate
#-----------------------------------------------------------------------------
import logging # isort:skip
log = logging.getLogger(__name__)

#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------

# Standard library imports
import json
from os.path import dirname, exists, join
from typing import List, Optional, NamedTuple
from warnings import warn

# Bokeh imports
from ..core.templates import CSS_RESOURCES, JS_RESOURCES
from ..document.document import Document
from ..model import Model
from ..resources import BaseResources, Resources, DEFAULT_SERVER_HTTP_URL, servables
from ..settings import settings
from ..util.compiler import bundle_models

#-----------------------------------------------------------------------------
# Globals and constants
#-----------------------------------------------------------------------------

__all__ = (
    'Bundle',
    'bundle_for_objs_and_resources',
)

#-----------------------------------------------------------------------------
# General API
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# Dev API
#-----------------------------------------------------------------------------

class ScriptRef(object):

    def __init__(self, url, type="text/javascript"):
        self.url = url
        self.type = type

class Script(object):

    def __init__(self, content, type="text/javascript"):
        self.content = content
        self.type = type

class StyleRef(object):

    def __init__(self, url):
        self.url = url

class Style(object):

    def __init__(self, content):
        self.content = content

class Bundle(object):

    @classmethod
    def of(cls, js_files, js_raw, css_files, css_raw, hashes):
        return cls(js_files=js_files, js_raw=js_raw, css_files=css_files, css_raw=css_raw, hashes=hashes)

    def __init__(self, **kwargs):
        self.js_files = kwargs.get("js_files", [])
        self.js_raw = kwargs.get("js_raw", [])
        self.css_files = kwargs.get("css_files", [])
        self.css_raw = kwargs.get("css_raw", [])
        self.hashes = kwargs.get("hashes", None)

    def __iter__(self):
        yield self._render_js()
        yield self._render_css()

    def _render_js(self):
        return JS_RESOURCES.render(js_files=self.js_files, js_raw=self.js_raw, hashes=self.hashes)

    def _render_css(self):
        return CSS_RESOURCES.render(css_files=self.css_files, css_raw=self.css_raw)

    def scripts(self, tag=True):
        if tag:
            return JS_RESOURCES.render(js_raw=self.js_raw, js_files=[])
        else:
            return "\n".join(self.js_raw)

    @property
    def js_urls(self):
        return self.js_files

    @property
    def css_urls(self):
        return self.css_files

    def add(self, artifact):
        if isinstance(artifact, ScriptRef):
            self.js_files.append(artifact.url)
        elif isinstance(artifact, Script):
            self.js_raw.append(artifact.content)
        elif isinstance(artifact, StyleRef):
            self.css_files.append(artifact.url)
        elif isinstance(artifact, Style):
            self.css_raw.append(artifact.content)

def bundle_for_objs_and_resources(objs, resources):
    ''' Generate rendered CSS and JS resources suitable for the given
    collection of Bokeh objects

    Args:
        objs (seq[Model or Document]) :

        resources (BaseResources or tuple[BaseResources])

    Returns:
        Bundle

    '''
    # Any env vars will overide a local default passed in
    resources = settings.resources(default=resources)
    if isinstance(resources, str):
        resources = Resources(mode=resources)

    if resources is None or isinstance(resources, BaseResources):
        js_resources = css_resources = resources
    elif isinstance(resources, tuple) and len(resources) == 2 and all(r is None or isinstance(r, BaseResources) for r in resources):
        js_resources, css_resources = resources

        if js_resources and not css_resources:
            warn('No Bokeh CSS Resources provided to template. If required you will need to provide them manually.')

        if css_resources and not js_resources:
            warn('No Bokeh JS Resources provided to template. If required you will need to provide them manually.')
    else:
        raise ValueError("expected Resources or a pair of optional Resources, got %r" % resources)

    from copy import deepcopy

    # XXX: force all components on server and in notebook, because we don't know in advance what will be used
    use_widgets = _use_widgets(objs) if objs else True
    use_tables  = _use_tables(objs)  if objs else True
    use_gl      = _use_gl(objs)      if objs else True

    js_files = []
    js_raw = []
    css_files = []
    css_raw = []

    if js_resources:
        js_resources = deepcopy(js_resources)
        if not use_widgets and "bokeh-widgets" in js_resources.js_components:
            js_resources.js_components.remove("bokeh-widgets")
        if not use_tables and "bokeh-tables" in js_resources.js_components:
            js_resources.js_components.remove("bokeh-tables")
        if not use_gl and "bokeh-gl" in js_resources.js_components:
            js_resources.js_components.remove("bokeh-gl")

        js_files.extend(js_resources.js_files)
        js_raw.extend(js_resources.js_raw)

    if css_resources:
        css_resources = deepcopy(css_resources)
        css_files.extend(css_resources.css_files)
        css_raw.extend(css_resources.css_raw)

    if js_resources:
        extensions = _bundle_extensions(objs, js_resources)
        mode = resources.mode if resources is not None else "inline"
        if mode == "inline":
            js_raw.extend([ Resources._inline(bundle.artifact_path) for bundle in extensions ])
        elif mode == "server":
            js_files.extend([ bundle.server_url for bundle in extensions ])
        elif mode == "cdn":
            js_files.extend([ bundle.cdn_url for bundle in extensions ])
        else:
            js_files.extend([ bundle.artifact_path for bundle in extensions ])

    models = [ obj.__class__ for obj in _all_objs(objs) ] if objs else None
    ext = bundle_models(models)
    if ext is not None:
        js_raw.append(ext)

    return Bundle.of(js_files, js_raw, css_files, css_raw, js_resources.hashes if js_resources else None)

#-----------------------------------------------------------------------------
# Private API
#-----------------------------------------------------------------------------

def _query_extensions(objs, query):
    names = set()

    for obj in _all_objs(objs):
        if hasattr(obj, "__implementation__"):
            continue
        name = obj.__view_module__.split(".")[0]
        if name == "bokeh":
            continue
        if name in names:
            continue
        names.add(name)

        for model in Model.model_class_reverse_map.values():
            if model.__module__.startswith(name):
                if query(model):
                    return True

    return False

class ExtensionEmbed(NamedTuple):
    artifact_path: str
    server_url: str
    cdn_url: Optional[str] = None

def _bundle_extensions(objs, resources: Resources) -> List[ExtensionEmbed]:
    names = set()
    bundles = []

    extensions = [".min.js", ".js"] if resources.minified else [".js"]

    for obj in _all_objs(objs) if objs is not None else Model.model_class_reverse_map.values():
        if hasattr(obj, "__implementation__"):
            continue
        name = obj.__view_module__.split(".")[0]
        if name == "bokeh":
            continue
        if name in names:
            continue
        names.add(name)
        module = __import__(name)
        base = dirname(module.__file__)

        server_prefix = f"static/extensions"
        package_path = join(base, "package.json")
        if exists(package_path):
            with open(package_path) as io:
                pkg = json.load(io)
                pkg_name = pkg["name"]
                version = pkg.get("version", "latest")
                main = pkg.get("module", pkg["main"])
                artifact_path = join(base, main)
                server_path = f"{pkg_name}@^{version}/{main}"
                cdn_url = f"https://unpkg.com/{pkg_name}@^{version}/{main}"
        else:
            for ext in extensions:
                artifact_path = join(base, "dist", name + ext)
                server_path = f"{name}@latest/dist/{name + ext}"
                if exists(artifact):
                    break
            else:
                raise ValueError(f"can't resolve artifact path for '{name}' extension")
            cdn_url = None

        servables[server_path] = artifact_path
        server_url = f"{DEFAULT_SERVER_HTTP_URL}{server_prefix}/{server_path}"
        embed = ExtensionEmbed(artifact_path, server_url, cdn_url)
        bundles.append(embed)

    return bundles

def _all_objs(objs):
    all_objs = set()

    for obj in objs:
        if isinstance(obj, Document):
            for root in obj.roots:
                all_objs |= root.references()
        else:
            all_objs |= obj.references()

    return all_objs

def _any(objs, query):
    ''' Whether any of a collection of objects satisfies a given query predicate

    Args:
        objs (seq[Model or Document]) :

        query (callable)

    Returns:
        True, if ``query(obj)`` is True for some object in ``objs``, else False

    '''
    for obj in objs:
        if isinstance(obj, Document):
            if _any(obj.roots, query):
                return True
        else:
            if any(query(ref) for ref in obj.references()):
                return True
    return False

def _use_gl(objs):
    ''' Whether a collection of Bokeh objects contains a plot requesting WebGL

    Args:
        objs (seq[Model or Document]) :

    Returns:
        bool

    '''
    from ..models.plots import Plot
    return _any(objs, lambda obj: isinstance(obj, Plot) and obj.output_backend == "webgl")

def _use_tables(objs):
    ''' Whether a collection of Bokeh objects contains a TableWidget

    Args:
        objs (seq[Model or Document]) :

    Returns:
        bool

    '''
    from ..models.widgets import TableWidget
    return _any(objs, lambda obj: isinstance(obj, TableWidget)) or _ext_use_tables(objs)

def _use_widgets(objs):
    ''' Whether a collection of Bokeh objects contains a any Widget

    Args:
        objs (seq[Model or Document]) :

    Returns:
        bool

    '''
    from ..models.widgets import Widget
    return _any(objs, lambda obj: isinstance(obj, Widget)) or _ext_use_widgets(objs)

def _ext_use_tables(objs):
    from ..models.widgets import TableWidget
    return _query_extensions(objs, lambda cls: issubclass(cls, TableWidget))

def _ext_use_widgets(objs):
    from ..models.widgets import Widget
    return _query_extensions(objs, lambda cls: issubclass(cls, Widget))

#-----------------------------------------------------------------------------
# Code
#-----------------------------------------------------------------------------
