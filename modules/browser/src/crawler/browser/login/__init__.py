"""抖音登录流程：cookie 登录与扫码登录。

``flow.DouyinLogin`` 只驱动浏览器（清 cookie、写 cookie、刷新页面、抓二维码），
登录态校验与 cookie 同步一律经注入的 ``crawler.browser.facade.protocols.LoginApi``
完成；本包不 import ``crawler.douyin_client``（裁决 R10.1）。
"""
