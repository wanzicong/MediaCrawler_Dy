"""CDP 端点探测、本机拉起与远程接入。

本包只负责"如何得到一个连上 CDP 的 Browser 对象"：本地连接器、本机启动器与
远程管理器各自独占一个模块，均不持有 Playwright 生命周期（生命周期归
``crawler.browser.session``）。
"""
