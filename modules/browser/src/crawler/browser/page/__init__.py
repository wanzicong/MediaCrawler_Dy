"""站点无关页面基元与只读端口。

``port.py`` 定义上层唯一可用的浏览器面（``BrowserPage``），``handle.py`` 是它的
唯一实现（附带 goto / set_cookies 等不出门面的内部能力），``primitives.py`` 提供
不依赖任何站点语义的 Playwright 页面基元。
"""
