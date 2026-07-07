# 平台源本地配置模板

复制本文件为：

```text
projects/ruoyu-article-group/config/platform-sources.local.json
```

然后把 URL 改成你自己的公开榜单页、搜索页、热榜页或已授权采集页。

真实 cookie/token 不要写进 JSON。需要登录态的平台只填写环境变量名，例如：

```json
{
  "name": "微博热搜公开页",
  "platform": "weibo",
  "mode": "optional_cookie",
  "url": "https://s.weibo.com/top/summary",
  "cookie_env": "WEIBO_COOKIE"
}
```

本机运行前再设置：

```bash
export WEIBO_COOKIE='只放在本机，不提交 Git'
```

当前示例默认覆盖的平台信号：

- 微博：热搜/搜索讨论信号，可选 `WEIBO_COOKIE`。
- 知乎：热榜/问答讨论信号，可选 `ZHIHU_COOKIE`。
- B站：排行榜/视频讨论信号，可选 `BILIBILI_COOKIE`。
- 豆瓣电影：电影榜单/口碑信号，默认公开访问。

这些信号用于生成自媒体文章的选题母本，不等于事实结论。正式写作前必须二次核查人物、作品、时间、数据与原始来源。
