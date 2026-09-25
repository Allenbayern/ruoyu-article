# 微信公开文章正文抓取

项目现在提供一条独立的微信公开文章抓取路径。它只接受
`mp.weixin.qq.com/s/...`（以及移动端同源域名）的公开链接，不读取登录态，
不注入 Cookie，不执行验证码或反爬 JavaScript。

## 为什么要有专用路径

微信对桌面端请求可能返回 HTTP 200 的“环境异常”页面。HTTP 状态码本身不
代表拿到了文章。抓取器会在公开链接上补齐 `scene=25`，使用移动端浏览器
请求头，然后只在页面存在 `#js_content` 且正文非空时通过。验证码页、空壳页
和网络失败都有明确错误码，不会被保存成材料。

## 直接阅读

```bash
uv run python -m article_group.wechat_capture \
  'https://mp.weixin.qq.com/s/文章ID'
```

默认输出标题和清洗后的正文；需要机器可读字段时加 `--json`。

## 写入 run 证据目录

```bash
uv run python -m article_group.wechat_capture \
  'https://mp.weixin.qq.com/s/文章ID' \
  --run-root runs/2026-09-14/controlled-001 \
  --source-id WX-001 \
  --role research-reference \
  --independence-group wechat-reference-1
```

这会创建：

- `sources/WX-001.clean.md`：只包含 `#js_content` 正文的本地快照；
- `sources/WX-001.source.json`：标题、账号、原始链接、实际抓取链接、抓取
  方法、`page_fulltext` 类型、`fulltext` 来源级别和 `clean_sha256`。

快照和 sidecar 均禁止覆盖。`captcha_or_access_blocked` 表示拿到的是访问
拦截页，`static_body_missing` 表示没有文章根节点，`fetch_failed` 表示公开
请求没有完成；这些状态都不能进入写作材料包。
